"""持久化子 Agent 模块

提供持久化子 Agent 能力，与普通 subagent（单次请求内生命周期）不同，
持久化 Agent 可以在用户明确要求时创建，持续运行并有独立任务目标。

使用方式:
    agent = PersistentAgent(
        agent_id="research_agent_001",
        name="调研助手",
        goal="收集关于 XX 主题的资料",
        system_prompt="你是一个专业的调研助手...",
    )
    await agent.start()
    result = await agent.send_task("搜索最新的 XX 资料")
    await agent.stop()
"""

from __future__ import annotations

import time
import uuid
import asyncio
from typing import Any, Dict, List, Optional

from gsuid_core.logger import logger
from gsuid_core.server import on_core_shutdown
from gsuid_core.ai_core.gs_agent import GsCoreAIAgent, create_agent
from gsuid_core.ai_core.agent_mesh.models import AgentStatus, AgentMessage
from gsuid_core.ai_core.agent_mesh.message_bus import get_message_bus


class PersistentAgent:
    """持久化子 Agent

    带独立目标和状态的长期 Agent，与普通 subagent 的区别：
    1. 生命周期跨请求：创建后持续运行，直到用户停止或达到目标
    2. 有独立的任务目标：可以自主决策下一步行动
    3. 支持消息总线通信：可以与其他 Agent 协作
    4. 支持状态持久化：可以在进程重启后恢复

    Attributes:
        agent_id: Agent 唯一标识
        name: Agent 名称
        goal: Agent 的长期目标
        status: 当前状态
        system_prompt: 系统提示词
        max_idle_seconds: 最大空闲时间（秒），超过自动停止
    """

    def __init__(
        self,
        agent_id: str,
        name: str,
        goal: str,
        system_prompt: str | None = None,
        max_idle_seconds: int = 3600,
        max_iterations: int = 15,
    ) -> None:
        self.agent_id = agent_id
        self.name = name
        self.goal = goal
        self.status = AgentStatus.IDLE
        self.max_idle_seconds = max_idle_seconds
        self.max_iterations = max_iterations

        # 构建系统提示词
        self.system_prompt = system_prompt or self._build_default_prompt()

        # 内部 Agent 实例
        self._agent: Optional[GsCoreAIAgent] = None

        # 任务队列和结果
        self._task_queue: asyncio.Queue[str] = asyncio.Queue()
        self._result_queue: asyncio.Queue[str] = asyncio.Queue()

        # 生命周期
        self._running = False
        self._main_task: Optional[asyncio.Task] = None
        self._last_active: float = time.time()

        # 任务历史
        self._task_history: List[Dict[str, Any]] = []

    def _build_default_prompt(self) -> str:
        """构建默认的持久化 Agent 系统提示词"""
        return f"""你是一个持久化智能助手，名称为「{self.name}」。

【你的长期目标】
{self.goal}

【工作原则】
1. 你是一个持续运行的 Agent，会接收多个任务
2. 每个任务都要认真完成，并给出高质量的结果
3. 你可以利用之前任务的经验来改进后续工作
4. 如果任务超出你的能力范围，明确说明原因

【当前状态】
- Agent ID: {self.agent_id}
- 创建时间: {time.strftime("%Y-%m-%d %H:%M:%S")}
"""

    async def start(self) -> None:
        """启动持久化 Agent

        创建内部 Agent 实例并启动主循环。
        """
        if self._running:
            logger.warning(f"🕸️ [PersistentAgent] Agent '{self.name}' 已在运行")
            return

        self._agent = create_agent(
            system_prompt=self.system_prompt,
            max_iterations=self.max_iterations,
            create_by="PersistentAgent",
            task_level="high",
        )

        self._running = True
        self.status = AgentStatus.IDLE
        self._main_task = asyncio.create_task(self._main_loop())

        # 注册到消息总线
        bus = get_message_bus()
        await bus.register_agent(self.agent_id, self._handle_message)

        logger.info(f"🕸️ [PersistentAgent] Agent '{self.name}' ({self.agent_id}) 已启动，目标: {self.goal[:50]}...")

    async def stop(self) -> None:
        """停止持久化 Agent"""
        if not self._running:
            return

        self._running = False
        self.status = AgentStatus.STOPPED

        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass

        # 从消息总线注销
        bus = get_message_bus()
        await bus.unregister_agent(self.agent_id)

        logger.info(f"🕸️ [PersistentAgent] Agent '{self.name}' ({self.agent_id}) 已停止")

    async def send_task(self, task: str) -> str:
        """向 Agent 发送任务

        Args:
            task: 任务描述

        Returns:
            任务执行结果
        """
        if not self._running:
            return f"❌ Agent '{self.name}' 未运行，请先调用 start()"

        await self._task_queue.put(task)

        # 等待结果
        try:
            result = await asyncio.wait_for(self._result_queue.get(), timeout=300.0)
            return result
        except asyncio.TimeoutError:
            return f"⚠️ Agent '{self.name}' 任务执行超时（300秒）"

    async def _main_loop(self) -> None:
        """Agent 主循环：从任务队列取任务执行"""
        while self._running:
            try:
                # 检查空闲超时
                if self.status == AgentStatus.IDLE:
                    idle_time = time.time() - self._last_active
                    if idle_time > self.max_idle_seconds:
                        logger.info(
                            f"🕸️ [PersistentAgent] Agent '{self.name}' 空闲超时 "
                            f"({idle_time:.0f}s > {self.max_idle_seconds}s)，自动停止"
                        )
                        await self.stop()
                        return

                # 等待任务（带超时，用于检查空闲）
                try:
                    task_text = await asyncio.wait_for(self._task_queue.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    continue

                # 执行任务
                self.status = AgentStatus.WORKING
                self._last_active = time.time()

                logger.info(f"🕸️ [PersistentAgent] Agent '{self.name}' 开始执行任务: {task_text[:50]}...")

                assert self._agent is not None
                result = await self._agent.run(
                    user_message=task_text,
                    return_mode="return",
                )

                # 记录任务历史
                self._task_history.append(
                    {
                        "task": task_text,
                        "result": result,
                        "timestamp": time.time(),
                    }
                )

                # 返回结果
                await self._result_queue.put(result)

                self.status = AgentStatus.IDLE
                self._last_active = time.time()

                logger.info(f"🕸️ [PersistentAgent] Agent '{self.name}' 任务完成，结果长度: {len(result)} 字符")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"🕸️ [PersistentAgent] Agent '{self.name}' 执行异常: {e}")
                self.status = AgentStatus.ERROR
                try:
                    await self._result_queue.put(f"❌ 任务执行异常: {e}")
                except Exception:
                    pass
                self.status = AgentStatus.IDLE

    async def _handle_message(self, message: AgentMessage) -> None:
        """处理来自消息总线的消息

        Args:
            message: 收到的消息
        """
        if message.topic == "task_assign":
            # 其他 Agent 分配任务
            task_text = message.payload.get("task", "")
            if task_text:
                await self._task_queue.put(task_text)
                logger.info(f"🕸️ [PersistentAgent] Agent '{self.name}' 收到来自 '{message.sender_id}' 的任务")

        elif message.topic == "status_query":
            # 状态查询，回复当前状态
            bus = get_message_bus()
            await bus.publish(
                AgentMessage(
                    sender_id=self.agent_id,
                    receiver_id=message.sender_id,
                    topic="status_reply",
                    payload={
                        "agent_id": self.agent_id,
                        "name": self.name,
                        "status": self.status.value,
                        "goal": self.goal,
                        "task_count": len(self._task_history),
                        "last_active": self._last_active,
                    },
                    reply_to=message.message_id,
                )
            )

    def get_info(self) -> Dict[str, Any]:
        """获取 Agent 信息"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "goal": self.goal,
            "status": self.status.value,
            "running": self._running,
            "task_count": len(self._task_history),
            "last_active": self._last_active,
            "idle_seconds": time.time() - self._last_active,
        }


# 全局持久化 Agent 注册表
_persistent_agents: Dict[str, PersistentAgent] = {}


def get_persistent_agent(agent_id: str) -> Optional[PersistentAgent]:
    """获取已注册的持久化 Agent"""
    return _persistent_agents.get(agent_id)


def list_persistent_agents() -> List[Dict[str, Any]]:
    """列出所有持久化 Agent"""
    return [agent.get_info() for agent in _persistent_agents.values()]


async def create_persistent_agent(
    name: str,
    goal: str,
    system_prompt: str | None = None,
    max_idle_seconds: int = 3600,
) -> PersistentAgent:
    """创建并启动一个持久化 Agent

    Args:
        name: Agent 名称
        goal: Agent 的长期目标
        system_prompt: 自定义系统提示词（可选）
        max_idle_seconds: 最大空闲时间（秒）

    Returns:
        创建的 PersistentAgent 实例
    """
    agent_id = f"persistent_{uuid.uuid4().hex[:8]}"

    agent = PersistentAgent(
        agent_id=agent_id,
        name=name,
        goal=goal,
        system_prompt=system_prompt,
        max_idle_seconds=max_idle_seconds,
    )

    await agent.start()
    _persistent_agents[agent_id] = agent

    return agent


async def stop_all_persistent_agents() -> None:
    """停止所有持久化 Agent（用于框架关闭时清理）"""
    for agent in list(_persistent_agents.values()):
        await agent.stop()
    _persistent_agents.clear()
    logger.info("🕸️ [PersistentAgent] 所有持久化 Agent 已停止")


@on_core_shutdown(priority=10)
async def _on_shutdown_persistent_agents():
    """框架关闭时停止所有持久化 Agent"""
    await stop_all_persistent_agents()
