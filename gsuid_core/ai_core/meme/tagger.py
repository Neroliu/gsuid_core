"""表情包 VLM 打标引擎

MemeTagEngine 负责后台消费打标队列，调用 AI Agent 理解图片内容，
生成情绪/场景标签，并将结果写入数据库和 Qdrant 向量索引。
使用 create_agent + extract_json_from_text 复用现有基础设施。

图片处理由 GsCoreAIAgent._execute_run 自动完成：
- 模型支持图片时直接传图
- 模型不支持图片时通过 understand_image 转述为文字
"""

import base64
import asyncio
from typing import Optional

from pydantic_ai.messages import ImageUrl

from gsuid_core.logger import logger
from gsuid_core.ai_core.utils import extract_json_from_text
from gsuid_core.ai_core.gs_agent import create_agent
from gsuid_core.ai_core.meme.config import meme_config
from gsuid_core.ai_core.meme.library import MemeLibrary, _read_file, get_memes_base_path
from gsuid_core.ai_core.meme.database_model import AiMemeRecord

# 打标队列
_tag_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)

# 打标信号量
_tag_semaphore: Optional[asyncio.Semaphore] = None

# 打标 worker 任务引用
_worker_task: Optional[asyncio.Task] = None

# VLM 打标提示词
TAG_PROMPT = """你是一个图片分析助手。请分析这张图片并返回 JSON 格式的标签信息。

请返回以下格式的 JSON（不要包含其他内容）：
{
    "description": "简短描述图片内容（20字以内）",
    "emotion_tags": ["情绪标签1", "情绪标签2"],
    "scene_tags": ["场景标签1", "场景标签2"],
    "persona_hint": "common",
    "nsfw_score": 0.0
}

字段说明：
- description: 图片内容的简短描述
- emotion_tags: 情绪标签列表，如 "开心", "无语", "搞笑", "可爱", "愤怒", "悲伤", "惊讶", "尴尬", "得意", "委屈"
- scene_tags: 场景标签列表，如 "日常", "吐槽", "卖萌", "怼人", "安慰", "庆祝", "晚安", "早安"
- persona_hint: 建议的 persona 归属，如果不确定填 "common"
- nsfw_score: NSFW 分数（0.0~1.0），0 表示完全安全，1 表示完全不安全

只返回 JSON，不要有其他文字。"""


async def start_tag_worker() -> None:
    """启动后台打标 worker"""
    global _tag_semaphore, _worker_task

    semaphore_count: int = meme_config.get_config("meme_vlm_semaphore").data
    _tag_semaphore = asyncio.Semaphore(semaphore_count)

    _worker_task = asyncio.create_task(_tag_worker_loop())
    logger.info(f"[Meme] 打标 worker 已启动，并发上限: {semaphore_count}")


async def stop_tag_worker() -> None:
    """停止后台打标 worker"""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    logger.info("[Meme] 打标 worker 已停止")


async def enqueue_tag(meme_id: str) -> None:
    """将 meme_id 加入打标队列

    Args:
        meme_id: 表情包 ID
    """
    if _tag_queue.full():
        logger.warning(f"[Meme] 打标队列已满（>{_tag_queue.maxsize}），丢弃: {meme_id}")
        return
    await _tag_queue.put(meme_id)
    logger.debug(f"[Meme] 加入打标队列: {meme_id}")


async def _tag_worker_loop() -> None:
    """打标 worker 主循环"""
    while True:
        try:
            meme_id = await _tag_queue.get()
            if _tag_semaphore is None:
                await asyncio.sleep(1)
                _tag_queue.task_done()
                continue

            async with _tag_semaphore:
                await _tag_single(meme_id)

            _tag_queue.task_done()

            # 打标间隔
            from gsuid_core.ai_core.meme.config import MEME_TAG_INTERVAL_SEC

            await asyncio.sleep(MEME_TAG_INTERVAL_SEC)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Meme] 打标 worker 异常: {e}")
            await asyncio.sleep(5)


