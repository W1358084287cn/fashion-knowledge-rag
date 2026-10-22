# -*- coding: utf-8 -*-
"""
知识库管理接口（仅管理员）
------------------------------------------------------------
- 多文件上传，保存到本地 uploads 目录，可选择切片策略
- 上传成功后立即提交后台离线任务（Agent1 + Agent2 + 自动召回测试）
- 文件列表、状态轮询、重新处理、删除
- 向量片段查看 / 人工修改 / 删除（修改后同步重建向量，立即影响检索）
- 单文件召回测试与知识图谱数据导出
- 一键导入 MySQL 商品结构化数据
"""
import json
import os
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_

from ..api_utils import fail, ok
from ..config import settings
from ..db import get_agent_config, session_scope
from ..models import Goods, KbFile, RecallTest
from ..prompts import ALLOWED_ENTITY_TYPES, ALLOWED_RELATIONS
from ..security import get_current_admin
from ..services import neo4j_store, qdrant_store
from ..services.audit import write_operation
from ..services.chunking import STRATEGY_LABELS, normalize_strategy
from ..services.embedding_client import EmbeddingError, embed_query_async, embed_texts_sync
from ..services.jobs import enqueue_file, enqueue_recall
from ..services.parsers import ParseError, parse_file
from ..services.pipeline import build_goods_text
from ..services.text_utils import build_sparse_vector, clean_text_with_stats

router = APIRouter(prefix="/api/kb", tags=["知识库"])

# 允许上传的扩展名（.doc 旧格式无法用 python-docx 解析，需另存为 .docx）
ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".docx", ".pdf", ".pptx",
    ".xlsx", ".xls", ".csv", ".json", ".sql",
}
MAX_FILES_PER_UPLOAD = 10


def _serialize_file(row: KbFile) -> dict:
    """文件记录的对外结构（含切片策略、自动清洗统计与召回测试结果）。"""
    def _json(value, default):
        try:
            return json.loads(value) if value else default
        except (ValueError, TypeError):
            return default

    return {
        "id": int(row.id),
        "file_name": row.file_name,
        "file_type": row.file_type,
        "source_type": row.source_type,
        "file_size": int(row.file_size or 0),
        "status": row.status,
        "progress": int(row.progress or 0),
        "chunk_count": int(row.chunk_count or 0),
        "triple_count": int(row.triple_count or 0),
        "error_msg": row.error_msg or "",
        "chunk_strategy": row.chunk_strategy or "semantic",
        "chunk_strategy_label": STRATEGY_LABELS.get(row.chunk_strategy or "semantic", "语义切分"),
        "clean_stats": _json(row.clean_stats, {}),
        "recall_status": row.recall_status or "pending",
        "recall_score": int(row.recall_score or 0),
        "recall_detail": _json(row.recall_detail, {}),
        "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "",
        "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M:%S") if row.updated_at else "",
    }


def _guess_source_type(file_name: str, ext: str) -> str:
    """根据文件名 / 扩展名推断来源类型。"""
    name_lower = file_name.lower()
    if ext in (".xlsx", ".xls", ".csv"):
        return "表格数据"
    if any(k in name_lower for k in ("聊天", "chat", "会话", "客服记录")):
        return "聊天记录"
    return "文档"


