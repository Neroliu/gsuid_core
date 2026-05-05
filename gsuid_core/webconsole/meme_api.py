"""
Meme Management APIs
提供表情包管理相关的 RESTful APIs

包括表情包列表查询、详情获取、图片获取、更新、移动、删除、
手动上传、重新打标、统计概览等功能。
"""

import io
from typing import Dict, List, Optional

from fastapi import File, Form, Depends, UploadFile
from pydantic import Field, BaseModel
from fastapi.responses import StreamingResponse

from gsuid_core.webconsole.app_app import app
from gsuid_core.webconsole.web_api import require_auth
from gsuid_core.ai_core.meme.tagger import enqueue_tag
from gsuid_core.ai_core.meme.library import (
    MemeLibrary,
    _read_file,
    get_memes_base_path,
)
from gsuid_core.ai_core.meme.database_model import AiMemeRecord

# ─────────────────────────────────────────────
# Pydantic 请求模型
# ─────────────────────────────────────────────


class MemeUpdateRequest(BaseModel):
    """更新表情包标签/描述请求"""

    description: Optional[str] = Field(None, max_length=500, description="描述文本")
    emotion_tags: Optional[List[str]] = Field(None, description="情绪标签列表")
    scene_tags: Optional[List[str]] = Field(None, description="场景标签列表")
    custom_tags: Optional[List[str]] = Field(None, description="自定义标签列表")
    persona_hint: Optional[str] = Field(None, max_length=64, description="归属提示")


class MemeMoveRequest(BaseModel):
    """移动表情包请求"""

    target_folder: str = Field(..., min_length=1, max_length=128, description="目标文件夹名")


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────


def _record_to_dict(record: AiMemeRecord) -> dict:
    """将 AiMemeRecord 转换为 API 响应字典"""
    return {
        "meme_id": record.meme_id,
        "file_path": record.file_path,
        "file_size": record.file_size,
        "file_mime": record.file_mime,
        "width": record.width,
        "height": record.height,
        "source_group": record.source_group,
        "folder": record.folder,
        "persona_hint": record.persona_hint,
        "emotion_tags": record.emotion_tags,
        "scene_tags": record.scene_tags,
        "description": record.description,
        "custom_tags": record.custom_tags,
        "status": record.status,
        "nsfw_score": record.nsfw_score,
        "use_count": record.use_count,
        "last_used_at": str(record.last_used_at) if record.last_used_at else None,
        "last_used_group": record.last_used_group,
        "created_at": str(record.created_at),
        "tagged_at": str(record.tagged_at) if record.tagged_at else None,
        "updated_at": str(record.updated_at),
    }


# ─────────────────────────────────────────────
# 1. 列表查询
# ─────────────────────────────────────────────


