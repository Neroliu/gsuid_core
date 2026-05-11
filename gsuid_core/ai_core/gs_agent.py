"""
PydanticAI Agent 核心模块
基于 pydantic_ai 实现的轻量级 Agent
"""

import time
import asyncio
from typing import Any, Set, List, Union, Literal, TypeVar, Optional, Sequence, overload

import httpx
from pydantic_ai import Agent
from pydantic_graph import End
from pydantic_ai.agent import CallToolsNode, ModelRequestNode
from pydantic_ai.usage import UsageLimits
from pydantic_ai.messages import (
    ImageUrl,
    TextPart,
    UserContent,
    ModelMessage,
    ModelRequest,
    ThinkingPart,
    ToolCallPart,
    ModelResponse,
    ToolReturnPart,
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.openai import OpenAIChatModel

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.ai_core.utils import send_chat_result
from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.skills import skills_toolset
from gsuid_core.ai_core.rag.tools import ToolList, search_tools, get_main_agent_tools
from gsuid_core.ai_core.configs.models import get_model_for_task
from gsuid_core.ai_core.session_logger import AISessionLogger
from gsuid_core.ai_core.persona.prompts import CHARACTER_BUILDING_TEMPLATE
from gsuid_core.ai_core.configs.ai_config import ai_config

_T = TypeVar("_T")


def _extract_run_context(history: List[ModelMessage], max_fact_len: int = 2000) -> str:
    """从历史消息中提取"已知事实"和"模型推理片段"，按轮次组织。

    相比只提取 ToolReturnPart，还保留 TextPart（LLM 中间推理），
    因为这些推理有时本身就是有价值的结论。
    """
    sections: list[str] = []
    round_num = 0

    for msg in history:
        if isinstance(msg, ModelResponse):
            round_num += 1
            texts: list[str] = []
            calls: list[str] = []
            for part in msg.parts:
                if isinstance(part, TextPart) and part.content.strip():
                    t = part.content.strip()
                    if len(t) > 500:
                        t = t[:500] + "...[截断]"
                    texts.append(t)
                elif isinstance(part, ToolCallPart):
                    calls.append(part.tool_name)

            if texts or calls:
                header = f"【第{round_num}轮】"
                if calls:
                    header += f" 调用工具: {', '.join(calls)}"
                if texts:
                    header += "\n" + "\n".join(texts)
                sections.append(header)

        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    content = str(part.content).strip()
                    if len(content) > max_fact_len:
                        content = content[:max_fact_len] + f"\n...[截断, 共{len(content)}字符]"
                    sections.append(f"  → [{part.tool_name}] 返回: {content}")

    return "\n".join(sections) if sections else ""


def _truncate_message_for_log(msg: Any, max_base64_len: int = 100) -> Any:
    """
    截断消息中的长 base64 数据，用于日志输出。

    Args:
        msg: 消息内容，可能是 str、ImageUrl 或其列表
        max_base64_len: base64 数据最大显示长度

    Returns:
        截断后的消息副本
    """
    from pydantic_ai.messages import ImageUrl

    if isinstance(msg, str):
        # 检查是否是 base64 DataURI
        if ";base64," in msg and len(msg) > max_base64_len:
            return f"{msg[:max_base64_len]}...[base64截断, 总长={len(msg)}]"
        return msg
    elif isinstance(msg, ImageUrl):
        url = msg.url
        if ";base64," in url and len(url) > max_base64_len:
            return ImageUrl(url=f"{url[:max_base64_len]}...[base64截断, 总长={len(url)}]")
        return msg
    elif isinstance(msg, list):
        return [_truncate_message_for_log(item, max_base64_len) for item in msg]
    return msg


def _truncate_history_with_tool_safety(
    history: List[ModelMessage],
    max_history: int,
) -> List[ModelMessage]:
    """
    安全截断 history，确保保留的消息中 ToolCallPart 和 ToolReturnPart 完全配对。

    问题：如果简单地从末尾截断 history，可能导致 ToolReturnPart 被保留
    但其对应的 ToolCallPart 被丢弃（在被截断的前半部分），从而在下一轮请求时出现
    "tool result's tool id not found" 错误。

    解决策略：
    1. 先做一次试探性截断：保留最后 max_history 条消息
    2. 扫描截断结果，收集所有保留的 ToolReturnPart 的 tool_call_id
    3. 扫描截断结果，收集所有保留的 ToolCallPart 的 tool_call_id
    4. 如果有 return 找不到对应的 call，说明截断点切到了 tool call/return 对的中间
    5. 向前移动截断点，直到所有保留的 return 都有对应的 call

    Args:
        history: 原始消息历史
        max_history: 最大保留消息数

    Returns:
        截断后的安全消息历史
    """
    if len(history) <= max_history:
        return history

    # 从 max_history 开始，逐步扩大保留范围，直到 tool call/return 完全配对
    truncate_index = len(history) - max_history

    while truncate_index > 0:
        truncated = history[truncate_index:]

        # 收集截断结果中所有 ToolCallPart 的 tool_call_id
        retained_call_ids: Set[str] = set()
        # 收集截断结果中所有 ToolReturnPart 的 tool_call_id
        retained_return_ids: Set[str] = set()

        for msg in truncated:
            if isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        retained_call_ids.add(part.tool_call_id)
            elif isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        retained_return_ids.add(part.tool_call_id)

        # 找出截断结果中的孤立 return（有 return 但没有对应的 call）
        orphaned = retained_return_ids - retained_call_ids

        if not orphaned:
            # 所有保留的 return 都有对应的 call，截断安全
            logger.debug(
                f"🧠 [GsCoreAIAgent] 安全截断 history: {len(history)} -> {len(truncated)} (截断点: {truncate_index})"
            )
            return truncated

        # 有孤立 return，需要向前移动截断点
        # 找到所有孤立 return 所在的消息索引（相对于原始 history）
        min_orphaned_idx = len(history)  # 初始化为最大值
        for idx, msg in enumerate(history):
            if idx < truncate_index:
                continue  # 只看截断范围内的
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart) and part.tool_call_id in orphaned:
                        min_orphaned_idx = min(min_orphaned_idx, idx)

        # 向前移动截断点到孤立 return 之前，再留 2 条消息的缓冲
        new_truncate_index = max(0, min_orphaned_idx - 2)
        if new_truncate_index >= truncate_index:
            # 安全阀：如果无法继续前移，直接保留全部历史
            logger.warning(f"🧠 [GsCoreAIAgent] 无法安全截断 history，保留全部 {len(history)} 条")
            return history

        truncate_index = new_truncate_index

    # truncate_index == 0，保留全部历史
    logger.debug(f"🧠 [GsCoreAIAgent] 安全截断 history: {len(history)} -> {len(history)} (保留全部)")
    return history


