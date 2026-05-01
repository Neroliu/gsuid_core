# 26. MCP Config API - /api/ai/mcp

> MCP 配置 API 提供对 MCP (Model Context Protocol) 服务器配置的管理能力。用户可以通过这些 API 自由添加、编辑、删除 MCP 服务器配置。**所有增删改和 toggle 操作会自动触发实时工具注册/注销，无需重启服务或手动调用 reload。**

## MCP 配置说明

每个 MCP 配置对应一个 MCP 服务器，配置以 JSON 文件形式存储在 `data/ai_core/mcp_configs/` 目录下。

**配置字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | MCP 服务器显示名称 |
| command | string | 是 | 启动命令，如 `uvx`, `npx`, `python` |
| args | array | 否 | 命令参数列表，默认 `[]` |
| env | object | 否 | 环境变量字典，默认 `{}` |
| enabled | boolean | 否 | 是否启用，默认 `true` |

**配置文件示例**：
```json
{
    "name": "MiniMax",
    "command": "uvx",
    "args": ["minimax-coding-plan-mcp"],
    "env": {"MINIMAX_API_KEY": "your_key"},
    "enabled": true
}
```

---

## 26.1 获取 MCP 配置列表

```
GET /api/ai/mcp/list
```

**请求头**：
```
Authorization: Bearer <token>
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
                "enabled": true
            }
        ],
        "count": 1
    }
}
```

**响应字段说明**：
| 字段 | 类型 | 说明 |
|------|------|------|
| status | integer | 状态码，0表示成功 |
| msg | string | 状态信息 |
| data.configs | array | MCP 配置列表 |
| data.configs[].config_id | string | 配置 ID（文件名不含扩展名） |
| data.configs[].name | string | MCP 服务器名称 |
| data.configs[].command | string | 启动命令 |
| data.configs[].args | array | 命令参数 |
| data.configs[].env | object | 环境变量 |
| data.configs[].enabled | boolean | 是否启用 |
| data.count | integer | 配置总数 |

---

## 26.2 获取 MCP 配置详情

```
GET /api/ai/mcp/{config_id}
```

**请求头**：
```
Authorization: Bearer <token>
```

**路径参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| config_id | string | 是 | 配置 ID |

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "config_id": "minimax",
        "name": "MiniMax",
        "command": "uvx",
        "args": ["minimax-coding-plan-mcp"],
        "env": {"MINIMAX_API_KEY": "***"},
        "enabled": true
    }
}
```

**错误响应**（配置不存在）：
```json
{
    "status": 1,
    "msg": "MCP 配置 'xxx' 不存在",
    "data": null
}
```

---

## 26.3 创建 MCP 配置

```
POST /api/ai/mcp
```

**请求头**：
```
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体**：
```json
{
    "name": "MiniMax",
    "command": "uvx",
    "args": ["minimax-coding-plan-mcp"],
    "env": {"MINIMAX_API_KEY": "your_key"},
    "enabled": true
}
```

**请求体字段说明**：
| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | - | MCP 服务器名称，同时用于生成 config_id |
| command | string | 是 | - | 启动命令 |
| args | array | 否 | `[]` | 命令参数 |
| env | object | 否 | `{}` | 环境变量 |
| enabled | boolean | 否 | `true` | 是否启用 |

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "config_id": "minimax",
        "name": "MiniMax",
        "tool_count": 3,
        "register_msg": "注册完成，共 3 个工具"
    }
}
```

**错误响应**（配置已存在）：
```json
{
    "status": 1,
    "msg": "配置 'minimax' 已存在",
    "data": null
}
```

**说明**：
- `config_id` 由 `name` 自动生成：转小写，特殊字符替换为下划线
- 创建后会自动连接 MCP 服务器并实时注册工具，无需手动 reload
- `tool_count` 表示成功注册的工具数量

---

## 26.4 更新 MCP 配置

```
PUT /api/ai/mcp/{config_id}
```

**请求头**：
```
Authorization: Bearer <token>
Content-Type: application/json
```

**路径参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| config_id | string | 是 | 配置 ID |

**请求体**（只需传要更新的字段）：
```json
{
    "command": "npx",
    "args": ["-y", "minimax-mcp"],
    "env": {"MINIMAX_API_KEY": "new_key"}
}
```

**请求体字段说明**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 否 | MCP 服务器名称 |
| command | string | 否 | 启动命令 |
| args | array | 否 | 命令参数 |
| env | object | 否 | 环境变量 |
| enabled | boolean | 否 | 是否启用 |

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "config_id": "minimax",
        "tool_count": 5,
        "register_msg": "注册完成，共 5 个工具"
    }
}
```