@router.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    strategy: str = Form("semantic"),
    identity: dict = Depends(get_current_admin),
):
    """
    多文件上传。
    每个文件独立校验，允许部分成功；返回成功列表与失败原因。
    strategy：切片策略 semantic / paragraph / chapter，入库后自动做召回测试。
    """
    if not files:
        return fail(1001, "请选择要上传的文件")
    if len(files) > MAX_FILES_PER_UPLOAD:
        return fail(1001, f"单次最多上传 {MAX_FILES_PER_UPLOAD} 个文件")
    strategy = normalize_strategy(strategy)

    created = []
    errors = []
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    for upload in files:
        original_name = os.path.basename(upload.filename or "未命名文件")
        ext = os.path.splitext(original_name)[1].lower()

        # 1. 类型校验
        if ext not in ALLOWED_EXTENSIONS:
            errors.append({"file_name": original_name, "error": f"不支持的文件类型 {ext or '无扩展名'}"})
            continue

        # 2. 保存到磁盘（uuid 命名，避免同名覆盖与路径穿越）
        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest_path = os.path.join(settings.UPLOAD_DIR, stored_name)
        size = 0
        too_large = False
        try:
            with open(dest_path, "wb") as out:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        too_large = True
                        break
                    out.write(chunk)
        except Exception as exc:  # noqa: BLE001
            errors.append({"file_name": original_name, "error": f"文件保存失败：{exc}"})
            continue
        finally:
            await upload.close()

        if too_large:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            errors.append({"file_name": original_name, "error": f"文件超过 {settings.MAX_UPLOAD_MB}MB 限制"})
            continue
        if size == 0:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            errors.append({"file_name": original_name, "error": "文件内容为空"})
            continue

        # 3. 写入数据库
        with session_scope() as db:
            row = KbFile(
                file_name=original_name,
                stored_name=stored_name,
                file_path=dest_path,
                file_type=ext,
                source_type=_guess_source_type(original_name, ext),
                file_size=size,
                status="pending",
                progress=0,
                chunk_strategy=strategy,
            )
            db.add(row)
            db.flush()
            file_id = int(row.id)
            result = _serialize_file(row)

        # 4. 立即触发离线处理（异步线程，不阻塞上传响应）
        enqueue_file(file_id)
        created.append(result)
        write_operation("admin", identity.get("sub", "admin"), "上传知识文件",
                        target=original_name,
                        detail=f"ID={file_id}，策略={STRATEGY_LABELS.get(strategy)}")

    if not created:
        message = errors[0]["error"] if errors else "上传失败"
        return fail(1001, message, data={"errors": errors})
    return ok({"items": created, "errors": errors},
              msg=f"成功上传 {len(created)} 个文件，正在后台处理（{STRATEGY_LABELS.get(strategy)}）")


