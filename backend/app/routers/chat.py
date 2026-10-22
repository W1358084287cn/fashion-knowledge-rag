# -*- coding: utf-8 -*-
"""
Agent3 在线问答接口（SSE 流式）
------------------------------------------------------------
管理端测试页与客户端共用同一个接口，身份由 Token 决定：
- 携带管理员 Token -> user_type=admin
- 携带普通用户 Token -> user_type=user（记录用户 ID / 账号）
- 未携带 Token     -> user_type=guest

流程：
  1. 命中高频问题缓存 -> 直接分片输出
  2. 并行检索 Neo4j + Qdrant
  3. 两份资料都为空 -> 原样返回“暂无相关信息”（不调用大模型，杜绝幻觉）
  4. 否则组装强约束 Prompt，LangChain 流式生成
  5. 全程自动保存对话历史与检索日志
"""
import asyncio
import json
import logging
import re
import time
import uuid
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func

from ..api_utils import fail, ok
from ..config import settings
from ..db import SessionLocal, get_agent_config, session_scope
from ..models import ChatHistory
from ..prompts import NO_INFO_ANSWER
from ..schemas import ChatRequest, HistorySaveRequest
from ..security import decode_token, token_from_request
from ..services.audit import write_retrieval
from ..services.cache import answer_cache
from ..services.llm_client import LLMError, stream_answer
from ..services.retrieval import build_cache_key, retrieve
from ..services.text_utils import extract_keywords, normalize_question

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["智能问答"])

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def _sse(event: str, data: dict) -> str:
    """组装 SSE 消息帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _resolve_identity(request: Request, token: Optional[str]) -> dict:
    """
    解析当前提问者身份。
    返回 {role, username, user_id}；管理员与普通用户都可用于区分各自的聊天记录。
    """
    payload = decode_token(token_from_request(request, token) or "")
    if not payload:
        return {"role": "guest", "username": "", "user_id": None}
    role = payload.get("role")
    if role not in ("admin", "user"):
        return {"role": "guest", "username": "", "user_id": None}
    return {
        "role": role,
        "username": payload.get("sub", "") or "",
        "user_id": payload.get("uid"),
    }


def _resolve_user_type(request: Request, token: Optional[str]) -> str:
    """兼容旧调用：返回 admin / user / guest。"""
    return _resolve_identity(request, token)["role"]


def _load_agent3():
    """读取 Agent3 最新配置（每次请求都读，实现热更新）。"""
    db = SessionLocal()
    try:
        return get_agent_config(db, "agent3")
    finally:
        db.close()


def _save_message(session_id: str, user_type: str, role: str, content: str,
                  identity: Optional[dict] = None) -> None:
    """保存单条对话消息（失败只记录日志，不影响问答主流程）。"""
    if not content:
        return
    identity = identity or {}
    try:
        with session_scope() as db:
            db.add(ChatHistory(
                session_id=session_id,
                user_type=user_type,
                role=role,
                content=content[:20000],
                user_id=identity.get("user_id") if user_type == "user" else None,
                username=(identity.get("username") or "")[:50] or None,
            ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("对话历史保存失败：%s", exc)


async def _typewriter(text: str, chunk_size: int = 4, delay: float = 0.015) -> AsyncIterator[str]:
    """把完整文本按小片段输出，模拟打字机效果（缓存命中 / 兜底回答使用）。"""
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]
        await asyncio.sleep(delay)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, request: Request, token: Optional[str] = Query(None)):
    """
    SSE 流式问答。
    事件类型：
      meta   会话信息
      status 检索阶段提示
      delta  增量文本
      done   结束（含 cached 标记）
      error  错误提示
    """
    question = normalize_question(payload.question)
    if not question:
        return fail(1001, "请输入您的问题")

    session_id = (payload.session_id or "").strip()
    if not SESSION_ID_PATTERN.match(session_id):
        session_id = uuid.uuid4().hex

    identity = _resolve_identity(request, token)
    user_type = identity["role"]

    async def event_generator() -> AsyncIterator[str]:
        # 先返回会话信息，前端可立即建立气泡
        yield _sse("meta", {"session_id": session_id, "user_type": user_type,
                            "username": identity["username"]})

        # 用户消息先落库
        await asyncio.to_thread(_save_message, session_id, user_type, "user",
                                question, identity)

        cfg = await asyncio.to_thread(_load_agent3)
        if not (cfg.llm_api_key or "").strip():
            yield _sse("error", {"message": "尚未配置 Agent3 的 LLM ApiKey，请先到管理端完成配置"})
            return

        # ---------- 高频问题缓存 ----------
        cache_started = time.time()
        cache_key = build_cache_key(question, cfg)
        cached = answer_cache.get(cache_key)
        if cached:
            # 兼容两种缓存格式：旧版只存字符串，新版存 {answer, sources}
            if isinstance(cached, dict):
                cached_text = cached.get("answer", "")
                cached_sources = cached.get("sources")
            else:
                cached_text, cached_sources = str(cached), None
            yield _sse("status", {"stage": "cache", "message": "命中高频问题缓存"})
            if cached_sources:
                yield _sse("sources", cached_sources)
            async for piece in _typewriter(cached_text):
                yield _sse("delta", {"content": piece})
            await asyncio.to_thread(_save_message, session_id, user_type, "assistant",
                                    cached_text, identity)
            # 缓存命中也记一条检索日志，保证管理端看到的提问记录完整
            await asyncio.to_thread(
                write_retrieval, session_id, question, identity,
                len((cached_sources or {}).get("documents", [])),
                len((cached_sources or {}).get("triples", [])),
                0.9, int((time.time() - cache_started) * 1000),
                {}, ["命中高频问题缓存"], cached_sources,
            )
            yield _sse("done", {"cached": True})
            return

        # ---------- 并行检索 ----------
        yield _sse("status", {"stage": "retrieving", "message": "正在检索知识库与知识图谱"})
        started = time.time()
        try:
            keywords = extract_keywords(question)
            result = await retrieve(cfg, question, keywords)
        except Exception as exc:  # noqa: BLE001
            logger.exception("检索失败")
            yield _sse("error", {"message": f"知识库检索失败：{exc}"})
            return

        # 把检索命中的出处先发给前端，回答结束后客户端可展示「参考来源」
        sources = result.sources()
        retrieval_ms = int((time.time() - started) * 1000)
        yield _sse("sources", sources)

        # 检索日志：留存命中状态、召回准确度、耗时与召回快照，管理端可查
        await asyncio.to_thread(
            write_retrieval, session_id, question, identity,
            len(result.documents), len(result.triples),
            result.top_similarity, retrieval_ms,
            result.filters, result.degraded, sources,
        )

        yield _sse("status", {
            "stage": "generating",
            "message": "正在生成回答",
            "doc_count": len(result.documents),
            "triple_count": len(result.triples),
        })

        # ---------- 无参考资料：短路返回 ----------
        if result.is_empty:
            async for piece in _typewriter(NO_INFO_ANSWER):
                yield _sse("delta", {"content": piece})
            await asyncio.to_thread(_save_message, session_id, user_type, "assistant",
                                    NO_INFO_ANSWER, identity)
            yield _sse("done", {"cached": False, "elapsed": round(time.time() - started, 2)})
            return

        # ---------- 流式生成 ----------
        answer_parts = []
        try:
            async for delta in stream_answer(
                cfg,
                doc_chunks=result.doc_context,
                kg_triples=result.kg_context,
                question=question,
            ):
                if await request.is_disconnected():
                    logger.info("客户端已断开，停止生成")
                    return
                answer_parts.append(delta)
                yield _sse("delta", {"content": delta})
        except LLMError as exc:
            yield _sse("error", {"message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式生成异常")
            yield _sse("error", {"message": f"回答生成失败：{exc}"})
            return

        answer = "".join(answer_parts).strip()
        if answer:
            # 缓存答案的同时缓存出处，命中缓存时也能展示来源
            answer_cache.set(cache_key, {"answer": answer, "sources": sources})
            await asyncio.to_thread(_save_message, session_id, user_type, "assistant",
                                    answer, identity)
        yield _sse("done", {
            "cached": False,
            "elapsed": round(time.time() - started, 2),
            "degraded": result.degraded,
        })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证逐字输出
        },
    )


@router.post("/history")
async def save_history(payload: HistorySaveRequest, request: Request):
    """
    对话历史保存接口（管理端 / 客户端共用）。
    SSE 接口已自动保存，此接口预留给前端异常重试、补存等场景。
    """
    role = payload.role if payload.role in ("user", "assistant") else "user"
    content = (payload.content or "").strip()
    if not content:
        return fail(1001, "消息内容不能为空")
    if not SESSION_ID_PATTERN.match(payload.session_id or ""):
        return fail(1001, "会话 ID 不合法")

    identity = _resolve_identity(request, payload.token)
    user_type = identity["role"]
    await asyncio.to_thread(_save_message, payload.session_id, user_type, role,
                            content, identity)
    return ok(None, msg="已保存")


@router.get("/sessions")
def list_sessions(
    request: Request,
    token: ***[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """
    当前身份的会话列表（客户端查自己的，管理端查自己的测试对话）。
    返回会话标题（首条提问）、消息数、首末时间，用于侧边栏历史对话。
    """
    identity = _resolve_identity(request, token)
    if identity["role"] == "guest":
        return ok({"items": []})

    with session_scope() as db:
        query = db.query(
            ChatHistory.session_id,
            func.min(ChatHistory.created_at).label("started"),
            func.max(ChatHistory.created_at).label("lasted"),
            func.count(ChatHistory.id).label("msg_count"),
        )
        if identity["role"] == "admin":
            query = query.filter(ChatHistory.user_type == "admin")
        else:
            if identity["user_id"]:
                query = query.filter(ChatHistory.user_id == identity["user_id"])
            else:
                query = query.filter(ChatHistory.user_type == "user").filter(
                    ChatHistory.user_id.is_(None))

        rows = (
            query.group_by(ChatHistory.session_id)
            .order_by(func.max(ChatHistory.created_at).desc())
            .limit(limit)
            .all()
        )
        items = []
        for row in rows:
            first = (
                db.query(ChatHistory.content)
                .filter(ChatHistory.session_id == row.session_id,
                        ChatHistory.role == "user")
                .order_by(ChatHistory.id.asc())
                .first()
            )
            items.append({
                "session_id": row.session_id,
                "title": (first[0] if first else "新对话")[:40],
                "message_count": int(row.msg_count),
                "started_at": row.started.strftime("%m-%d %H:%M") if row.started else "",
                "last_at": row.lasted.strftime("%m-%d %H:%M") if row.lasted else "",
            })
    return ok({"items": items, "role": identity["role"]})


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request,
                   token: ***[str] = Query(None)):
    """删除自己的某个会话（只允许删除本人 OpenID / 管理员名下的记录）。"""
    if not SESSION_ID_PATTERN.match(session_id):
        return fail(1001, "会话 ID 不合法")
    identity = _resolve_identity(request, token)
    if identity["role"] == "guest":
        return fail(1002, "请先登录")

    with session_scope() as db:
        query = db.query(ChatHistory).filter(ChatHistory.session_id == session_id)
        if identity["role"] == "admin":
            query = query.filter(ChatHistory.user_type == "admin")
        elif identity["user_id"]:
            query = query.filter(ChatHistory.user_id == identity["user_id"])
        else:
            query = query.filter(ChatHistory.user_type == "user")
        deleted = query.delete(synchronize_session=False)

    return ok({"deleted": deleted}, msg="会话已删除")


@router.get("/history")
def get_history(
    request: Request,
    session_id: str = Query(..., max_length=64),
    token: ***[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
):
    """
    按会话 ID 查询历史消息（用于刷新页面后恢复对话）。
    带上 Token 时只返回当前身份自己的消息，客户端与管理端的历史互不可见。
    """
    if not SESSION_ID_PATTERN.match(session_id):
        return fail(1001, "会话 ID 不合法")

    identity = _resolve_identity(request, token)

    with session_scope() as db:
        query = db.query(ChatHistory).filter(ChatHistory.session_id == session_id)
        if identity["role"] == "admin":
            query = query.filter(ChatHistory.user_type == "admin")
        elif identity["role"] == "user" and identity["user_id"]:
            query = query.filter(ChatHistory.user_id == identity["user_id"])
        rows = (
            query
            .order_by(ChatHistory.id.asc())
            .limit(limit)
            .all()
        )
        items = [{
            "role": r.role,
            "content": r.content,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        } for r in rows]
    return ok({"items": items})
