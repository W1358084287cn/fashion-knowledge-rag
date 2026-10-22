# -*- coding: utf-8 -*-
"""
操作日志 / 检索日志落库
------------------------------------------------------------
- 日志写入失败只打印，不影响主业务流程
- 管理端「用户与日志」页面直接读取这两张表
"""
import json
import logging
from typing import Optional

from ..db import session_scope
from ..models import OperationLog, RetrievalLog

logger = logging.getLogger(__name__)


def write_operation(actor_type: str, actor: str, action: str,
                    target: str = "", detail: str = "", ip: str = "") -> None:
    """写入一条操作日志（登录、上传、删除、重处理、配置修改等）。"""
    try:
        with session_scope() as db:
            db.add(OperationLog(
                actor_type=actor_type,
                actor=(actor or "")[:50],
                action=action[:50],
                target=(target or "")[:200],
                detail=(detail or "")[:2000],
                ip=(ip or "")[:64],
            ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("操作日志写入失败：%s", exc)


def write_retrieval(
    session_id: str,
    question: str,
    identity: Optional[dict],
    doc_count: int,
    triple_count: int,
    top_score: float,
    latency_ms: int,
    filters: Optional[dict] = None,
    degraded: Optional[list] = None,
    sources: Optional[dict] = None,
) -> None:
    """写入一条检索日志，并计算召回准确度等级。"""
    hit = bool(doc_count or triple_count)
    accuracy, level = grade_accuracy(doc_count, triple_count, top_score)
    try:
        with session_scope() as db:
            db.add(RetrievalLog(
                session_id=(session_id or "")[:64],
                user_id=(identity or {}).get("user_id"),
                username=str((identity or {}).get("username", ""))[:50],
                user_type=str((identity or {}).get("role", "guest"))[:10],
                question=question[:500],
                doc_count=int(doc_count),
                triple_count=int(triple_count),
                top_score=round(float(top_score or 0), 4),
                hit=hit,
                accuracy=accuracy,
                accuracy_level=level,
                latency_ms=int(latency_ms),
                filters=json.dumps(filters or {}, ensure_ascii=False)[:200],
                degraded="；".join(degraded or [])[:200],
                sources=json.dumps(sources or {}, ensure_ascii=False)[:6000],
            ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("检索日志写入失败：%s", exc)


def grade_accuracy(doc_count: int, triple_count: int, top_score: float) -> tuple:
    """
    召回准确度评估（启发式，可解释）：
    - 无任何命中                 -> miss  0 分
    - 相似度 >= 0.62 且有文档命中 -> high  95 分
    - 相似度 >= 0.52              -> medium 80 分
    - 其余有命中                  -> low  60 分
    有图谱三元组但无文档时，按 low 处理（图谱作为补充依据）。
    """
    if not doc_count and not triple_count:
        return 0, "miss"
    score = float(top_score or 0)
    if doc_count and score >= 0.62:
        return 95, "high"
    if doc_count and score >= 0.52:
        return 80, "medium"
    return 60, "low"
