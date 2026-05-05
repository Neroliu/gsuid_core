# 表情包模块（MemeModule）设计文档

> **版本**: v2.0 | **适用环境**: 2C2G 低配机器 | **面向**: 群聊 AI Agent（GsCore 框架）

---

## 1. 概述

让 AI 在群聊中具备「表情包意识」：

| 能力 | 描述 |
|------|------|
| **自动采集** | 监听群聊图片，经过滤后异步入库 |
| **智能打标** | 调用 AI Agent 理解图片内容，生成情绪/场景标签 |
| **分类存储** | 按 Persona 归档 + 通用库，支持文件系统 + SQLModel + Qdrant 向量索引 |
| **智能发送** | AI 工具调用，根据情境自主决策发送哪张表情包 |
| **Web 管理** | WebConsole 管理 API 提供完整增删改查、使用频次展示 |

---

## 2. 文件结构

```
gsuid_core/ai_core/meme/
├── config.py                # 配置项（StringConfig）
├── database_model.py        # AiMemeRecord SQLModel 表
├── filter.py                # 去重 + 质量过滤
├── library.py               # 文件 + DB + Qdrant 操作
├── observer.py              # 消息流监听
├── selector.py              # 检索 + 决策
├── startup.py               # @on_core_start 钩子
└── tagger.py                # VLM 打标引擎

gsuid_core/ai_core/buildin_tools/
└── meme_tools.py            # 3 个 @ai_tools（send_meme, collect_meme, search_meme）

gsuid_core/webconsole/docs/
└── 29-meme.md               # WebConsole API 文档
```

---

## 3. 核心设计

### 3.1 异步架构（不阻塞主流程）

| 操作 | 异步策略 | 说明 |
|------|----------|------|
| 图片采集 | `asyncio.create_task` | fire-and-forget，不阻塞 handle_ai_chat |
| 图片下载 | `httpx.AsyncClient` | 异步 HTTP |
| 文件读写 | `@to_thread` | 通过线程池异步化 PIL/Path 操作 |
| VLM 打标 | `asyncio.Queue` + `Semaphore(1)` | 后台 worker 循环消费 |
| 数据库操作 | `@with_session` | SQLModel 异步 session |
| 向量检索 | `client.query_points()` | Qdrant 异步客户端 |

### 3.2 打标流程

```
群聊图片 → observer（asyncio.create_task）
  → filter（MIME/尺寸/大小/每日限额/磁盘空间）
    → library.save_raw()（写文件 + 写 DB，status=pending）
      → tagger.enqueue_tag()（加入 asyncio.Queue）
        → _tag_worker_loop()（后台消费）
          → _get_vision_task_level()（优先低级模型）
          → create_agent() + ImageUrl（复用 Agent 基础设施）
          → extract_json_from_text()（复用 JSON 解析）
          → library.update_tags() + move_file() + sync_to_qdrant()
```

### 3.3 发送流程

```
AI 调用 send_meme(mood, scene)
  → selector.pick()
    → 冷却检查
    → 向量检索（persona 专属 → 通用库）
    → 降级：随机选取
    → 降级：最久未使用
  → _read_file()（@to_thread 异步读取）
  → convert_img() + MessageSegment.image()
  → bot.send()
  → record_usage()
```

### 3.4 能力感知

打标前通过 `model_support` 配置检查模型是否支持图片输入：
- 优先使用低级模型（节省成本）
- 低级模型不支持图片时才用高级模型
- 都不支持时标记为 `pending_manual`，等待人工处理

---

## 4. 配置项

配置文件: `data/ai_core/meme_config.json`

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `meme_enable` | bool | `true` | 总开关 |
| `meme_auto_collect` | bool | `true` | 自动采集群聊图片 |
| `meme_max_file_kb` | int | `512` | 单文件最大大小(KB) |
| `meme_allowed_mime` | list | `["image/jpeg", "image/png", "image/gif", "image/webp"]` | 允许的图片格式 |
| `meme_min_width` | int | `60` | 最小宽度(px) |
| `meme_min_height` | int | `60` | 最小高度(px) |
| `meme_daily_collect_limit` | int | `30` | 每群每日自动采集上限 |
| `meme_vlm_semaphore` | int | `1` | VLM 打标并发上限 |
| `meme_tag_interval_sec` | int | `3` | 打标间隔(秒) |
| `meme_nsfw_threshold` | float | `0.6` | NSFW 分数阈值 |
| `meme_send_cooldown_sec` | int | `60` | 同一会话发图冷却(秒) |
| `meme_recent_exclude_count` | int | `10` | 排除最近N张已发图 |

---

## 5. 数据库模型

### AiMemeRecord

表名自动推导为 `aimemerecord`（SQLModel 规范，不使用 `__tablename__`）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `meme_id` | str (PK) | sha256(图片内容)[:16] |
| `file_path` | str | 相对路径，如 `common/ab12cd34.webp` |
| `file_size` | int | 文件大小（字节） |
| `file_mime` | str | MIME 类型 |
| `width` / `height` | int | 图片尺寸 |
| `source_group` / `source_user` | str | 来源信息（不对外暴露） |
| `folder` | str | `inbox` / `common` / `persona_{name}` / `rejected` |
| `persona_hint` | str | Persona 归属提示 |
| `emotion_tags` / `scene_tags` / `custom_tags` | JSON | 标签列表 |
| `description` | str | 图片描述 |
| `status` | str | `pending` / `tagged` / `manual` / `pending_manual` / `rejected` |
| `nsfw_score` | float | NSFW 分数 |
| `use_count` | int | 使用次数 |
| `last_used_at` | datetime | 最后使用时间 |
| `qdrant_id` | str | Qdrant point ID |

---

## 6. WebConsole API

详见 [`gsuid_core/webconsole/docs/29-meme.md`](../webconsole/docs/29-meme.md)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/meme/list` | 列表查询（支持向量检索 `?q=xxx`） |
| GET | `/api/meme/{meme_id}` | 获取详情 |
| GET | `/api/meme/image/{meme_id}` | 获取图片流 |
| PUT | `/api/meme/{meme_id}` | 更新标签 |
| POST | `/api/meme/{meme_id}/move` | 移动文件夹 |
| DELETE | `/api/meme/{meme_id}` | 删除 |
| POST | `/api/meme/upload` | 上传 |
| POST | `/api/meme/{meme_id}/retag` | 重新打标 |
| GET | `/api/meme/stats` | 统计概览 |

---

## 7. 降级策略

| 场景 | 处理方式 |
|------|---------|
| 模型不支持图片输入 | 采集时 observer 检查 `model_support`，不支持则跳过；打标时标记 `pending_manual` |
| VLM 打标失败 | 标记 `pending_manual`，等待人工处理 |
| 磁盘空间不足 (<200MB) | 停止采集 |
| 打标队列积压 (>100) | 丢弃新入队任务，记录日志 |
| 向量检索无结果 | 降级随机选取 |
| 图片 URL 失效 | 采集丢弃，不写库 |
