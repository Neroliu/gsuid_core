"""
MCP 工具配置模块

管理 web_search 和 image_understand 使用的 MCP 工具配置。
配置 ID 格式为 "{mcp_id} - {tool_name}"，例如 "minimax - web_search"。

存储在 data/ai_core/mcp_tools_config.json
"""

from typing import Dict

from gsuid_core.data_store import get_res_path
from gsuid_core.utils.plugins_config.models import GSC, GsStrConfig
from gsuid_core.utils.plugins_config.gs_config import StringConfig

MCP_TOOLS_CONFIG: Dict[str, GSC] = {
    "websearch_mcp_tool_id": GsStrConfig(
        "Web Search MCP 工具",
        "指定 Web Search 使用的 MCP 工具，格式为 '{mcp_id} - {tool_name}'，例如 'minimax - web_search'",
        "",
    ),
    "image_understand_mcp_tool_id": GsStrConfig(
        "Image Understand MCP 工具",
        "指定图片理解使用的 MCP 工具，格式为 '{mcp_id} - {tool_name}'，例如 'minimax - understand_image'",
        "",
    ),
}

mcp_tools_config = StringConfig(
    "GsCore AI MCP 工具配置",
    get_res_path("ai_core") / "mcp_tools_config.json",
    MCP_TOOLS_CONFIG,
)
