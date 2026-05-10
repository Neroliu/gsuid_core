"""
AI Session Logs APIs
提供 AI Agent 会话执行日志的 RESTful APIs

统一合并内存活跃会话 + 本地持久化日志，去重后提供给前端，
便于前端渲染 AI 调用历史栈，清晰展示每一步结果。
"""

import json
import time
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime

from fastapi import Depends
from pydantic import Field, BaseModel

from gsuid_core.logger import logger
from gsuid_core.ai_core.history import get_history_manager
from gsuid_core.ai_core.resource import AI_SESSION_LOGS_PATH
from gsuid_core.webconsole.app_app import app
from gsuid_core.webconsole.web_api import require_auth

# ─────────────────────────────────────────────
# Pydantic 请求模型
# ─────────────────────────────────────────────


class SessionLogsFilterRequest(BaseModel):
    """Session 日志筛选请求"""

    session_id: Optional[str] = Field(None, description="按 session_id 精确筛选")
    create_by: Optional[str] = Field(None, description="按创建来源筛选 (Chat/SubAgent/BuildPersona/LLM)")
    persona_name: Optional[str] = Field(None, description="按 Persona 名称筛选")
    is_active: Optional[bool] = Field(None, description="按是否活跃筛选 (true=仅活跃, false=仅已结束)")
    date_from: Optional[str] = Field(None, description="起始日期 YYYY-MM-DD")
    date_to: Optional[str] = Field(None, description="结束日期 YYYY-MM-DD")
    limit: int = Field(default=50, ge=1, le=200, description="返回数量限制")
    offset: int = Field(default=0, ge=0, description="偏移量")


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────


def _build_summary_from_memory(sid: str, session: Any) -> Dict[str, Any]:
    """从内存中的活跃 Session 构建日志摘要"""
    logger_obj: Optional[Any] = getattr(session, "_session_logger", None)

    if logger_obj is not None:
        entries: List[Dict[str, Any]] = getattr(logger_obj, "entries", [])
        created_at: float = getattr(logger_obj, "created_at", 0)
        updated_at: float = getattr(logger_obj, "updated_at", 0)
        session_uuid: Optional[str] = getattr(logger_obj, "session_uuid", None)
        persona_name: Optional[str] = getattr(logger_obj, "persona_name", None)
        create_by: Optional[str] = getattr(logger_obj, "create_by", None)
        ended_at: Optional[float] = getattr(logger_obj, "ended_at", None)
        file_name: Optional[str] = str(getattr(logger_obj, "_file_path", Path("")).name) or None
    else:
        entries = []
        created_at = 0
        updated_at = 0
        session_uuid = None
        persona_name = None
        create_by = None
        ended_at = None
        file_name = None

    # 计算运行时长
    duration: Optional[float] = None
    if ended_at and created_at:
        duration = ended_at - created_at
    elif created_at:
        duration = time.time() - created_at

    # 统计各类型条目数量
    type_counts: Dict[str, int] = {}
    for entry in entries:
        etype: str = entry.get("type", "unknown")
        type_counts[etype] = type_counts.get(etype, 0) + 1

    return {
        "session_id": sid,
        "session_uuid": session_uuid,
        "persona_name": persona_name,
        "create_by": create_by,
        "created_at": created_at,
        "created_at_str": datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S") if created_at else None,
        "updated_at": updated_at,
        "updated_at_str": datetime.fromtimestamp(updated_at).strftime("%Y-%m-%d %H:%M:%S") if updated_at else None,
        "ended_at": ended_at,
        "ended_at_str": datetime.fromtimestamp(ended_at).strftime("%Y-%m-%d %H:%M:%S") if ended_at else None,
        "duration_seconds": round(duration, 2) if duration else None,
        "entry_count": len(entries),
        "type_counts": type_counts,
        "is_active": ended_at is None,
        "source": "memory",
        "file_name": file_name,
    }