async def _tag_single(meme_id: str) -> None:
    """对单个表情包进行 VLM 打标

    图片处理由 GsCoreAIAgent._execute_run 自动完成：
    - 模型支持图片时直接传图
    - 模型不支持图片时通过 understand_image 转述为文字

    Args:
        meme_id: 表情包 ID
    """
    record = await AiMemeRecord.get_by_meme_id(meme_id)
    if record is None:
        logger.warning(f"[Meme] 打标时找不到记录: {meme_id}")
        return

    # 检查状态，避免重复打标
    if record.status not in ("pending", "pending_manual"):
        return

    # 读取图片文件
    file_path = get_memes_base_path() / record.file_path
    if not file_path.exists():
        logger.warning(f"[Meme] 图片文件不存在: {file_path}")
        await MemeLibrary.mark_tag_failed(meme_id)
        return

    image_data = await _read_file(file_path)
    image_b64 = base64.b64encode(image_data).decode("utf-8")

    # 调用 Agent 进行打标（直接传 ImageUrl，由 _execute_run 自动处理图片能力判断）
    tag_result = await _call_tag_agent(image_b64, record.file_mime)
    if tag_result is None:
        logger.warning(f"[Meme] VLM 打标失败: {meme_id}")
        await MemeLibrary.mark_tag_failed(meme_id)
        return

    # NSFW 检查
    nsfw_threshold: float = meme_config.get_config("meme_nsfw_threshold").data
    if tag_result["nsfw_score"] >= nsfw_threshold:
        logger.info(f"[Meme] NSFW 分数过高，标记为 rejected: {meme_id}")
        await MemeLibrary.mark_rejected(meme_id, tag_result["nsfw_score"])
        return

    # 更新标签
    persona_hint = tag_result["persona_hint"]
    # 确定目标文件夹
    target_folder = "common"
    if persona_hint and persona_hint != "common":
        target_folder = f"persona_{persona_hint}"

    await MemeLibrary.update_tags(
        meme_id=meme_id,
        description=tag_result["description"],
        emotion_tags=tag_result["emotion_tags"],
        scene_tags=tag_result["scene_tags"],
        persona_hint=persona_hint,
        status="tagged",
    )

    # 移动文件到目标文件夹
    await MemeLibrary.move_file(meme_id, target_folder)

    # 同步到 Qdrant
    record = await AiMemeRecord.get_by_meme_id(meme_id)
    if record is not None:
        await MemeLibrary.sync_to_qdrant(record)

    logger.info(f"[Meme] 打标完成: {meme_id} -> {target_folder}")


async def _call_tag_agent(
    image_b64: str,
    file_mime: str,
) -> Optional[dict]:
    """通过 Agent 进行图片打标

    使用 create_agent 创建临时 Agent，传入 ImageUrl。
    GsCoreAIAgent._execute_run 会自动根据模型能力决定：
    - 模型支持图片：直接传图给 LLM
    - 模型不支持图片：调用 understand_image 转述为文字

    Args:
        image_b64: Base64 编码的图片数据
        file_mime: 图片 MIME 类型

    Returns:
        解析后的标签字典，失败返回 None
    """

    # 创建临时 Agent（无工具，纯文本+图片分析）
    agent = create_agent(
        system_prompt=TAG_PROMPT,
        max_tokens=500,
        max_iterations=1,
        create_by="MemeTagger",
        task_level="low",
    )

    # 构建包含图片的用户消息（ImageUrl 会被 _execute_run 自动处理）
    img_url = f"data:{file_mime};base64,{image_b64}"
    user_message = [ImageUrl(url=img_url)]

    result = await agent.run(
        user_message=user_message,
        return_mode="return",
    )

    if not result:
        logger.warning("[Meme] Agent 返回空结果")
        return None

    # 使用 extract_json_from_text 解析
    parsed = extract_json_from_text(result)
    if not isinstance(parsed, dict):
        logger.warning("[Meme] 解析结果不是 dict")
        return None

    # 确保字段类型正确
    return {
        "description": str(parsed.get("description", "")),
        "emotion_tags": list(parsed.get("emotion_tags", [])),
        "scene_tags": list(parsed.get("scene_tags", [])),
        "persona_hint": str(parsed.get("persona_hint", "common")),
        "nsfw_score": float(parsed.get("nsfw_score", 0.0)),
    }
