"""
Buildin Tools 模块

系统内建AI工具模块，提供自主型AI常用的基础工具函数。

## 工具分类

### Self工具, 只有主Agent能调用 (category="self")
- query_user_favorability: 查询用户好感度
- update_user_favorability: 更新用户好感度（增量）
- create_subagent: 创建子Agent完成特定任务
- send_message_by_ai: 发送消息给用户
- add_once_task: 添加一次性定时任务
- add_interval_task: 添加循环任务
- list_scheduled_tasks: 列出所有定时任务
- query_scheduled_task: 查询任务详情
- modify_scheduled_task: 修改任务
- cancel_scheduled_task: 取消任务
- pause_scheduled_task: 暂停任务
- resume_scheduled_task: 恢复任务

### 默认内置工具, 主Agent调用时也会加载 (category="buildin")
直接调用，不需要特别理由不会拒绝。
- search_knowledge: 检索知识库内容
- search_image: 检索图片资源
- web_search_tool: Web搜索工具
- web_fetch_tool: 网页抓取工具（将网页转换为Markdown）
- query_user_memory: 查询用户记忆
- get_self_persona_info: 获取自身Persona信息
- set_user_favorability: 设置用户好感度（绝对值）

### 通常工具 (category="common")
有选择地调用，当用户明确需要相关功能时使用。
- send_meme: 发送表情包
- collect_meme: 收藏表情包
- search_meme: 搜索表情包
- create_persistent_agent_tool: 创建持久化子Agent
- send_agent_task_tool: 向持久化Agent发送任务
- list_agents_tool: 列出所有活跃的持久化Agent
- stop_agent_tool: 停止指定的持久化Agent

### 子Agent工具 (category="default")
通过 create_subagent 调用，用于文件操作、代码执行等。
- execute_shell_command: 执行系统命令
- get_current_date: 获取当前日期时间
- read_file_content: 读取文件内容
- write_file_content: 写入文件内容
- execute_file: 执行脚本文件
- diff_file_content: 对比文件差异
- list_directory: 列出目录内容

所有工具均使用 @ai_tools(category=...) 装饰器注册。
"""

# 工具装饰器
from gsuid_core.ai_core.register import ai_tools

# AI日期工具 - 获取当前日期时间
from gsuid_core.ai_core.buildin_tools.get_time import (
    get_current_date,
    _get_current_date,
)

# Subagent工具 - 创建子Agent完成特定任务
from gsuid_core.ai_core.buildin_tools.subagent import create_subagent

# 定时任务工具 - 管理定时/循环任务（增删改查启停）
from gsuid_core.ai_core.buildin_tools.scheduler import (
    add_once_task,
    add_interval_task,
    list_scheduled_tasks,
    pause_scheduled_task,
    query_scheduled_task,
    cancel_scheduled_task,
    modify_scheduled_task,
    resume_scheduled_task,
)

# 自我信息工具 - 获取自身Persona信息
from gsuid_core.ai_core.buildin_tools.self_info import get_self_persona_info

# 网页抓取工具 - 抓取网页内容并转换为Markdown
from gsuid_core.ai_core.buildin_tools.web_fetch import web_fetch_tool

# 表情包工具 - 发送/收藏/搜索表情包
from gsuid_core.ai_core.buildin_tools.meme_tools import (
    send_meme,
    search_meme,
    collect_meme,
)

# RAG检索工具 - 知识库查询，支持类别/插件筛选
from gsuid_core.ai_core.buildin_tools.rag_search import (
    search_image,
    search_knowledge,
)

# Web搜索工具 - 基于Tavily的web搜索
from gsuid_core.ai_core.buildin_tools.web_search import web_search_tool

# 文件管理工具 - 读写执行文件和diff对比
from gsuid_core.ai_core.buildin_tools.file_manager import (
    execute_file,
    list_directory,
    diff_file_content,
    read_file_content,
    write_file_content,
)

# 数据库查询工具 - 查询用户数据
from gsuid_core.ai_core.buildin_tools.database_query import (
    query_user_memory,
    query_user_favorability,
)

# 消息发送工具 - 主动发送消息
from gsuid_core.ai_core.buildin_tools.message_sender import (
    send_message_by_ai,
)

# Agent Mesh 工具 - 持久化 Agent 协作
from gsuid_core.ai_core.buildin_tools.agent_mesh_tools import (
    stop_agent_tool,
    list_agents_tool,
    send_agent_task_tool,
    create_persistent_agent_tool,
)

# 命令执行工具 - 执行系统命令
from gsuid_core.ai_core.buildin_tools.command_executor import execute_shell_command

# 好感度管理工具 - 管理用户好感度
from gsuid_core.ai_core.buildin_tools.favorability_manager import (
    set_user_favorability,
    update_user_favorability,
)

# 动态工具发现 - 允许AI搜索和发现可能需要的新工具
from gsuid_core.ai_core.buildin_tools.dynamic_tool_discovery import (
    discover_tools,
    list_available_tools,
)

__all__ = [
    # 工具装饰器
    "ai_tools",
    # RAG检索工具
    "search_knowledge",
    "search_image",
    # Web搜索工具
    "web_search_tool",
    # 网页抓取工具
    "web_fetch_tool",
    # 消息发送工具
    "send_message_by_ai",
    # 命令执行工具
    "execute_shell_command",
    # 数据库查询工具
    "query_user_favorability",
    "query_user_memory",
    # 好感度管理工具
    "update_user_favorability",
    "set_user_favorability",
    # 表情包工具
    "send_meme",
    "collect_meme",
    "search_meme",
    # AI日期工具
    "get_current_date",
    "_get_current_date",
    # Subagent工具
    "create_subagent",
    # 自我信息工具
    "get_self_persona_info",
    # 文件管理工具
    "read_file_content",
    "write_file_content",
    "execute_file",
    "diff_file_content",
    "list_directory",
    # 定时任务工具
    "add_once_task",
    "add_interval_task",
    "list_scheduled_tasks",
    "query_scheduled_task",
    "modify_scheduled_task",
    "cancel_scheduled_task",
    "pause_scheduled_task",
    "resume_scheduled_task",
    # 动态工具发现
    "discover_tools",
    "list_available_tools",
    # Agent Mesh 工具
    "create_persistent_agent_tool",
    "send_agent_task_tool",
    "list_agents_tool",
    "stop_agent_tool",
]
