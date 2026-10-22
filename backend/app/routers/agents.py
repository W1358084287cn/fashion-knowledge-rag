# -*- coding: utf-8 -*-
"""
Agent 模型配置接口（仅管理员）
------------------------------------------------------------
- 列表返回 3 个 Agent 的功能说明与配置
- 密钥字段只返回“是否已配置”，绝不回显明文
- 保存后立即生效（下次问答读取最新配置），无需重启服务
"""
from datetime import datetime

from fastapi import APIRouter, Depends

from ..api_utils import fail, ok
from ..db import DEFAULT_AGENTS, session_scope
from ..models import AgentConfig
from ..schemas import AgentConfigUpdate
from ..security import get_current_admin
from ..services.cache import answer_cache

router = APIRouter(prefix="/api/agents", tags=["Agent 配置"])

AGENT_ORDER = ["agent1", "agent2", "agent3"]


def _serialize(cfg: AgentConfig) -> dict:
    """输出给前端的安全结构：不包含密钥明文。"""
    return {
        "agent_key": cfg.agent_key,
        "agent_name": cfg.agent_name,
        "description": cfg.description,
        "llm_url": cfg.llm_url or "",
        "llm_model": cfg.llm_model or "",
        "llm_api_key_set": bool(cfg.llm_api_key),
        "embedding_url": cfg.embedding_url or "",
        "embedding_model": cfg.embedding_model or "",
        "embedding_api_key_set": bool(cfg.embedding_api_key),
        "updated_at": cfg.updated_at.strftime("%Y-%m-%d %H:%M:%S") if cfg.updated_at else "",
    }


def _default_of(agent_key: str) -> dict:
    """取默认配置，用于重置。"""
    return next((x for x in DEFAULT_AGENTS if x["agent_key"] == agent_key), DEFAULT_AGENTS[0])


@router.get("")
def list_agents(_: dict = Depends(get_current_admin)):
    """查询 3 个 Agent 的配置与功能说明。"""
    with session_scope() as db:
        rows = db.query(AgentConfig).all()
        by_key = {r.agent_key: r for r in rows}
        data = []
        for key in AGENT_ORDER:
            if key in by_key:
                data.append(_serialize(by_key[key]))
            else:
                # 极端情况下表被清空，直接返回默认配置，保证页面可用
                cfg = AgentConfig(**_default_of(key))
                data.append(_serialize(cfg))
    return ok(data)


@router.put("/{agent_key}")
def update_agent(
    agent_key: str,
    payload: AgentConfigUpdate,
    _: dict = Depends(get_current_admin),
):
    """
    更新指定 Agent 配置。
    规则：
    - URL / 模型名：传了非 None 值就更新
    - ApiKey：只有传了非空字符串才更新，空字符串表示“保持原密钥不变”
    """
    if agent_key not in AGENT_ORDER:
        return fail(1001, "Agent 标识不合法")

    with session_scope() as db:
        cfg = db.query(AgentConfig).filter(AgentConfig.agent_key == agent_key).first()
        if not cfg:
            return fail(2001, "Agent 配置不存在，请重新初始化数据库")

        if payload.llm_url is not None:
            cfg.llm_url = payload.llm_url.strip()
        if payload.llm_model is not None and payload.llm_model.strip():
            cfg.llm_model = payload.llm_model.strip()
        if payload.llm_api_key:  # 空字符串不覆盖
            cfg.llm_api_key = ***()

        if payload.embedding_url is not None:
            cfg.embedding_url = payload.embedding_url.strip()
        if payload.embedding_model is not None and payload.embedding_model.strip():
            cfg.embedding_model = payload.embedding_model.strip()
        if payload.embedding_api_key:
            cfg.embedding_api_key = ***()

        cfg.updated_at = datetime.now()
        result = _serialize(cfg)

    # 配置变更后清空问答缓存，避免返回旧答案
    answer_cache.clear()
    return ok(result, msg="配置已保存，立即生效")


@router.post("/{agent_key}/reset")
def reset_agent(agent_key: str, _: dict = Depends(get_current_admin)):
    """重置为默认配置（会清空该 Agent 的密钥，需重新填写）。"""
    if agent_key not in AGENT_ORDER:
        return fail(1001, "Agent 标识不合法")

    default = _default_of(agent_key)
    with session_scope() as db:
        cfg = db.query(AgentConfig).filter(AgentConfig.agent_key == agent_key).first()
        if not cfg:
            return fail(2001, "Agent 配置不存在")
        cfg.llm_url = default["llm_url"]
        cfg.llm_model = default["llm_model"]
        cfg.llm_api_key = ""
        cfg.embedding_url = default["embedding_url"]
        cfg.embedding_model = default["embedding_model"]
        cfg.embedding_api_key = ""
        cfg.updated_at = datetime.now()
        result = _serialize(cfg)

    answer_cache.clear()
    return ok(result, msg="已重置为默认配置")
