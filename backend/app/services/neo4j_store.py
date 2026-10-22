# -*- coding: utf-8 -*-
"""
Neo4j 知识图谱封装
------------------------------------------------------------
图模型：
  (:Entity:商品 {name, type})
  (h)-[:面料是 {source_file_id, source_file}]->(t)
  ... 只允许需求中约定的 5 种关系与 7 类实体

离线：Agent2 抽取的三元组写入图谱
在线：Agent3 根据问题关键词并行查询图谱关联信息
"""
from typing import Dict, List, Optional

from neo4j import AsyncGraphDatabase, GraphDatabase

from ..config import settings
from ..prompts import ALLOWED_ENTITY_TYPES, ALLOWED_RELATIONS


class GraphStoreError(Exception):
    """图数据库异常（提示信息可直接展示）。"""


# 关系 -> 尾实体类型，用于给节点自动补类型标签
RELATION_TAIL_TYPE = {
    "面料是": "面料",
    "支持售后": "售后政策",
    "保养方式为": "保养方式",
    "对应检测报告": "检测报告",
    "适用尺码": "尺码",
}

# 约束脚本（与 backend/neo4j/*** 保持一致）
CONSTRAINT_STATEMENTS = [
    "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE",
    "CREATE INDEX entity_type_idx IF NOT EXISTS FOR (e:Entity) ON (e.type)",
]


def _safe_label(label: str) -> str:
    """只允许白名单内的实体类型作为标签，避免 Cypher 注入。"""
    return label if label in ALLOWED_ENTITY_TYPES else "商品"


def ensure_constraints_sync() -> None:
    """启动时创建唯一约束与索引（幂等）。"""
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            for statement in CONSTRAINT_STATEMENTS:
                session.run(statement).consume()
        print("[Neo4j] 约束与索引检查完成")
    except Exception as exc:  # noqa: BLE001
        raise GraphStoreError(f"Neo4j 连接失败：{exc}") from exc
    finally:
        driver.close()


def upsert_triples(triples: List[dict], file_id: int, file_name: str) -> int:
    """
    写入三元组。
    - 实体按 name MERGE，节点自动补充类型标签与 type 属性
    - 关系带上 source_file_id，便于按文件删除，且不同文件的三元组互不覆盖
    返回成功写入的关系数量。
    """
    valid: List[dict] = []
    seen = set()
    for item in triples:
        if not isinstance(item, dict):
            continue
        head = str(item.get("head", "")).strip()[:100]
        relation = str(item.get("relation", "")).strip()
        tail = str(item.get("tail", "")).strip()[:200]
        if not head or not tail:
            continue
        if relation not in ALLOWED_RELATIONS:
            continue  # 严格限制关系类型，防止模型自由发挥
        key = (head, relation, tail)
        if key in seen:
            continue
        seen.add(key)
        valid.append({"head": head, "relation": relation, "tail": tail})

    if not valid:
        return 0

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    written = 0
    try:
        with driver.session() as session:
            for item in valid:
                tail_type = _safe_label(RELATION_TAIL_TYPE.get(item["relation"], "商品"))
                head_label = _safe_label("商品")
                # 关系类型与标签都已通过白名单校验，这里可以安全地拼接到 Cypher 中。
                # 注意：先只用 :Entity 做 MERGE，再单独 SET 类型标签，
                # 这样同名实体不会因为标签不同触发唯一约束冲突（例如同款号被抽成不同实体）。
                cypher = f"""
                MERGE (h:`Entity` {{name: $head}})
                SET h:`{head_label}`, h.type = $head_type
                MERGE (t:`Entity` {{name: $tail}})
                SET t:`{tail_type}`, t.type = $tail_type
                MERGE (h)-[r:`{item['relation']}` {{source_file_id: $file_id}}]->(t)
                SET r.source_file = $file_name, r.updated_at = timestamp()
                """
                session.run(
                    cypher,
                    head=item["head"],
                    head_type="商品",
                    tail=item["tail"],
                    tail_type=tail_type,
                    file_id=file_id,
                    file_name=file_name,
                ).consume()
                written += 1
    except Exception as exc:  # noqa: BLE001
        raise GraphStoreError(f"知识图谱写入失败：{exc}") from exc
    finally:
        driver.close()
    return written


