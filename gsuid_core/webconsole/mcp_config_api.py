"""
MCP Config APIs

提供 MCP 服务器配置管理的 RESTful APIs，包括增删改查、启用/禁用、热重载等。
用户可以通过这些 API 自由添加和管理 MCP 服务器配置。
所有增删改和 toggle 操作会自动触发实时工具注册/注销，无需重启服务。
"""

from typing import Any, Dict, List, Optional

from fastapi import Depends
from pydantic import BaseModel

from gsuid_core.webconsole.app_app import app
from gsuid_core.webconsole.web_api import require_auth
from gsuid_core.ai_core.mcp.startup import (
    unregister_mcp_server,
    register_all_mcp_tools,
    register_single_mcp_server,
)
from gsuid_core.ai_core.mcp.config_manager import MCPConfig, mcp_config_manager


class MCPConfigCreate(BaseModel):
    """MCP 配置创建请求模型"""

    name: str
    command: str
    args: List[str] = []
    env: Dict[str, str] = {}
    enabled: bool = True


class MCPConfigUpdate(BaseModel):
    """MCP 配置更新请求模型"""

    name: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = None


@app.get("/api/ai/mcp/list")
async def get_mcp_configs_list(
    _: Dict = Depends(require_auth),
) -> Dict[str, Any]:
    """
    获取所有 MCP 配置列表

    Returns:
        status: 0成功
        data: MCP 配置列表
    """
    configs = mcp_config_manager.list_configs()
    return {
        "status": 0,
        "msg": "ok",
        "data": {
            "configs": configs,
            "count": len(configs),
        },
    }


@app.get("/api/ai/mcp/{config_id}")
async def get_mcp_config_detail(
    config_id: str,
    _: Dict = Depends(require_auth),
) -> Dict[str, Any]:
    """
    获取指定 MCP 配置的详细信息

    Args:
        config_id: 配置 ID

    Returns:
        status: 0成功，1失败
        data: 配置详情
    """
    config = mcp_config_manager.get_config(config_id)
    if config is None:
        return {
            "status": 1,
            "msg": f"MCP 配置 '{config_id}' 不存在",
            "data": None,
        }

    data = config.to_dict()
    data["config_id"] = config_id
    return {
        "status": 0,
        "msg": "ok",
        "data": data,
    }


@app.post("/api/ai/mcp")
async def create_mcp_config(
    body: MCPConfigCreate,
    _: Dict = Depends(require_auth),
) -> Dict[str, Any]:
    """
    创建新的 MCP 配置

    Args:
        body: MCP 配置信息

    Returns:
        status: 0成功，1失败
        data: 创建结果
    """
    import re

    # 从 name 生成 config_id（转小写，特殊字符替换为下划线）
    config_id = re.sub(r"[^a-zA-Z0-9_-]", "_", body.name.lower()).strip("_")
    if not config_id:
        return {
            "status": 1,
            "msg": "无效的配置名称，无法生成 config_id",
            "data": None,
        }

    config = MCPConfig(
        name=body.name,
        command=body.command,
        args=body.args,
        env=body.env,
        enabled=body.enabled,
    )

    success, msg = mcp_config_manager.create_config(config_id, config)
    if not success:
        return {
            "status": 1,
            "msg": msg,
            "data": None,
        }

    # 实时注册 MCP 工具
    tool_count = 0
    register_msg = ""
    if config.enabled:
        tool_count, register_msg = await register_single_mcp_server(config_id)

    return {
        "status": 0,
        "msg": "ok",
        "data": {
            "config_id": config_id,
            "name": body.name,
            "tool_count": tool_count,
            "register_msg": register_msg,
        },
    }