@router.get("/files")
def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("", max_length=20),
    keyword: str = Query("", max_length=100),
    _: dict = Depends(get_current_admin),
):
    """分页查询知识库文件列表（管理端每 3 秒轮询一次处理进度）。"""
    with session_scope() as db:
        query = db.query(KbFile)
        if status:
            query = query.filter(KbFile.status == status)
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            query = query.filter(or_(KbFile.file_name.like(like), KbFile.source_type.like(like)))

        total = query.count()
        rows = query.order_by(KbFile.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        items = [_serialize_file(r) for r in rows]

    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("/files/{file_id}/reprocess")
def reprocess_file(
    file_id: int,
    strategy: str = Query("", max_length=20),
    identity: dict = Depends(get_current_admin),
):
    """重新执行离线处理（会先清理该文件的旧向量与图谱数据），可指定新的切片策略。"""
    with session_scope() as db:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if not row:
            return fail(2001, "文件不存在")
        if not os.path.exists(row.file_path):
            return fail(2001, "源文件已丢失，请重新上传")
        row.status = "pending"
        row.progress = 0
        row.error_msg = None
        row.recall_status = "pending"
        if strategy.strip():
            row.chunk_strategy = normalize_strategy(strategy)
        chosen = row.chunk_strategy

    enqueue_file(file_id)
    write_operation("admin", identity.get("sub", "admin"), "重新处理知识文件",
                    target=f"文件ID={file_id}", detail=f"策略={STRATEGY_LABELS.get(chosen)}")
    return ok({"id": file_id, "chunk_strategy": chosen}, msg="已重新加入处理队列")


@router.get("/files/{file_id}/raw")
def raw_content(file_id: int, _: dict = Depends(get_current_admin)):
    """
    查看源文件内容（修复“看不了源文件”）：
    - original_text：解析器从原始文件里读出的文本（未清洗）
    - cleaned_text：程序自动清洗后的文本（实际参与切片的内容）
    - clean_stats：清洗明细（字符数变化 + 被剔除内容示例）
    """
    with session_scope() as db:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if not row:
            return fail(2001, "文件不存在")
        file_name = row.file_name
        file_path = row.file_path
        file_type = (row.file_type or "").lower()
        strategy = row.chunk_strategy or "semantic"

    if not file_path or not os.path.exists(file_path):
        return fail(2001, "原始文件已不在服务器磁盘上（可能已清理 uploads 目录）")

    try:
        parsed = parse_file(file_path, file_type or os.path.splitext(file_name)[1].lower(), file_name)
    except ParseError as exc:
        return fail(2001, f"源文件解析失败：{exc}")

    cleaned, stats = clean_text_with_stats(parsed.text)
    return ok({
        "id": int(file_id),
        "file_name": file_name,
        "file_type": file_type,
        "source_type": parsed.source_type,
        "original_text": parsed.text,
        "cleaned_text": cleaned,
        "clean_stats": stats,
        "chunk_strategy": strategy,
        "chunk_strategy_label": STRATEGY_LABELS.get(strategy, "语义切分"),
    })


@router.get("/files/{file_id}/download")
def download_source(file_id: int, _: dict = Depends(get_current_admin)):
    """下载 / 预览原始上传文件（Word、Excel、PPT、PDF、SQL 等原格式）。"""
    with session_scope() as db:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if not row:
            return fail(2001, "文件不存在")
        file_name = row.file_name
        file_path = row.file_path

    if not file_path or not os.path.exists(file_path):
        return fail(2001, "原始文件已不在服务器磁盘上")
    return FileResponse(path=file_path, filename=file_name)


@router.get("/vector-overview")
def vector_overview(_: dict = Depends(get_current_admin)):
    """向量库图形化看板：集合信息、点数、维度、索引、片段分布。"""
    try:
        data = qdrant_store.collection_overview()
    except qdrant_store.VectorStoreError as exc:
        return fail(2001, str(exc))
    return ok(data)


@router.post("/search")
async def search_vectors(
    payload: dict = Body(...),
    _: dict = Depends(get_current_admin),
):
    """
    向量库图形化检索：输入一句话，直接看命中的片段与相似度。
    用于小白理解“向量检索到底召回了什么”，不经过大模型回答。
    """
    query = str(payload.get("query", "") or "").strip()
    if not query:
        return fail(1001, "请输入检索内容")
    if len(query) > 200:
        return fail(1001, "检索内容过长（最多 200 字）")

    top_k = int(payload.get("top_k") or 8)
    top_k = max(1, min(top_k, 20))
    filters = {}
    if payload.get("file_id"):
        filters["file_id"] = int(payload["file_id"])
    if payload.get("category"):
        filters["category"] = str(payload["category"])

    with session_scope() as db:
        cfg = get_agent_config(db, "agent3")

    try:
        dense_vector = await embed_query_async(cfg, query)
        indices, values = build_sparse_vector(query)
        docs = await qdrant_store.hybrid_search(
            dense_vector=dense_vector,
            sparse_indices=indices,
            sparse_values=values,
            filters=filters or None,
            top_k_final=top_k,
        )
    except EmbeddingError as exc:
        return fail(2001, f"Embedding 调用失败：{exc}")
    except qdrant_store.VectorStoreError as exc:
        return fail(2001, str(exc))

    # 混合检索按 RRF 分数排序；把首条归一化为 100%，便于管理端直观对比名次强弱
    top_score = max((float(doc.get("score", 0) or 0) for doc in docs), default=0.0)

    items = []
    for rank, doc in enumerate(docs, start=1):
        meta = doc.get("payload", {}) or {}
        score = float(doc.get("score", 0) or 0)
        items.append({
            "rank": rank,
            "id": doc.get("id"),
            "file_id": int(meta.get("file_id", 0) or 0),
            "file_name": str(meta.get("file_name", "") or ""),
            "chunk_index": int(meta.get("chunk_index", 0) or 0),
            "category": str(meta.get("category", "") or ""),
            "goods_no": str(meta.get("goods_no", "") or ""),
            "source_type": str(meta.get("source_type", "") or ""),
            "text": str(meta.get("text", "") or ""),
            "score": round(score, 4),
            "match": round(score / top_score, 4) if top_score > 0 else 0.0,
            "similarity": round(float(doc.get("dense_score", 0) or 0), 4),
        })
    return ok({"items": items, "total": len(items), "query": query})


@router.get("/files/{file_id}/chunks")
def list_chunks(file_id: int, _: dict = Depends(get_current_admin)):
    """查看某个文件的全部向量片段（管理端点击即可查看 / 修改）。"""
    try:
        items = qdrant_store.list_chunks_by_file(file_id)
    except qdrant_store.VectorStoreError as exc:
        return fail(2001, str(exc))
    return ok({"items": items, "total": len(items)})


@router.put("/files/{file_id}/chunks/{point_id}")
def update_chunk(
    file_id: int,
    point_id: str,
    payload: dict = Body(...),
    identity: dict = Depends(get_current_admin),
):
    """
    人工修改单个向量片段：
    - 更新文本后重新计算稠密 / 稀疏向量，改动立即对检索生效
    - 同时可修改分类标签与商品款号
    """
    text = str(payload.get("text", "") or "").strip()
    if not text:
        return fail(1001, "片段内容不能为空")
    if len(text) > 5000:
        return fail(1001, "片段内容过长（最多 5000 字）")

    with session_scope() as db:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if not row:
            return fail(2001, "文件不存在")
        cfg1 = get_agent_config(db, "agent1")

    try:
        vector = embed_texts_sync(cfg1, [text])[0]
        indices, values = build_sparse_vector(text)
        patch = {}
        if payload.get("category"):
            patch["category"] = str(payload["category"])[:50]
        if payload.get("goods_no"):
            patch["goods_no"] = str(payload["goods_no"]).strip().upper()[:50]
        qdrant_store.update_chunk_text(point_id, text, vector, indices, values, patch)
    except (EmbeddingError, qdrant_store.VectorStoreError) as exc:
        return fail(2001, f"片段更新失败：{exc}")

    write_operation("admin", identity.get("sub", "admin"), "修改向量片段",
                    target=f"文件ID={file_id}", detail=f"片段ID={point_id}，长度={len(text)}")
    return ok({"id": point_id, "text": text}, msg="片段已更新，向量已同步重建")


@router.delete("/files/{file_id}/chunks/{point_id}")
def remove_chunk(file_id: int, point_id: str,
                 identity: dict = Depends(get_current_admin)):
    """人工删除单个无效片段（例如重复、乱码、与业务无关的内容）。"""
    try:
        qdrant_store.delete_chunk(point_id)
    except qdrant_store.VectorStoreError as exc:
        return fail(2001, str(exc))

    with session_scope() as db:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if row and row.chunk_count and row.chunk_count > 0:
            row.chunk_count = int(row.chunk_count) - 1

    write_operation("admin", identity.get("sub", "admin"), "删除向量片段",
                    target=f"文件ID={file_id}", detail=f"片段ID={point_id}")
    return ok({"id": point_id}, msg="片段已删除")


@router.post("/files/{file_id}/recall-test")
def trigger_recall_test(file_id: int, identity: dict = Depends(get_current_admin)):
    """对已入库文件手动触发一次召回测试（后台执行，前端轮询文件状态查看结果）。"""
    with session_scope() as db:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if not row:
            return fail(2001, "文件不存在")
        if not row.chunk_count:
            return fail(2001, "该文件还没有入库切片，请先等待处理完成")
        row.recall_status = "running"

    if not enqueue_recall(file_id):
        return fail(2001, "该文件正在测试中，请稍候")
    write_operation("admin", identity.get("sub", "admin"), "发起召回测试",
                    target=f"文件ID={file_id}")
    return ok({"id": file_id}, msg="召回测试已开始，请稍候查看结果")


@router.get("/files/{file_id}/recall")
def recall_detail(file_id: int, _: dict = Depends(get_current_admin)):
    """召回测试明细：按轮次展示问题、命中情况与准确度，用于答辩讲解自愈过程。"""
    with session_scope() as db:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if not row:
            return fail(2001, "文件不存在")
        level = row.recall_status or "pending"
        score = int(row.recall_score or 0)
        strategy = row.chunk_strategy or "semantic"
        rows = (
            db.query(RecallTest)
            .filter(RecallTest.file_id == file_id)
            .order_by(RecallTest.id.asc())
            .limit(200)
            .all()
        )
        items = [{
            "iteration": int(r.iteration),
            "strategy": r.strategy,
            "strategy_label": STRATEGY_LABELS.get(r.strategy, r.strategy),
            "question": r.question,
            "hit": bool(r.hit),
            "score": round(float(r.score or 0), 4),
            "doc_count": int(r.doc_count or 0),
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        } for r in rows]

    return ok({
        "file_id": file_id,
        "status": level,
        "score": score,
        "chunk_strategy": strategy,
        "chunk_strategy_label": STRATEGY_LABELS.get(strategy, strategy),
        "items": items,
    })


@router.get("/graph")
def graph_view(limit: int = Query(300, ge=1, le=1000), _: dict = Depends(get_current_admin)):
    """知识图谱可视化数据（节点 / 关系），管理端用可拖拽画布渲染。"""
    try:
        data = neo4j_store.graph_data(limit=limit)
    except neo4j_store.GraphStoreError as exc:
        return fail(2001, str(exc))
    data["relation_types"] = ALLOWED_RELATIONS
    data["entity_types"] = ALLOWED_ENTITY_TYPES
    return ok(data)


@router.post("/graph/relationships")
def create_graph_relationship(payload: dict = Body(...), identity: dict = Depends(get_current_admin)):
    """手动建立实体关联：source_id / target_id 为画布节点 ID，relation 为预设关系。"""
    try:
        result = neo4j_store.create_relationship(
            str(payload.get("source_id", "") or ""),
            str(payload.get("target_id", "") or ""),
            str(payload.get("relation", "") or ""),
        )
    except neo4j_store.GraphStoreError as exc:
        return fail(2001, str(exc))
    if not result["created"]:
        return fail(2001, "这两个实体之间已存在相同关联，无需重复添加")
    write_operation(
        "admin", str(identity.get("username", "admin")), "新增图谱关联",
        target=str(payload.get("relation", "")),
        detail=json.dumps({
            "source": payload.get("source_name", ""),
            "target": payload.get("target_name", ""),
        }, ensure_ascii=False),
    )
    return ok(result)


@router.delete("/graph/relationships/{rel_id}")
def delete_graph_relationship(rel_id: str, identity: dict = Depends(get_current_admin)):
    """删除一条实体关联（只删关系，不删除两端实体）。"""
    try:
        deleted = neo4j_store.delete_relationship(rel_id)
    except neo4j_store.GraphStoreError as exc:
        return fail(2001, str(exc))
    if not deleted:
        return fail(2001, "关联不存在或已被删除")
    write_operation("admin", str(identity.get("username", "admin")), "删除图谱关联",
                    target=rel_id[:200])
    return ok({"deleted": True})


@router.delete("/files/{file_id}")
def delete_file(file_id: int, identity: dict = Depends(get_current_admin)):
    """删除知识库文件：同时清理 Qdrant 向量、Neo4j 关系与磁盘文件。"""
    with session_scope() as db:
        row = db.query(KbFile).filter(KbFile.id == file_id).first()
        if not row:
            return fail(2001, "文件不存在")
        file_path = row.file_path
        file_name = row.file_name
        db.query(RecallTest).filter(RecallTest.file_id == file_id).delete()
        db.delete(row)

    warnings = []
    try:
        qdrant_store.delete_by_file_id(file_id)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"向量清理失败：{exc}")
    try:
        neo4j_store.delete_by_file_id(file_id)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"图谱清理失败：{exc}")
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"磁盘文件删除失败：{exc}")

    write_operation("admin", identity.get("sub", "admin"), "删除知识文件",
                    target=file_name, detail=f"文件ID={file_id}")
    return ok({"id": file_id, "warnings": warnings, "file_name": file_name}, msg="已删除")