def _parse_log_file(path: Path) -> Optional[Dict[str, Any]]:
    """解析单个日志 JSON 文件，返回摘要信息"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)

        created_at: float = data.get("created_at", 0)
        ended_at: Optional[float] = data.get("ended_at")
        entry_count: int = data.get("entry_count", 0)

        # 计算运行时长
        duration: Optional[float] = None
        if ended_at and created_at:
            duration = ended_at - created_at
        elif created_at:
            duration = time.time() - created_at

        # 统计各类型条目数量
        type_counts: Dict[str, int] = {}
        for entry in data.get("entries", []):
            etype: str = entry.get("type", "unknown")
            type_counts[etype] = type_counts.get(etype, 0) + 1

        return {
            "session_id": data.get("session_id"),
            "session_uuid": data.get("session_uuid"),
            "persona_name": data.get("persona_name"),
            "create_by": data.get("create_by"),
            "created_at": created_at,
            "created_at_str": datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S") if created_at else None,
            "updated_at": data.get("updated_at"),
            "updated_at_str": (
                datetime.fromtimestamp(data.get("updated_at", 0)).strftime("%Y-%m-%d %H:%M:%S")
                if data.get("updated_at")
                else None
            ),
            "ended_at": ended_at,
            "ended_at_str": datetime.fromtimestamp(ended_at).strftime("%Y-%m-%d %H:%M:%S") if ended_at else None,
            "duration_seconds": round(duration, 2) if duration else None,
            "entry_count": entry_count,
            "type_counts": type_counts,
            "is_active": ended_at is None,
            "source": "disk",
            "file_name": path.name,
        }
    except Exception:
        return None


def _load_log_detail(path: Path) -> Optional[Dict[str, Any]]:
    """加载单个日志文件的完整内容"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
        return data
    except Exception:
        return None


def _list_log_files() -> List[Path]:
    """列出所有日志文件"""
    if not AI_SESSION_LOGS_PATH.exists():
        return []

    files: List[Path] = [p for p in AI_SESSION_LOGS_PATH.iterdir() if p.is_file() and p.suffix == ".json"]
    return files


def _build_unified_list() -> List[Dict[str, Any]]:
    """
    构建统一的日志列表：合并内存活跃会话 + 磁盘持久化文件，按 session_uuid 去重

    去重规则：同一 session_uuid 在内存和磁盘中都存在时，优先使用内存版本（更新）
    """
    # 1. 收集内存中活跃 Session
    memory_map: Dict[str, Dict[str, Any]] = {}  # session_uuid -> summary
    memory_session_id_map: Dict[str, str] = {}  # session_id -> session_uuid (用于快速查找)

    history_manager = get_history_manager()
    sessions = history_manager.get_all_ai_sessions()

    for sid, session in sessions.items():
        summary = _build_summary_from_memory(sid, session)
        uuid_val: Optional[str] = summary.get("session_uuid")
        if uuid_val:
            memory_map[uuid_val] = summary
            memory_session_id_map[sid] = uuid_val
        else:
            # 没有 uuid 的兜底：用 session_id 作为 key
            memory_map[sid] = summary

    # 2. 收集磁盘持久化文件
    disk_map: Dict[str, Dict[str, Any]] = {}  # session_uuid -> summary
    for path in _list_log_files():
        info = _parse_log_file(path)
        if info is None:
            continue
        uuid_val: Optional[str] = info.get("session_uuid")
        if uuid_val:
            # 同一 uuid 可能有多份文件（异常情况），取最新的
            existing = disk_map.get(uuid_val)
            if existing is None or info.get("updated_at", 0) > existing.get("updated_at", 0):
                disk_map[uuid_val] = info
        else:
            # 没有 uuid 的兜底：用 file_name 作为 key
            disk_map[path.name] = info

    # 3. 合并去重：内存优先
    unified: Dict[str, Dict[str, Any]] = {}

    # 先加入磁盘文件
    for key, info in disk_map.items():
        unified[key] = info

    # 内存版本覆盖磁盘版本（同一 session_uuid）
    for key, info in memory_map.items():
        unified[key] = info

    # 4. 按 created_at 倒序排列
    results = sorted(
        unified.values(),
        key=lambda x: x.get("created_at", 0),
        reverse=True,
    )

    return results


