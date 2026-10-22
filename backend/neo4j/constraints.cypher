// ============================================================
// 服装多源文档智能客服系统 - Neo4j 约束脚本
// 适用版本：Neo4j 5.x
// 执行方式：
//   docker exec -i fashion-cs-neo4j cypher-shell -u neo4j -p fashion123 < constraints.cypher
// 或浏览器打开 http://localhost:7474 逐条执行。
// 后端启动时也会自动执行同样的语句（幂等）。
// ============================================================

// 1. 实体名称唯一约束：保证同一实体不会重复建节点
CREATE CONSTRAINT entity_name_unique IF NOT EXISTS
FOR (e:Entity) REQUIRE e.name IS UNIQUE;

// 2. 实体类型索引：加速按类型过滤
CREATE INDEX entity_type_idx IF NOT EXISTS
FOR (e:Entity) ON (e.type);

// 3. 关系来源文件索引：删除知识库文件时快速定位
CREATE INDEX rel_file_idx IF NOT EXISTS
FOR ()-[r]-() ON (r.source_file_id);
