# -*- coding: utf-8 -*-
"""
Qdrant 向量库封装
------------------------------------------------------------
集合结构：
- 命名向量 dense：语义向量（BAAI/bge-m3 embedding，1024 维，Cosine）
- 命名向量 sparse：稀疏关键词向量（本地 TF + 哈希下标）
- payload：文本片段 + 元标签（source_type / goods_no / category / file_id ...）

在线检索：
1. 稠密检索 + 稀疏检索各召回 TopK
2. 两路结果按名次做 RRF（Reciprocal Rank Fusion）融合
3. 支持 payload 标签过滤，缩小检索范围
"""
from typing import Dict, List, Optional

from qdrant_client import AsyncQdrantClient, QdrantClient, models

from ..config import settings


class VectorStoreError(Exception):
    """向量库异常（提示信息可直接展示）。"""


# 需要建立 payload 索引的字段：加速标签过滤
PAYLOAD_INDEX_FIELDS = ["file_id", "source_type", "goods_no", "category"]


def _collection_config() -> dict:
    """集合配置：稠密 + 稀疏双向量。"""
    return {
        "vectors_config": {
            "dense": models.VectorParams(
                size=settings.EMBEDDING_DIM,
                distance=models.Distance.COSINE,
            )
        },
        "sparse_vectors_config": {
            "sparse": models.SparseVectorParams()
        },
    }


def _ensure_payload_indexes(client: QdrantClient) -> None:
    """为元标签字段建立 keyword 索引（已存在时忽略异常）。"""
    for field in PAYLOAD_INDEX_FIELDS:
        try:
            client.create_payload_index(
                collection_name=settings.QDRANT_COLLECTION,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:  # noqa: BLE001
            # 索引已存在或当前版本不支持时忽略，不影响检索正确性
            pass


def ensure_collection_sync() -> None:
    """同步确保集合存在（离线入库、启动自检使用）。"""
    client = QdrantClient(url=settings.QDRANT_URL, timeout=10)
    try:
        exists = client.collection_exists(settings.QDRANT_COLLECTION)
        if not exists:
            client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                **_collection_config(),
            )
            print(f"[Qdrant] 已创建集合：{settings.QDRANT_COLLECTION}")
        else:
            info = client.get_collection(settings.QDRANT_COLLECTION)
            existing_dim = info.config.params.vectors.get("dense").size
            if existing_dim != settings.EMBEDDING_DIM:
                raise VectorStoreError(
                    f"Qdrant 集合维度 {existing_dim} 与 EMBEDDING_DIM={settings.EMBEDDING_DIM} 不一致。"
                    "请删除集合后重新处理文档，或修改 .env 中 EMBEDDING_DIM。"
                )
        _ensure_payload_indexes(client)
    except VectorStoreError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"Qdrant 连接失败：{exc}") from exc
    finally:
        client.close()


async def ensure_collection_async() -> None:
    """异步确保集合存在（在线问答前调用）。"""
    client = AsyncQdrantClient(url=settings.QDRANT_URL, timeout=10)
    try:
        exists = await client.collection_exists(settings.QDRANT_COLLECTION)
        if not exists:
            await client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                **_collection_config(),
            )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"Qdrant 连接失败：{exc}") from exc
    finally:
        await client.close()


def _build_filter(filters: Optional[Dict[str, str]]) -> Optional[models.Filter]:
    """
    根据标签构造过滤条件。
    filters 示例：{"category": "售后", "source_type": "文档", "goods_no": "FY2026-001"}
    """
    if not filters:
        return None
    must = []
    for key, value in filters.items():
        if value:
            must.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
    if not must:
        return None
    return models.Filter(must=must)


def upsert_chunks(points: List[dict]) -> int:
    """
    批量写入切片。
    points 每项：{
        "id": str,
        "dense": List[float],
        "sparse_indices": List[int],
        "sparse_values": List[float],
        "payload": dict
    }
    返回成功写入数量。
    """
    if not points:
        return 0
    client = QdrantClient(url=settings.QDRANT_URL, timeout=30)
    try:
        ensure_collection_sync()
        structs = []
        for p in points:
            structs.append(models.PointStruct(
                id=p["id"],
                vector={
                    "dense": p["dense"],
                    "sparse": models.SparseVector(
                        indices=p["sparse_indices"],
                        values=p["sparse_values"],
                    ),
                },
                payload=p["payload"],
            ))
        client.upsert(collection_name=settings.QDRANT_COLLECTION, points=structs, wait=True)
        return len(structs)
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"向量入库失败：{exc}") from exc
    finally:
        client.close()


def delete_by_file_id(file_id: int) -> None:
    """按文件 ID 删除该文件产生的全部向量（删除知识库文件时调用）。"""
    client = QdrantClient(url=settings.QDRANT_URL, timeout=30)
    try:
        if not client.collection_exists(settings.QDRANT_COLLECTION):
            return
        client.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=models.FilterSelector(filter=models.Filter(
                must=[models.FieldCondition(
                    key="file_id",
                    match=models.MatchValue(value=file_id),
                )]
            )),
            wait=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"向量删除失败：{exc}") from exc
    finally:
        client.close()


