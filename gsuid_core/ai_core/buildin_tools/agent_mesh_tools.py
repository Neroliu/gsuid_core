"""Agent Mesh 工具模块

提供 AI 可调用的 Agent 协作工具，包括：
- create_persistent_agent_tool: 创建持久化子 Agent
- send_agent_task_tool: 向持久化 Agent 发送任务
- list_agents_tool: 列出所有活跃的持久化 Agent
- stop_agent_tool: 停止指定的持久化 Agent

与 create_subagent 的区别：
- create_subagent: 一次性任务，执行完即销毁，同步返回结果，框架内部使用
- 本模块工具: 持久化 Agent，跨请求运行，适合需要长期执行的复杂任务
"""

from pydantic_ai import RunContext

from gsuid_core.logger import logger
from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.register import ai_tools


@ai_tools(category="common")
async def create_persistent_agent_tool(
    ctx: RunContext[ToolContext],
    name: str,
    goal: str,
    system_prompt: str = "",
) -> str:
    """
    创建一个持久化子 Agent，它会持续运行并有独立的任务目标。
    与 create_subagent 不同，持久化 Agent 可以跨多次对话保持状态和记忆。

    【何时使用此工具而非 create_subagent】
    - 用户明确要求"创建一个XX助手/Agent"并希望它持续运行
    - 任务需要长期执行，如"帮我持续监控XX"、"定期收集XX资料"
    - 需要跨多轮对话保持上下文的复杂项目

    【何时不应使用此工具】
    - 一次性任务（如"帮我查一下XX"）→ 使用 create_subagent
    - 简单的问答或信息查询 → 直接回复
    - 框架内部的自动摘要等操作 → 使用 create_subagent

    【使用流程】
    1. 调用此工具创建 Agent，获得 agent_id
    2. 使用 send_agent_task 工具向 Agent 发送具体任务
    3. 任务完成后可继续发送新任务
    4. 不再需要时调用 stop_agent 工具停止

    Args:
        name: Agent 名称，用于标识和展示，如 "调研助手"、"代码审查员"
        goal: Agent 的长期目标描述，越具体越好，如 "收集关于 LangChain 最新版本的资料并整理成报告"
        system_prompt: 自定义系统提示词（可选，留空使用默认的通用提示词）
    """
    from gsuid_core.ai_core.agent_mesh.persistent_agent import create_persistent_agent

    logger.info(f"🕸️ [AgentMesh] 创建持久化 Agent: {name}, 目标: {goal[:50]}...")

    agent = await create_persistent_agent(
        name=name,
        goal=goal,
        system_prompt=system_prompt or None,
    )

    return (
        f"✅ 持久化 Agent 已创建\n"
        f"- ID: {agent.agent_id}\n"
        f"- 名称: {agent.name}\n"
        f"- 目标: {agent.goal}\n"
        f"使用 send_agent_task 工具向它发送任务。"
    )


@ai_tools(category="common")
async def send_agent_task_tool(
    ctx: RunContext[ToolContext],
    agent_id: str,
    task: str,
) -> str:
    """
    向已创建的持久化 Agent 发送任务并等待执行结果。
    Agent 会利用其长期目标上下文来理解和执行任务。

    【使用前提】
    - 必须先通过 create_persistent_agent_tool 创建 Agent 并获得 agent_id
    - Agent 必须处于运行状态（可通过 list_agents_tool 检查）

    【任务描述建议】
    - 尽量具体明确，包含期望的输出格式
    - 可以引用之前的任务结果，Agent 会保持上下文
    - 示例："搜索最新的 Python 3.13 新特性，整理成要点列表"

    【注意事项】
    - 任务执行可能需要较长时间（最长 300 秒超时）
    - 如果 Agent 不存在或已停止，会返回错误信息
    - 同一 Agent 同时只能执行一个任务

    Args:
        agent_id: 目标 Agent 的 ID（由 create_persistent_agent_tool 返回的 ID）
        task: 要执行的任务描述，尽量具体明确
    """
    from gsuid_core.ai_core.agent_mesh.persistent_agent import get_persistent_agent

    agent = get_persistent_agent(agent_id)
    if agent is None:
        return f"❌ 找不到 Agent: {agent_id}，请检查 ID 是否正确或 Agent 是否已停止。"

    logger.info(f"🕸️ [AgentMesh] 向 Agent '{agent.name}' 发送任务: {task[:50]}...")

    result = await agent.send_task(task)
    return f"【Agent '{agent.name}' 执行结果】\n{result}"


@ai_tools(category="common")
async def list_agents_tool(
    ctx: RunContext[ToolContext],
) -> str:
    """
    列出所有当前活跃的持久化 Agent 及其状态信息。

    【何时使用】
    - 用户询问"有哪些 Agent 在运行"
    - 在创建新 Agent 前检查是否已有同功能的 Agent
    - 在发送任务前确认目标 Agent 是否在线

    【返回信息】
    - Agent ID、名称、当前状态（idle/working/error）
    - 已执行的任务数量
    - 空闲时间（超过 1 小时未活动的 Agent 会被自动停止）
    """
    from gsuid_core.ai_core.agent_mesh.persistent_agent import list_persistent_agents

    agents = list_persistent_agents()

    if not agents:
        return "当前没有活跃的持久化 Agent。"

    lines = ["当前活跃的持久化 Agent:"]
    for info in agents:
        lines.append(
            f"- [{info['agent_id']}] {info['name']} "
            f"(状态: {info['status']}, 已执行 {info['task_count']} 个任务, "
            f"空闲 {info['idle_seconds']:.0f}s)"
        )

    return "\n".join(lines)


@ai_tools(category="common")
async def stop_agent_tool(
    ctx: RunContext[ToolContext],
    agent_id: str,
) -> str:
    """
    停止指定的持久化 Agent，释放其占用的资源。

    【何时使用】
    - 用户明确要求停止某个 Agent
    - Agent 的目标已完成，不再需要
    - 需要重新创建 Agent（先停止旧的再创建新的）

    【注意事项】
    - 停止后 Agent 的历史任务记录会丢失
    - Agent 空闲超过 1 小时会自动停止
    - 框架关闭时所有 Agent 会被自动停止

    Args:
        agent_id: 要停止的 Agent 的 ID（通过 list_agents_tool 或 create_persistent_agent_tool 获得）
    """
    from gsuid_core.ai_core.agent_mesh.persistent_agent import get_persistent_agent

    agent = get_persistent_agent(agent_id)
    if agent is None:
        return f"❌ 找不到 Agent: {agent_id}。"

    agent_name = agent.name
    await agent.stop()
    return f"✅ Agent '{agent_name}' ({agent_id}) 已停止。"
