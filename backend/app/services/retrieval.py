# -*- coding: utf-8 -*-
"""
Agent3 在线检索层
------------------------------------------------------------
并行执行：
  - Neo4j 图谱关键词查询
  - Qdrant 稠密 + 稀疏混合检索（RRF 融合、payload 标签过滤）

为缩短首字延迟：
  1. 图谱查询与问题 Embedding 同时开始
  2. Embedding 完成后立即发起 Qdrant 检索
  3. 两路结果统一组装为短 Prompt
"""
import asyncio
import logging
from typing import Dict, List, Optional

from ..config import settings
from ..prompts import ALLOWED_CATEGORIES
from . import neo4j_store, qdrant_store
from .embedding_client import EmbeddingError, embed_query_async
from .text_utils import build_sparse_vector, detect_category, detect_goods_no

logger = logging.getLogger(__name__)


class RetrievalResult:
    """一次问答的检索结果。"""

    def __init__(self):
        self.documents: List[dict] = []
        self.triples: List[dict] = []
        self.filters: Dict[str, str] = {}
        self.degraded: List[str] = []  # 记录降级原因，便于答辩时说明

    @property
    def doc_context(self) -> str:
        """Qdrant 片段拼接（限制总长度，避免 Prompt 过长拖慢推理）。"""
        if not self.documents:
            return "（无）"
        parts = []
        total = 0
        for i, doc in enumerate(self.documents, start=1):
            payload = doc.get("payload", {})
            text = str(payload.get("text", "")).strip()
            meta = (
                f"来源:{payload.get('source_type', '') or '未知'}"
                f" | 分类:{payload.get('category', '') or '无'}"
                f" | 款号:{payload.get('goods_no', '') or '无'}"
                f" | 文件:{payload.get('file_name', '')}"
            )
            block = f"[片段{i}]（{meta}）\n{text}"
            if total + len(block) > 6000:
                break
            parts.append(block)
            total += len(block)
        return "\n\n".join(parts)

    @property
    def kg_context(self) -> str:
        """图谱三元组拼接为易读文本。"""
        if not self.triples:
            return "（无）"
        lines = []
        for t in self.triples[:30]:
            lines.append(f"{t['head']} --{t['relation']}--> {t['tail']}")
        return "\n".join(lines)

    @property
    def is_empty(self) -> bool:
        """两份资料都为空时，服务端直接返回“暂无相关信息”。"""
        return not self.documents and not self.triples

    @property
    def top_similarity(self) -> float:
        """最高稠密相似度（0~1），用于召回准确度评估与日志展示。"""
        scores = [float(d.get("dense_score", 0) or 0) for d in self.documents]
        return round(max(scores), 4) if scores else 0.0

    def sources(self) -> Dict[str, list]:
        """
        返回给前端的「回答出处」：
        - documents：命中的知识库片段（文件名 / 分类 / 款号 / 摘要 / 相似度）
        - triples：命中的知识图谱三元组（主实体 / 关系 / 尾实体）
        前端据此展示“参考来源”，让用户能核对答案依据，避免无出处回答。
        """
        docs = []
        for i, doc in enumerate(self.documents[: settings.TOP_K_FINAL], start=1):
            payload = doc.get("payload", {}) or {}
            docs.append({
                "index": i,
                "file_name": str(payload.get("file_name", "") or "未知文件"),
                "source_type": str(payload.get("source_type", "") or "文档"),
                "category": str(payload.get("category", "") or ""),
                "goods_no": str(payload.get("goods_no", "") or ""),
                "snippet": str(payload.get("text", "") or "").strip()[:180],
                "score": round(float(doc.get("score", 0) or 0), 4),
                "similarity": round(float(doc.get("dense_score", 0) or 0), 4),
            })
        triples = [{
            "head": t.get("head", ""),
            "relation": t.get("relation", ""),
            "tail": t.get("tail", ""),
        } for t in self.triples[:30]]
        return {"documents": docs, "triples": triples}


def detect_filters(question: str) -> Dict[str, str]:
    """
    从问题中识别 Qdrant payload 过滤条件：
    - 内容分类：命中面料/尺码/售后/保养/活动关键词
    - 商品款号：出现款号时精确过滤
    """
    filters: Dict[str, str] = {}
    category = detect_category(question)
    if category in ALLOWED_CATEGORIES:
        filters["category"] = category
    goods_no = detect_goods_no(question)
    if goods_no:
        filters["goods_no"] = goods_no
    return filters


async def _search_qdrant_safe(cfg, question: str, filters: Dict[str, str]) -> List[dict]:
    """
    Qdrant 检索（带标签过滤与自动回退）：
    标签过滤能缩小范围，但可能过窄；若过滤后结果不足 3 条，
    自动去掉过滤条件再检索一次，保证召回率。
    """
    try:
        dense_vector = await embed_query_async(cfg, question)
        indices, values = build_sparse_vector(question)
        docs = await qdrant_store.hybrid_search(
            dense_vector=dense_vector,
            sparse_indices=indices,
            sparse_values=values,
            filters=filters,
        )
        if filters and len(docs) < 3:
            # 过滤过窄时自动回退：只保留 file_id 这类强约束，去掉分类/款号条件
            fallback_filters = {k: v for k, v in filters.items() if k == "file_id"} or None
            fallback = await qdrant_store.hybrid_search(
                dense_vector=dense_vector,
                sparse_indices=indices,
                sparse_values=values,
                filters=fallback_filters,
            )
            merged = {d["id"]: d for d in docs}
            for d in fallback:
                merged.setdefault(d["id"], d)
            docs = list(merged.values())[: settings.TOP_K_FINAL]
        return docs
    except (EmbeddingError, qdrant_store.VectorStoreError) as exc:
        logger.warning("Qdrant 检索降级：%s", exc)
        return []


async def retrieve(cfg, question: str, keywords: List[str],
                   extra_filters: Optional[Dict] = None) -> RetrievalResult:
    """
    并行检索。
    - 图谱查询不依赖 Embedding，先启动
    - Qdrant 需要先算问题向量，与图谱查询重叠执行

    extra_filters：额外过滤条件（召回测试时按 file_id 限定只测当前文件）。
    """
    result = RetrievalResult()
    result.filters = detect_filters(question)
    if extra_filters:
        result.filters.update({k: v for k, v in extra_filters.items() if v is not None})

    # 先创建图谱查询任务（不阻塞）
    graph_task = asyncio.create_task(neo4j_store.search_triples(keywords))

    # 向量检索（内部先 Embedding 再 Qdrant）
    try:
        result.documents = await _search_qdrant_safe(cfg, question, result.filters)
    except Exception as exc:  # noqa: BLE001
        logger.warning("向量检索异常：%s", exc)
        result.degraded.append("向量检索不可用")

    # 等待图谱查询完成
    try:
        result.triples = await graph_task
    except Exception as exc:  # noqa: BLE001
        logger.warning("图谱检索降级：%s", exc)
        result.degraded.append("知识图谱不可用")
    return result


def build_cache_key(question: str, cfg) -> str:
    """
    缓存 key = 问题 + Agent3 配置更新时间。
    配置一经修改，旧答案立即失效，避免“改了密钥还返回旧结果”。
    """
    updated = getattr(cfg, "updated_at", None)
    version = updated.isoformat() if updated else "default"
    return f"{question.strip().lower()}||{version}"
