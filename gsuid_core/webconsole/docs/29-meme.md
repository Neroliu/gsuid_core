# 29 - 表情包管理 API (Meme)

> **模块**: `gsuid_core/webconsole/meme_api.py`
> **前缀**: `/api/meme`
> **认证**: 所有端点均需 `require_auth`

## 概述

表情包管理 API 提供完整的表情包增删改查、手动上传、重新打标、统计概览等功能。
前端页面通过调用这些 REST API 实现管理界面，无需维护本地状态。

---

## API 清单

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/meme/list` | 列表查询 |
| GET | `/api/meme/{meme_id}` | 获取单条记录详情 |
| GET | `/api/meme/image/{meme_id}` | 获取原始图片文件 |
| PUT | `/api/meme/{meme_id}` | 更新标签/描述/归属 |
| POST | `/api/meme/{meme_id}/move` | 移动表情包到目标文件夹 |
| DELETE | `/api/meme/{meme_id}` | 删除表情包（文件+记录） |
| POST | `/api/meme/upload` | 手动上传表情包 |
| POST | `/api/meme/{meme_id}/retag` | 重新触发 VLM 打标 |
| GET | `/api/meme/stats` | 统计概览 |

---

## 详细接口

### 1. 列表查询

```
GET /api/meme/list
```

**查询参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `folder` | string | 否 | - | 文件夹过滤，如 `common`, `persona_xxx` |
| `status` | string | 否 | - | 状态过滤：`pending`, `tagged`, `manual`, `pending_manual`, `rejected` |
| `sort` | string | 否 | `created_at_desc` | 排序方式：`created_at_desc`, `use_count_desc`, `use_count_asc` |
| `page` | int | 否 | `1` | 页码 |
| `page_size` | int | 否 | `20` | 每页数量 |
| `q` | string | 否 | - | 搜索关键词（语义向量检索） |

**响应**:

```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "records": [
            {
                "meme_id": "ab12cd34ef56gh78",
                "file_path": "common/ab12cd34ef56gh78.webp",
                "file_size": 123456,
                "file_mime": "image/webp",
                "width": 300,
                "height": 300,
                "source_group": "",
                "folder": "common",
                "persona_hint": "common",
                "emotion_tags": ["搞笑", "无语"],
                "scene_tags": ["吐槽"],
                "description": "一只猫翻白眼",
                "custom_tags": [],
                "status": "tagged",
                "nsfw_score": 0.0,
                "use_count": 5,
                "last_used_at": "2026-05-03T12:00:00",
                "last_used_group": "123456",
                "created_at": "2026-05-01T08:00:00",
                "tagged_at": "2026-05-01T08:05:00",
                "updated_at": "2026-05-03T12:00:00"
            }
        ],
        "total": 100,
        "page": 1,
        "page_size": 20
    }
}
```

### 2. 获取单条记录详情

```
GET /api/meme/{meme_id}
```

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `meme_id` | string | 表情包 ID（sha256 前 16 位） |

**响应**: 同列表查询中的单条记录格式。

### 3. 获取原始图片文件

```
GET /api/meme/image/{meme_id}
```

**路径参数**: 同上。

**响应**: 返回图片二进制流，`Content-Type` 为图片 MIME 类型。

### 4. 更新标签/描述/归属

```
PUT /api/meme/{meme_id}
```

**请求体** (JSON):

```json
{
    "description": "新描述",
    "emotion_tags": ["开心", "搞笑"],
    "scene_tags": ["日常"],
    "custom_tags": ["猫咪"],
    "persona_hint": "common"
}
```

所有字段均为可选，只更新传入的字段。更新后状态自动设为 `manual`。

**响应**:

```json
{
    "status": 0,
    "msg": "更新成功",
    "data": null
}
```

### 5. 移动表情包到目标文件夹

```
POST /api/meme/{meme_id}/move
```

**表单参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `target_folder` | string | 是 | 目标文件夹名，如 `common`, `persona_xxx` |

**响应**:

```json
{
    "status": 0,
    "msg": "已移动到 common",
    "data": null
}
```

### 6. 删除表情包

```
DELETE /api/meme/{meme_id}
```

删除文件和数据库记录，同时删除 Qdrant 向量索引。

**响应**:

```json
{
    "status": 0,
    "msg": "删除成功",
    "data": null
}
```

### 7. 手动上传表情包

```
POST /api/meme/upload
```

**表单参数** (multipart/form-data):

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `file` | file | 是 | - | 图片文件 |
| `folder` | string | 否 | `common` | 目标文件夹 |
| `auto_tag` | bool | 否 | `true` | 是否自动触发 VLM 打标 |

**响应**:

```json
{
    "status": 0,
    "msg": "上传成功",
    "data": {
        "meme_id": "ab12cd34ef56gh78"
    }
}
```

### 8. 重新触发 VLM 打标

```
POST /api/meme/{meme_id}/retag
```

将记录状态重置为 `pending` 并加入打标队列。

**响应**:

```json
{
    "status": 0,
    "msg": "已加入打标队列",
    "data": null
}
```

### 9. 统计概览

```
GET /api/meme/stats
```

**响应**:

```json
{
    "status": 0,
    "msg": "ok",
    "data": {
        "total": 500,
        "status_counts": {
            "pending": 10,
            "tagged": 400,
            "manual": 50,
            "pending_manual": 30,
            "rejected": 10
        },
        "folder_counts": {
            "inbox": 10,
            "common": 300,
            "persona_早柚": 100,
            "rejected": 10
        },
        "total_usage": 1234,
        "top_memes": [
            {
                "meme_id": "ab12cd34ef56gh78",
                "description": "一只猫翻白眼",
                "use_count": 50,
                "file_path": "common/ab12cd34ef56gh78.webp"
            }
        ]
    }
}
```

---

## 数据模型

### AiMemeRecord 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `meme_id` | string | 主键，sha256(图片内容)[:16] |
| `file_path` | string | 相对路径，如 `common/ab12cd34.webp` |
| `file_size` | int | 文件大小（字节） |
| `file_mime` | string | MIME 类型 |
| `width` | int | 图片宽度（px） |
| `height` | int | 图片高度（px） |
| `source_group` | string | 来源群组 ID（不对外暴露） |
| `folder` | string | 文件夹：`inbox`, `common`, `persona_{name}`, `rejected` |
| `persona_hint` | string | Persona 归属提示 |
| `emotion_tags` | string[] | 情绪标签 |
| `scene_tags` | string[] | 场景标签 |
| `description` | string | 图片描述 |
| `custom_tags` | string[] | 自定义标签 |
| `status` | string | 状态：`pending`, `tagged`, `manual`, `pending_manual`, `rejected` |
| `nsfw_score` | float | NSFW 分数（0~1） |
| `use_count` | int | 使用次数 |
| `last_used_at` | datetime | 最后使用时间 |
| `last_used_group` | string | 最后使用的群组 |
| `created_at` | datetime | 创建时间 |
| `tagged_at` | datetime | 打标完成时间 |
| `updated_at` | datetime | 最后更新时间 |

### 状态流转

```
pending → tagged (VLM 打标成功)
pending → pending_manual (VLM 打标失败)
pending_manual → tagged (重新打标成功)
pending_manual → manual (人工编辑)
tagged → manual (人工编辑)
any → rejected (NSFW 或质量不达标)
```

---

## 前端页面设计要点

1. **列表页**: 瀑布流图片网格，支持文件夹/状态过滤、排序（最新/发送次数）。每张卡片显示缩略图、简要描述、情绪标签、使用次数。支持关键字搜索（调用 `?q=xxx`）。
2. **详情面板**: 大图预览，可编辑描述、情绪标签、场景标签、自定义标签、Persona 归属。显示使用统计（次数、最后使用时间、群）。提供移动文件夹、重新打标、删除操作。
3. **上传区**: 拖拽或点击上传，可选择目标文件夹，支持自动打标或手动输入标签。
4. **统计概览**: 展示总图片数、AI 发送总次数、待打标数、各文件夹分布（图表）。Top 10 最常用表情包（图片+次数）。
