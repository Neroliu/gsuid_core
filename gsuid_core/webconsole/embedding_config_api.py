"""
Embedding Config APIs

提供嵌入模型配置的 RESTful APIs
支持查看和修改嵌入模型提供方（local/openai）及其配置
"""

from typing import Any, Dict

from fastapi import Depends

from gsuid_core.webconsole.app_app import app
from gsuid_core.webconsole.web_api import require_auth
from gsuid_core.ai_core.configs.ai_config import (
    ai_config,
    local_embedding_config,
    openai_embedding_config,
)


def _string_config_to_dict(config: Any) -> Dict[str, Any]:
    """将 StringConfig 对象转换为字典用于 JSON 序列化"""
    return {
        "title": config.title,
        "desc": config.desc,
        "data": config.data,
        "options": getattr(config, "options", []),
    }


# ==================== 嵌入模型配置 ====================


@app.get("/api/embedding_config/provider")
async def get_embedding_provider(_: Dict = Depends(require_auth)) -> Dict:
    """
    获取当前嵌入模型提供方

    Returns:
        status: 0成功
        data: 当前嵌入模型提供方信息
    """
    provider = ai_config.get_config("embedding_provider").data
    return {
        "status": 0,
        "msg": "ok",
        "data": {
            "provider": provider,
            "available_providers": ["local", "openai"],
        },
    }


@app.post("/api/embedding_config/provider")
async def set_embedding_provider(data: Dict, _: Dict = Depends(require_auth)) -> Dict:
    """
    设置嵌入模型提供方

    Args:
        data: {"provider": "local" | "openai"}

    Returns:
        status: 0成功
    """
    provider = data.get("provider", "")
    if provider not in ("local", "openai"):
        return {
            "status": 1,
            "msg": f"不支持的嵌入模型提供方: '{provider}'，仅支持 'local' 或 'openai'",
            "data": None,
        }

    ai_config.set_config("embedding_provider", provider)

    # 重置嵌入提供方单例，下次使用时会重新初始化
    from gsuid_core.ai_core.rag.embedding import reset_embedding_provider

    reset_embedding_provider()

    return {
        "status": 0,
        "msg": f"嵌入模型提供方已切换为 '{provider}'，重启后生效",
        "data": {"provider": provider},
    }


@app.get("/api/embedding_config/local")
async def get_local_embedding_config(_: Dict = Depends(require_auth)) -> Dict:
    """
    获取本地嵌入模型配置

    Returns:
        status: 0成功
        data: 本地嵌入模型配置详情
    """
    config_dict = {}
    for key in local_embedding_config.config:
        config_dict[key] = _string_config_to_dict(local_embedding_config.get_config(key))

    return {
        "status": 0,
        "msg": "ok",
        "data": config_dict,
    }


@app.post("/api/embedding_config/local")
async def set_local_embedding_config(data: Dict, _: Dict = Depends(require_auth)) -> Dict:
    """
    保存本地嵌入模型配置

    Args:
        data: 配置项键值对，如 {"embedding_model_name": "BAAI/bge-small-zh-v1.5"}

    Returns:
        status: 0成功
    """
    for key, value in data.items():
        local_embedding_config.set_config(key, value)

    return {
        "status": 0,
        "msg": "本地嵌入模型配置已保存，重启后生效",
        "data": None,
    }


@app.get("/api/embedding_config/openai")
async def get_openai_embedding_config(_: Dict = Depends(require_auth)) -> Dict:
    """
    获取 OpenAI 嵌入模型配置

    Returns:
        status: 0成功
        data: OpenAI 嵌入模型配置详情
    """
    config_dict = {}
    for key in openai_embedding_config.config:
        config_dict[key] = _string_config_to_dict(openai_embedding_config.get_config(key))

    return {
        "status": 0,
        "msg": "ok",
        "data": config_dict,
    }


@app.post("/api/embedding_config/openai")
async def set_openai_embedding_config(data: Dict, _: Dict = Depends(require_auth)) -> Dict:
    """
    保存 OpenAI 嵌入模型配置

    Args:
        data: 配置项键值对，如 {"base_url": "...", "api_key": ["sk-xxx"], "embedding_model": "..."}

    Returns:
        status: 0成功
    """
    for key, value in data.items():
        openai_embedding_config.set_config(key, value)

    return {
        "status": 0,
        "msg": "OpenAI 嵌入模型配置已保存，重启后生效",
        "data": None,
    }


@app.get("/api/embedding_config/summary")
async def get_embedding_config_summary(_: Dict = Depends(require_auth)) -> Dict:
    """
    获取嵌入模型配置摘要（一次性获取所有信息）

    Returns:
        status: 0成功
        data: 嵌入模型配置摘要
    """
    provider = ai_config.get_config("embedding_provider").data

    # 本地配置
    local_config = {}
    for key in local_embedding_config.config:
        local_config[key] = _string_config_to_dict(local_embedding_config.get_config(key))

    # OpenAI 配置
    openai_config_dict = {}
    for key in openai_embedding_config.config:
        openai_config_dict[key] = _string_config_to_dict(openai_embedding_config.get_config(key))

    return {
        "status": 0,
        "msg": "ok",
        "data": {
            "provider": provider,
            "available_providers": ["local", "openai"],
            "local_config": local_config,
            "openai_config": openai_config_dict,
        },
    }
