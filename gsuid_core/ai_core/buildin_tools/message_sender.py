"""
消息发送工具模块

提供主动向用户发送消息的能力，支持文本消息和图片消息。
"""

from typing import TYPE_CHECKING, List, Optional, cast

from pydantic_ai import RunContext

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Message
from gsuid_core.segment import MessageSegment
from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.register import ai_tools
from gsuid_core.utils.resource_manager import RM

if TYPE_CHECKING:
    pass


@ai_tools(category="self")
async def send_message_by_ai(
    ctx: RunContext[ToolContext],
    text: str = "",
    image_id: str = "",
    user_id: Optional[str] = None,
) -> str:
    """
    主动发送消息给用户

    支持发送文本消息、图片消息，或两者同时发送。
    AI 可以任意传入 text 和/或 image_id，系统会按顺序发送。

    Args:
        ctx: 工具执行上下文（包含bot和ev对象）
        text: 文本内容，可选
        image_id: 图片资源ID，可选，格式通常为"res_xxxxxx"或"img_xxxxx"
        user_id: 可选，目标用户ID，默认为事件关联的用户

    Returns:
        发送结果描述字符串

    Example:
        >>> await send_message_by_ai(ctx, text="你好！这是一条主动消息。")
        >>> await send_message_by_ai(ctx, text="提醒你...", user_id="123456")
        >>> await send_message_by_ai(ctx, image_id="res_abc123")
        >>> await send_message_by_ai(ctx, text="这是你要的图片！", image_id="res_abc123")
    """
    tool_ctx: ToolContext = ctx.deps
    bot: Optional[Bot] = tool_ctx.bot

    if bot is None:
        logger.warning("🧠 [BuildinTools] send_message_by_ai: Bot对象为空，无法发送消息")
        return "发送失败：Bot对象不可用"

    if not text and not image_id:
        return "发送失败：text 和 image_id 至少提供一个"

    target_id = user_id or getattr(tool_ctx.ev, "user_id", None) or getattr(tool_ctx.ev, "散列id", None)

    try:
        parts: List[Message] = []
        if text:
            parts.append(MessageSegment.text(text))
        if image_id:
            # 资源ID（如 img_xxxxxxxx）需要通过 RM 获取实际图片数据
            if image_id.startswith("http") or image_id.startswith("base64://"):
                parts.append(MessageSegment.image(image_id))
            else:
                try:
                    logger.debug(f"🧠 [BuildinTools] 调用 RM.get('{image_id}')")
                    img_data = await RM.get(image_id)
                    logger.debug(f"🧠 [BuildinTools] RM.get 成功, img_data type={type(img_data)}")
                    parts.append(MessageSegment.image(img_data))
                except ValueError as e:
                    logger.warning(f"🧠 [BuildinTools] RM.get({image_id}) 抛出 ValueError: {e}")
                    # 区分"资源不存在"和"资源转换失败"
                    if "找不到资源" in str(e):
                        return f"❌ 找不到资源ID: {image_id}，可能已过期或ID不正确。"
                    else:
                        return f"❌ 资源ID: {image_id} 数据转换失败: {e}"

        if len(parts) == 1:
            await bot.send(parts[0])
        else:
            await bot.send(cast(Message, parts))

        content_desc = []
        if text:
            content_desc.append("文本")
        if image_id:
            content_desc.append(f"图片({image_id})")
        logger.info(f"🧠 [BuildinTools] 发送 {'+'.join(content_desc)} 给用户 {target_id}")
        return f"消息已发送给用户 {target_id}"

    except Exception as e:
        logger.exception(f"🧠 [BuildinTools] send_message_by_ai 发送消息失败: {e}")
        return f"发送失败：{str(e)}"
