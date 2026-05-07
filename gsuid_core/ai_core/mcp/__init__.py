"""
MCP (Model Context Protocol) 客户端模块

提供通用的 MCP 客户端功能，用于连接和调用 MCP 服务器。
基于 fastmcp 实现，支持异步操作。

支持用户通过 WebConsole API 自由添加 MCP 服务器配置，
框架启动时自动连接 MCP 服务器并将工具注册为 AI 工具。

Example:
    >>> from gsuid_core.ai_core.mcp import MCPClient
    >>> client = MCPClient(
    ...     name="MiniMax",
    ...     command="uvx",
    ...     args=["minimax-coding-plan-mcp"],
    ...     env={"MINIMAX_API_KEY": "your_key"},
    ... )
    >>> tools = await client.list_tools()
    >>> result = await client.call_tool("web_search", {"query": "Python"})
"""

from gsuid_core.ai_core.mcp.client import MCPClient, MCPToolInfo, MCPToolResult
from gsuid_core.ai_core.mcp.server import (
    get_mcp_server,
    get_mcp_trigger_count,
)
from gsuid_core.ai_core.mcp.startup import (
    unregister_mcp_server,
    register_all_mcp_tools,
    register_single_mcp_server,
)
from gsuid_core.ai_core.mcp.mcp_presets import MCP_PRESETS
from gsuid_core.ai_core.mcp.config_manager import (
    MCPConfig,
    MCPConfigManager,
    MCPToolDefinition,
    parse_mcp_tool_id,
    format_mcp_tool_id,
    mcp_config_manager,
)

__all__ = [
    "MCPClient",
    "MCPToolInfo",
    "MCPToolResult",
    "MCPConfig",
    "MCPToolDefinition",
    "MCPConfigManager",
    "MCP_PRESETS",
    "mcp_config_manager",
    "parse_mcp_tool_id",
    "format_mcp_tool_id",
    "register_all_mcp_tools",
    "register_single_mcp_server",
    "unregister_mcp_server",
    "get_mcp_server",
    "get_mcp_trigger_count",
]
