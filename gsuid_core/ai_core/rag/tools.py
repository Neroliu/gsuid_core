"""工具向量存储 - 管理工具的入库和检索"""

from typing import TYPE_CHECKING, Any, Set, Dict, List, Union

from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    VectorParamsDiff,
)

from gsuid_core.logger import logger
from gsuid_core.ai_core.models import ToolBase, ToolContext
from gsuid_core.ai_core.register import get_all_tools, get_registered_tools

if TYPE_CHECKING:
    from pydantic_ai.tools import Tool
from .base import (
    DIMENSION,
    TOOLS_COLLECTION_NAME,
    get_point_id,
    calculate_hash,
)

if TYPE_CHECKING:
    ToolList = List["Tool[ToolContext]"]
else:
    ToolList = List[Any]


async def init_tools_collection():
    """初始化工具向量集合"""
    from gsuid_core.ai_core.rag.base import client

    if client is None:
        return

    if not await client.collection_exists(TOOLS_COLLECTION_NAME):
        logger.info(f"🧠 [Tools] 初始化新集合: {TOOLS_COLLECTION_NAME}")
        await client.create_collection(
            collection_name=TOOLS_COLLECTION_NAME,
            vectors_config=VectorParams(size=DIMENSION, distance=Distance.COSINE, on_disk=True),
            on_disk_payload=True,
        )
    else:
        # 已存在的 collection：尝试迁移向量到磁盘存储
        try:
            col_info = await client.get_collection(collection_name=TOOLS_COLLECTION_NAME)
            vectors_config = col_info.config.params.vectors
            # 单向量模式：检查 on_disk 状态
            if isinstance(vectors_config, VectorParams) and not vectors_config.on_disk:
                logger.info(f"🧠 [Tools] 迁移集合 {TOOLS_COLLECTION_NAME} 向量到磁盘存储...")
                await client.update_collection(
                    collection_name=TOOLS_COLLECTION_NAME,
                    vectors_config={"": VectorParamsDiff(on_disk=True)},
                )
                logger.info(f"🧠 [Tools] 集合 {TOOLS_COLLECTION_NAME} 迁移完成")
        except Exception as e:
            logger.warning(f"🧠 [Tools] 检查/迁移集合 on_disk 配置失败: {e}")


async def sync_tools(tools_map: Dict[str, ToolBase]) -> None:
    """同步工具到向量库（增量更新）

    Args:
        tools_map: 工具字典，key为工具名称，value为工具信息
    """
    from gsuid_core.ai_core.rag.base import client, embedding_model

    if client is None or embedding_model is None:
        logger.debug("🧠 [Tools] AI功能未启用，跳过工具同步")
        return

    logger.info("🧠 [Tools] 开始同步工具库...")

    # 1. 获取向量库中现有工具
    existing_tools: Dict[str, dict] = {}
    next_page_offset = None

    while True:
        records, next_page_offset = await client.scroll(
            collection_name=TOOLS_COLLECTION_NAME,
            limit=100,
            with_payload=True,
            with_vectors=False,
            offset=next_page_offset,
        )
        for record in records:
            if record.payload is None:
                continue
            tool_name = record.payload.get("name")
            if tool_name:
                existing_tools[tool_name] = {
                    "id": record.id,
                    "hash": record.payload.get("_hash"),
                }
        if next_page_offset is None:
            break

    # 2. 准备要写入的工具
    points_to_upsert = []
    local_tool_names: Set[str] = set(tools_map.keys())

    for tool_name, tool in tools_map.items():
        # 计算哈希
        tool_dict = {"name": tool.name, "description": tool.description}
        current_hash = calculate_hash(tool_dict)

        # 检查是否需要更新
        is_new = tool_name not in existing_tools
        is_modified = not is_new and existing_tools[tool_name]["hash"] != current_hash

        if is_new or is_modified:
            action_str = "新增" if is_new else "更新"
            logger.info(f"🧠 [Tools] [{action_str}] 工具: {tool_name}")

            # 生成向量：使用 name + description
            desc_and_name = f"{tool_name}\n{tool.description}"
            vector = list(await embedding_model.aembed([desc_and_name]))[0]

            # 构建payload
            payload = {"name": tool.name, "description": tool.description, "_hash": current_hash}

            points_to_upsert.append(
                PointStruct(
                    id=get_point_id(tool_name),
                    vector=list(vector),
                    payload=payload,
                )
            )

    # 3. 执行更新
    if points_to_upsert:
        logger.info(f"🧠 [Tools] 写入 {len(points_to_upsert)} 个工具...")
        await client.upsert(collection_name=TOOLS_COLLECTION_NAME, points=points_to_upsert)

    # 4. 清理已删除的工具
    if local_tool_names:
        ids_to_delete = [
            existing_tools[tool_name]["id"] for tool_name in existing_tools.keys() if tool_name not in local_tool_names
        ]
        if ids_to_delete:
            await client.delete(
                collection_name=TOOLS_COLLECTION_NAME,
                points_selector=ids_to_delete,
            )
            logger.info(f"🧠 [Tools] 清理 {len(ids_to_delete)} 个已删除的工具")
    else:
        logger.info("🧠 [Tools] 本地工具为空，跳过清理步骤")

    logger.info("🧠 [Tools] 工具同步完成")


