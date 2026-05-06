import re
import json
import asyncio
from typing import Any, Literal, Optional, Sequence

from PIL import Image
from json_repair import repair_json
from pydantic_ai.messages import ImageUrl, UserContent

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import Message, MessageSegment
from gsuid_core.utils.image.convert import convert_img
from gsuid_core.utils.resource_manager import RM


def extract_json_from_text(raw_text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw_text).strip()
    cleaned = repair_json(cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
        if match:
            stripped = match.group(0).strip()
            cl = repair_json(stripped)
            data = json.loads(cl)
        else:
            raise
    return data


async def handle_tool_result(bot: Optional[Bot], result: Any, max_length: int = 4000) -> str:
    """
    序列化工具执行结果, 当函数返回Message对象时调用Bot.send方法发送, 并将序列化后的字符串返回方便AI识别。

    Args:
        bot: Bot 对象
        result: 工具函数返回的结果
        max_length: 最大返回长度，超长会被截断

    Returns:
        序列化的字符串
    """
    if isinstance(result, Message):
        a = "生成内容成功!"
        if bot is not None:
            await bot.send(result)
            a += ", 已经发送了相关消息！"
        else:
            a += ", 由于没有Bot对象, 未发送相关消息！"
        return a
    elif isinstance(result, str):
        res_str = result
    elif isinstance(result, dict):
        res_str = json.dumps(result, ensure_ascii=False)
    elif isinstance(result, Image.Image):
        img_bytes = await convert_img(result)
        a = f"生成了图片资源, 资源ID: {RM.register(img_bytes)}"
        if bot is not None:
            await bot.send(img_bytes)
            a += ", 已经发送了相关资源！"
        else:
            a += ", 由于没有Bot对象, 未发送相关资源！"
        return a
    elif isinstance(result, bytes):
        a = f"生成了某项资源, 资源ID: {RM.register(result)}"
        if bot is not None:
            await bot.send(result)
            a += ", 已经发送了相关资源！"
        else:
            a += ", 由于没有Bot对象, 未发送相关资源！"
        return a
    elif isinstance(result, list):
        res_str = json.dumps(result, ensure_ascii=False)
    elif hasattr(result, "model_dump_json"):
        # Pydantic v2
        res_str = result.model_dump_json()
    elif hasattr(result, "json"):
        # Pydantic v1
        res_str = result.json()
    else:
        res_str = str(result)

    # 截断过长的返回值，防止 Token 爆炸
    if len(res_str) > max_length:
        return res_str[:max_length] + f"\n...[系统截断: 省略后 {len(res_str) - max_length} 字符]"
    return res_str


def _normalize_image_url(raw: str) -> str:
    """将各种图片格式统一转为可消费的 URL（HTTP 或 DataURI）

    Args:
        raw: 原始图片标识，支持 http/https URL、base64:// 前缀、data:image/ 前缀、裸 base64

    Returns:
        标准化的图片 URL
    """
    if raw.startswith(("http", "https")):
        return raw
    if raw.startswith("base64://"):
        return f"data:image/png;base64,{raw[10:]}"
    if raw.startswith("data:image/"):
        return raw
    return f"data:image/png;base64,{raw}"


def _build_relationship_description(
    favorability: Optional[int],
    user_name: Optional[str],
    user_id: str,
) -> str:
    """将好感度转换为有温度的关系描述，而非机械的区间标签"""
    name = user_name or user_id

    if favorability is None:
        return f"{name} 找你说话了。"

    if favorability < 0:
        return f"{name} 又来了。"
    elif favorability < 20:
        return f"{name} 来找你了，你们不太熟。"
    elif favorability < 50:
        return f"{name} 找你说话，见过几次面的那种。"
    elif favorability < 75:
        return f"{name} 找你了，算是熟人了。"
    else:
        return f"{name} 找你说话了，你们挺熟的。"


async def prepare_content_payload(
    ev: Event,
    task_level: Literal["high", "low"] = "high",
    favorability: Optional[int] = None,
    favorability_zone: Optional[str] = None,
) -> Sequence[UserContent]:
    """
    准备消息内容列表给AI看, 包含文本、图片ID、文件内容、事件对象

    图片处理由 GsCoreAIAgent._execute_run 自动完成：
    - 模型支持图片时直接传图
    - 模型不支持图片时通过 understand_image 转述为文字

    Args:
        ev: 事件对象
        task_level: 任务级别
        favorability: 当前用户好感度 (可选)
        favorability_zone: 好感度区间描述 (可选)

    Returns:
        content payload 列表（可能包含 ImageUrl，由 _execute_run 自动处理）
    """
    content_payload: list[UserContent] = []

    # 获取用户昵称
    nickname = None
    if ev.sender:
        nickname = ev.sender.get("nickname") or ev.sender.get("card") or None

    # 叙事性关系描述（Bug-01 + Prompt-2.2: 替代数字+区间标签）
    relationship_desc = _build_relationship_description(favorability, nickname, str(ev.user_id))
    current_turn_header = f"{relationship_desc}\n"

    # @状态：只在被@时才注入（潜在-01: 修正 is_at_me → is_tome）
    is_at_me = getattr(ev, "is_tome", False) or (ev.user_type == "direct")
    if is_at_me:
        current_turn_header += "（直接找你说的）\n"

    current_turn_header += "--- 消息 ---\n"

    text = current_turn_header
    if not ev.text:
        text += "用户没有发送文本内容。"
    else:
        text += ev.text.strip()

    # 预处理, 将用户发送的文本/AT/图片ID等信息整合到一个字符串中, 方便AI处理
    for i in ev.image_id_list:
        text += f"\n--- 用户上传图片ID: {i} ---\n"

    for at in ev.at_list:
        text += f"\n--- 提及用户(@用户): {at} ---\n"

    content_payload.append(text)

    # 处理用户图片消息（直接附加 ImageUrl，由 _execute_run 自动处理能力判断）
    for i in ev.image_list:
        if isinstance(i, str):
            content_payload.append(ImageUrl(url=_normalize_image_url(i)))
        else:
            logger.warning(f"无法处理图片ID: {i}")

    return content_payload


async def send_chat_result(bot: Bot, chat_result: str):
    """
    解析并发送 chat_result，支持：
    - 按换行分割多条消息
    - @用户ID 语法 → MessageSegment.at(user_id)
    """
    if not chat_result:
        return

    # 按换行分割为多条消息
    blocks = re.split(r"\n\s*\n", chat_result.strip())

    for block in blocks:
        if not block.strip():
            continue

        segments = _parse_at_segments(block)

        # 计算纯文本长度
        plain_text = re.sub(r"@\d+", "", block)

        # 模拟打字延迟（见下方的优化建议）
        delay = min(max(len(plain_text) / 7, 0.5), 3.0)
        await asyncio.sleep(delay)

        await bot.send(segments)


def _parse_at_segments(text: str) -> list[Message]:
    """
    将含有 @用户ID 的文本解析为 MessageSegment 列表。

    规则：
    - @后跟纯数字（QQ号格式）才会被解析为 at segment
    - 其余文本保持为 text segment
    - 示例输入："好哦 @444835641 你来看"
    - 示例输出：[Text("好哦 "), At(444835641), Text(" 你来看")]
    """
    # 匹配 @数字，前后允许空格（空格属于分隔符，不计入文本内容）
    pattern = re.compile(r"\s*@(\d+)\s*")
    segments: list[Message] = []
    last_end = 0

    for match in pattern.finditer(text):
        # 匹配前的普通文本
        before = text[last_end : match.start()]
        if before:
            segments.append(MessageSegment.text(before))

        # @ 片段
        user_id = match.group(1)
        segments.append(MessageSegment.at(user_id))

        last_end = match.end()

    # 剩余文本
    tail = text[last_end:]
    if tail:
        segments.append(MessageSegment.text(tail))

    # 如果没有任何 @ 匹配，直接返回原始字符串（兼容旧调用）
    if not segments:
        return [MessageSegment.text(text)]

    return segments