def list_chunks_by_file(file_id: int, limit: int = 1000) -> List[dict]:
    """
    列出某个文件的全部向量片段（按 chunk_index 排序），供管理端查看 / 编辑。
    返回：{id, chunk_index, text, source_type, goods_no, category, file_name}
    """
    client = QdrantClient(url=settings.QDRANT_URL, timeout=30)
    try:
        if not client.collection_exists(settings.QDRANT_COLLECTION):
            return []
        records, _ = client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            scroll_filter=models.Filter(must=[models.FieldCondition(
                key="file_id",
                match=models.MatchValue(value=int(file_id)),
            )]),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        items = []
        for rec in records:
            payload = rec.payload or {}
            items.append({
                "id": str(rec.id),
                "chunk_index": int(payload.get("chunk_index", 0) or 0),
                "text": str(payload.get("text", "") or ""),
                "source_type": str(payload.get("source_type", "") or ""),
                "goods_no": str(payload.get("goods_no", "") or ""),
                "category": str(payload.get("category", "") or ""),
                "file_name": str(payload.get("file_name", "") or ""),
            })
        items.sort(key=lambda x: x["chunk_index"])
        return items
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"读取向量片段失败：{exc}") from exc
    finally:
        client.close()


def update_chunk_text(point_id: str, text: str, dense_vector: List[float],
                      sparse_indices: List[int], sparse_values: List[float],
                      payload_patch: Optional[dict] = None) -> None:
    """
    人工修改单个切片：同步更新 payload 文本、稠密向量与稀疏向量，
    保证修改后立刻参与检索，而不是只改展示。
    """
    client = QdrantClient(url=settings.QDRANT_URL, timeout=30)
    try:
        patch = {"text": text}
        if payload_patch:
            patch.update(payload_patch)
        client.set_payload(
            collection_name=settings.QDRANT_COLLECTION,
            payload=patch,
            points=[point_id],
            wait=True,
        )
        client.update_vectors(
            collection_name=settings.QDRANT_COLLECTION,
            points=[models.PointVectors(
                id=point_id,
                vector={
                    "dense": dense_vector,
                    "sparse": models.SparseVector(
                        indices=sparse_indices,
                        values=sparse_values,
                    ),
                },
            )],
            wait=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"切片更新失败：{exc}") from exc
    finally:
        client.close()


def delete_chunk(point_id: str) -> None:
    """删除单个切片（管理端人工剔除无效片段）。"""
    client = QdrantClient(url=settings.QDRANT_URL, timeout=20)
    try:
        client.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=models.PointIdsList(points=[point_id]),
            wait=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"切片删除失败：{exc}") from exc
    finally:
        client.close()


def _rrf_fuse(dense_points: list, sparse_points: list, top_k: int, rrf_k: int = 60) -> List[dict]:
    """
    手动实现 RRF 融合：
        score(d) = Σ 1 / (rrf_k + rank_i(d))
    rank 从 1 开始。融合后按分数倒序取 top_k。
    """
    merged: Dict[str, dict] = {}

    for rank, point in enumerate(dense_points, start=1):
        pid = str(point.id)
        item = merged.setdefault(pid, {"id": pid, "payload": point.payload or {}, "score": 0.0,
                                       "dense_rank": None, "sparse_rank": None,
                                       "dense_score": 0.0, "sparse_score": 0.0})
        item["score"] += 1.0 / (rrf_k + rank)
        item["dense_rank"] = rank
        # 保留稠密相似度原始分数，用于召回准确度评估（RRF 分数不适合做阈值判断）
        item["dense_score"] = float(getattr(point, "score", 0.0) or 0.0)

    for rank, point in enumerate(sparse_points, start=1):
        pid = str(point.id)
        item = merged.setdefault(pid, {"id": pid, "payload": point.payload or {}, "score": 0.0,
                                       "dense_rank": None, "sparse_rank": None,
                                       "dense_score": 0.0, "sparse_score": 0.0})
        item["score"] += 1.0 / (rrf_k + rank)
        item["sparse_rank"] = rank
        item["sparse_score"] = float(getattr(point, "score", 0.0) or 0.0)

    ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]