async def get_main_agent_tools(query: str = "") -> ToolList:
    """获取主Agent基础工具集

    - self 分类：始终加载
    - buildin 分类：按阈值 0.45 以上加载，最多 6 个（如果有 query 则按 query 筛选）

    by_trigger 分类的工具不再无条件加载，而是通过 search_tools() 向量检索按需加载，
    避免插件数量膨胀导致工具列表过大（100+ 工具）浪费 Token 并降低 LLM 选工具准确率。

    Args:
        query: 用户查询字符串，用于筛选 buildin 工具。如果为空则使用通用查询。
    """
    from gsuid_core.ai_core.rag.base import client, embedding_model

    all_tools_cag = get_registered_tools()
    result_tools = []

    # self 分类始终加载（ToolBase 包装对象，需要取 .tool）
    if "self" in all_tools_cag:
        for tool_base in all_tools_cag["self"].values():
            result_tools.append(tool_base.tool)
        logger.debug(f"🧠 [Tools] self 分类加载 {len(all_tools_cag['self'])} 个工具")

    # buildin 分类按阈值加载（search_tools 返回的已经是 Tool 对象）
    if "buildin" in all_tools_cag:
        if client is not None and embedding_model is not None:
            # 使用用户查询加载高相似度的 buildin 工具，如果 query 为空则使用通用查询
            search_query = query if query else "buildin tool utility common function"
            buildin_tools_search = await search_tools(
                query=search_query,
                limit=3,
                category="buildin",
                threshold=0.3,
            )
            logger.debug(
                f"🧠 [Tools] buildin 分类通过阈值筛选加载 {len(buildin_tools_search)} 个工具 (query: {search_query})"
            )
            result_tools.extend(buildin_tools_search)
        else:
            # AI功能未启用时，加载所有 buildin 工具（ToolBase 包装对象，需要取 .tool）
            for tool_base in all_tools_cag["buildin"].values():
                result_tools.append(tool_base.tool)
            logger.debug(f"🧠 [Tools] buildin 分类加载 {len(all_tools_cag['buildin'])} 个工具（AI未启用）")

    return result_tools


async def search_tools(
    query: str,
    limit: int = 10,
    category: Union[str, list[str]] = "all",
    non_category: Union[str, list[str]] = "",
    threshold: float = 0.5,
    debug: bool = False,
) -> ToolList:
    """根据自然语言意图检索关联工具

    category 和 non_category 不会同时生效, 且 non_category 优先级比 category 高

    Args:
        query: 用户查询的自然语言描述
        limit: 返回结果数量限制，默认为10
        category: 工具分类名称，可选值："buildin"、"default"、"common"、"all"，默认为"all", 也可传入列表
        non_category: 将不会在这个分类中找工具, 优先级比category高，可选值："self"、"buildin"、"common"，默认为空
        threshold: 相似度分数阈值，只有分数高于该值的工具才会被返回，默认为0.65
        debug: 是否启用调试模式，启用后会记录所有返回工具的分数（无论是否超过阈值），默认为False

    Returns:
        匹配的工具列表

    Raises:
        RuntimeError: AI功能未启用时抛出
    """
    from gsuid_core.ai_core.rag.base import client, embedding_model

    if client is None or embedding_model is None:
        raise RuntimeError("AI功能未启用，无法搜索工具")

    logger.info(f"🧠 [Tools] 正在查询: {query}, threshold={threshold}, limit={limit}, debug={debug}")
    query_vec = list(await embedding_model.aembed([query]))[0]

    # 如果启用 debug，使用大 limit 获取所有工具以便查看分数
    if debug:
        response = await client.query_points(
            collection_name=TOOLS_COLLECTION_NAME,
            query=list(query_vec),
            limit=1000,  # debug 模式下用大 limit 获取所有工具
        )
    else:
        response = await client.query_points(
            collection_name=TOOLS_COLLECTION_NAME,
            query=list(query_vec),
            limit=limit,
            score_threshold=threshold if threshold > 0 else None,
        )

    tool_names: List[str] = []
    score_map: Dict[str, float] = {}
    all_scores_info = []

    for point in response.points:
        if point.payload and point.payload.get("name"):
            name = point.payload.get("name")
            score = point.score
            if name:
                # 如果启用了 debug 且工具分数低于阈值，则不加入结果
                if debug and threshold > 0 and score < threshold:
                    all_scores_info.append(f"{name}={score:.4f}(未达阈值)")
                    continue
                tool_names.append(name)
                score_map[name] = score
                all_scores_info.append(f"{name}={score:.4f}")

    if debug:
        logger.debug(f"🧠 [Tools] 向量搜索所有工具分数(debug): {', '.join(all_scores_info)}")

    # 根据 category/non_category 过滤工具
    if category == "all":
        all_tools_dict = get_all_tools()
    else:
        all_tools_cag = get_registered_tools()
        if isinstance(category, str):
            category = [category]

        all_tools_dict = {}
        if non_category:
            if isinstance(non_category, str):
                non_category = [non_category]
            for cat in all_tools_cag:
                if cat in non_category:
                    continue
                all_tools_dict.update(all_tools_cag[cat])
        else:
            for cat in category:
                if cat not in all_tools_cag:
                    continue
                all_tools_dict.update(all_tools_cag[cat])

    # 从 all_tools_dict 中筛选出 tool_names 中的工具
    # all_tools_dict 的 value 是 ToolBase 对象（有 .tool 属性），也可能是 Tool 对象
    tools = []
    filtered_info = []
    for tool_name in tool_names:
        if tool_name in all_tools_dict:
            tool_obj = all_tools_dict[tool_name]
            if hasattr(tool_obj, "tool"):
                tools.append(tool_obj.tool)
            else:
                tools.append(tool_obj)
            filtered_info.append(f"{tool_name}({score_map[tool_name]:.4f})")

    logger.info(f"🧠 [Tools] 查询结果(category={category}): {', '.join(filtered_info)}")

    return tools