class GsCoreAIAgent:
    """
    基于 PydanticAI 的 Agent 封装类

    Attributes:
        model_name: 模型名称
        api_key: API 密钥
        base_url: API 基础 URL
        max_tokens: 最大输出 token 数
        system_prompt: 系统提示词
    """

    def __init__(
        self,
        openai_chat_model: Optional[OpenAIChatModel] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 30000,
        max_iterations: Optional[int] = None,
        persona_name: Optional[str] = None,
        max_history: int = 20,
        create_by: str = "LLM",
        task_level: Literal["high", "low"] = "high",
        session_id: Optional[str] = None,
    ):
        self.history: List[ModelMessage] = []
        self.max_history = max_history
        self.system_prompt = system_prompt
        self.persona_name = persona_name  # 用于热重载检查
        # 用于串行执行 run 方法的锁
        self._run_lock = asyncio.Lock()
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations  # 自定义迭代次数限制，None时使用配置默认值
        self.task_level: Literal["high", "low"] = task_level  # 任务级别，用于选择对应的模型配置

        self.create_by = create_by
        self.session_id: Optional[str] = session_id

        self.model = openai_chat_model
        if self.model is None:
            self.model = get_model_for_task(task_level)

        # 初始化会话日志记录器
        self._session_logger: Optional[AISessionLogger] = None
        if session_id is not None:
            self._session_logger = AISessionLogger(
                session_id=session_id,
                system_prompt=system_prompt,
                persona_name=persona_name,
                create_by=create_by,
            )
            if system_prompt is not None:
                self._session_logger.log_system_prompt(system_prompt)

    def extract_history(self):
        if self.max_history <= 0:
            self.history = []
            return

        if len(self.history) > self.max_history:
            self.history = _truncate_history_with_tool_safety(
                self.history,
                self.max_history,
            )
            logger.debug(f"🧠 [GsCoreAIAgent] 历史记录已截断至 {len(self.history)} 条")

    async def _prepare_user_message(
        self,
        content_list: list[UserContent],
    ) -> Union[str, list[UserContent]]:
        """处理用户消息中的图片内容

        当 user_message 为 Sequence[UserContent] 时，检查其中是否包含 ImageUrl。
        如果包含，根据当前模型的 model_support 配置决定：
        - 模型支持图片：保留 ImageUrl，返回 list[UserContent]
        - 模型不支持图片：调用 understand_image 将图片转述为文本，合并到文本消息中

        Args:
            content_list: 用户消息内容列表

        Returns:
            处理后的消息，可能是 str 或 list[UserContent]
        """
        from gsuid_core.ai_core.configs.models import get_model_config_for_task
        from gsuid_core.ai_core.image_understand import understand_image

        model_config = get_model_config_for_task(self.task_level)
        model_support: str = model_config.get_config("model_support").data

        # 分离文本和图片
        text_parts: list[str] = []
        image_urls: list[str] = []
        for item in content_list:
            if isinstance(item, ImageUrl):
                image_urls.append(item.url)
            elif isinstance(item, str):
                text_parts.append(item)

        if "image" in model_support:
            # 模型支持图片，保留原始内容
            result: list[UserContent] = []
            for item in content_list:
                if isinstance(item, str):
                    result.append(f"【用户发言】\n{item}")
                else:
                    result.append(item)
            return result

        # 模型不支持图片，调用图片理解模块转述
        if image_urls:
            logger.info(f"🖼️ [ImageUnderstand] 当前模型不支持图片，开始图片理解转述，共 {len(image_urls)} 张图片")
            descriptions: list[str] = []
            for idx, url in enumerate(image_urls):
                try:
                    description = await understand_image(image_url=url)
                    descriptions.append(f"图片{idx + 1}: {description}")
                except Exception as e:
                    logger.error(f"🖼️ [ImageUnderstand] 图片 {idx + 1} 理解失败: {e}")
                    descriptions.append(f"图片{idx + 1}: [图片理解失败]")

            if descriptions:
                image_text = "--- 图片内容描述 ---\n" + "\n".join(descriptions)
                text_parts.append(image_text)

        combined = "\n".join(text_parts) if text_parts else ""
        return f"【用户发言】\n{combined}"

    @overload
    async def _execute_run(
        self,
        user_message: Union[str, Sequence[UserContent]],
        bot: Optional[Bot] = None,
        ev: Optional[Event] = None,
        rag_context: Optional[str] = None,
        tools: Optional[ToolList] = None,
        return_mode: Literal["always", "return", "by_bot"] = "by_bot",
        output_type: None = None,
    ) -> str: ...

    @overload
    async def _execute_run(
        self,
        user_message: Union[str, Sequence[UserContent]],
        bot: Optional[Bot] = None,
        ev: Optional[Event] = None,
        rag_context: Optional[str] = None,
        tools: Optional[ToolList] = None,
        return_mode: Literal["always", "return", "by_bot"] = "by_bot",
        output_type: type[_T] = ...,
    ) -> _T: ...

    async def _execute_run(
        self,
        user_message: Union[str, Sequence[UserContent]],
        bot: Optional[Bot] = None,
        ev: Optional[Event] = None,
        rag_context: Optional[str] = None,
        tools: Optional[ToolList] = None,
        return_mode: Literal["always", "return", "by_bot"] = "by_bot",
        output_type: Optional[type] = None,
    ) -> Union[str, Any]:
        """
        实际执行 Agent 运行的内部方法

        Args:
            output_type: 当指定为某个 Pydantic 模型类时，利用 pydantic_ai 的
                output_type 特性，要求模型必须返回符合该模型结构的 JSON。
                此时返回值为该 Pydantic 模型实例而非字符串。
        """
        from gsuid_core.ai_core.statistics import statistics_manager

        _tool_call_list: list[str] = []  # 用于记录本次运行中被调用的工具列表，供后续统计使用

        # 使用自定义迭代次数限制（如果有），否则使用配置默认值
        if self.max_iterations is not None:
            limits = UsageLimits(request_limit=self.max_iterations)
        else:
            multi_agent_lenth: int = ai_config.get_config("multi_agent_lenth").data
            limits = UsageLimits(request_limit=multi_agent_lenth)

        # 记录开始时间用于延迟统计
        start_time = time.time()

        logger.info("🧠 [GsCoreAIAgent] ====== Agent 运行开始 ======")
        context = ToolContext(bot=bot, ev=ev)

        # 记录原始用户问题，供后续强制总结使用
        last_user_question: str = ""
        if isinstance(user_message, str):
            last_user_question = user_message.strip()
        elif isinstance(user_message, Sequence):
            # 从 Sequence[UserContent] 中提取纯文本
            last_user_question = "\n".join(item for item in user_message if isinstance(item, str)).strip()

        # 处理用户消息：当传入 Sequence[UserContent] 时，自动处理其中的图片
        if isinstance(user_message, Sequence) and not isinstance(user_message, str):
            final_user_message = await self._prepare_user_message(list(user_message))
        else:
            final_user_message = f"【用户发言】\n{user_message}"

        if rag_context:
            if isinstance(final_user_message, str):
                final_user_message = f"{final_user_message}\n\n{rag_context}"
            elif isinstance(final_user_message, list):
                final_user_message = list(final_user_message)
                final_user_message.append(f"\n\n{rag_context}")
            logger.info("🧠[GsCoreAIAgent] 已添加 RAG 上下文")

        # 截断日志输出中的 base64 数据，避免日志过长
        truncated_msg = _truncate_message_for_log(final_user_message)
        logger.trace(f"🧠[GsCoreAIAgent] 用户消息: {truncated_msg}")

        # 记录用户输入到 session logger
        if self._session_logger is not None:
            self._session_logger.log_run_start(final_user_message)
            self._session_logger.log_user_input(final_user_message)

        if tools is None:
            tools = []

        if self.create_by in ["SubAgent", "Chat", "Agent", "AutoPlanner"]:
            if not tools:
                qy = ""
                if isinstance(user_message, str):
                    qy = user_message
                elif ev is not None:
                    qy = ev.raw_text

                tools = await get_main_agent_tools(query=qy)

                if qy:
                    logger.debug(f"🧠 [GsCoreAIAgent] 尝试搜索工具: {qy}")
                    tools += await search_tools(
                        query=qy,
                        limit=6,
                        non_category=["self", "buildin"],
                    )
                logger.debug(f"🧠 [GsCoreAIAgent] 主Agent工具数量: {len(tools)}")
            else:
                logger.debug(f"🧠 [GsCoreAIAgent] 传入Tools列表: {len(tools)}，已传入参数")
        else:
            logger.debug("🧠 [GsCoreAIAgent] 不搜索工具")

        logger.debug(f"🧠 [GsCoreAIAgent] 工具列表: {[tool.name for tool in tools]}")

        tools = list({obj.name: obj for obj in tools}.values())

        # 当 return_model 指定时，使用 output_type 让 pydantic_ai 强制结构化输出
        # output_type 默认为 str（返回文本），指定 Pydantic 模型时强制返回结构化 JSON
        _agent = Agent(
            model=self.model,
            deps_type=ToolContext,
            system_prompt=self.system_prompt or "你是一个智能助手, 简短的一句话回答问题即可。",
            model_settings={"max_tokens": self.max_tokens},
            tools=tools,
            toolsets=[skills_toolset],
            retries=3,
            output_type=output_type or str,
        )

        # 截断历史记录，避免无限制增长
        self.extract_history()

        try:
            logger.info("🧠 [GsCoreAIAgent] 开始执行 _agent.iter()...")
            logger.info(f"🧠 [GsCoreAIAgent] 当前 history: {len(self.history)}")

            async with _agent.iter(
                final_user_message,
                deps=context,  # type: ignore[arg-type]
                message_history=self.history,
                usage_limits=limits,
            ) as agent_run:
                # 遍历每一步 Node
                async for node in agent_run:
                    # 1. 发起大模型请求前的处理
                    if isinstance(node, ModelRequestNode):
                        logger.debug("🧠 [GsCoreAIAgent] ⚡ 触发节点: ModelRequestNode")

                        if self._session_logger is not None:
                            self._session_logger.log_node_transition("ModelRequestNode")

                        for part in node.request.parts:
                            if isinstance(part, ToolReturnPart):
                                # 返回的可能是对象也可能是字符串，这里为了打印转成 str
                                tool_result_str = str(part.content)
                                if len(tool_result_str) > 200:
                                    tool_result_str = tool_result_str[:200] + f"...[截断, 共{len(tool_result_str)}字符]"
                                logger.debug(
                                    f"[✅ 工具执行完毕]: 工具名称='{part.tool_name}', 结果给到Agent={tool_result_str}"
                                )
                                if self._session_logger is not None:
                                    self._session_logger.log_tool_return(
                                        part.tool_name, part.content, part.tool_call_id
                                    )

                        logger.debug("🧠  ▶ [发起请求]: 正在等待大模型思考...")

                    # 2. 获取到大模型响应，准备调用工具或者输出文本
                    # 这里使用了 isinstance，Pyright 就能明确知道此时 node 是 CallToolsNode，拥有 model_response 属性
                    elif isinstance(node, CallToolsNode):
                        logger.debug("🧠 [GsCoreAIAgent] ⚡ 触发节点: CallToolsNode")

                        if self._session_logger is not None:
                            self._session_logger.log_node_transition("CallToolsNode")

                        # 遍历大模型返回的具体片段 (Parts)
                        for part in node.model_response.parts:
                            # 拦截到模型即将调用工具
                            if isinstance(part, ToolCallPart):
                                logger.debug(f"[🔧 大模型请求调用工具]: 工具名称='{part.tool_name}', 参数={part.args}")
                                _tool_call_list.append(part.tool_name)
                                if self._session_logger is not None:
                                    self._session_logger.log_tool_call(part.tool_name, part.args, part.tool_call_id)

                            # 大模型直接输出文本
                            elif isinstance(part, TextPart):
                                _text = part.content.strip()
                                logger.debug(f"🧠 [大模型文本]: {_text}")
                                if self._session_logger is not None:
                                    self._session_logger.log_text_output(_text)
                                if bot and _text and return_mode in ["always", "by_bot"]:
                                    await send_chat_result(bot, _text, ev=ev)

                            elif isinstance(part, ThinkingPart):
                                _thinking = part.content.strip()
                                logger.trace(f"🧠 [大模型思考]: {_thinking}")
                                if self._session_logger is not None:
                                    self._session_logger.log_thinking(_thinking)
                                if bot and _thinking:
                                    pass

                    # 3. 运行结束节点
                    elif isinstance(node, End):
                        logger.debug("🧠 [GsCoreAIAgent] ⚡ 触发节点: End")
                        logger.debug("  ✅ [运行结束]: 最终结果生成完毕")
                        if self._session_logger is not None:
                            self._session_logger.log_node_transition("End")

            # 遍历完成后，直接从 agent_run 中获取最终结果
            result = agent_run.result
            if result:
                logger.info("🧠 [GsCoreAIAgent] _agent.iter() 执行成功!")

                self.history.extend(result.new_messages())

                # 记录 Token 使用量和延迟统计
                try:
                    # 记录响应延迟
                    latency = time.time() - start_time
                    statistics_manager.record_latency(latency=latency)

                    try:
                        usage_obj = result.usage()
                        input_tokens: int = usage_obj.input_tokens
                        output_tokens: int = usage_obj.output_tokens
                        logger.info(f"📊 [GsCoreAIAgent] Token消耗: input={input_tokens}, output={output_tokens}")
                        if input_tokens > 0 or output_tokens > 0:
                            statistics_manager.record_token_usage(
                                model_name=self.model.model_name if self.model else "unknown",
                                chat_type=self.create_by,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                            )
                            if self._session_logger is not None:
                                self._session_logger.log_token_usage(
                                    input_tokens,
                                    output_tokens,
                                    self.model.model_name if self.model else "unknown",
                                )
                    except AttributeError as e:
                        # result 没有 usage 属性（如 pydantic_graph End 节点返回的结果）
                        logger.info(f"📊 [GsCoreAIAgent] result.usage 访问失败: {e}")
                        pass
                except Exception as e:
                    logger.warning(f"📊 [GsCoreAIAgent] 记录统计失败: {e}")

                # 当 return_model 指定时，直接返回 Pydantic 模型实例
                if output_type is not None:
                    if self._session_logger is not None:
                        self._session_logger.log_run_end(result.output)
                        self._session_logger.log_result(result.output, _tool_call_list)
                    return result.output

                # 始终返回字符串类型
                result_msg = str(result.output).strip()
                if _tool_call_list:
                    result_msg += f"\n\n（🔧 本次执行工具调用列表: {'、'.join(_tool_call_list)}）"

                if self._session_logger is not None:
                    self._session_logger.log_run_end(result_msg)
                    self._session_logger.log_result(result_msg, _tool_call_list)

                if return_mode in ["by_bot"] and bot and ev:
                    return ""
                return result_msg

            # result 为空时的默认返回值
            return "Agent 执行完成，但未返回有效结果"

        except UsageLimitExceeded:
            # 达到限制后的处理逻辑
            logger.warning(f"🧠 [PydanticAI] Agent 达到最高思考轮数限制 {limits.request_limit}")
            statistics_manager.record_error(error_type="usage_limit")
            if self._session_logger is not None:
                self._session_logger.log_error("usage_limit", f"达到最高思考轮数限制 {limits.request_limit}")

            # 安抚用户
            if bot:
                await bot.send("⏳ 思考链过长，正在根据已有线索为你整理最终结论...")

            # ✨ 【关键点2】发起"强制总结"请求
            try:
                user_question = last_user_question or "用户之前提出的问题"

                # 从历史中提取已获取的事实和模型推理片段
                run_context = _extract_run_context(self.history)

                if run_context:
                    final_message = (
                        f"【用户的问题】\n{user_question}\n\n"
                        f"【已获取的信息和推理过程】\n{run_context}\n\n"
                        "请根据以上已知信息，根据人设风格直接回答用户的问题。"
                        "禁止调用任何工具，只输出自然语言文本。"
                    )
                else:
                    final_message = (
                        f"【用户的问题】\n{user_question}\n\n"
                        "请直接回答这个问题（根据你的已有知识和角色性格），不要调用任何工具。"
                    )

                # 创建无工具精简 Agent（tools=[] = 内部无 schema，从根源消除工具调用）
                _fallback_agent = Agent(
                    model=self.model,
                    system_prompt=self.system_prompt or "你是一个智能助手。",
                    model_settings={"max_tokens": self.max_tokens},
                    tools=[],
                    toolsets=[],
                    retries=0,
                    output_type=str,
                )

                # message_history 为空：所有上下文已聚焦到 final_message 中
                fallback_result = await _fallback_agent.run(
                    final_message,
                    message_history=[],
                    usage_limits=UsageLimits(request_limit=1),
                )

                if bot:
                    await send_chat_result(bot, fallback_result.output, ev=ev)
                return ""

            except Exception as e:
                logger.error(f"🧠 [PydanticAI] 强制总结失败: {e}")
                if self._session_logger is not None:
                    self._session_logger.log_error("fallback_failed", str(e))
                fallback_error = (
                    "⚠️ 问题较复杂，现有信息不足以给出准确答案。可以尝试提高思维链长度，或换个方式描述问题。"
                )
                if bot:
                    await bot.send(fallback_error)
                    return ""
                return fallback_error

        except httpx.TimeoutException as e:
            # HTTP 请求超时
            logger.warning(f"🧠 [PydanticAI] Agent 运行异常: 请求超时 {e}")
            statistics_manager.record_error(error_type="timeout")
            if self._session_logger is not None:
                self._session_logger.log_error("timeout", str(e))
            return "执行出错: 请求超时"

        except httpx.HTTPError as e:
            # 其他 HTTP 错误（网络相关）
            error_str = str(e).lower()
            if "rate" in error_str or "429" in error_str or "limit" in error_str:
                logger.warning(f"🧠 [PydanticAI] Agent 运行异常: Rate Limit {e}")
                statistics_manager.record_error(error_type="rate_limit")
                if self._session_logger is not None:
                    self._session_logger.log_error("rate_limit", str(e))
            else:
                logger.warning(f"🧠 [PydanticAI] Agent 运行异常: 网络错误 {e}")
                statistics_manager.record_error(error_type="network_error")
                if self._session_logger is not None:
                    self._session_logger.log_error("network_error", str(e))
            return f"执行出错: {str(e)}"

        except Exception as e:
            logger.error(f"🧠 [PydanticAI] Agent 运行异常: {e}")
            logger.exception("🧠 [PydanticAI] 异常详情:")
            if "529" in str(e):
                statistics_manager.record_error(error_type="api_529_error")
            else:
                statistics_manager.record_error(error_type="agent_error")
            if self._session_logger is not None:
                self._session_logger.log_error("agent_error", str(e))
            return f"执行出错: {str(e)}"

    @overload
    async def run(
        self,
        user_message: Union[str, Sequence[UserContent]],
        bot: Optional[Bot] = None,
        ev: Optional[Event] = None,
        rag_context: Optional[str] = None,
        tools: Optional[ToolList] = None,
        return_mode: Literal["always", "return", "by_bot"] = "by_bot",
        output_type: None = None,
    ) -> str: ...

    @overload
    async def run(
        self,
        user_message: Union[str, Sequence[UserContent]],
        bot: Optional[Bot] = None,
        ev: Optional[Event] = None,
        rag_context: Optional[str] = None,
        tools: Optional[ToolList] = None,
        return_mode: Literal["always", "return", "by_bot"] = "by_bot",
        output_type: type[_T] = ...,
    ) -> _T: ...

    async def run(
        self,
        user_message: Union[str, Sequence[UserContent]],
        bot: Optional[Bot] = None,
        ev: Optional[Event] = None,
        rag_context: Optional[str] = None,
        tools: Optional[ToolList] = None,
        return_mode: Literal["always", "return", "by_bot"] = "by_bot",
        output_type: Optional[type] = None,
    ) -> Union[str, Any]:
        """
        运行 Agent 并返回结果

        此方法使用锁机制确保同一时间只有一个请求在执行，
        其他请求会挂起等待，执行时自动继承历史记录

        Args:
            output_type: 当指定为某个 Pydantic 模型类时，利用 pydantic_ai 的
                output_type 特性，要求模型必须返回符合该模型结构的 JSON。
                此时返回值为该 Pydantic 模型实例而非字符串。

        Returns:
            Agent 执行结果。默认返回 str，当 output_type 指定时返回对应模型实例
        """
        async with self._run_lock:
            logger.info("🧠 [GsCoreAIAgent] 获取到执行锁，开始执行...")
            result = await self._execute_run(
                user_message=user_message,
                bot=bot,
                ev=ev,
                rag_context=rag_context,
                tools=tools,
                return_mode=return_mode,
                output_type=output_type,
            )
            logger.info("🧠 [GsCoreAIAgent] 执行完成，释放锁")
            return result


