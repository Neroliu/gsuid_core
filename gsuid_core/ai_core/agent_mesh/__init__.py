"""Agent 间通信与协作协议模块

提供持久化子 Agent、Agent 间异步消息总线、多 Agent 任务协调器等能力。

模块结构:
- models.py: AgentTask / AgentMessage 数据模型
- persistent_agent.py: 持久化子 Agent（带独立目标和状态的长期 Agent）
- message_bus.py: Agent 间异步消息总线
- coordinator.py: 多 Agent 任务协调器（DAG 依赖图执行）
"""

from .models import AgentTask, TaskStatus, AgentStatus, AgentMessage
from .coordinator import AgentCoordinator
from .message_bus import MessageBus, get_message_bus
from .persistent_agent import PersistentAgent

__all__ = [
    "AgentMessage",
    "AgentTask",
    "AgentStatus",
    "TaskStatus",
    "MessageBus",
    "get_message_bus",
    "PersistentAgent",
    "AgentCoordinator",
]
