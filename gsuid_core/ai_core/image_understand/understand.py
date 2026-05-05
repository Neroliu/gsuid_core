"""
Image Understand 公共 API 模块

提供统一的图片理解接口，根据用户配置自动选择图片理解服务提供商（MCP）。
外部模块应通过本模块的函数调用图片理解，无需关心底层实现细节。
"""

import os
import base64
import tempfile

import aiofiles

from gsuid_core.logger import logger
from gsuid_core.ai_core.configs.ai_config import ai_config
from gsuid_core.ai_core.mcp.mcp_tool_caller import call_mcp_tool
from gsuid_core.ai_core.mcp.mcp_tools_config import mcp_tools_config


def _get_provider() -> str:
    """
    获取当前配置的图片理解服务提供方

    Returns:
        提供方名称，如 "MCP"
    """
    return ai_config.get_config("image_understand_provider").data


async def _prepare_image_for_mcp(image_url: str) -> str:
    """
    准备图片数据给 MCP 工具使用

    MiniMax MCP 的 understand_image 工具期望文件路径，不是 base64 或 URL。
    如果是 base64 DataURI，需要先保存为临时文件。

    Args:
        image_url: 图片来源，支持 HTTP/HTTPS URL、base64 DataURI 或文件路径

    Returns:
        文件路径（临时文件路径或原始 URL/路径）
    """
    # 如果已经是 HTTP/HTTPS URL 或文件路径，直接返回
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url

    if os.path.exists(image_url):
        return image_url

    # 如果是 base64 DataURI 格式，保存为临时文件
    if image_url.startswith("data:"):
        # 解析 DataURI 格式: data:image/png;base64,xxxxx
        if ";base64," in image_url:
            header, b64_data = image_url.split(";base64,", 1)
            # 提取 MIME 类型
            mime_type = header.replace("data:", "")
            # 解码 base64
            image_bytes = base64.b64decode(b64_data)

            # 创建临时文件
            suffix = ".png"
            if mime_type == "image/jpeg":
                suffix = ".jpg"
            elif mime_type == "image/gif":
                suffix = ".gif"
            elif mime_type == "image/webp":
                suffix = ".webp"

            temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
            os.close(temp_fd)
            async with aiofiles.open(temp_path, "wb") as f:
                await f.write(image_bytes)

            logger.debug(f"🖼️ [ImageUnderstand] 已保存图片到临时文件: {temp_path}")
            return temp_path

    # 其他情况直接返回
    return image_url


async def understand_image(
    image_url: str,
    prompt: str | None = None,
) -> str:
    """
    统一的图片理解接口

    根据用户配置的 image_understand_provider 自动选择图片理解服务。
    将图片内容转述为文本描述，供不支持图片的 LLM 模型使用。

    Args:
        image_url: 图片来源，支持 HTTP/HTTPS URL、base64 DataURI 或文件路径
        prompt: 对图片的提问或分析要求，默认为通用描述

    Returns:
        图片内容的文本描述

    Raises:
        RuntimeError: 图片理解失败时抛出

    Example:
        >>> description = await understand_image("https://example.com/image.png")
        >>> print(description)
        "这是一张风景照片，画面中有一座山..."
    """
    if not prompt:
        prompt = "请详细描述这张图片的内容，包括主要对象、场景、文字、颜色等信息。"

    provider = _get_provider()

    if provider == "MCP":
        mcp_tool_id = mcp_tools_config.get_config("image_understand_mcp_tool_id").data

        if not mcp_tool_id:
            raise RuntimeError("Image Understand MCP 工具未配置，请前往 AI 配置页面设置")

        # MiniMax MCP 的 understand_image 工具期望文件路径
        # 需要将图片数据保存为临时文件
        image_source = await _prepare_image_for_mcp(image_url)

        arguments = {
            "image_source": image_source,
            "prompt": prompt,
        }

        try:
            result = await call_mcp_tool(mcp_tool_id=mcp_tool_id, arguments=arguments)

            if result.is_error:
                raise RuntimeError(f"Image Understand MCP 调用失败: {result.text}")

            return result.text
        finally:
            # 清理临时文件
            if image_source != image_url and os.path.exists(image_source):
                try:
                    os.unlink(image_source)
                    logger.debug(f"🖼️ [ImageUnderstand] 已删除临时文件: {image_source}")
                except Exception as e:
                    logger.warning(f"🖼️ [ImageUnderstand] 删除临时文件失败: {e}")

    # 未知 provider
    logger.warning(f"🖼️ [ImageUnderstand] 未知的提供方 '{provider}'，仅支持 MCP")
    raise RuntimeError(f"Image Understand 不支持该提供方: {provider}")
