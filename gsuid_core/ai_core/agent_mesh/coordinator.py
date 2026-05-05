"""多 Agent 任务协调器

基于 DAG（有向无环图）的任务协调器，支持：
- 定义任务依赖关系
- 自动拓扑排序执行
- 并行执行无依赖任务
- 失败重试和错误传播

使用方式:
    coordinator = AgentCoordinator()

    # 定义任务
    t1 = AgentTask(name="收集资料", description="...", agent_id="research_agent")
    t2 = AgentTask(name="撰写报告", description="...", agent_id="writer_agent", dependencies=[t1.task_id])
    t3 = AgentTask(name="审核发布", description="...", agent_id="reviewer_agent", dependencies=[t2.task_id])

    # 执行
    results = await coordinator.execute([t1, t2, t3])
"""

from __future__ import annotations

import time
import asyncio
from typing import Any, Dict, List, Callable, Optional, Awaitable

from gsuid_core.logger import logger

from .models import AgentTask, TaskStatus

# 任务执行函数类型：接收 AgentTask，返回结果字典
TaskExecutor = Callable[[AgentTask], Awaitable[Dict[str, Any]]]


class AgentCoordinator:
    """多 Agent 任务协调器

    基于 DAG 依赖图的任务协调执行器。
    支持任务的拓扑排序、并行执行、失败重试。

    Attributes:
        _executors: Agent ID -> 执行函数的映射
        _tasks: 任务 ID -> AgentTask 的映射
        _max_concurrent: 最大并发任务数
    """

    def __init__(self, max_concurrent: int = 5) -> None:
        self._executors: Dict[str, TaskExecutor] = {}
        self._tasks: Dict[str, AgentTask] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def register_executor(self, agent_id: str, executor: TaskExecutor) -> None:
        """注册 Agent 的任务执行函数

        Args:
            agent_id: Agent ID
            executor: 执行函数，接收 AgentTask 返回结果字典
        """
        self._executors[agent_id] = executor
        logger.debug(f"🕸️ [Coordinator] 注册执行器: {agent_id}")

    async def execute(self, tasks: List[AgentTask]) -> Dict[str, AgentTask]:
        """执行一组任务（基于 DAG 依赖关系）

        自动进行拓扑排序，并行执行无依赖任务，串行执行有依赖任务。

        Args:
            tasks: 任务列表

        Returns:
            任务 ID -> 最终 AgentTask 状态的映射

        Raises:
            ValueError: 存在循环依赖时抛出
        """
        # 构建任务映射
        self._tasks = {t.task_id: t for t in tasks}

        # 验证 DAG（检查循环依赖）
        self._validate_dag()

        logger.info(f"🕸️ [Coordinator] 开始执行 {len(tasks)} 个任务，最大并发: {self._max_concurrent}")

        # 执行所有任务
        await self._execute_dag()

        # 统计结果
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        logger.info(
            f"🕸️ [Coordinator] 执行完成: {completed} 成功, {failed} 失败, {len(tasks) - completed - failed} 其他"
        )

        return self._tasks

    def _validate_dag(self) -> None:
        """验证任务依赖关系是否构成 DAG（无循环依赖）

        Raises:
            ValueError: 存在循环依赖时抛出
        """
        visited: set[str] = set()
        in_stack: set[str] = set()

        def _dfs(task_id: str) -> None:
            if task_id in in_stack:
                raise ValueError(f"检测到循环依赖，涉及任务: {task_id}")
            if task_id in visited:
                return

            in_stack.add(task_id)
            task = self._tasks.get(task_id)
            if task:
                for dep_id in task.dependencies:
                    if dep_id not in self._tasks:
                        raise ValueError(f"任务 '{task_id}' 依赖的任务 '{dep_id}' 不存在")
                    _dfs(dep_id)
            in_stack.remove(task_id)
            visited.add(task_id)

        for task_id in self._tasks:
            _dfs(task_id)

    async def _execute_dag(self) -> None:
        """执行 DAG 中的所有任务"""
        # 持续执行直到所有任务到达终态
        while True:
            # 找出所有可以执行的任务（依赖已完成且自身未执行）
            ready_tasks = self._get_ready_tasks()

            if not ready_tasks:
                # 检查是否所有任务都到达终态
                if all(t.is_terminal for t in self._tasks.values()):
                    break
                # 有任务在运行中，等待
                await asyncio.sleep(0.1)
                continue

            # 并行执行就绪的任务
            coros = [self._execute_single_task(task) for task in ready_tasks]
            await asyncio.gather(*coros, return_exceptions=True)

    def _get_ready_tasks(self) -> List[AgentTask]:
        """获取所有可以执行的任务

        条件：
        1. 状态为 PENDING 或 WAITING_DEPS
        2. 所有依赖任务都已完成（COMPLETED）
        """
        ready: List[AgentTask] = []

        for task in self._tasks.values():
            if task.status not in (TaskStatus.PENDING, TaskStatus.WAITING_DEPS):
                continue

            # 检查依赖
            all_deps_completed = True
            for dep_id in task.dependencies:
                dep_task = self._tasks.get(dep_id)
                if dep_task is None or dep_task.status != TaskStatus.COMPLETED:
                    all_deps_completed = False
                    break

            if all_deps_completed:
                ready.append(task)
            elif task.status == TaskStatus.PENDING:
                task.status = TaskStatus.WAITING_DEPS

        return ready

    async def _execute_single_task(self, task: AgentTask) -> None:
        """执行单个任务

        Args:
            task: 要执行的任务
        """
        async with self._semaphore:
            executor = self._executors.get(task.agent_id)
            if executor is None:
                task.status = TaskStatus.FAILED
                task.error_message = f"未找到 Agent '{task.agent_id}' 的执行器"
                logger.error(f"🕸️ [Coordinator] {task.error_message}")
                return

            # 收集依赖任务的输出作为输入
            enriched_input = dict(task.input_data)
            for dep_id in task.dependencies:
                dep_task = self._tasks.get(dep_id)
                if dep_task and dep_task.output_data:
                    enriched_input[f"dep:{dep_id}"] = dep_task.output_data

            task.input_data = enriched_input
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            logger.info(
                f"🕸️ [Coordinator] 执行任务 '{task.name}' (Agent: {task.agent_id}, 依赖: {len(task.dependencies)})"
            )

            # 执行（带重试）
            for attempt in range(task.max_retries + 1):
                try:
                    result = await executor(task)
                    task.output_data = result
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = time.time()

                    logger.info(f"🕸️ [Coordinator] 任务 '{task.name}' 完成 (耗时: {task.duration_seconds:.1f}s)")
                    return

                except Exception as e:
                    task.retry_count = attempt + 1
                    task.error_message = str(e)

                    if attempt < task.max_retries:
                        logger.warning(
                            f"🕸️ [Coordinator] 任务 '{task.name}' 失败 (重试 {attempt + 1}/{task.max_retries}): {e}"
                        )
                        await asyncio.sleep(1.0 * (attempt + 1))  # 指数退避
                    else:
                        task.status = TaskStatus.FAILED
                        task.completed_at = time.time()
                        logger.error(f"🕸️ [Coordinator] 任务 '{task.name}' 最终失败: {e}")

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        task = self._tasks.get(task_id)
        if task:
            return task.to_dict()
        return None

    def get_all_task_statuses(self) -> Dict[str, Dict[str, Any]]:
        """获取所有任务状态"""
        return {tid: t.to_dict() for tid, t in self._tasks.items()}

    def get_execution_summary(self) -> Dict[str, Any]:
        """获取执行摘要"""
        tasks = list(self._tasks.values())
        return {
            "total": len(tasks),
            "completed": sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in tasks if t.status == TaskStatus.FAILED),
            "running": sum(1 for t in tasks if t.status == TaskStatus.RUNNING),
            "pending": sum(1 for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.WAITING_DEPS)),
            "total_duration": sum(t.duration_seconds for t in tasks if t.duration_seconds is not None),
        }
