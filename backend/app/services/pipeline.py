# -*- coding: utf-8 -*-
"""
Agent1 文档预处理 + Agent2 知识抽取（离线流水线）
------------------------------------------------------------
触发时机：管理端上传文件 / 导入 MySQL 商品数据后，后台线程异步执行，不阻塞问答。

流程：
  原始文件 -> 解析 -> 自动清洗脏数据 -> 按所选策略切片
           -> 逐片调用 LLM 打元标签（Agent1）
           -> Embedding 向量化 -> 写入 Qdrant（稠密 + 稀疏）
           -> 自动召回测试：不达标则自动切换切片策略重建索引，最多 3 轮（自愈）
           -> 逐片调用 LLM 抽取三元组（Agent2）-> 写入 Neo4j
"""
import json
import uuid
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from ..db import SessionLocal, get_agent_config
from ..models import KbFile
from ..prompts import (
    AGENT1_TAG_PROMPT, AGENT2_EXTRACT_PROMPT, ALLOWED_CATEGORIES,
)
from . import neo4j_store, qdrant_store
from .chunking import STRATEGIES, STRATEGY_LABELS, normalize_strategy, split_text
from .embedding_client import EmbeddingError, embed_texts_sync
from .llm_client import LLMError, chat_text_sync, parse_json_array, parse_json_object
from .parsers import ParseError, parse_file
from .recall_eval import run_recall_test
from .text_utils import (
    build_sparse_vector, clean_text_with_stats, detect_category, detect_goods_no,
)

# 允许的来源类型（与标签提示词保持一致）
ALLOWED_SOURCE_TYPES = ["文档", "聊天记录", "表格数据"]

# 召回测试最多尝试的轮数（每轮换一种切片策略）
MAX_RECALL_ATTEMPTS = 3


def _update_file(file_id: int, **fields) -> None:
    """独立短事务更新文件状态，长时间任务不会一直占用数据库连接。"""
    db: Session = SessionLocal()
    try:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if row:
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
            db.commit()
    finally:
        db.close()


def _fail(file_id: int, message: str) -> None:
    """统一失败处理：写入错误原因，管理端可直接看到。"""
    _update_file(file_id, status="failed", error_msg=message[:1000])
    print(f"[离线处理] 文件 {file_id} 失败：{message}")


def _load_agent_config(agent_key: str):
    """读取 Agent 配置并立即关闭会话，避免后台长任务占用数据库连接。"""
    db = SessionLocal()
    try:
        return get_agent_config(db, agent_key)
    finally:
        db.close()


def _tag_chunk(cfg, chunk: str, source_hint: str) -> dict:
    """
    调用 Agent1 打标签，并对模型输出做二次校验：
    - 来源类型 / 内容分类必须落在白名单内
    - 款号优先采用模型结果，缺失时用正则兜底
    模型返回异常时走本地关键词兜底，保证离线任务不因单条文本中断。
    返回值中 _llm_ok 标记本次大模型是否成功，供上层统计失败次数。
    """
    prompt = AGENT1_TAG_PROMPT.replace("{chunk_text}", chunk)
    llm_ok = True
    try:
        raw = chat_text_sync(cfg, prompt, temperature=0.0, max_tokens=200)
        data = parse_json_object(raw) or {}
    except LLMError:
        # 由上层统计连续失败次数，这里先用兜底标签
        data = {}
        llm_ok = False

    source_type = str(data.get("source_type", "")).strip()
    if source_type not in ALLOWED_SOURCE_TYPES:
        source_type = source_hint if source_hint in ALLOWED_SOURCE_TYPES else "文档"

    goods_no = str(data.get("goods_no", "")).strip().upper()[:50]
    if not goods_no:
        goods_no = detect_goods_no(chunk)

    category = str(data.get("category", "")).strip()
    if category not in ALLOWED_CATEGORIES:
        category = detect_category(chunk)

    return {
        "source_type": source_type,
        "goods_no": goods_no,
        "category": category,
        "_llm_ok": llm_ok,
    }


def _extract_triples(cfg, text: str) -> List[dict]:
    """调用 Agent2 抽取三元组；解析失败返回空列表（符合“无可抽取内容返回 []”）。"""
    prompt = AGENT2_EXTRACT_PROMPT.replace("{clean_text}", text)
    raw = chat_text_sync(cfg, prompt, temperature=0.0, max_tokens=1000)
    data = parse_json_array(raw)
    triples = []
    for item in data:
        if not isinstance(item, dict):
            continue
        head = str(item.get("head", "")).strip()
        relation = str(item.get("relation", "")).strip()
        tail = str(item.get("tail", "")).strip()
        if head and relation and tail:
            triples.append({"head": head, "relation": relation, "tail": tail})
    return triples


