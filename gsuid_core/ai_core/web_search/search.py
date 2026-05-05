"""
Web Search 公共 API 模块

提供统一的 web 搜索接口，根据用户配置自动选择搜索引擎（Tavily / Exa / MCP）。
外部模块应通过本模块的函数调用搜索，无需关心底层搜索引擎的实现细节。
"""

from gsuid_core.logger import logger
from gsuid_core.ai_core.configs.ai_config import ai_config
from gsuid_core.ai_core.mcp.mcp_tool_caller import call_mcp_tool
from gsuid_core.ai_core.mcp.mcp_tools_config import mcp_tools_config

from .exa_search import exa_search
from .tavily_search import (
    tavily_search,
    tavily_search_with_context,
)


def _get_provider() -> str:
    """
    获取当前配置的搜索引擎提供方

    Returns:
        搜索引擎名称，如 "Tavily"、"Exa" 或 "MCP"
    """
    return ai_config.get_config("websearch_provider").data


async def _mcp_search(query: str, max_results: int | None = None) -> list[dict]:
    """
    使用 MCP 进行 web 搜索

    Args:
        query: 搜索查询关键词
        max_results: 最大返回结果数量

    Returns:
        搜索结果列表
    """
    mcp_tool_id = mcp_tools_config.get_config("websearch_mcp_tool_id").data

    if not mcp_tool_id:
        raise RuntimeError("Web Search MCP 工具未配置，请前往 AI 配置页面设置")

    arguments: dict[str, str | int] = {"query": query}
    if max_results is not None:
        arguments["max_results"] = max_results

    result = await call_mcp_tool(mcp_tool_id=mcp_tool_id, arguments=arguments)

    if result.is_error:
        raise RuntimeError(f"Web Search MCP 调用失败: {result.text}")

    return _parse_mcp_search_result(result.text, max_results)


def _parse_mcp_search_result(raw_text: str, max_results: int | None = None) -> list[dict]:
    """
    解析 MCP web search 返回的原始文本为结构化结果

    Args:
        raw_text: MCP 返回的原始文本
        max_results: 最大结果数

    Returns:
        搜索结果列表
    """
    import json

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning(f"🌐 [WebSearch][MCP] 解析 JSON 失败，原始文本: {raw_text[:200]}...")
        return []

    # 调试日志：打印原始返回数据
    logger.debug(f"🌐 [WebSearch][MCP] 原始返回数据: {raw_text[:500]}...")

    # 尝试解析为结果列表
    # MiniMax MCP 返回格式可能是 {"organic": [...]} 或 {"results": [...]} 或直接是 [...]
    if isinstance(data, list):
        results = data
    elif isinstance(data, dict):
        if "organic" in data:
            results = data["organic"]
        elif "results" in data:
            results = data["results"]
        else:
            results = [data]
    else:
        results = [data]

    # 限制结果数量
    if max_results is not None and len(results) > max_results:
        results = results[:max_results]

    # 标准化结果格式
    normalized: list[dict] = []
    for item in results:
        if isinstance(item, dict):
            normalized.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", item.get("snippet", "")),
                    "score": item.get("score", 0.0),
                }
            )
        else:
            normalized.append({"title": str(item), "url": "", "content": "", "score": 0.0})

    return normalized


async def web_search(
    query: str,
    max_results: int | None = None,
) -> list[dict]:
    """
    统一的 web 搜索接口

    根据用户配置的 websearch_provider 自动选择搜索引擎。

    Args:
        query: 搜索查询关键词
        max_results: 最大返回结果数量，默认由各搜索引擎配置决定

    Returns:
        搜索结果列表，每条包含 title、url、content、score 等字段

    Example:
        >>> results = await web_search("Python 教程")
        >>> for r in results:
        ...     print(r["title"], r["url"])
    """
    provider = _get_provider()

    if provider == "Exa":
        return await exa_search(query=query, max_results=max_results)

    if provider == "MCP":
        return await _mcp_search(query=query, max_results=max_results)

    # 默认使用 Tavily
    return await tavily_search(query=query, max_results=max_results)


async def web_search_with_context(
    query: str,
    max_results: int = 5,
) -> dict:
    """
    统一的带上下文 web 搜索接口

    根据用户配置的 websearch_provider 自动选择搜索引擎。
    该方法会同时返回搜索结果和 AI 生成的摘要答案（如果搜索引擎支持）。

    Args:
        query: 搜索查询关键词
        max_results: 最大返回结果数量，默认5条

    Returns:
        包含 results(结果列表) 和 answer(AI摘要) 的字典
    """
    provider = _get_provider()

    if provider == "Exa":
        results = await exa_search(query=query, max_results=max_results)
        return {"results": results, "answer": None}

    if provider == "MCP":
        results = await _mcp_search(query=query, max_results=max_results)
        return {"results": results, "answer": None}

    # 默认使用 Tavily
    return await tavily_search_with_context(query=query, max_results=max_results)
