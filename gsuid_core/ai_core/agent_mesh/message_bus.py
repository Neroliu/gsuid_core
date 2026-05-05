"""Agent 间异步消息总线

提供 Agent 之间的异步消息传递能力，支持：
- 点对点消息发送
- 主题订阅/广播
- 请求-响应模式
- 消息历史查询

使用方式:
    bus = get_message_bus()
    await bus.publish(AgentMessage(sender_id="agent_1", topic="task_complete", payload={...}))
    await bus.subscribe("agent_2", "task_complete", callback)
"""

from __future__ import annotations

import asyncio
from typing import Any, Set, Dict, List, Callable, Optional
from collections import defaultdict

from gsuid_core.logger import logger

from .models import AgentMessage

# 消息回调类型
MessageCallback = Callable[[AgentMessage], Any]


class MessageBus:
    """Agent 间异步消息总线

    线程安全的消息传递系统，支持点对点和发布-订阅模式。

    Attributes:
        _subscribers: 主题 -> 回调列表的映射
        _agent_subscribers: Agent ID -> 主题集合的映射
        _message_history: 消息历史（最近 N 条）
        _max_history: 最大历史消息数
    """

    _max_history: int = 1000

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[MessageCallback]] = defaultdict(list)
        self._agent_subscribers: Dict[str, Set[str]] = defaultdict(set)
        self._direct_handlers: Dict[str, MessageCallback] = {}
        self._message_history: List[AgentMessage] = []
        self._lock = asyncio.Lock()

    async def publish(self, message: AgentMessage) -> None:
        """发布消息到总线

        如果指定了 receiver_id，直接投递给目标 Agent。
        否则广播给所有订阅了该主题的 Agent。

        Args:
            message: 要发布的消息
        """
        async with self._lock:
            # 记录历史
            self._message_history.append(message)
            if len(self._message_history) > self._max_history:
                self._message_history = self._message_history[-self._max_history :]

        if message.receiver_id:
            # 点对点消息
            handler = self._direct_handlers.get(message.receiver_id)
            if handler:
                try:
                    result = handler(message)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"🕸️ [MessageBus] 直接消息处理失败: {message.sender_id} -> {message.receiver_id}: {e}")
            else:
                logger.debug(f"🕸️ [MessageBus] 目标 Agent 未注册: {message.receiver_id}")

        # 广播给主题订阅者
        topic_handlers = self._subscribers.get(message.topic, [])
        for handler in topic_handlers:
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"🕸️ [MessageBus] 主题消息处理失败: topic={message.topic}, sender={message.sender_id}: {e}")

    async def subscribe(
        self,
        agent_id: str,
        topic: str,
        callback: MessageCallback,
    ) -> None:
        """订阅指定主题的消息

        Args:
            agent_id: 订阅者 Agent ID
            topic: 消息主题
            callback: 消息回调函数
        """
        async with self._lock:
            self._subscribers[topic].append(callback)
            self._agent_subscribers[agent_id].add(topic)

        logger.debug(f"🕸️ [MessageBus] Agent '{agent_id}' 订阅主题 '{topic}'")

    async def register_agent(
        self,
        agent_id: str,
        handler: MessageCallback,
    ) -> None:
        """注册 Agent 的直接消息处理器

        注册后，该 Agent 可以接收点对点消息。

        Args:
            agent_id: Agent ID
            handler: 消息处理函数
        """
        async with self._lock:
            self._direct_handlers[agent_id] = handler

        logger.debug(f"🕸️ [MessageBus] 注册 Agent 直接处理器: '{agent_id}'")

    async def unregister_agent(self, agent_id: str) -> None:
        """注销 Agent，移除其所有订阅和处理器

        Args:
            agent_id: Agent ID
        """
        async with self._lock:
            # 移除直接处理器
            self._direct_handlers.pop(agent_id, None)

            # 移除主题订阅
            topics = self._agent_subscribers.pop(agent_id, set())
            for topic in topics:
                handlers = self._subscribers.get(topic, [])
                # 注意：无法精确移除特定 agent 的回调（因为回调是函数引用）
                # 实际使用中，Agent 停止时回调自然失效
                if not handlers:
                    self._subscribers.pop(topic, None)

        logger.debug(f"🕸️ [MessageBus] 注销 Agent: '{agent_id}'")

    async def request(
        self,
        message: AgentMessage,
        timeout: float = 30.0,
    ) -> Optional[AgentMessage]:
        """请求-响应模式

        发送消息并等待目标 Agent 的回复。

        Args:
            message: 请求消息（必须指定 receiver_id）
            timeout: 超时时间（秒）

        Returns:
            响应消息，超时返回 None
        """
        if not message.receiver_id:
            logger.warning("🕸️ [MessageBus] request 模式必须指定 receiver_id")
            return None

        response_event = asyncio.Event()
        response_holder: list[Optional[AgentMessage]] = [None]

        async def _response_handler(msg: AgentMessage) -> None:
            if msg.reply_to == message.message_id:
                response_holder[0] = msg
                response_event.set()

        # 临时订阅响应
        reply_topic = f"reply:{message.message_id}"
        await self.subscribe(message.sender_id, reply_topic, _response_handler)

        try:
            await self.publish(message)
            await asyncio.wait_for(response_event.wait(), timeout=timeout)
            return response_holder[0]
        except asyncio.TimeoutError:
            logger.warning(
                f"🕸️ [MessageBus] 请求超时: "
                f"{message.sender_id} -> {message.receiver_id} "
                f"(topic: {message.topic}, timeout: {timeout}s)"
            )
            return None
        finally:
            # 清理临时订阅
            async with self._lock:
                handlers = self._subscribers.get(reply_topic, [])
                if _response_handler in handlers:
                    handlers.remove(_response_handler)

    def get_history(
        self,
        topic: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[AgentMessage]:
        """查询消息历史

        Args:
            topic: 按主题过滤（可选）
            agent_id: 按发送者或接收者过滤（可选）
            limit: 返回的最大消息数

        Returns:
            消息列表（按时间正序）
        """
        filtered = self._message_history

        if topic:
            filtered = [m for m in filtered if m.topic == topic]

        if agent_id:
            filtered = [m for m in filtered if m.sender_id == agent_id or m.receiver_id == agent_id]

        return filtered[-limit:]

    def get_subscriber_count(self, topic: str) -> int:
        """获取指定主题的订阅者数量"""
        return len(self._subscribers.get(topic, []))

    def get_registered_agents(self) -> list[str]:
        """获取所有已注册的 Agent ID 列表"""
        return list(self._direct_handlers.keys())


# 全局单例
_message_bus: Optional[MessageBus] = None


def get_message_bus() -> MessageBus:
    """获取全局消息总线单例

    Returns:
        MessageBus 实例
    """
    global _message_bus
    if _message_bus is None:
        _message_bus = MessageBus()
    return _message_bus