def _build_index(file_id: int, cfg1, chunks: List[str], source_type: str,
                 file_name: str, progress_from: int = 25, progress_span: int = 45) -> List[dict]:
    """
    对切片打标签 + 向量化 + 写入 Qdrant。
    返回写入的点列表（含 text / index / 标签），供后续图谱抽取复用。
    """
    _update_file(file_id, status="tagging", progress=progress_from)
    tagged_chunks = []
    llm_fail_count = 0
    for idx, chunk in enumerate(chunks):
        tag = _tag_chunk(cfg1, chunk, source_type)
        if not tag.get("_llm_ok", True):
            llm_fail_count += 1
        tagged_chunks.append({"text": chunk, "index": idx, **tag})
        if idx % 5 == 0:
            _update_file(
                file_id,
                progress=progress_from + int(progress_span * 0.55 * (idx + 1) / len(chunks)),
            )

    # 所有文本都拿不到 LLM 标签，说明密钥/网络有问题，直接失败并给出明确提示
    if llm_fail_count == len(chunks):
        raise LLMError("Agent1 打标签失败：请检查管理端 LLM URL 与 ApiKey 配置")

    _update_file(file_id, status="embedding",
                 progress=progress_from + int(progress_span * 0.6))

    points = []
    batch_size = 10
    for start in range(0, len(tagged_chunks), batch_size):
        batch = tagged_chunks[start:start + batch_size]
        vectors = embed_texts_sync(cfg1, [b["text"] for b in batch])
        for item, vector in zip(batch, vectors):
            sparse_indices, sparse_values = build_sparse_vector(item["text"])
            points.append({
                "id": str(uuid.uuid4()),
                "dense": vector,
                "sparse_indices": sparse_indices,
                "sparse_values": sparse_values,
                "payload": {
                    "text": item["text"],
                    "file_id": file_id,
                    "file_name": file_name,
                    "source_type": item["source_type"],
                    "goods_no": item["goods_no"],
                    "category": item["category"],
                    "chunk_index": item["index"],
                },
            })
        _update_file(
            file_id,
            progress=progress_from + int(progress_span * 0.6)
            + int(progress_span * 0.4 * (start + len(batch)) / len(tagged_chunks)),
        )

    qdrant_store.upsert_chunks(points)
    return tagged_chunks


