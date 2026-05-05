"""表情包消息流监听器

MemeObserver 接入 handle_ai.py 消息预处理，
识别群聊中的图片消息并异步入队过滤。
"""

import io
import asyncio
from typing import List, Optional

import httpx
from PIL import Image

from gsuid_core.pool import to_thread
from gsuid_core.models import Event
from gsuid_core.ai_core.meme.config import meme_config


def _extract_image_urls(ev: Event) -> List[str]:
    """从事件中提取图片 URL 列表

    Args:
        ev: 事件对象

    Returns:
        图片 URL 列表
    """
    image_urls: List[str] = []

    for segment in ev.content:
        if segment.type == "image" and isinstance(segment.data, str):
            # segment.data 可能是 "link://http://..." 或 "base64://..."
            if segment.data.startswith("link://"):
                image_urls.append(segment.data[7:])
            # base64 图片不处理（无法下载）

    return image_urls


async def _download_image(url: str) -> Optional[tuple[bytes, str]]:
    """下载图片并获取 MIME 类型

    Args:
        url: 图片 URL

    Returns:
        (图片数据, MIME 类型) 或 None
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return None

            content_type = response.headers.get("content-type", "")
            # 提取 MIME 类型
            mime = content_type.split(";")[0].strip().lower()
            if not mime.startswith("image/"):
                # 尝试从 URL 推断
                url_lower = url.lower()
                if url_lower.endswith((".jpg", ".jpeg")):
                    mime = "image/jpeg"
                elif url_lower.endswith(".png"):
                    mime = "image/png"
                elif url_lower.endswith(".gif"):
                    mime = "image/gif"
                elif url_lower.endswith(".webp"):
                    mime = "image/webp"
                else:
                    return None

            return response.content, mime

    except httpx.HTTPError:
        return None


@to_thread
def _get_image_dimensions(image_data: bytes) -> tuple[int, int]:
    """获取图片尺寸（同步，通过 to_thread 异步化）

    Args:
        image_data: 图片二进制数据

    Returns:
        (宽度, 高度)
    """
    img = Image.open(io.BytesIO(image_data))
    return img.size


async def observe_message_for_memes(ev: Event, persona_name: str) -> None:
    """监听消息中的图片并异步入队

    此函数在 handle_ai.py 的消息预处理阶段调用，
    在 AI 调用之前执行，不阻塞主流程。

    Args:
        ev: 事件对象
        persona_name: 当前 persona 名称
    """
    # 总开关检查
    if not meme_config.get_config("meme_enable").data:
        return
    if not meme_config.get_config("meme_auto_collect").data:
        return

    # 只处理群聊消息
    if not ev.group_id:
        return

    # 提取图片 URL
    image_urls = _extract_image_urls(ev)
    if not image_urls:
        return

    # 限制每次最多处理 5 张图片
    for url in image_urls[:5]:
        asyncio.create_task(
            _process_image(
                url=url,
                source_group=ev.group_id,
                source_user=ev.user_id,
            )
        )


async def _process_image(
    url: str,
    source_group: str,
    source_user: str,
) -> None:
    """处理单张图片：下载 -> 获取尺寸 -> 入队过滤

    Args:
        url: 图片 URL
        source_group: 来源群组 ID
        source_user: 来源用户 ID
    """
    from gsuid_core.ai_core.meme.filter import MemeFilter

    # 下载图片
    result = await _download_image(url)
    if result is None:
        return

    image_data, file_mime = result

    # 获取图片尺寸（通过 to_thread 异步化）
    width, height = await _get_image_dimensions(image_data)

    # 入队过滤
    await MemeFilter.enqueue(
        image_data=image_data,
        file_mime=file_mime,
        width=width,
        height=height,
        source_group=source_group,
        source_user=source_user,
        source_url=url,
    )