def delete_by_file_id(file_id: int) -> None:
    """删除某文件写入的关系，并清理孤立实体节点。"""
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        with driver.session() as session:
            session.run(
                "MATCH ()-[r {source_file_id: $file_id}]->() DELETE r",
                file_id=file_id,
            ).consume()
            # 只清理没有任何关系的孤立实体，避免影响其他文件的知识
            session.run("MATCH (n:Entity) WHERE NOT (n)--() DELETE n").consume()
    except Exception as exc:  # noqa: BLE001
        raise GraphStoreError(f"知识图谱删除失败：{exc}") from exc
    finally:
        driver.close()


async def search_triples(keywords: List[str], limit: int = 30) -> List[dict]:
    """
    在线图谱检索：按问题关键词做实体名包含匹配，返回关联三元组。
    - 限制返回条数，避免 Prompt 过长
    - 结果在 Python 侧去重
    """
    if not keywords:
        return []

    cypher = """
    MATCH (h:Entity)-[r]->(t:Entity)
    WHERE any(k IN $keywords WHERE h.name CONTAINS k OR t.name CONTAINS k OR type(r) CONTAINS k)
    RETURN h.name AS head, type(r) AS relation, t.name AS tail,
           coalesce(h.type, '') AS head_type, coalesce(t.type, '') AS tail_type
    LIMIT $limit
    """
    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        async with driver.session() as session:
            result = await session.run(cypher, keywords=keywords, limit=limit)
            records = await result.data()
    except Exception as exc:  # noqa: BLE001
        raise GraphStoreError(f"知识图谱查询失败：{exc}") from exc
    finally:
        await driver.close()

    seen = set()
    triples: List[dict] = []
    for rec in records:
        key = (rec.get("head"), rec.get("relation"), rec.get("tail"))
        if key in seen:
            continue
        seen.add(key)
        triples.append({
            "head": rec.get("head", ""),
            "relation": rec.get("relation", ""),
            "tail": rec.get("tail", ""),
            "head_type": rec.get("head_type", ""),
            "tail_type": rec.get("tail_type", ""),
        })
    return triples


def graph_data(limit: int = 300) -> Dict[str, List[dict]]:
    """
    导出图谱可视化数据（管理端画布拖拽展示）。
    返回 nodes（含 id/name/type）与 links（含 source/target/relation）。
    """
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        with driver.session() as session:
            # 实体单独查询：即使某个实体暂无关系，也要能在画布/下拉框中被选择
            node_records = session.run(
                """
                MATCH (n:Entity)
                RETURN elementId(n) AS id, n.name AS name, coalesce(n.type, '') AS type
                LIMIT $node_limit
                """,
                node_limit=max(600, limit * 3),
            ).data()
            records = session.run(
                """
                MATCH (h:Entity)-[r]->(t:Entity)
                RETURN elementId(r) AS rid, elementId(h) AS hid, h.name AS hname,
                       coalesce(h.type, '') AS htype,
                       elementId(t) AS tid, t.name AS tname, coalesce(t.type, '') AS ttype,
                       type(r) AS rel, r.source_file AS file_name,
                       coalesce(r.manual, false) AS manual
                LIMIT $limit
                """,
                limit=limit,
            ).data()
    except Exception as exc:  # noqa: BLE001
        raise GraphStoreError(f"知识图谱导出失败：{exc}") from exc
    finally:
        driver.close()

    nodes: Dict[str, dict] = {}
    for rec in node_records:
        nodes[rec["id"]] = {
            "id": rec["id"],
            "name": rec.get("name") or "",
            "type": rec.get("type") or "实体",
        }

    links: List[dict] = []
    for rec in records:
        hid, tid = rec["hid"], rec["tid"]
        if hid not in nodes:
            nodes[hid] = {"id": hid, "name": rec["hname"], "type": rec["htype"] or "商品"}
        if tid not in nodes:
            nodes[tid] = {"id": tid, "name": rec["tname"], "type": rec["ttype"] or "实体"}
        links.append({
            "id": rec.get("rid") or f"{hid}-{tid}-{rec['rel']}",
            "source": hid,
            "target": tid,
            "relation": rec["rel"],
            "file_name": rec.get("file_name") or "",
            "manual": bool(rec.get("manual")),
        })
    return {"nodes": list(nodes.values()), "links": links}