@app.get("/api/meme/list")
async def get_meme_list(
    folder: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "created_at_desc",
    page: int = 1,
    page_size: int = 20,
    q: Optional[str] = None,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    列表查询表情包

    Args:
        folder: 文件夹过滤
        status: 状态过滤
        sort: 排序方式
        page: 页码
        page_size: 每页数量
        q: 搜索关键词（语义向量检索）

    Returns:
        status: 0成功，1失败
        data: 包含 records、total、page、page_size 的分页结果
    """
    try:
        if q:
            # 语义向量检索
            records = await MemeLibrary.search_by_text(q, top_k=page_size * 5)
            # 手动分页
            total = len(records)
            start = (page - 1) * page_size
            end = start + page_size
            page_records = records[start:end]
        elif folder:
            # 按文件夹查询
            page_records, total = await AiMemeRecord.get_by_folder(
                folder=folder,
                status=status,
                sort=sort,
                page=page,
                page_size=page_size,
            )
        else:
            # 查询所有记录
            page_records, total = await AiMemeRecord.get_all_records(
                status=status,
                sort=sort,
                page=page,
                page_size=page_size,
            )

        records_data = [_record_to_dict(r) for r in page_records]

        return {
            "status": 0,
            "msg": "ok",
            "data": {
                "records": records_data,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
    except Exception as e:
        return {"status": 1, "msg": f"查询失败: {e}", "data": None}


# ─────────────────────────────────────────────
# 2. 获取单条记录详情
# ─────────────────────────────────────────────


@app.get("/api/meme/{meme_id}")
async def get_meme_detail(
    meme_id: str,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    获取单条表情包详情

    Args:
        meme_id: 表情包 ID（sha256 前 16 位）

    Returns:
        status: 0成功，1失败
        data: 表情包详情
    """
    try:
        record = await AiMemeRecord.get_by_meme_id(meme_id)
        if not record:
            return {"status": 1, "msg": "表情包不存在", "data": None}

        return {"status": 0, "msg": "ok", "data": _record_to_dict(record)}
    except Exception as e:
        return {"status": 1, "msg": f"查询失败: {e}", "data": None}


# ─────────────────────────────────────────────
# 3. 获取原始图片文件
# ─────────────────────────────────────────────


@app.get("/api/meme/image/{meme_id}")
async def get_meme_image(
    meme_id: str,
    _: Dict = Depends(require_auth),
) -> StreamingResponse:
    """
    获取原始图片文件

    Args:
        meme_id: 表情包 ID（sha256 前 16 位）

    Returns:
        图片二进制流，Content-Type 为图片 MIME 类型
    """
    try:
        record = await AiMemeRecord.get_by_meme_id(meme_id)
        if not record:
            return StreamingResponse(
                io.BytesIO(b"meme not found"),
                status_code=404,
                media_type="text/plain",
            )

        file_path = get_memes_base_path() / record.file_path
        image_data = await _read_file(file_path)
        if not image_data:
            return StreamingResponse(
                io.BytesIO(b"file not found"),
                status_code=404,
                media_type="text/plain",
            )

        return StreamingResponse(
            io.BytesIO(image_data),
            media_type=record.file_mime,
            headers={"Content-Disposition": f"inline; filename={record.meme_id}"},
        )
    except Exception as e:
        return StreamingResponse(
            io.BytesIO(f"error: {e}".encode()),
            status_code=500,
            media_type="text/plain",
        )


# ─────────────────────────────────────────────
# 4. 更新标签/描述/归属
# ─────────────────────────────────────────────


@app.put("/api/meme/{meme_id}")
async def update_meme(
    meme_id: str,
    req: MemeUpdateRequest,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    更新表情包标签/描述/归属

    Args:
        meme_id: 表情包 ID
        req: 更新请求体

    Returns:
        status: 0成功，1失败
    """
    try:
        record = await AiMemeRecord.get_by_meme_id(meme_id)
        if not record:
            return {"status": 1, "msg": "表情包不存在", "data": None}

        success = await MemeLibrary.update_tags(
            meme_id=meme_id,
            description=req.description,
            emotion_tags=req.emotion_tags,
            scene_tags=req.scene_tags,
            custom_tags=req.custom_tags,
            persona_hint=req.persona_hint,
            status="manual",
        )
        if not success:
            return {"status": 1, "msg": "更新失败", "data": None}

        # 同步到 Qdrant
        updated_record = await AiMemeRecord.get_by_meme_id(meme_id)
        if updated_record:
            await MemeLibrary.sync_to_qdrant(updated_record)

        return {"status": 0, "msg": "更新成功", "data": None}
    except Exception as e:
        return {"status": 1, "msg": f"更新失败: {e}", "data": None}


# ─────────────────────────────────────────────
# 5. 移动表情包到目标文件夹
# ─────────────────────────────────────────────


@app.post("/api/meme/{meme_id}/move")
async def move_meme(
    meme_id: str,
    req: MemeMoveRequest,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    移动表情包到目标文件夹

    Args:
        meme_id: 表情包 ID
        req: 移动请求体

    Returns:
        status: 0成功，1失败
    """
    try:
        record = await AiMemeRecord.get_by_meme_id(meme_id)
        if not record:
            return {"status": 1, "msg": "表情包不存在", "data": None}

        success = await MemeLibrary.move_file(meme_id, req.target_folder)
        if not success:
            return {"status": 1, "msg": "移动失败", "data": None}

        return {"status": 0, "msg": f"已移动到 {req.target_folder}", "data": None}
    except Exception as e:
        return {"status": 1, "msg": f"移动失败: {e}", "data": None}


# ─────────────────────────────────────────────
# 6. 删除表情包
# ─────────────────────────────────────────────


@app.delete("/api/meme/{meme_id}")
async def delete_meme(
    meme_id: str,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    删除表情包（文件+记录）

    Args:
        meme_id: 表情包 ID

    Returns:
        status: 0成功，1失败
    """
    try:
        record = await AiMemeRecord.get_by_meme_id(meme_id)
        if not record:
            return {"status": 1, "msg": "表情包不存在", "data": None}

        success = await MemeLibrary.delete_meme(meme_id)
        if not success:
            return {"status": 1, "msg": "删除失败", "data": None}

        return {"status": 0, "msg": "删除成功", "data": None}
    except Exception as e:
        return {"status": 1, "msg": f"删除失败: {e}", "data": None}


# ─────────────────────────────────────────────
# 7. 手动上传表情包
# ─────────────────────────────────────────────


@app.post("/api/meme/upload")
async def upload_meme(
    file: UploadFile = File(...),
    folder: str = Form("common"),
    auto_tag: bool = Form(True),
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    手动上传表情包

    Args:
        file: 图片文件
        folder: 目标文件夹
        auto_tag: 是否自动触发 VLM 打标

    Returns:
        status: 0成功，1失败
        data: 包含 meme_id 的上传结果
    """
    try:
        from PIL import Image

        # 读取文件内容
        image_data = await file.read()

        # 获取 MIME 类型
        file_mime = file.content_type or "image/jpeg"

        # 获取图片尺寸
        img = Image.open(io.BytesIO(image_data))
        width, height = img.size

        # 保存到库中（save_raw 保存到 inbox，后续可移动）
        record = await MemeLibrary.save_raw(
            image_data=image_data,
            file_mime=file_mime,
            width=width,
            height=height,
            source_group="manual",
        )

        if not record:
            return {"status": 1, "msg": "保存失败（可能已存在）", "data": None}

        # 如果指定了非 inbox 文件夹，移动过去
        if folder != "inbox":
            await MemeLibrary.move_file(record.meme_id, folder)

        # 更新状态
        if auto_tag:
            await AiMemeRecord.update_record(record.meme_id, {"status": "pending"})
            await enqueue_tag(record.meme_id)
        else:
            await AiMemeRecord.update_record(record.meme_id, {"status": "manual"})

        return {
            "status": 0,
            "msg": "上传成功",
            "data": {"meme_id": record.meme_id},
        }
    except Exception as e:
        return {"status": 1, "msg": f"上传失败: {e}", "data": None}


# ─────────────────────────────────────────────
# 8. 重新触发 VLM 打标
# ─────────────────────────────────────────────


@app.post("/api/meme/{meme_id}/retag")
async def retag_meme(
    meme_id: str,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    重新触发 VLM 打标

    Args:
        meme_id: 表情包 ID

    Returns:
        status: 0成功，1失败
    """
    try:
        record = await AiMemeRecord.get_by_meme_id(meme_id)
        if not record:
            return {"status": 1, "msg": "表情包不存在", "data": None}

        # 重置状态为待打标
        await AiMemeRecord.update_record(meme_id, {"status": "pending"})

        # 加入打标队列
        await enqueue_tag(meme_id)

        return {"status": 0, "msg": "已加入打标队列", "data": None}
    except Exception as e:
        return {"status": 1, "msg": f"操作失败: {e}", "data": None}


# ─────────────────────────────────────────────
# 9. 统计概览
# ─────────────────────────────────────────────


@app.get("/api/meme/stats")
async def get_meme_stats(
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    获取表情包统计概览

    Returns:
        status: 0成功，1失败
        data: 统计信息
    """
    try:
        stats = await AiMemeRecord.get_stats()
        return {"status": 0, "msg": "ok", "data": stats}
    except Exception as e:
        return {"status": 1, "msg": f"获取统计失败: {e}", "data": None}
