"""
Image Understand 模块

提供统一的图片理解接口，将图片内容转述为文本描述。
支持多种图片理解服务提供商（目前支持 MiniMax）。

当 LLM 模型不支持图片输入时，可调用本模块将图片转述为文本后再发送给 LLM。
"""

from gsuid_core.ai_core.image_understand.understand import understand_image

__all__ = ["understand_image"]
