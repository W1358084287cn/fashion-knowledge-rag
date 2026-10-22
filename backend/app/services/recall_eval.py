# -*- coding: utf-8 -*-
"""
自动召回测试与自愈评估
------------------------------------------------------------
用途：
1. 文件入库后自动抽样生成测试问题，检索向量库，校验“能否召回原文片段”
2. 召回不达标时由流水线自动切换切片策略重试（自愈循环）
3. 管理端「召回测试」按钮也复用本模块，对已入库文件做一次体检

判定方式（可解释、无需人工标注）：
- 从切片中自动生成问题
- 用该问题检索（限定在当前文件内）
- 若 Top5 片段与源片段的最大二元组重合度 >= 0.35，视为命中
- 命中率 >= 60% 视为通过
"""
import asyncio
import json
import logging
from typing import Dict, List, Optional, Tuple

from ..db import SessionLocal, get_agent_config, session_scope
from ..models import KbFile, RecallTest
from .llm_client import LLMError, chat_text_sync
from .retrieval import retrieve
from .text_utils import extract_keywords

logger = logging.getLogger(__name__)

# 测试问题生成提示词：只输出一句自然的中文问题
QUESTION_PROMPT = """你是服装客服质检助手。请根据下面这段知识库文本，生成一个用户可能会问的中文问题。
要求：
1. 问题必须能且只能由这段文本回答；
2. 只输出问题本身，不要序号、引号、解释；
3. 不超过 30 个字。
文本：
{chunk}"""

# 召回通过阈值
HIT_SIMILARITY = 0.35      # 片段二元组重合度达到该值视为命中
PASS_RATIO = 0.6           # 命中率 >= 60% 视为召回通过
MAX_QUESTIONS = 3          # 每个文件最多生成 3 个测试问题


def _bigrams(text: str) -> set:
    """字符二元组集合，用于快速计算片段重合度。"""
    text = (text or "").strip()
    if len(text) < 2:
        return set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _similarity(source: str, target: str) -> float:
    """以源片段为基准的重合度：命中片段覆盖了多少源片段内容。"""
    a, b = _bigrams(source), _bigrams(target)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a))


def _pick_samples(chunks: List[str], limit: int) -> List[int]:
    """均匀抽取样本下标：首、中、尾，保证覆盖面。"""
    total = len(chunks)
    if total <= limit:
        return list(range(total))
    step = total / limit
    return sorted({int(i * step) for i in range(limit)} - {total})


def _fallback_question(chunk: str) -> str:
    """LLM 不可用时的兜底问题：用关键词拼一句自然查询。"""
    keywords = [k for k in extract_keywords(chunk, limit=6) if len(k) >= 2]
    if not keywords:
        return chunk[:20]
    return "关于" + "、".join(keywords[:3]) + "的信息是什么？"


def generate_questions(cfg, chunks: List[str], limit: int = MAX_QUESTIONS) -> List[Tuple[int, str]]:
    """从切片中生成测试问题，返回 [(切片下标, 问题)]。"""
    samples = []
    for idx in _pick_samples(chunks, limit):
        chunk = chunks[idx]
        if len(chunk.strip()) < 20:
            continue
        question = ""
        if (getattr(cfg, "llm_api_key", "") or "").strip():
            try:
                raw = chat_text_sync(
                    cfg,
                    QUESTION_PROMPT.replace("{chunk}", chunk[:800]),
                    temperature=0.2,
                    max_tokens=80,
                )
                question = (raw or "").strip().splitlines()[0].strip().strip('"“”')
                # 过滤模型跑偏的长输出
                if len(question) > 60 or "生成" in question or "问题" == question:
                    question = ""
            except LLMError:
                question = ""
        if not question:
            question = _fallback_question(chunk)
        samples.append((idx, question))
    return samples


