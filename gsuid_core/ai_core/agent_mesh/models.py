"""Agent 间通信数据模型

定义 Agent 任务、消息、状态等核心数据结构。
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import field, dataclass


class TaskStatus(str, Enum):
    """任务状态枚举"""

    PENDING = "pending"  # 等待执行
    RUNNING = "running"  # 正在执行
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 执行失败
    CANCELLED = "cancelled"  # 已取消
    WAITING_DEPS = "waiting_deps"  # 等待依赖任务完成


class AgentStatus(str, Enum):
    """Agent 状态枚举"""

    IDLE = "idle"  # 空闲
    WORKING = "working"  # 工作中
    PAUSED = "paused"  # 暂停
    STOPPED = "stopped"  # 已停止
    ERROR = "error"  # 错误状态


@dataclass
class AgentMessage:
    """Agent 间消息

    用于 Agent 之间通过消息总线进行异步通信。

    Attributes:
        message_id: 消息唯一 ID
        sender_id: 发送者 Agent ID
        receiver_id: 接收者 Agent ID（None 表示广播）
        topic: 消息主题/类型
        payload: 消息负载数据
        timestamp: 消息创建时间戳
        reply_to: 回复目标消息 ID（用于请求-响应模式）
    """

    sender_id: str
    topic: str
    payload: Dict[str, Any] = field(default_factory=dict)
    receiver_id: Optional[str] = None
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    reply_to: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "topic": self.topic,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "reply_to": self.reply_to,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentMessage:
        """从字典创建"""
        return cls(
            message_id=data["message_id"],
            sender_id=data["sender_id"],
            receiver_id=data.get("receiver_id"),
            topic=data["topic"],
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", time.time()),
            reply_to=data.get("reply_to"),
        )


@dataclass
class AgentTask:
    """Agent 任务定义

    用于描述一个可由 Agent 执行的任务单元，支持 DAG 依赖关系。

    Attributes:
        task_id: 任务唯一 ID
        name: 任务名称
        description: 任务描述
        agent_id: 负责执行的 Agent ID
        status: 任务状态
        dependencies: 依赖的任务 ID 列表（这些任务完成后才能执行）
        input_data: 任务输入数据
        output_data: 任务输出数据（执行完成后填充）
        error_message: 错误信息（执行失败时填充）
        created_at: 创建时间
        started_at: 开始执行时间
        completed_at: 完成时间
        max_retries: 最大重试次数
        retry_count: 当前重试次数
    """

    name: str
    description: str
    agent_id: str
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: TaskStatus = TaskStatus.PENDING
    dependencies: List[str] = field(default_factory=list)
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    max_retries: int = 2
    retry_count: int = 0

    @property
    def is_terminal(self) -> bool:
        """任务是否已到达终态"""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    @property
    def duration_seconds(self) -> Optional[float]:
        """任务执行耗时（秒）"""
        if self.started_at is None:
            return None
        end = self.completed_at or time.time()
        return end - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentTask:
        """从字典创建"""
        return cls(
            task_id=data["task_id"],
            name=data["name"],
            description=data["description"],
            agent_id=data["agent_id"],
            status=TaskStatus(data["status"]),
            dependencies=data.get("dependencies", []),
            input_data=data.get("input_data", {}),
            output_data=data.get("output_data", {}),
            error_message=data.get("error_message"),
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            max_retries=data.get("max_retries", 2),
            retry_count=data.get("retry_count", 0),
        )
