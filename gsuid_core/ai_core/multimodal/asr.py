"""语音转文字模块（ASR）

提供统一的语音识别接口，支持多种 ASR 服务提供商。
当前支持通过 MCP 工具进行语音识别。

使用方式:
    from gsuid_core.ai_core.multimodal.asr import transcribe_audio

    text = await transcribe_audio(audio_data=b"...", format="ogg")
"""

import os
import tempfile

import aiofiles

from gsuid_core.logger import logger
from gsuid_core.ai_core.configs.ai_config import ai_config
from gsuid_core.ai_core.mcp.mcp_tool_caller import call_mcp_tool
from gsuid_core.ai_core.mcp.mcp_tools_config import mcp_tools_config


def _get_asr_provider() -> str:
    """获取当前配置的 ASR 服务提供方

    Returns:
        提供方名称，如 "MCP"
    """
    return ai_config.get_config("asr_provider").data


async def _prepare_audio_for_mcp(
    audio_data: bytes,
    audio_format: str = "ogg",
) -> str:
    """准备音频数据给 MCP 工具使用

    MCP 的 ASR 工具通常期望文件路径，需要将 bytes 保存为临时文件。

    Args:
        audio_data: 音频二进制数据
        audio_format: 音频格式（ogg/mp3/wav/m4a）

    Returns:
        临时文件路径
    """
    suffix = f".{audio_format}"
    temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(temp_fd)
    async with aiofiles.open(temp_path, "wb") as f:
        await f.write(audio_data)

    logger.debug(f"🎤 [ASR] 已保存音频到临时文件: {temp_path}")
    return temp_path


async def transcribe_audio(
    audio_data: bytes,
    audio_format: str = "ogg",
    language: str | None = None,
) -> str:
    """统一的语音转文字接口

    根据用户配置的 asr_provider 自动选择 ASR 服务。
    将音频数据转录为文本，供 AI 处理。

    Args:
        audio_data: 音频二进制数据
        audio_format: 音频格式（ogg/mp3/wav/m4a），默认 ogg
        language: 语言代码（如 "zh"、"en"），None 表示自动检测

    Returns:
        转录后的文本

    Raises:
        RuntimeError: ASR 转录失败时抛出

    Example:
        >>> text = await transcribe_audio(audio_bytes, audio_format="ogg")
        >>> print(text)
        "你好，我想问一下..."
    """
    provider = _get_asr_provider()

    if provider == "MCP":
        mcp_tool_id = mcp_tools_config.get_config("asr_mcp_tool_id").data

        if not mcp_tool_id:
            raise RuntimeError("ASR MCP 工具未配置，请前往 AI 配置页面设置 asr_mcp_tool_id")

        # 将音频数据保存为临时文件
        audio_path = await _prepare_audio_for_mcp(audio_data, audio_format)

        arguments: dict[str, str] = {"audio_source": audio_path}
        if language:
            arguments["language"] = language

        try:
            result = await call_mcp_tool(
                mcp_tool_id=mcp_tool_id,
                arguments=arguments,
            )

            if result.is_error:
                raise RuntimeError(f"ASR MCP 调用失败: {result.text}")

            return result.text
        finally:
            # 清理临时文件
            if os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                    logger.debug(f"🎤 [ASR] 已删除临时文件: {audio_path}")
                except Exception as e:
                    logger.warning(f"🎤 [ASR] 删除临时文件失败: {e}")

    # 未知 provider
    logger.warning(f"🎤 [ASR] 未知的提供方 '{provider}'，仅支持 MCP")
    raise RuntimeError(f"ASR 不支持该提供方: {provider}")