async def _evaluate_async(cfg, file_id: int, chunks: List[str],
                          samples: List[Tuple[int, str]]) -> List[dict]:
    """逐条执行检索并计算命中情况。"""
    results: List[dict] = []
    for idx, question in samples:
        expected = chunks[idx]
        try:
            result = await retrieve(
                cfg, question, extract_keywords(question),
                extra_filters={"file_id": int(file_id)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("召回测试检索失败：%s", exc)
            results.append({
                "chunk_index": idx,
                "question": question,
                "hit": False,
                "similarity": 0.0,
                "doc_count": 0,
                "matched_index": None,
                "error": str(exc)[:200],
            })
            continue

        best_sim = 0.0
        matched_index = None
        for doc in result.documents[:5]:
            payload = doc.get("payload", {}) or {}
            sim = _similarity(expected, str(payload.get("text", "") or ""))
            if sim > best_sim:
                best_sim = sim
                matched_index = payload.get("chunk_index")
        results.append({
            "chunk_index": idx,
            "question": question,
            "hit": best_sim >= HIT_SIMILARITY,
            "similarity": round(best_sim, 4),
            "doc_count": len(result.documents),
            "matched_index": matched_index,
            "top_similarity": result.top_similarity,
        })
    return results


def summarize(results: List[dict], strategy: str, iteration: int) -> dict:
    """汇总命中率、准确度评分与结论。"""
    total = len(results) or 1
    hits = sum(1 for r in results if r.get("hit"))
    ratio = hits / total
    accuracy = int(round(ratio * 100))
    passed = ratio >= PASS_RATIO and hits > 0
    return {
        "strategy": strategy,
        "iteration": iteration,
        "total": len(results),
        "hits": hits,
        "accuracy": accuracy,
        "passed": passed,
        "results": results,
    }


def run_recall_test(file_id: int, cfg, chunks: List[str],
                    strategy: str, iteration: int = 1,
                    persist: bool = True) -> dict:
    """
    对一个文件的切片执行召回测试（同步入口，供后台线程调用）。
    结果写入 recall_tests 表，并更新 kb_files.recall_* 字段。
    """
    if not chunks:
        summary = summarize([], strategy, iteration)
        summary["error"] = "切片为空，无法测试"
        return summary

    samples = generate_questions(cfg, chunks)
    results = asyncio.run(_evaluate_async(cfg, file_id, chunks, samples))
    summary = summarize(results, strategy, iteration)

    if persist:
        try:
            with session_scope() as db:
                for item in summary["results"]:
                    db.add(RecallTest(
                        file_id=int(file_id),
                        strategy=strategy,
                        iteration=int(iteration),
                        question=str(item.get("question", ""))[:500],
                        hit=bool(item.get("hit")),
                        score=float(item.get("similarity", 0) or 0),
                        doc_count=int(item.get("doc_count", 0) or 0),
                        detail=json.dumps(item, ensure_ascii=False),
                    ))
                row = db.query(KbFile).filter(KbFile.id == int(file_id)).first()
                if row:
                    row.recall_status = "passed" if summary["passed"] else "failed"
                    row.recall_score = summary["accuracy"]
                    row.recall_detail = json.dumps(summary, ensure_ascii=False)[:6000]
        except Exception as exc:  # noqa: BLE001
            logger.warning("召回测试结果落库失败：%s", exc)
    return summary


def run_recall_for_existing_file(file_id: int) -> dict:
    """
    对已入库文件做召回体检：直接从 Qdrant 读取切片，不重新解析文件。
    管理端「召回测试」按钮使用。
    """
    from . import qdrant_store

    db = SessionLocal()
    try:
        row = db.query(KbFile).filter(KbFile.id == int(file_id)).first()
        if not row:
            return {"passed": False, "error": "文件不存在"}
        strategy = row.chunk_strategy or "semantic"
        cfg = get_agent_config(db, "agent3")
    finally:
        db.close()

    try:
        chunks = qdrant_store.fetch_texts_by_file_id(file_id)
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "error": f"读取切片失败：{exc}"}
    if not chunks:
        return {"passed": False, "error": "该文件还没有入库切片"}

    # 标记为测试中，便于前端轮询看到状态
    try:
        with session_scope() as db:
            row = db.query(KbFile).filter(KbFile.id == int(file_id)).first()
            if row:
                row.recall_status = "running"
    except Exception:  # noqa: BLE001
        pass

    summary = run_recall_test(file_id, cfg, chunks, strategy, iteration=1, persist=True)
    summary["chunk_total"] = len(chunks)
    return summary