def _apply_filters(
    items: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    create_by: Optional[str] = None,
    persona_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """对统一列表应用筛选条件"""
    results: List[Dict[str, Any]] = []

    for item in items:
        if session_id and item.get("session_id") != session_id:
            continue
        if create_by and item.get("create_by") != create_by:
            continue
        if persona_name and item.get("persona_name") != persona_name:
            continue
        if is_active is not None and item.get("is_active") != is_active:
            continue

        if date_from or date_to:
            created_str: Optional[str] = item.get("created_at_str")
            if created_str:
                date_part: str = created_str[:10]
                if date_from and date_part < date_from:
                    continue
                if date_to and date_part > date_to:
                    continue

        results.append(item)

    return results


def _find_log_by_session_id_and_uuid(
    session_id: str,
    session_uuid: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    根据 session_id + session_uuid 查找日志详情

    当 session_uuid 提供时，精确匹配到具体实例；
    当 session_uuid 为 None 时，返回该 session_id 最新的实例（向后兼容）。

    优先从内存查找（活跃会话），其次从磁盘文件查找。
    """
    # 1. 优先从内存查找
    history_manager = get_history_manager()
    session = history_manager.get_ai_session(session_id)
    if session is not None:
        logger_obj: Optional[Any] = getattr(session, "_session_logger", None)
        if logger_obj is not None:
            mem_uuid: Optional[str] = getattr(logger_obj, "session_uuid", None)
            # 如果指定了 uuid，必须匹配；否则取内存中的
            if session_uuid is None or mem_uuid == session_uuid:
                return {
                    "session_id": session_id,
                    "session_uuid": mem_uuid,
                    "persona_name": getattr(logger_obj, "persona_name", None),
                    "create_by": getattr(logger_obj, "create_by", None),
                    "created_at": getattr(logger_obj, "created_at", 0),
                    "updated_at": getattr(logger_obj, "updated_at", 0),
                    "ended_at": getattr(logger_obj, "ended_at", None),
                    "entry_count": len(getattr(logger_obj, "entries", [])),
                    "entries": getattr(logger_obj, "entries", []),
                    "source": "memory",
                }

    # 2. 从磁盘文件查找
    best_data: Optional[Dict[str, Any]] = None
    best_updated_at: float = 0

    for path in _list_log_files():
        data = _load_log_detail(path)
        if data is None:
            continue
        if data.get("session_id") != session_id:
            continue
        # 如果指定了 uuid，必须匹配
        if session_uuid is not None and data.get("session_uuid") != session_uuid:
            continue

        updated_at: float = data.get("updated_at", 0)
        if updated_at > best_updated_at:
            best_updated_at = updated_at
            best_data = data
            best_data["source"] = "disk"  # type: ignore

    return best_data


# ─────────────────────────────────────────────
# 1. 统一日志列表 API（合并内存 + 磁盘，去重）
# ─────────────────────────────────────────────


@app.get("/api/ai/session_logs")
async def list_session_logs(
    session_id: Optional[str] = None,
    create_by: Optional[str] = None,
    persona_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    获取 AI Session 日志列表（统一合并内存活跃 + 磁盘持久化，去重）

    返回综合列表，每个条目包含 source 字段标识来源（"memory" 或 "disk"），
    is_active 字段标识是否仍在运行。同一 session_uuid 在内存和磁盘中都存在时，
    优先使用内存版本（数据更新）。结果按创建时间倒序排列。

    Args:
        session_id: 按 session_id 精确筛选
        create_by: 按创建来源筛选
        persona_name: 按 Persona 名称筛选
        is_active: 按是否活跃筛选 (true=仅活跃, false=仅已结束)
        date_from: 起始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        status: 0成功，1失败
        data: 日志列表及分页信息
    """
    try:
        unified = _build_unified_list()
        filtered = _apply_filters(
            unified,
            session_id=session_id,
            create_by=create_by,
            persona_name=persona_name,
            is_active=is_active,
            date_from=date_from,
            date_to=date_to,
        )

        total: int = len(filtered)
        paginated = filtered[offset : offset + limit]

        return {
            "status": 0,
            "msg": "ok",
            "data": {
                "items": paginated,
                "total": total,
                "limit": limit,
                "offset": offset,
            },
        }
    except Exception as e:
        logger.error(f"📝 [SessionLogsAPI] 获取日志列表失败: {e}")
        return {
            "status": 1,
            "msg": f"获取日志列表失败: {str(e)}",
            "data": None,
        }


# ─────────────────────────────────────────────
# 2. 日志详情 API（按 session_id + session_uuid 查找，优先内存）
# ─────────────────────────────────────────────


@app.get("/api/ai/session_logs/{session_id}/{session_uuid}/detail")
async def get_session_log_detail(
    session_id: str,
    session_uuid: str,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    获取指定 Session 实例的日志详情

    通过 session_id + session_uuid 精确定位到某个具体实例。
    同一 session_id 可能有多个实例（不同 session_uuid），用于区分
    同一会话的不同运行记录。

    优先从内存查找活跃会话的实时日志，若不存在则从磁盘文件查找。

    Args:
        session_id: Session ID（如 bot:onebot:group:123456）
        session_uuid: Session 实例 UUID（如 abc12345）

    Returns:
        status: 0成功，1失败
        data: 完整日志数据
    """
    try:
        data = _find_log_by_session_id_and_uuid(session_id, session_uuid)
        if data is None:
            return {
                "status": 1,
                "msg": f"未找到 Session 日志: {session_id}/{session_uuid}",
                "data": None,
            }

        return {"status": 0, "msg": "ok", "data": data}
    except Exception as e:
        logger.error(f"📝 [SessionLogsAPI] 获取日志详情失败: {e}")
        return {
            "status": 1,
            "msg": f"获取日志详情失败: {str(e)}",
            "data": None,
        }


# ─────────────────────────────────────────────
# 3. 日志文件详情 API（按文件名查找，调试用）
# ─────────────────────────────────────────────


@app.get("/api/ai/session_logs/file/{file_name}")
async def get_session_log_by_file(
    file_name: str,
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    按文件名获取单个持久化日志详情（调试用）

    直接从磁盘读取指定 JSON 文件。适用于需要查看特定历史实例的场景。

    Args:
        file_name: 日志文件名（含 .json 后缀）

    Returns:
        status: 0成功，1失败
        data: 完整日志数据
    """
    try:
        # 安全检查：防止目录遍历
        if ".." in file_name or "/" in file_name or "\\" in file_name:
            return {"status": 1, "msg": "非法文件名", "data": None}

        path = AI_SESSION_LOGS_PATH / file_name
        if not path.exists():
            return {"status": 1, "msg": f"未找到日志文件: {file_name}", "data": None}

        data = _load_log_detail(path)
        if data is None:
            return {"status": 1, "msg": f"解析日志文件失败: {file_name}", "data": None}

        return {"status": 0, "msg": "ok", "data": data}
    except Exception as e:
        logger.error(f"📝 [SessionLogsAPI] 获取日志文件失败: {e}")
        return {
            "status": 1,
            "msg": f"获取日志文件失败: {str(e)}",
            "data": None,
        }


# ─────────────────────────────────────────────
# 4. 日志统计 API
# ─────────────────────────────────────────────


@app.get("/api/ai/session_logs/stats/overview")
async def get_session_logs_overview(
    _: Dict = Depends(require_auth),
) -> Dict:
    """
    获取 Session 日志统计概览

    返回日志总数、今日新增、活跃 Session 数等统计信息。

    Returns:
        status: 0成功，1失败
        data: 统计概览
    """
    try:
        unified = _build_unified_list()

        today_str: str = datetime.now().strftime("%Y-%m-%d")
        today_count: int = 0
        active_count: int = 0
        memory_count: int = 0
        disk_count: int = 0
        create_by_counts: Dict[str, int] = {}

        for item in unified:
            created_str: Optional[str] = item.get("created_at_str")
            if created_str and created_str.startswith(today_str):
                today_count += 1

            if item.get("is_active"):
                active_count += 1

            source: Optional[str] = item.get("source")
            if source == "memory":
                memory_count += 1
            elif source == "disk":
                disk_count += 1

            cb: Optional[str] = item.get("create_by")
            if cb:
                create_by_counts[cb] = create_by_counts.get(cb, 0) + 1

        return {
            "status": 0,
            "msg": "ok",
            "data": {
                "total": len(unified),
                "today_count": today_count,
                "active_count": active_count,
                "memory_count": memory_count,
                "disk_count": disk_count,
                "create_by_distribution": create_by_counts,
                "log_path": str(AI_SESSION_LOGS_PATH),
            },
        }
    except Exception as e:
        logger.error(f"📝 [SessionLogsAPI] 获取日志统计失败: {e}")
        return {
            "status": 1,
            "msg": f"获取日志统计失败: {str(e)}",
            "data": None,
        }
