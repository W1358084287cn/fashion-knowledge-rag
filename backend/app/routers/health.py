# -*- coding: utf-8 -*-
"""
健康检查接口
------------------------------------------------------------
用于部署后快速确认 MySQL / Qdrant / Neo4j 是否连通，
以及 3 个 Agent 的密钥是否已配置。
"""
import httpx
from fastapi import APIRouter
from neo4j import GraphDatabase
from sqlalchemy import text

from ..api_utils import ok
from ..config import settings
from ..db import SessionLocal
from ..models import AgentConfig

router = APIRouter(prefix="/api", tags=["健康检查"])


def _check_mysql() -> bool:
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return True
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return False


def _check_qdrant() -> bool:
    try:
        resp = httpx.get(f"{settings.QDRANT_URL}/collections", timeout=3)
        return resp.status_code < 400
    except Exception:  # noqa: BLE001
        return False


def _check_neo4j() -> bool:
    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        try:
            driver.verify_connectivity()
            return True
        finally:
            driver.close()
    except Exception:  # noqa: BLE001
        return False


def _agent_status() -> list:
    """检查三个 Agent 的密钥配置状态（不返回密钥内容）。"""
    db = SessionLocal()
    try:
        rows = db.query(AgentConfig).order_by(AgentConfig.id.asc()).all()
        return [{
            "agent_key": r.agent_key,
            "agent_name": r.agent_name,
            "llm_ready": bool(r.llm_api_key),
            "embedding_ready": bool(r.embedding_api_key),
        } for r in rows]
    except Exception:  # noqa: BLE001
        return []
    finally:
        db.close()


@router.get("/health")
def health():
    """服务健康状态。"""
    mysql_ok = _check_mysql()
    qdrant_ok = _check_qdrant()
    neo4j_ok = _check_neo4j()
    return ok({
        "status": "ok" if (mysql_ok and qdrant_ok and neo4j_ok) else "degraded",
        "mysql": mysql_ok,
        "qdrant": qdrant_ok,
        "neo4j": neo4j_ok,
        "agents": _agent_status(),
        "admin_account": settings.ADMIN_USERNAME,
    })
