# MCP 工具集成 - 变更记录

> 日期: 2026-04-30
> 变更类型: 新功能 (Feature)

## 变更概述

新增 MCP (Model Context Protocol) 工具集成系统，允许用户通过 WebConsole 前端自由添加、管理 MCP 服务器配置，框架启动时自动连接 MCP 服务器并将工具注册为 AI 工具，使 AI 可以自由调用 MCP 工具并利用返回结果。

---

## 变更文件清单

### 新增文件

| 文件路径 | 说明 |
|----------|------|
| [`gsuid_core/ai_core/mcp/config_manager.py`](../gsuid_core/ai_core/mcp/config_manager.py) | MCP 配置管理器，管理 `data/ai_core/mcp_configs/` 目录下的 JSON 配置文件，支持增删改查 |
| [`gsuid_core/ai_core/mcp/startup.py`](../gsuid_core/ai_core/mcp/startup.py) | MCP 工具启动注册模块，框架启动时自动连接 MCP 服务器并注册工具到 `_TOOL_REGISTRY` |
| [`gsuid_core/webconsole/mcp_config_api.py`](../gsuid_core/webconsole/mcp_config_api.py) | MCP 配置 WebConsole API，提供 RESTful 增删改查接口 |
| [`docs/MCP_TOOL_INTEGRATION_CHANGELOG.md`](MCP_TOOL_INTEGRATION_CHANGELOG.md) | 本文档 |

### 修改文件

| 文件路径 | 变更内容 |
|----------|----------|
| [`gsuid_core/ai_core/resource.py`](../gsuid_core/ai_core/resource.py) | 新增 `MCP_CONFIGS_PATH` 路径常量，指向 `data/ai_core/mcp_configs/` |
| [`gsuid_core/ai_core/mcp/__init__.py`](../gsuid_core/ai_core/mcp/__init__.py) | 导出新增的 `MCPConfig`、`MCPConfigManager`、`mcp_config_manager`、`register_all_mcp_tools` |
| [`gsuid_core/webconsole/__init__.py`](../gsuid_core/webconsole/__init__.py) | 导入 `mcp_config_api` 模块以注册 MCP API 路由 |
| [`docs/AI_TRIGGER_FLOW.md`](AI_TRIGGER_FLOW.md) | 更新模块结构、工具分类表、新增 5.5.11 MCP 工具集成章节、新增 8.0 MCP 配置 API 章节 |
| [`gsuid_core/webconsole/docs/26-mcp-config.md`](../gsuid_core/webconsole/docs/26-mcp-config.md) | 新增 MCP Config API 文档，包含所有 7 个端点的详细说明 |
| [`gsuid_core/webconsole/docs/README.md`](../gsuid_core/webconsole/docs/README.md) | 目录中新增第 25 项 MCP Config API 链接 |
| [`gsuid_core/webconsole/docs/14-ai-tools.md`](../gsuid_core/webconsole/docs/14-ai-tools.md) | 工具分类表中新增 `mcp` 分类说明 |

---

## 架构设计

### 数据流

```
用户 (WebConsole 前端)
    │
    │  POST /api/ai/mcp (创建配置)
    │  PUT /api/ai/mcp/{id} (更新配置)
    │  DELETE /api/ai/mcp/{id} (删除配置)
    │  POST /api/ai/mcp/reload (热重载)
    ▼
┌─────────────────────────────────────────┐
│  webconsole/mcp_config_api.py           │
│  (FastAPI RESTful API)                  │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  ai_core/mcp/config_manager.py          │
│  MCPConfigManager (JSON 文件存储)        │
│  data/ai_core/mcp_configs/*.json        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  ai_core/mcp/startup.py                 │
│  register_all_mcp_tools()               │
│  ├── MCPClient.list_tools()             │
│  ├── 动态创建包装函数                     │
│  └── 注册到 _TOOL_REGISTRY["mcp"]       │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  ai_core/register.py                    │
│  _TOOL_REGISTRY["mcp"]                  │
│  (MCP 工具与其他工具统一管理)              │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  ai_core/gs_agent.py                    │
│  AI Agent 通过 search_tools() 发现      │
│  并调用 MCP 工具                         │
└─────────────────────────────────────────┘
```

### 工具分类扩展

