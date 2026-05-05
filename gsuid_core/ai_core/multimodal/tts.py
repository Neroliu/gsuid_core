"""文字转语音模块（TTS）

提供统一的语音合成接口，支持多种 TTS 服务提供商。
用于 Persona 的声音表达，让 AI 回复可以以语音形式发送。

使用方式:
    from gsuid_core.ai_core.multimodal.tts import synthesize_speech

    audio_bytes = await synthesize_speech(text="你好呀", voice="default")
"""

import os
import base64

import aiofiles

from gsuid_core.logger import logger
from gsuid_core.ai_core.configs.ai_config import ai_config
from gsuid_core.ai_core.mcp.mcp_tool_caller import call_mcp_tool
from gsuid_core.ai_core.mcp.mcp_tools_config import mcp_tools_config


def _get_tts_provider() -> str:
    """获取当前配置的 TTS 服务提供方

    Returns:
        提供方名称，如 "MCP"
    """
    return ai_config.get_config("tts_provider").data


async def synthesize_speech(
    text: str,
    voice: str | None = None,
    speed: float = 1.0,
    output_format: str = "mp3",
) -> bytes:
    """统一的文字转语音接口

    根据用户配置的 tts_provider 自动选择 TTS 服务。
    将文本合成为语音音频数据。

    Args:
        text: 要合成的文本内容
        voice: 语音角色名称（如 "alloy"、"nova"），None 使用默认语音
        speed: 语速倍率，范围 0.25-4.0，默认 1.0
        output_format: 输出音频格式（mp3/ogg/wav），默认 mp3

    Returns:
        合成后的音频二进制数据

    Raises:
        RuntimeError: TTS 合成失败时抛出

    Example:
        >>> audio = await synthesize_speech("你好呀，今天天气真好")
        >>> await bot.send(audio)  # 发送语音消息
    """
    provider = _get_tts_provider()

    if provider == "MCP":
        mcp_tool_id = mcp_tools_config.get_config("tts_mcp_tool_id").data

        if not mcp_tool_id:
            raise RuntimeError("TTS MCP 工具未配置，请前往 AI 配置页面设置 tts_mcp_tool_id")

        arguments: dict[str, str | float] = {
            "text": text,
            "output_format": output_format,
        }
        if voice:
            arguments["voice"] = voice
        if speed != 1.0:
            arguments["speed"] = speed

        result = await call_mcp_tool(
            mcp_tool_id=mcp_tool_id,
            arguments=arguments,
        )

        if result.is_error:
            raise RuntimeError(f"TTS MCP 调用失败: {result.text}")

        # MCP 工具返回的可能是文件路径或 base64 编码的音频数据
        return await _parse_tts_result(result.text)

    # 未知 provider
    logger.warning(f"🔊 [TTS] 未知的提供方 '{provider}'，仅支持 MCP")
    raise RuntimeError(f"TTS 不支持该提供方: {provider}")


async def _parse_tts_result(result_text: str) -> bytes:
    """解析 TTS MCP 工具的返回结果

    MCP 工具可能返回以下格式之一：
    1. 文件路径 -> 读取文件内容
    2. data:audio/mp3;base64,xxxxx 格式的 DataURI -> 解码 base64 部分
    3. 纯 base64 编码的音频数据 -> 解码

    通过前缀检测和路径存在性判断来确定格式，不使用 try-except 兜底。

    Args:
        result_text: MCP 工具返回的文本

    Returns:
        音频二进制数据

    Raises:
        RuntimeError: 无法识别返回格式时抛出
    """
    stripped = result_text.strip()

    # 情况1: 返回的是文件路径（存在且是文件）
    if os.path.isfile(stripped):
        async with aiofiles.open(stripped, "rb") as f:
            return await f.read()

    # 情况2: 返回的是 DataURI 格式 (data:audio/mp3;base64,xxxxx)
    if stripped.startswith("data:audio/") and ";base64," in stripped:
        _, b64_data = stripped.split(";base64,", 1)
        return base64.b64decode(b64_data)

    # 情况3: 返回的是纯 base64 编码数据
    # base64 字符集: A-Z, a-z, 0-9, +, /, =（填充符）
    # 有效 base64 长度必须是 4 的倍数（去除空白后）
    if stripped and len(stripped) % 4 == 0:
        valid_base64_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r ")
        if all(c in valid_base64_chars for c in stripped):
            decoded = base64.b64decode(stripped.replace("\n", "").replace("\r", ""))
            # 验证是否是有效的音频数据（至少 100 字节）
            if len(decoded) > 100:
                return decoded

    raise RuntimeError(f"无法解析 TTS 返回结果: {result_text[:200]}")
