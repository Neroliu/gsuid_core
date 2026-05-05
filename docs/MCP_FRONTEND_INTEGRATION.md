# MCP 配置前端集成文档

## 变更概述

本次重构对 MCP 配置系统进行了重大升级，主要变更：

1. **MCP Config 新增字段**：
   - `register_as_ai_tools`: bool - 是否将该 MCP 服务器的工具注册为 AI Tools
   - `tools`: list[MCPToolDefinition] - 该 MCP 服务器的所有可用工具及其参数定义

2. **新增 mcp_tools_config.json**：
   - 存储在 `data/ai_core/mcp_tools_config.json`
   - 包含 `websearch_mcp_tool_id` 和 `image_understand_mcp_tool_id`
   - ID 格式：`{mcp_id} - {tool_name}`，例如 `minimax - web_search`

3. **新增 API 端点**：
   - `GET /api/ai/mcp/{config_id}/tools` - 从已配置的 MCP 服务器发现工具
   - `POST /api/ai/mcp/discover` - 从临时配置发现工具
   - `POST /api/ai/mcp/import` - 从 JSON 导入 MCP 配置
   - `GET /api/ai/mcp/presets` - 获取 MCP 预设列表

---

## API 详解

### 1. 获取 MCP 配置列表

```
GET /api/ai/mcp/list
```

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "configs": [
            {
                "config_id": "minimax",
                "name": "MiniMax",
                "command": "uvx",
                "args": ["minimax-coding-plan-mcp"],
                "env": {"MINIMAX_API_KEY": "***"},
                "enabled": true,
                "register_as_ai_tools": false,
                "tools": [
                    {
                        "name": "web_search",
                        "description": "Web search tool",
                        "parameters": {
                            "query": {"type": "string", "required": true},
                            "max_results": {"type": "integer", "required": false}
                        }
                    },
                    {
                        "name": "understand_image",
                        "description": "Image understanding tool",
                        "parameters": {
                            "prompt": {"type": "string", "required": true},
                            "image_source": {"type": "string", "required": true}
                        }
                    }
                ]
            }
        ],
        "count": 1
    }
}
```

### 2. 从已配置的 MCP 服务器发现工具

```
GET /api/ai/mcp/{config_id}/tools。
```

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "config_id": "minimax",
        "tools": [
            {
                "name": "web_search",
                "description": "Web search tool",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer"}
                    },
                    "required": ["query"]
                }
            }
        ],
        "count": 2
    }
}
```

### 3. 从临时配置发现工具（不保存）

```
POST /api/ai/mcp/tools/discover
Content-Type: application/json

{
    "name": "MiniMax",
    "command": "uvx",
    "args": ["minimax-coding-plan-mcp"],
    "env": {
        "MINIMAX_API_KEY": "your_key_here"
    }
}
```

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "tools": [...],
        "count": 2
    }
}
```

### 4. 从 JSON 导入 MCP 配置

```
POST /api/ai/mcp/tools/import
Content-Type: application/json

{
    "json_config": "{\n  \"mcpServers\": {\n    \"MiniMax\": {\n      \"command\": \"uvx\",\n      \"args\": [\"minimax-coding-plan-mcp\"],\n      \"env\": {\n        \"MINIMAX_API_KEY\": \"your_key\"\n      }\n    }\n  }\n}"
}
```

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "config_id": "minimax",
        "name": "MiniMax",
        "tools_count": 2,
        "tool_names": ["web_search", "understand_image"]
    }
}
```

### 5. 获取 MCP 预设列表

```
GET /api/ai/mcp/presets
```

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "presets": [
            {
                "name": "MiniMax",
                "description": "MiniMax MCP 服务，提供 Web Search 和 Image Understand 功能",
                "command": "uvx",
                "args": ["minimax-coding-plan-mcp"],
                "env_template": {
                    "MINIMAX_API_KEY": "",
                    "MINIMAX_API_HOST": "https://api.minimaxi.com",
                    "MINIMAX_API_RESOURCE_MODE": "url"
                },
                "default_tools": [
                    {"name": "web_search", "description": "Web search tool"},
                    {"name": "understand_image", "description": "Image understanding tool"}
                ]
            },
            {
                "name": "Firecrawl",
                "description": "网页抓取和爬虫服务",
                "command": "uvx",
                "args": ["firecrawl-mcp"],
                "env_template": {
                    "FIRECRAWL_API_KEY": ""
                },
                "default_tools": [...]
            }
        ],
        "count": 5
    }
}
```

### 6. 创建 MCP 配置

```
POST /api/ai/mcp
Content-Type: application/json