@router.post("/import-goods")
def import_goods(
    strategy: str = Query("semantic", max_length=20),
    identity: dict = Depends(get_current_admin),
):
    """
    把 MySQL goods 表中的结构化商品数据导入知识库。
    实现方式：拼成自然语言文本 -> 落盘为 txt -> 走统一离线流水线。
    """
    with session_scope() as db:
        goods_list = db.query(Goods).order_by(Goods.id.asc()).all()
        if not goods_list:
            return fail(2001, "暂无商品数据，请先在 goods 表中维护数据")
        text = build_goods_text(goods_list)

        stored_name = f"{uuid.uuid4().hex}.txt"
        dest_path = os.path.join(settings.UPLOAD_DIR, stored_name)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(text)

        file_name = f"MySQL商品数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        row = KbFile(
            file_name=file_name,
            stored_name=stored_name,
            file_path=dest_path,
            file_type=".txt",
            source_type="表格数据",
            file_size=os.path.getsize(dest_path),
            status="pending",
            progress=0,
            chunk_strategy=normalize_strategy(strategy),
        )
        db.add(row)
        db.flush()
        file_id = int(row.id)
        result = _serialize_file(row)

    enqueue_file(file_id)
    write_operation("admin", identity.get("sub", "admin"), "导入商品数据",
                    target=file_name, detail=f"共 {len(goods_list)} 条，文件ID={file_id}")
    return ok(result, msg=f"已导入 {len(goods_list)} 条商品数据，正在后台处理")


@router.get("/stats")
def kb_stats(_: dict = Depends(get_current_admin)):
    """知识库概览：文件状态统计、向量数量、图谱规模。"""
    with session_scope() as db:
        total = db.query(KbFile).count()
        status_rows = db.query(KbFile.status, func.count(KbFile.id)).group_by(KbFile.status).all()
        status_map = {s: int(c) for s, c in status_rows}

    vector_count = qdrant_store.count_points()
    graph = neo4j_store.graph_stats()
    return ok({
        "file_total": total,
        "status": status_map,
        "vector_count": vector_count,
        "graph_nodes": graph["nodes"],
        "graph_relations": graph["relations"],
    })