def process_file(file_id: int) -> None:
    """离线处理主流程（在后台线程中执行）。"""
    db = SessionLocal()
    try:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if not row:
            return
        file_path = row.file_path
        file_name = row.file_name
        ext = row.file_type
        forced_source = row.source_type
        strategy = normalize_strategy(row.chunk_strategy or "semantic")
        # 重新处理前先清理旧的向量与图谱数据，避免重复
        if row.chunk_count and row.chunk_count > 0:
            try:
                qdrant_store.delete_by_file_id(file_id)
                neo4j_store.delete_by_file_id(file_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[离线处理] 清理旧数据失败（忽略）：{exc}")
    finally:
        db.close()

    try:
        # ---------- 1. 解析 ----------
        _update_file(file_id, status="parsing", progress=5, error_msg=None,
                     chunk_count=0, triple_count=0,
                     recall_status="pending", recall_score=0, recall_detail=None)
        result = parse_file(file_path, ext, file_name)
        source_type = forced_source if forced_source in ALLOWED_SOURCE_TYPES else result.source_type

        # ---------- 2. 自动清洗脏数据（不做人工清洗） ----------
        _update_file(file_id, progress=12)
        text, clean_stats = clean_text_with_stats(result.text)
        if len(text) < 10:
            raise ParseError("清洗后文本过短，可能是空文件或扫描件未识别")
        _update_file(file_id, clean_stats=json.dumps(clean_stats, ensure_ascii=False))

        cfg1 = _load_agent_config("agent1")
        cfg3 = _load_agent_config("agent3")

        # ---------- 3. 切片 + 入库 + 自动召回测试（自愈循环） ----------
        attempt_order = [strategy] + [s for s in STRATEGIES if s != strategy]
        attempt_order = attempt_order[:MAX_RECALL_ATTEMPTS]
        chosen_strategy = strategy
        chosen_chunks: List[str] = []
        best_summary: dict = {}

        for attempt, current in enumerate(attempt_order, start=1):
            _update_file(
                file_id,
                status="chunking",
                progress=18,
                chunk_strategy=current,
                recall_status="running",
            )
            chunks = split_text(text, current)
            if not chunks:
                continue
            _update_file(file_id, chunk_count=len(chunks), progress=22)

            # 换策略重试前先清空上一轮向量，避免两套切片混在一起
            if attempt > 1:
                try:
                    qdrant_store.delete_by_file_id(file_id)
                except Exception as exc:  # noqa: BLE001
                    print(f"[离线处理] 重试清理向量失败（忽略）：{exc}")

            tagged = _build_index(file_id, cfg1, chunks, source_type, file_name,
                                  progress_from=25, progress_span=45)
            _update_file(file_id, progress=72)

            # 自动召回测试：抽样生成问题 -> 检索 -> 计算命中率
            _update_file(file_id, recall_status="running", progress=76)
            summary = run_recall_test(file_id, cfg3, chunks, current,
                                      iteration=attempt, persist=True)
            chosen_strategy, chosen_chunks = current, chunks
            if not best_summary or summary.get("accuracy", 0) >= best_summary.get("accuracy", 0):
                best_summary = summary
            if summary.get("passed"):
                # 达标：保留本轮索引，结束自愈循环
                best_summary = summary
                chosen_strategy, chosen_chunks = current, chunks
                break
            print(f"[离线处理] 文件 {file_id} 第 {attempt} 轮策略 {current} "
                  f"召回准确度 {summary.get('accuracy')}%，自动调整策略重试")

        if not chosen_chunks:
            raise ParseError("文本切片为空，请检查文件内容")

        # 所有轮次都未达标时，保留准确度最高的一轮结果（已由 run_recall_test 落库）
        _update_file(
            file_id,
            chunk_strategy=chosen_strategy,
            chunk_count=len(chosen_chunks),
            recall_status="passed" if best_summary.get("passed") else "failed",
            recall_score=int(best_summary.get("accuracy", 0) or 0),
            recall_detail=json.dumps(best_summary, ensure_ascii=False)[:6000],
            progress=80,
        )

        # ---------- 4. Agent2 知识抽取 + 图谱入库 ----------
        _update_file(file_id, status="kg", progress=84)
        cfg2 = _load_agent_config("agent2")
        all_triples: List[dict] = []
        kg_fail = 0
        for idx, chunk in enumerate(chosen_chunks):
            try:
                all_triples.extend(_extract_triples(cfg2, chunk))
                kg_fail = 0
            except LLMError as exc:
                kg_fail += 1
                if kg_fail >= 3:
                    raise LLMError(f"Agent2 知识抽取失败：{exc}")
            _update_file(file_id, progress=84 + int(12 * (idx + 1) / len(chosen_chunks)))

        triple_count = neo4j_store.upsert_triples(all_triples, file_id, file_name)

        # ---------- 5. 完成 ----------
        _update_file(
            file_id,
            status="done",
            progress=100,
            chunk_count=len(chosen_chunks),
            triple_count=triple_count,
            error_msg=None,
        )
        print(f"[离线处理] 文件 {file_id} 完成：策略 {STRATEGY_LABELS.get(chosen_strategy)}，"
              f"切片 {len(chosen_chunks)}，三元组 {triple_count}，"
              f"召回准确度 {best_summary.get('accuracy', 0)}%")

    except (ParseError, LLMError, EmbeddingError, qdrant_store.VectorStoreError,
            neo4j_store.GraphStoreError) as exc:
        _fail(file_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail(file_id, f"处理异常：{exc}")


def build_goods_text(goods_list) -> str:
    """
    把 MySQL 商品结构化数据拼成自然语言文本，交给统一的离线流水线处理。
    这样"表格数据"也走 Agent1 + Agent2，保证三条入库路径一致。
    """
    lines = []
    for g in goods_list:
        lines.append(
            f"商品款号：{g.goods_no}；商品名称：{g.name}；面料成分：{g.fabric}；"
            f"可选尺码：{g.sizes}；可选颜色：{g.colors}；保养方式：{g.care}；"
            f"售后政策：{g.after_sale}；活动信息：{g.activity}；检测报告编号：{g.report_no}。"
        )
    return "\n".join(lines)