{
    "name": "MiniMax",
    "command": "uvx",
    "args": ["minimax-coding-plan-mcp"],
    "env": {
        "MINIMAX_API_KEY": "your_key"
    },
    "enabled": true,
    "register_as_ai_tools": false,
    "tools": [
        {
            "name": "web_search",
            "description": "Web search tool",
            "parameters": {
                "query": {"type": "string", "required": true},
                "max_results": {"type": "integer", "required": false}
            }
        }
    ]
}
```

### 7. 获取 mcp_tools_config

```
GET /api/core/config/get?config_name=GsCore AI MCP 工具配置
```

**响应**：
```json
{
    "status": 0,
    "data": {
        "websearch_mcp_tool_id": "minimax - web_search",
        "image_understand_mcp_tool_id": "minimax - understand_image"
    }
}
```

### 8. 设置 mcp_tools_config

```
POST /api/core/config/set
Content-Type: application/json

{
    "config_name": "GsCore AI MCP 工具配置",
    "key": "websearch_mcp_tool_id",
    "value": "minimax - web_search"
}
```

---

## 前端页面设计建议

### MCP 管理页面 (`/mcp-config`)

#### 布局结构

```
┌─────────────────────────────────────────────────────────────────────────┐
│ MCP 服务器管理                                           [+ 添加服务器] │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ ┌─ 服务器列表 ──────────────────────────────────────────────────────┐   │
│ │                                                                    │   │
│ │  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐       │   │
│ │  │ MiniMax       │  │ Firecrawl      │  │ + 添加预设     │       │   │
│ │  │ ✓ 已启用       │  │ ✗ 已禁用       │  │                │       │   │
│ │  │ 工具: 2      │  │ 工具: 2       │  │                │       │   │
│ │  │ [编辑] [删除] │  │ [编辑] [删除]  │  │                │       │   │
│ │  └────────────────┘  └────────────────┘  └────────────────┘       │   │
│ │                                                                    │   │
│ └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│ ┌─ 快捷添加 ────────────────────────────────────────────────────────┐   │
│ │                                                                    │   │
│ │  [粘贴 JSON 添加]                                                 │   │
│ │                                                                    │   │
│ │  ┌────────────────────────────────────────────────────────────┐  │   │
│ │  │ {                                                            │  │   │
│ │  │   "mcpServers": {                                           │  │   │
│ │  │     "MiniMax": {                                            │  │   │
│ │  │       "command": "uvx",                                      │  │   │
│ │  │       "args": ["minimax-coding-plan-mcp"],                  │  │   │
│ │  │       "env": {"MINIMAX_API_KEY": "..."}                    │  │   │
│ │  │     }                                                        │  │   │
│ │  │   }                                                          │  │   │
│ │  │ }                                                            │  │   │
│ │  └────────────────────────────────────────────────────────────┘  │   │
│ │                                                                    │   │
│ │  [导入配置]                                                       │   │
│ │                                                                    │   │
│ └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 添加/编辑服务器对话框