**说明**：
- 只更新请求体中提供的字段，未提供的字段保持不变
- 更新后会自动重新连接 MCP 服务器并实时重新注册工具，无需手动 reload

---

## 26.5 删除 MCP 配置

```
DELETE /api/ai/mcp/{config_id}
```

**请求头**：
```
Authorization: Bearer <token>
```

**路径参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| config_id | string | 是 | 配置 ID |

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "config_id": "minimax",
        "removed_tool_count": 3
    }
}
```

**错误响应**（配置不存在）：
```json
{
    "status": 1,
    "msg": "配置 'xxx' 不存在",
    "data": null
}
```

**说明**：
- 删除操作会同时删除配置文件、内存缓存，并实时注销已注册的 MCP 工具
- `removed_tool_count` 表示被移除的工具数量

---

## 26.6 切换启用/禁用状态

```
POST /api/ai/mcp/{config_id}/toggle
```

**请求头**：
```
Authorization: Bearer <token>
```

**路径参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| config_id | string | 是 | 配置 ID |

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "config_id": "minimax",
        "enabled": false,
        "tool_count": 0,
        "register_msg": "已禁用，移除了 3 个工具"
    }
}
```

**说明**：
- 此接口会将当前状态取反（启用→禁用，禁用→启用）
- 切换后会自动实时注册或注销工具：启用时连接服务器注册工具，禁用时注销已注册工具

---

## 26.7 热重载所有配置

```
POST /api/ai/mcp/reload
```

**请求头**：
```
Authorization: Bearer <token>
```

**响应**：
```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "old_tool_count": 5,
        "new_tool_count": 8,
        "config_count": 2
    }
}
```

**响应字段说明**：
| 字段 | 类型 | 说明 |
|------|------|------|
| data.old_tool_count | integer | 重载前已注册的 MCP 工具数量 |
| data.new_tool_count | integer | 重载后注册的 MCP 工具数量 |
| data.config_count | integer | 当前配置总数 |

**说明**：
- 此接口会清除所有已注册的 MCP 工具，重新加载配置文件，并重新连接所有启用的 MCP 服务器注册工具
- 通常不需要手动调用此接口，因为增删改和 toggle 操作已自动触发实时注册/注销
- 仅在需要批量刷新所有 MCP 工具时使用（如手动编辑了配置文件后）
- 重载过程中如果某个 MCP 服务器连接失败，不会影响其他服务器的注册

---

## 前端使用建议

1. **首次加载**：调用 `GET /api/ai/mcp/list` 获取所有配置列表
2. **添加配置**：调用 `POST /api/ai/mcp` 创建新配置，工具会自动实时注册，响应中包含 `tool_count`
3. **编辑配置**：调用 `PUT /api/ai/mcp/{config_id}` 更新配置，工具会自动重新注册
4. **删除配置**：调用 `DELETE /api/ai/mcp/{config_id}` 删除配置，已注册工具会自动注销
5. **启用/禁用**：调用 `POST /api/ai/mcp/{config_id}/toggle` 切换状态，工具会自动注册或注销
6. **批量刷新**：调用 `POST /api/ai/mcp/reload` 重新加载所有配置并重新注册所有工具
7. **查看已注册工具**：调用 `GET /api/ai/tools/list?category=mcp` 查看所有已注册的 MCP 工具