def create_relationship(source_id: str, target_id: str, relation: str) -> Dict[str, object]:
    """
    手动为两个已有实体建立关联（管理员在画布上直接选“谁和谁有关联”）。

    - 两端必须已存在（按 elementId 定位，避免同名实体歧义）
    - 关系类型必须在白名单内
    - 同一对实体同一关系只保留一条，避免重复连线
    返回 {"created": bool, "id": 关系ID}。
    """
    relation = str(relation or "").strip()
    if relation not in ALLOWED_RELATIONS:
        raise GraphStoreError("不支持的关系类型，请从预设关系中选择")
    if not source_id or not target_id or source_id == target_id:
        raise GraphStoreError("请选择两个不同的实体")

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        with driver.session() as session:
            record = session.run(
                f"""
                MATCH (h:Entity) WHERE elementId(h) = $sid
                MATCH (t:Entity) WHERE elementId(t) = $tid
                OPTIONAL MATCH (h)-[existing:`{relation}`]->(t)
                WITH h, t, existing
                WHERE existing IS NULL
                CREATE (h)-[r:`{relation}` {{source_file: '手动维护', manual: true, updated_at: timestamp()}}]->(t)
                RETURN elementId(r) AS rid
                """,
                sid=source_id,
                tid=target_id,
            ).single()
            if record:
                return {"created": True, "id": record["rid"]}
            # 没有返回记录：要么实体不存在，要么关系已存在，再查一次给出准确提示
            exists = session.run(
                "MATCH (h:Entity) WHERE elementId(h) = $sid MATCH (t:Entity) WHERE elementId(t) = $tid "
                "RETURN count(h) + count(t) AS c",
                sid=source_id, tid=target_id,
            ).single()
    except Exception as exc:  # noqa: BLE001
        raise GraphStoreError(f"关联创建失败：{exc}") from exc
    finally:
        driver.close()

    if not exists or int(exists["c"]) < 2:
        raise GraphStoreError("实体不存在或已被删除，请刷新后重试")
    return {"created": False, "id": ""}


def delete_relationship(rel_id: str) -> bool:
    """删除指定关系（按 elementId 定位），不存在返回 False。"""
    if not rel_id:
        raise GraphStoreError("缺少关系 ID")
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        with driver.session() as session:
            record = session.run(
                "MATCH ()-[r]->() WHERE elementId(r) = $rid DELETE r RETURN 1 AS c",
                rid=rel_id,
            ).single()
        return bool(record and int(record["c"]) > 0)
    except Exception as exc:  # noqa: BLE001
        raise GraphStoreError(f"关系删除失败：{exc}") from exc
    finally:
        driver.close()


def graph_stats() -> Dict[str, int]:
    """图谱规模统计（管理端可展示）。"""
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        with driver.session() as session:
            nodes = session.run("MATCH (n:Entity) RETURN count(n) AS c").single()
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
        return {
            "nodes": int(nodes["c"]) if nodes else 0,
            "relations": int(rels["c"]) if rels else 0,
        }
    except Exception:  # noqa: BLE001
        return {"nodes": 0, "relations": 0}
    finally:
        driver.close()
