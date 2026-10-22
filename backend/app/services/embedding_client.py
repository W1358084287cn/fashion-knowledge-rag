# -*- coding: utf-8 -*-
"""
Embedding 调用封装（OpenAI 兼容 /embeddings 接口）
------------------------------------------------------------
- 默认对接硅基流动 BAAI/bge-m3（1024 维，OpenAI 兼容 /embeddings 接口）
- 离线入库使用同步版本，在线提问使用异步版本
- 批量调用按 10 条一组，兼容多数 OpenAI 兼容服务的单次条数限制
- 返回向量做 L2 归一化，配合 Qdrant Cosine 距离更稳定
"""
import math
import time
from typing import List

import httpx

from ..config import settings


class EmbeddingError(Exception):
    """向量化异常（提示信息可直接展示给管理员）。"""


def normalize_embedding_base_url(url: str) -> str:
    """去掉末尾的 /embeddings，得到 OpenAI SDK / HTTP 客户端需要的 base_url。"""
    url = (url or "").strip().rstrip("/")
    if url.endswith("/embeddings"):
        url = url[: -len("/embeddings")]
    return url.rstrip("/")


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _extract_embeddings(payload: dict) -> List[List[float]]:
    """从接口响应中按 index 排序取出向量。"""
    data = payload.get("data")
    if not isinstance(data, list):
        raise EmbeddingError(f"Embedding 接口返回格式异常：{str(payload)[:200]}")
    data = sorted(data, key=lambda x: x.get("index", 0))
    vectors = []
    for item in data:
        emb = item.get("embedding")
        if not isinstance(emb, list) or not emb:
            raise EmbeddingError("Embedding 接口未返回有效向量")
        vectors.append([float(x) for x in emb])
    return vectors


def _normalize(vector: List[float]) -> List[float]:
    """L2 归一化，避免不同模型输出尺度差异影响余弦相似度。"""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return vector
    return [x / norm for x in vector]


def _check_config(cfg):
    url = normalize_embedding_base_url(getattr(cfg, "embedding_url", ""))
    key = (getattr(cfg, "embedding_api_key", "") or "").strip()
    model = (getattr(cfg, "embedding_model", "") or "").strip()
    if not url:
        raise EmbeddingError("尚未配置 Embedding URL，请先在管理端填写并保存")
    if not key:
        raise EmbeddingError("尚未配置 Embedding ApiKey，请先在管理端填写并保存")
    if not model:
        raise EmbeddingError("尚未配置 Embedding 模型名，请先在管理端填写并保存")
    return f"{url}/embeddings", key, model


def _validate_dim(vectors: List[List[float]]) -> List[List[float]]:
    """校验向量维度与 Qdrant 集合维度一致，维度不符时给出可操作的提示。"""
    for vec in vectors:
        if len(vec) != settings.EMBEDDING_DIM:
            raise EmbeddingError(
                f"Embedding 向量维度为 {len(vec)}，与系统配置的 {settings.EMBEDDING_DIM} 不一致。"
                "请更换同维度模型，或修改 .env 中 EMBEDDING_DIM 后重建 Qdrant 集合。"
            )
    return [_normalize(v) for v in vectors]


def embed_texts_sync(cfg, texts: List[str], batch_size: int = 10) -> List[List[float]]:
    """
    同步批量向量化（离线 Agent1 使用）。
    网络异常自动重试 2 次，仍失败则抛出 EmbeddingError。
    """
    endpoint, api_key, model = _check_config(cfg)
    results: List[List[float]] = []

    with httpx.Client(timeout=60.0) as client:
        for start in range(0, len(texts), batch_size):
            batch = [t[:2000] for t in texts[start:start + batch_size]]  # 防止超长文本被接口拒绝
            payload = {"model": model, "input": batch, "encoding_format": "float"}

            last_exc = None
            for attempt in range(3):
                try:
                    resp = client.post(endpoint, headers=_headers(api_key), json=payload)
                    if resp.status_code == 401:
                        raise EmbeddingError("Embedding 密钥无效，请在管理端重新配置")
                    if resp.status_code >= 400:
                        raise EmbeddingError(f"Embedding 接口返回 {resp.status_code}：{resp.text[:200]}")
                    results.extend(_extract_embeddings(resp.json()))
                    last_exc = None
                    break
                except EmbeddingError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    time.sleep(1 + attempt)

            if last_exc is not None:
                raise EmbeddingError(f"Embedding 调用失败：{str(last_exc)[:200]}") from last_exc

    if len(results) != len(texts):
        raise EmbeddingError(f"向量数量不匹配：期望 {len(texts)} 条，实际返回 {len(results)} 条")
    return _validate_dim(results)


async def embed_query_async(cfg, text: str) -> List[float]:
    """
    异步向量化单条问题（Agent3 在线检索使用）。
    与 Qdrant 查询并行执行可以进一步降低首字延迟。
    """
    endpoint, api_key, model = _check_config(cfg)
    payload = {"model": model, "input": [text[:2000]], "encoding_format": "float"}

    last_exc = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(endpoint, headers=_headers(api_key), json=payload)
                if resp.status_code == 401:
                    raise EmbeddingError("Embedding 密钥无效，请在管理端重新配置")
                if resp.status_code >= 400:
                    raise EmbeddingError(f"Embedding 接口返回 {resp.status_code}：{resp.text[:200]}")
                vectors = _extract_embeddings(resp.json())
                return _validate_dim(vectors)[0]
            except EmbeddingError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(1 + attempt)

    raise EmbeddingError(f"Embedding 调用失败：{str(last_exc)[:200]}") from last_exc
