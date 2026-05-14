# 10. 消息推送 API - /api/BatchPush

## 10.1 批量推送
```
POST /api/BatchPush
```

**请求体**：
```json
{
    "push_text": "<p>推送内容</p><img src='base64,...'/>",
    "push_tag": "ALLUSER,ALLGROUP,g:123456|bot1,u:654321|bot2",
    "push_bot": "bot1,bot2"
}
```

**推送目标格式**：
- `ALLUSER`: 所有用户
- `ALLGROUP`: 所有群组
- `g:群ID|botID`: 指定群
- `u:用户ID|botID`: 指定用户

---

## 10.2 通用图片上传

```
POST /api/uploadImage/{suffix}/{filename}/{UPLOAD_PATH:path}
```

**描述**: 通用图片文件上传接口，允许向服务器指定的物理路径上传并保存图片文件。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `suffix` | string | 否 | 文件后缀名，如 `jpg`、`png` |
| `filename` | string | 否 | 自定义文件名（不含后缀） |
| `UPLOAD_PATH` | string | 是 | 上传目标路径 |

**请求体**: `multipart/form-data`，包含 `file` 字段（图片文件）

**响应**（成功）：
```json
{
    "status": 0,
    "msg": "上传成功",
    "data": {
        "filename": "20260514203000.jpg"
    }
}
```

---

## 10.3 通用图片读取

```
GET /api/getImage/{suffix}/{filename}/{IMAGE_PATH:path}
```

**描述**: 通用图片文件读取接口，从指定的物理路径读取并返回图片流。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `suffix` | string | 是 | 文件后缀名 |
| `filename` | string | 是 | 文件名（不含后缀） |
| `IMAGE_PATH` | string | 是 | 图片所在路径 |

**响应**: 返回图片二进制流（Content-Type: image/jpeg）

---

## 10.4 图片资源读取（阅后即焚）

```
GET /api/image/{image_id}
```

**描述**: 从机器人的 `image_res` 缓存目录获取图片返回，内置异步定时删除（阅后即焚）功能。此接口**不需要认证**。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_id` | string | 是 | 图片 ID |

**响应**: 返回图片二进制流（支持 JPEG、GIF 等格式）

**说明**：
- 如果配置了 `EnableCleanPicSrv` 为 `true`，图片在返回后会根据 `ScheduledCleanPicSrv` 配置的时间自动删除
- 支持 `.jpg`、`.gif` 等格式，GIF 会直接返回原始字节，其他格式会转换为 JPEG
