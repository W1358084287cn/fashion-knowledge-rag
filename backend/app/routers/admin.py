# -*- coding: utf-8 -*-
"""
管理端运营接口：用户、对话、检索日志、操作日志
------------------------------------------------------------
- 用户列表：客户端登录用户 + 提问次数 / 会话数 / 最近活跃时间
- 单个用户：会话列表、消息记录、每次提问的检索命中与召回准确度
- 检索日志：可按用户、命中状态、关键词筛选
- 操作日志：管理员与用户的关键操作全量留存
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_

from ..api_utils import fail, ok
from ..db import session_scope
from ..models import (
    ChatHistory, OperationLog, RetrievalLog, UserAccount,
)
from ..security import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["管理端运营"])

LEVEL_LABELS = {"high": "高", "medium": "中", "low": "低", "miss": "未命中"}


def _fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


@router.get("/overview")
def overview(_: dict = Depends(get_current_admin)):
    """管理端首页数据概览：用户数、提问数、命中率、今日数据。"""
    with session_scope() as db:
        user_total = db.query(UserAccount).count()
        question_total = db.query(RetrievalLog).count()
        hit_total = db.query(RetrievalLog).filter(RetrievalLog.hit.is_(True)).count()
        chat_total = db.query(ChatHistory).count()
        op_total = db.query(OperationLog).count()
        today = func.date(RetrievalLog.created_at) == func.curdate()
        question_today = db.query(RetrievalLog).filter(today).count()

    return ok({
        "user_total": user_total,
        "question_total": question_total,
        "hit_total": hit_total,
        "hit_rate": round(hit_total / question_total * 100, 1) if question_total else 0.0,
        "chat_total": chat_total,
        "operation_total": op_total,
        "question_today": question_today,
    })


@router.get("/users")
def list_users(_: dict = Depends(get_current_admin)):
    """客户端用户列表：带上提问次数、会话数、最近活跃时间与平均召回准确度。"""
    with session_scope() as db:
        users = db.query(UserAccount).order_by(UserAccount.id.asc()).all()
        stats = dict(
            (int(uid), (int(cnt), float(avg) if avg else 0.0))
            for uid, cnt, avg in (
                db.query(
                    RetrievalLog.user_id,
                    func.count(RetrievalLog.id),
                    func.avg(RetrievalLog.accuracy),
                )
                .filter(RetrievalLog.user_id.isnot(None))
                .group_by(RetrievalLog.user_id)
                .all()
            )
        )
        sessions = dict(
            (int(uid), int(cnt))
            for uid, cnt in (
                db.query(ChatHistory.user_id, func.count(func.distinct(ChatHistory.session_id)))
                .filter(ChatHistory.user_id.isnot(None))
                .group_by(ChatHistory.user_id)
                .all()
            )
        )
        last_active = dict(
            (int(uid), ts)
            for uid, ts in (
                db.query(ChatHistory.user_id, func.max(ChatHistory.created_at))
                .filter(ChatHistory.user_id.isnot(None))
                .group_by(ChatHistory.user_id)
                .all()
            )
        )
        items = []
        for user in users:
            count, avg = stats.get(int(user.id), (0, 0.0))
            items.append({
                "id": int(user.id),
                "username": user.username,
                "display_name": user.display_name or user.username,
                "created_at": _fmt(user.created_at),
                "last_login_at": _fmt(user.last_login_at),
                "question_count": count,
                "session_count": sessions.get(int(user.id), 0),
                "avg_accuracy": round(avg, 1),
                "last_active_at": _fmt(last_active.get(int(user.id))),
            })
    return ok({"items": items, "total": len(items)})


@router.get("/users/{user_id}/sessions")
def user_sessions(user_id: int, _: dict = Depends(get_current_admin)):
    """某个用户的所有会话（用于点击用户后查看提问记录）。"""
    with session_scope() as db:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        if not user:
            return fail(2001, "用户不存在")
        rows = (
            db.query(
                ChatHistory.session_id,
                func.min(ChatHistory.created_at).label("started"),
                func.max(ChatHistory.created_at).label("lasted"),
                func.count(ChatHistory.id).label("msg_count"),
            )
            .filter(ChatHistory.user_id == user_id, ChatHistory.user_type == "user")
            .group_by(ChatHistory.session_id)
            .order_by(func.max(ChatHistory.created_at).desc())
            .limit(100)
            .all()
        )
        # 每个会话的首个用户问题作为标题
        session_items = []
        for row in rows:
            first = (
                db.query(ChatHistory.content)
                .filter(ChatHistory.session_id == row.session_id,
                        ChatHistory.role == "user")
                .order_by(ChatHistory.id.asc())
                .first()
            )
            title = (first[0] if first else "（无提问）")[:60]
            session_items.append({
                "session_id": row.session_id,
                "title": title,
                "message_count": int(row.msg_count),
                "started_at": _fmt(row.started),
                "last_at": _fmt(row.lasted),
            })
        info = {
            "id": int(user.id),
            "username": user.username,
            "display_name": user.display_name or user.username,
            "last_login_at": _fmt(user.last_login_at),
        }
    return ok({"user": info, "items": session_items})


@router.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, _: dict = Depends(get_current_admin)):
    """会话完整消息 + 每次提问的检索命中与召回准确度。"""
    with session_scope() as db:
        rows = (
            db.query(ChatHistory)
            .filter(ChatHistory.session_id == session_id)
            .order_by(ChatHistory.id.asc())
            .limit(300)
            .all()
        )
        logs = (
            db.query(RetrievalLog)
            .filter(RetrievalLog.session_id == session_id)
            .order_by(RetrievalLog.id.asc())
            .all()
        )
        items = [{
            "role": r.role,
            "content": r.content,
            "created_at": _fmt(r.created_at),
        } for r in rows]
        retrievals = [{
            "id": int(log.id),
            "question": log.question,
            "hit": bool(log.hit),
            "accuracy": int(log.accuracy or 0),
            "accuracy_level": log.accuracy_level,
            "accuracy_label": LEVEL_LABELS.get(log.accuracy_level or "", "未命中"),
            "doc_count": int(log.doc_count or 0),
            "triple_count": int(log.triple_count or 0),
            "top_score": round(float(log.top_score or 0), 4),
            "latency_ms": int(log.latency_ms or 0),
            "created_at": _fmt(log.created_at),
        } for log in logs]
    return ok({"items": items, "retrievals": retrievals})


@router.get("/retrieval-logs")
def retrieval_logs(
    user_id: Optional[int] = Query(None),
    level: str = Query("", max_length=10),
    keyword: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    """检索日志（按用户 / 命中等级 / 提问关键词筛选）。"""
    with session_scope() as db:
        query = db.query(RetrievalLog)
        if user_id:
            query = query.filter(RetrievalLog.user_id == user_id)
        if level:
            query = query.filter(RetrievalLog.accuracy_level == level)
        if keyword.strip():
            query = query.filter(RetrievalLog.question.like(f"%{keyword.strip()}%"))

        total = query.count()
        rows = (
            query.order_by(RetrievalLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [{
            "id": int(log.id),
            "session_id": log.session_id,
            "username": log.username or "（未登录）",
            "user_type": log.user_type,
            "question": log.question,
            "hit": bool(log.hit),
            "accuracy": int(log.accuracy or 0),
            "accuracy_level": log.accuracy_level,
            "accuracy_label": LEVEL_LABELS.get(log.accuracy_level or "", "未命中"),
            "doc_count": int(log.doc_count or 0),
            "triple_count": int(log.triple_count or 0),
            "top_score": round(float(log.top_score or 0), 4),
            "latency_ms": int(log.latency_ms or 0),
            "created_at": _fmt(log.created_at),
        } for log in rows]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/operation-logs")
def operation_logs(
    actor_type: str = Query("", max_length=10),
    keyword: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    """操作日志（管理员 / 用户 的关键操作全量留存）。"""
    with session_scope() as db:
        query = db.query(OperationLog)
        if actor_type:
            query = query.filter(OperationLog.actor_type == actor_type)
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            query = query.filter(or_(
                OperationLog.action.like(like),
                OperationLog.target.like(like),
                OperationLog.actor.like(like),
            ))

        total = query.count()
        rows = (
            query.order_by(OperationLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [{
            "id": int(log.id),
            "actor_type": log.actor_type,
            "actor": log.actor,
            "action": log.action,
            "target": log.target,
            "detail": log.detail or "",
            "ip": log.ip,
            "created_at": _fmt(log.created_at),
        } for log in rows]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})