@app.put("/api/ai/mcp/{config_id}")
async def update_mcp_config(
    config_id: str,
    body: MCPConfigUpdate,
    _: Dict = Depends(require_auth),
) -> Dict[str, Any]:
    """
    更新 MCP 配置

    Args:
        config_id: 配置 ID
        body: 要更新的字段

    Returns:
        status: 0成功，1失败
        data: 更新结果
    """
    # 过滤掉 None 字段
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    if not updates:
        return {
            "status": 1,
            "msg": "没有提供要更新的字段",
            "data": None,
        }

    success, msg = mcp_config_manager.update_config(config_id, updates)
    if not success:
        return {
            "status": 1,
            "msg": msg,
            "data": None,
        }

    # 实时重新注册 MCP 工具（配置变更后重新连接服务器）
    tool_count, register_msg = await register_single_mcp_server(config_id)

    return {
        "status": 0,
        "msg": "ok",
        "data": {
            "config_id": config_id,
            "tool_count": tool_count,
            "register_msg": register_msg,
        },
    }


@app.delete("/api/ai/mcp/{config_id}")
async def delete_mcp_config(
    config_id: str,
    _: Dict = Depends(require_auth),
) -> Dict[str, Any]:
    """
    删除 MCP 配置

    Args:
        config_id: 配置 ID

    Returns:
        status: 0成功，1失败
        data: 删除结果
    """
    # 先注销已注册的 MCP 工具
    removed_count = await unregister_mcp_server(config_id)

    success, msg = mcp_config_manager.delete_config(config_id)
    if not success:
        return {
            "status": 1,
            "msg": msg,
            "data": None,
        }

    return {
        "status": 0,
        "msg": "ok",
        "data": {
            "config_id": config_id,
            "removed_tool_count": removed_count,
        },
    }


@app.post("/api/ai/mcp/{config_id}/toggle")
async def toggle_mcp_config(
    config_id: str,
    _: Dict = Depends(require_auth),
) -> Dict[str, Any]:
    """
    切换 MCP 配置的启用/禁用状态

    Args:
        config_id: 配置 ID

    Returns:
        status: 0成功，1失败
        data: 切换后的状态
    """
    config = mcp_config_manager.get_config(config_id)
    if config is None:
        return {
            "status": 1,
            "msg": f"MCP 配置 '{config_id}' 不存在",
            "data": None,
        }

    new_enabled = not config.enabled
    success, msg = mcp_config_manager.update_config(config_id, {"enabled": new_enabled})
    if not success:
        return {
            "status": 1,
            "msg": msg,
            "data": None,
        }

    # 实时注册或注销 MCP 工具
    if new_enabled:
        tool_count, register_msg = await register_single_mcp_server(config_id)
    else:
        removed_count = await unregister_mcp_server(config_id)
        tool_count = 0
        register_msg = f"已禁用，移除了 {removed_count} 个工具"

    return {
        "status": 0,
        "msg": "ok",
        "data": {
            "config_id": config_id,
            "enabled": new_enabled,
            "tool_count": tool_count,
            "register_msg": register_msg,
        },
    }


@app.post("/api/ai/mcp/reload")
async def reload_mcp_configs(
    _: Dict = Depends(require_auth),
) -> Dict[str, Any]:
    """
    热重载所有 MCP 配置并重新注册工具

    重新加载配置文件，并重新连接所有启用的 MCP 服务器注册工具。
    此操作会清除已注册的 MCP 工具并重新注册。

    Returns:
        status: 0成功
        data: 重载结果
    """
    from gsuid_core.ai_core.register import _TOOL_REGISTRY
    from gsuid_core.ai_core.mcp.startup import MCP_CATEGORY

    # 清除已注册的 MCP 工具
    if MCP_CATEGORY in _TOOL_REGISTRY:
        old_count = len(_TOOL_REGISTRY[MCP_CATEGORY])
        _TOOL_REGISTRY[MCP_CATEGORY].clear()
    else:
        old_count = 0

    # 重新加载配置
    mcp_config_manager.reload()

    # 重新注册工具
    await register_all_mcp_tools()

    new_count = len(_TOOL_REGISTRY.get(MCP_CATEGORY, {}))

    return {
        "status": 0,
        "msg": "ok",
        "data": {
            "old_tool_count": old_count,
            "new_tool_count": new_count,
            "config_count": len(mcp_config_manager.list_configs()),
        },
    }