```
┌─ 添加 MCP 服务器 ────────────────────────────────────────────────────┐
│                                                                     │
│  连接方式: (○) 手动填写    (●) 从预设选择                           │
│                                                                     │
│  选择预设: [MiniMax                    ▼]                            │
│                                                                     │
│  服务器名称: [MiniMax                    ]                           │
│  启动命令:   [uvx                       ]                           │
│  命令参数:   [minimax-coding-plan-mcp  ]                           │
│                                                                     │
│  环境变量:                                                          │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │ MINIMAX_API_KEY:     [****************************]         │     │
│  │ MINIMAX_API_HOST:    [https://api.minimaxi.com  ]         │     │
│  │ MINIMAX_API_RESOURCE_MODE: [url                       ]    │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                     │
│  [连接服务器并发现工具]  (点击后显示下方工具列表)                    │
│                                                                     │
│  发现的工具:                                                        │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │ ☑ web_search         Web search tool                       │     │
│  │ ☑ understand_image    Image understanding tool              │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                     │
│  注册为 AI Tools: [✓]                                              │
│                                                                     │
│                              [取消]  [保存配置]                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### AI 配置页面 - MCP 工具配置

```
┌─ MCP 工具配置 ─────────────────────────────────────────────────────┐
│                                                                     │
│  Web Search MCP:                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ [minimax - web_search                              ▼]      │   │
│  │                                                              │   │
│  │ 可用选项:                                                    │   │
│  │   - minimax - web_search                                     │   │
│  │   - firecrawl - scrape                                      │   │
│  │   - (未配置)                                                 │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Image Understand MCP:                                              │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ [minimax - understand_image                           ▼]    │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 预设选择对话框

```
┌─ 选择预设 ─────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ [MiniMax]     MiniMax MCP 服务                              │  │
│  │               提供 Web Search 和 Image Understand 功能        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ [Firecrawl]   网页抓取和爬虫服务                            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ [Tavily]      Tavily AI 搜索服务                             │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ [GitHub]      GitHub API 集成                                │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ [Filesystem] 本地文件系统操作                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│                              [取消]  [选择]                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 工作流程

### 流程 1: 从预设添加

1. 用户点击 "添加服务器"
2. 选择 "从预设选择"
3. 选择预设（如 MiniMax）
4. 自动填充 command、args、default_tools
5. 用户填写必要的 env（如 API Key）
6. 点击 "连接服务器并发现工具"
7. 显示发现的工具列表，用户可选择要启用的工具
8. 点击 "保存配置"

### 流程 2: 从 JSON 导入

1. 用户点击 "粘贴 JSON 添加"
2. 在文本框中粘贴 MCP JSON 配置
3. 点击 "导入配置"
4. 后端自动解析 JSON，连接服务器发现工具
5. 配置自动创建完成

### 流程 3: 手动添加

1. 用户点击 "添加服务器"
2. 选择 "手动填写"
3. 填写 server name、command、args、env
4. 点击 "连接服务器并发现工具"
5. 显示发现的工具列表
6. 点击 "保存配置"

### 流程 4: 配置 Web Search / Image Understand

1. 用户前往 AI Config 页面的 MCP 工具配置区块
2. Web Search MCP 下拉选择 `minimax - web_search`
3. Image Understand MCP 下拉选择 `minimax - understand_image`
4. 保存配置

---

## 下拉选项的数据源

前端下拉选项应从以下数据源获取：

1. **MCP 服务器列表**：
   - `GET /api/ai/mcp/list` 获取所有已配置的 MCP 服务器
   - 遍历每个服务器的 `tools` 数组
   - 生成选项：`{config_id} - {tool_name}`

2. **示例**：
```javascript
const response = await fetch('/api/ai/mcp/list');
const configs = response.data.configs;

const options = [];
for (const config of configs) {
    for (const tool of config.tools) {
        options.push({
            value: `${config.config_id} - ${tool.name}`,
            label: `${config.name} - ${tool.name}`,
        });
    }
}
```

---

## 错误处理

### 常见错误

| 错误 | 说明 | 处理方式 |
|------|------|----------|
| `连接 MCP 服务器失败` | MCP 服务器无法连接 | 检查 command、args、env 配置是否正确 |
| `配置 'xxx' 已存在` | 尝试创建已存在的配置 | 提示用户删除或重命名 |
| `不支持的 JSON 格式` | JSON 不包含 mcpServers 字段 | 提示用户粘贴正确的 MCP JSON |
| `无效的 JSON 格式` | JSON 解析失败 | 检查 JSON 语法 |

---

## 配置迁移

如果用户有旧的 `minimax_config.json`（`MINIMAX_CONFIG`），需要引导用户：

1. 导出旧配置中的 API Key
2. 在新的 MCP Config 页面创建 MiniMax 配置
3. 在 AI Config 页面的 MCP 工具配置中选择对应的工具