# 工厂函数
def create_agent(
    system_prompt: Optional[str] = None,
    max_tokens: int = 30000,
    max_iterations: Optional[int] = None,
    persona_name: Optional[str] = None,
    create_by: str = "LLM",
    max_history: int = 20,
    task_level: Literal["high", "low"] = "high",
    session_id: Optional[str] = None,
) -> GsCoreAIAgent:
    """
    创建 PydanticAI Agent 实例

    Args:
        model_name: 模型名称
        system_prompt: 系统提示词
        max_tokens: 最大输出 token 数
        max_iterations: 最大迭代次数限制，None 时使用配置默认值
        persona_name: Persona 名称（用于热重载检测）
        task_level: 任务级别，"high"表示高级任务，"low"表示低级任务
        session_id: 会话 ID，用于关联 session 日志

    Returns:
        PydanticAIAgent 实例

    Example:
        agent = create_agent(
            system_prompt='你是一个智能助手。',
        )
    """
    return GsCoreAIAgent(
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        max_iterations=max_iterations,
        persona_name=persona_name,
        create_by=create_by,
        max_history=max_history,
        task_level=task_level,
        session_id=session_id,
    )


async def build_new_persona(query: str) -> str:
    """
    构建新的角色提示词

    使用角色构建模板和用户查询，生成新的角色提示词。

    Args:
        query: 用户查询，描述新角色的特征和能力

    Returns:
        新角色的提示词字符串
    """
    agent = create_agent(
        system_prompt=CHARACTER_BUILDING_TEMPLATE,
        create_by="BuildPersona",
        task_level="high",
        session_id="build_persona",
    )
    response = await agent.run(query)
    return response.strip()