原有分类: `self`, `buildin`, `common`, `default`

新增分类: `mcp` - MCP 外部工具，启动时自动注册，按需加载

### 工具命名规则

MCP 工具注册时使用 `mcp_{server_name}_{tool_name}` 格式，避免不同 MCP 服务器之间的工具名冲突。

---

## WebConsole API 端点

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/api/ai/mcp/list` | 获取所有 MCP 配置列表 |
| GET | `/api/ai/mcp/{config_id}` | 获取指定配置详情 |
| POST | `/api/ai/mcp` | 创建新 MCP 配置 |
| PUT | `/api/ai/mcp/{config_id}` | 更新 MCP 配置 |
| DELETE | `/api/ai/mcp/{config_id}` | 删除 MCP 配置 |
| POST | `/api/ai/mcp/{config_id}/toggle` | 切换启用/禁用状态 |
| POST | `/api/ai/mcp/reload` | 热重载所有配置并重新注册工具 |
| GET | `/api/ai/mcp/presets` | 获取 MCP 预设配置列表 |
| GET | `/api/ai/mcp/{config_id}/tools` | 从已配置的 MCP 服务器发现工具 |
| POST | `/api/ai/mcp/tools/discover` | 从临时配置发现工具（不保存） |
| POST | `/api/ai/mcp/tools/import` | 从 JSON 导入 MCP 配置 |

> **注意**：所有增删改和 toggle 操作会自动触发实时工具注册/注销，无需重启服务或手动调用 reload。

---

## 配置文件格式

存储路径: `data/ai_core/mcp_configs/{config_id}.json`

```json
{
    "name": "MiniMax",
    "command": "uvx",
    "args": ["minimax-coding-plan-mcp"],
    "env": {"MINIMAX_API_KEY": "your_key"},
    "enabled": true,
    "register_as_ai_tools": false,
    "tools": [
        {
            "name": "web_search",
            "description": "Web search tool",
            "parameters": {
                "query": {"type": "string", "required": true}
            }
        }
    ],
    "tool_permissions": {
        "send_email": 0,
        "query_data": 6
    }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | MCP 服务器显示名称 |
| `command` | `str` | 启动命令（如 `uvx`, `npx`, `python`） |
| `args` | `list[str]` | 命令参数列表 |
| `env` | `dict[str, str]` | 环境变量字典 |
| `enabled` | `bool` | 是否启用 |
| `register_as_ai_tools` | `bool` | 是否将该 MCP 服务器的工具注册为 AI 工具，默认 `false` |
| `tools` | `list[MCPToolDefinition]` | 工具定义列表，默认 `[]` |
| `tool_permissions` | `dict[str, int]` | 工具权限配置，键为工具名，值为 pm 权限等级，默认 `{}` |

---

## 启动流程

1. 框架启动时，`on_core_start` 钩子（priority=5）触发 `register_all_mcp_tools()`
2. 从 `mcp_config_manager` 获取所有 `enabled=true` 的配置
3. 对每个配置创建 `MCPClient` 并调用 `list_tools()` 获取工具列表
4. 为每个 MCP 工具动态创建包装函数，解析 `input_schema` 生成正确的函数签名
5. 将工具注册到 `_TOOL_REGISTRY["mcp"]` 分类
6. AI Agent 通过 `search_tools()` 向量搜索发现并调用 MCP 工具

---

## 设计决策

1. **JSON 文件存储** vs 数据库: MCP 配置使用 JSON 文件存储在 `data/ai_core/mcp_configs/` 目录下，与 OpenAI 配置管理器模式一致，简单直观，便于手动编辑和备份。

2. **动态函数生成**: 为每个 MCP 工具动态创建包装函数，根据 `input_schema` 生成正确的类型注解和函数签名，确保 PydanticAI 能正确生成 JSON Schema 给 LLM。

3. **无状态 MCP 客户端**: 每次工具调用时建立连接、执行操作、断开连接，避免长连接管理的复杂性。

4. **热重载支持**: 通过 `POST /api/ai/mcp/reload` 可以在运行时重新加载配置并重新注册工具，无需重启服务。

5. **工具名冲突避免**: 使用 `mcp_{server_name}_{tool_name}` 格式命名，避免不同 MCP 服务器之间的工具名冲突。
