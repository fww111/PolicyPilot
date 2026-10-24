"""
Neo4j 图谱存储与多跳查询 —— 三维本体（时效/冲突/层级）的推理底座。

查询设计对应赛题"跨文档多跳知识推理"：
  - trace_supersede_chain：这政策被谁废止了？一路追到现行版本（时效维，2+ 跳）
  - find_conflicts：该事项与哪些同类互斥（冲突维，跨文件）
  - match_policies_for：企业画像 -> 可申事项 + 依据链（推理 Agent 的主查询）
"""

from __future__ import annotations

import os

from neo4j import GraphDatabase

from policy_pilot.ontology.policy_ontology import Triple


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "policy123")),
    )


CONSTRAINT_CYPHERS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Policy) REQUIRE p.policy_id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Subsidy) REQUIRE s.subsidy_id IS UNIQUE",
]


def upsert_triples(triples: list[Triple], driver=None) -> int:
    """三元组批量入库（MERGE 幂等）。rel_type 白名单防注入。"""
    allowed = {"SUPERSEDES", "CONFLICTS_WITH", "BELONGS_TO", "APPLIES_TO", "HAS_SUBSIDY",
               "REQUIRES", "ACCEPTED_BY", "ALIGNS_WITH", "LOCATED_IN", "QUALIFIED_AS",
               "SUPERIOR_TO", "HAS_ARTICLE", "ISSUED_BY"}
    driver = driver or get_driver()
    n = 0
    with driver.session() as session:
        for c in CONSTRAINT_CYPHERS:
            session.run(c)
        for t in triples:
            rel = t.relation.name
            if rel not in allowed:
                continue
            session.run(
                f"""
                MERGE (a:{t.subject_type} {{id: $sid}})
                MERGE (b:{t.object_type} {{id: $oid}})
                MERGE (a)-[r:{rel}]->(b)
                SET r.confidence = $conf, r.evidence = $ev, r.source = $src
                """,
                sid=t.subject_id, oid=t.object_id, conf=t.confidence,
                ev=t.evidence, src=t.source_policy_id,
            )
            n += 1
    return n


def trace_supersede_chain(policy_id: str, driver=None) -> list[dict]:
    """时效维多跳：沿 SUPERSEDES 追溯废止链。返回 [{from, to, evidence}]。"""
    driver = driver or get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH path = (p:Policy {id: $pid})-[:SUPERSEDES*1..5]->(newest:Policy)
            WHERE NOT (newest)-[:SUPERSEDES]->()
            RETURN [r IN relationships(path) | {from: startNode(r).id, to: endNode(r).id,
                    evidence: r.evidence}] AS chain, newest.id AS current
            """,
            pid=policy_id,
        )
        rows = [{"chain": r["chain"], "current_policy": r["current"]} for r in result]
    return rows


def find_conflicts(subsidy_id: str, driver=None) -> list[dict]:
    """冲突维：该事项的所有互斥事项及依据。"""
    driver = driver or get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s:Subsidy {id: $sid})-[c:CONFLICTS_WITH]-(other:Subsidy)
            RETURN other.id AS conflict_with, c.evidence AS evidence
            """,
            sid=subsidy_id,
        )
        return [{"conflict_with": r["conflict_with"], "evidence": r["evidence"]} for r in result]


def match_policies_for(enterprise: dict, driver=None) -> list[dict]:
    """推理主查询：企业画像 -> 可申 Subsidy + 政策文号 + 原文依据。

    TODO(v0.2): Condition 字段化谓词下推到 Cypher（field/op/value 动态拼接 + 参数化），
    当前先按 APPLIES_TO 类别匹配（行业/规模/资质/区域）。
    """
    driver = driver or get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s:Subsidy)-[:APPLIES_TO]->(cat)
            MATCH (p:Policy)-[:HAS_SUBSIDY]->(s)
            WHERE cat.id IN $categories
              AND p.status = '现行有效'
            OPTIONAL MATCH (s)-[c:CONFLICTS_WITH]-(other:Subsidy)
            RETURN s.id AS subsidy_id, s.title AS title, p.id AS policy_id,
                   collect(DISTINCT other.id) AS conflicts,
                   'TODO: evidence' AS evidence
            """,
            categories=_enterprise_categories(enterprise),
        )
        return [dict(r) for r in result]


def _enterprise_categories(ent: dict) -> list[str]:
    """企业画像 -> 图谱中的类别节点 ID（与抽取侧 APPLIES_TO 的 object_id 规范对齐）。"""
    cats = []
    if ent.get("industry_gb_code"):
        cats.append(f"行业:{ent['industry_gb_code']}")
    if ent.get("size"):
        cats.append(f"规模:{ent['size']}")
    for q in ent.get("qualifications", []):
        cats.append(f"资质:{q}")
    if ent.get("region_code"):
        cats.append(f"区域:{ent['region_code']}")
    for t in ent.get("themes", []):
        cats.append(f"主题:{t}")
    return cats