async def hybrid_search(
    dense_vector: List[float],
    sparse_indices: List[int],
    sparse_values: List[float],
    filters: Optional[Dict[str, str]] = None,
    top_k_each: Optional[int] = None,
    top_k_final: Optional[int] = None,
) -> List[dict]:
    """
    稠密 + 稀疏混合检索，RRF 融合。

    返回：[{id, score, payload, dense_rank, sparse_rank}, ...]
    """
    top_k_each = top_k_each or settings.TOP_K_EACH
    top_k_final = top_k_final or settings.TOP_K_FINAL
    query_filter = _build_filter(filters)

    client = AsyncQdrantClient(url=settings.QDRANT_URL, timeout=20)
    try:
        if not await client.collection_exists(settings.QDRANT_COLLECTION):
            return []

        dense_resp = await client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=dense_vector,
            using="dense",
            query_filter=query_filter,
            limit=top_k_each,
            with_payload=True,
            with_vectors=False,
        )

        sparse_resp = None
        if sparse_indices:
            sparse_resp = await client.query_points(
                collection_name=settings.QDRANT_COLLECTION,
                query=models.SparseVector(indices=sparse_indices, values=sparse_values),
                using="sparse",
                query_filter=query_filter,
                limit=top_k_each,
                with_payload=True,
                with_vectors=False,
            )

        return _rrf_fuse(
            dense_resp.points,
            sparse_resp.points if sparse_resp else [],
            top_k_final,
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"向量检索失败：{exc}") from exc
    finally:
        await client.close()


def count_points() -> int:
    """统计向量数量（健康检查 / 管理端展示用）。"""
    client = QdrantClient(url=settings.QDRANT_URL, timeout=10)
    try:
        if not client.collection_exists(settings.QDRANT_COLLECTION):
            return 0
        return client.count(collection_name=settings.QDRANT_COLLECTION, exact=True).count
    except Exception:  # noqa: BLE001
        return 0
    finally:
        client.close()


def fetch_texts_by_file_id(file_id: int, limit: int = 500) -> List[str]:
    """
    读取某个文件已入库的全部切片文本（按 chunk_index 排序）。
    用于「召回测试」：不必重新解析文件，直接基于现有向量切片生成测试问题。
    """
    client = QdrantClient(url=settings.QDRANT_URL, timeout=20)
    try:
        if not client.collection_exists(settings.QDRANT_COLLECTION):
            return []
        records, _ = client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            scroll_filter=models.Filter(must=[models.FieldCondition(
                key="file_id",
                match=models.MatchValue(value=int(file_id)),
            )]),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        items = []
        for rec in records:
            payload = rec.payload or {}
            text = str(payload.get("text", "") or "").strip()
            if text:
                items.append((int(payload.get("chunk_index", 0) or 0), text))
        items.sort(key=lambda x: x[0])
        return [text for _, text in items]
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"读取切片失败：{exc}") from exc
    finally:
        client.close()


def collection_overview() -> dict:
    """
    向量库图形化看板数据：
    - 集合基本信息：点数、稠密向量维度、距离度量
    - payload 索引字段
    - 按文件 / 分类 / 来源类型聚合的片段分布
    """
    client = QdrantClient(url=settings.QDRANT_URL, timeout=20)
    try:
        exists = client.collection_exists(settings.QDRANT_COLLECTION)
        if not exists:
            return {
                "collection": settings.QDRANT_COLLECTION,
                "exists": False,
                "points": 0,
                "dim": settings.EMBEDDING_DIM,
                "distance": "Cosine",
                "index_fields": [],
                "files": [],
                "categories": [],
                "source_types": [],
            }

        info = client.get_collection(settings.QDRANT_COLLECTION)
        dim = settings.EMBEDDING_DIM
        try:
            dim = info.config.params.vectors.get("dense").size
        except Exception:  # noqa: BLE001
            pass

        # 滚动读取 payload 做分布统计（演示规模有限，最多 3000 条）
        records, _ = client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=3000,
            with_payload=True,
            with_vectors=False,
        )
        file_counter: Dict[str, int] = {}
        category_counter: Dict[str, int] = {}
        source_counter: Dict[str, int] = {}
        for rec in records:
            payload = rec.payload or {}
            file_name = str(payload.get("file_name", "") or "未知文件")
            file_counter[file_name] = file_counter.get(file_name, 0) + 1
            category = str(payload.get("category", "") or "未分类")
            category_counter[category] = category_counter.get(category, 0) + 1
            source = str(payload.get("source_type", "") or "文档")
            source_counter[source] = source_counter.get(source, 0) + 1

        index_fields = []
        try:
            schema = info.payload_schema or {}
            index_fields = [{"field": k, "type": str(v.data_type)} for k, v in schema.items()]
        except Exception:  # noqa: BLE001
            index_fields = [{"field": f, "type": "keyword"} for f in PAYLOAD_INDEX_FIELDS]

        def _sorted(counter: Dict[str, int]) -> List[dict]:
            return [{"name": k, "count": v}
                    for k, v in sorted(counter.items(), key=lambda x: -x[1])]

        return {
            "collection": settings.QDRANT_COLLECTION,
            "exists": True,
            "points": int(getattr(info, "points_count", 0) or 0),
            "dim": int(dim),
            "distance": "Cosine",
            "index_fields": index_fields,
            "files": _sorted(file_counter),
            "categories": _sorted(category_counter),
            "source_types": _sorted(source_counter),
            "scanned": len(records),
        }
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"读取向量库信息失败：{exc}") from exc
    finally:
        client.close()
