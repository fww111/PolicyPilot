"""内存图引擎（networkx）—— Neo4j 的轻量替身与低资源部署形态。

设计动机：
  1. 开发期不被 Docker/内存问题卡死（16GB 本机跑 Nexent 全家桶时 Neo4j 常挤不下）
  2. 意外收获：零依赖轻量引擎 = "Skill 模板轻量化迁移"附加分的技术载体
     （迁到新城市/新行业：换数据不换引擎，pip 装个 networkx 就能跑）
  3. personalized PageRank 匹配：HippoRAG 2 思想的轻量落地——以企业画像类别节点
     为种子沿关系边扩散，替代朴素一跳标签匹配，天然支持多跳关联发现。

接口与 graph_store（Neo4j）对齐，通过 GRAPH_ENGINE=memory|neo4j 切换。
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from policy_pilot.ontology.policy_ontology import Triple

KG_DIR = Path(__file__).resolve().parents[3] / "data" / "kg"
PERSIST_PATH = KG_DIR / "memory_graph.json"


class MemoryGraphStore:
    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()

    # ---------------------------------------------------------------- 写入

    def upsert_triples(self, triples: list[Triple], valid_at: str | None = None) -> int:
        """入图时给每条边打双时间戳（Graphiti 思想）：
        valid_at=事实生效日（政策施行日），created_at=入图时间。
        失效边不删除，只追加 invalid_at（审计轨迹 + point-in-time 查询）。
        """
        from datetime import date as _d

        n = 0
        now = _d.today().isoformat()
        for t in triples:
            self.g.add_node(t.subject_id, type=t.subject_type)
            self.g.add_node(t.object_id, type=t.object_type)
            self.g.add_edge(
                t.subject_id,
                t.object_id,
                key=t.relation.name,
                relation=t.relation.name,
                relation_cn=t.relation.value,
                confidence=t.confidence,
                evidence=t.evidence,
                source=t.source_policy_id,
                valid_at=valid_at or now,
                created_at=now,
                invalid_at=None,
            )
            n += 1
        return n

    def invalidate_policy_edges(self, policy_id: str, reason: str) -> dict:
        """创新点③核心：政策废止 → 该政策的边批量失效（非删除），返回影响面报告。

       SUPERSEDES 边建立后调用：旧政策的 HAS_SUBSIDY/APPLIES_TO 等出边
        全部打 invalid_at；后续查询自动跳过，但历史问题仍可回溯。
        """
        from datetime import date as _d

        now = _d.today().isoformat()
        invalidated: list[dict] = []

        def _kill_out_edges(node: str) -> list[str]:
            """失效节点全部出边，返回其中的 Subsidy 节点（用于级联）。"""
            subs = []
            for _, v, k, d in list(self.g.out_edges(node, keys=True, data=True)):
                if d.get("invalid_at") is None and d["relation"] != "SUPERSEDES":
                    d["invalid_at"] = now
                    d["invalid_reason"] = reason
                    invalidated.append({"edge": f"{node} -[{d['relation']}]-> {v}", "object": v})
                    if self.g.nodes[v].get("type") == "Subsidy":
                        subs.append(v)
            return subs

        # 级联失效：政策出边 -> 其 Subsidy 的出边（事项随政策废止而失效）
        for sub in _kill_out_edges(policy_id):
            _kill_out_edges(sub)
        impacted_subsidies = [
            i["object"] for i in invalidated if self.g.nodes.get(i["object"], {}).get("type") == "Subsidy"
        ]
        return {
            "policy_id": policy_id,
            "reason": reason,
            "invalidated_at": now,
            "invalidated_edges": len(invalidated),
            "impacted_subsidies": impacted_subsidies,
        }

    # ---------------------------------------------------------------- 查询

    def _active(self) -> "nx.MultiDiGraph":
        """只含未失效边的图副本（invalid_at 为空的边）。"""
        h = nx.MultiDiGraph()
        h.add_nodes_from(self.g.nodes(data=True))
        for u, v, k, d in self.g.edges(keys=True, data=True):
            if d.get("invalid_at") is None:
                h.add_edge(u, v, key=k, **d)
        return h

    def trace_supersede_chain(self, policy_id: str) -> list[dict]:
        """时效维：沿 SUPERSEDES 追溯到最新现行版本（跳过失效边）。"""
        g = self._active()
        cur, chain, seen = policy_id, [], set()
        while cur not in seen:
            seen.add(cur)
            nexts = [
                (v, d) for _, v, d in g.out_edges(cur, data=True) if d["relation"] == "SUPERSEDES"
            ]
            if not nexts:
                break
            v, d = max(nexts, key=lambda x: x[1]["confidence"])
            chain.append({"from": cur, "to": v, "evidence": d.get("evidence", "")})
            cur = v
        return [{"chain": chain, "current_policy": cur if chain else policy_id}]

    def find_conflicts(self, subsidy_id: str) -> list[dict]:
        """冲突维：双向找互斥事项（跳过失效边）。"""
        g = self._active()
        out = []
        for _, v, d in g.out_edges(subsidy_id, data=True):
            if d["relation"] == "CONFLICTS_WITH":
                out.append({"conflict_with": v, "evidence": d.get("evidence", "")})
        for u, _, d in g.in_edges(subsidy_id, data=True):
            if d["relation"] == "CONFLICTS_WITH":
                out.append({"conflict_with": u, "evidence": d.get("evidence", "")})
        return out

    def match_policies_for(self, enterprise: dict, top_k: int = 10, target_type: str = "Subsidy") -> list[dict]:
        """推理主查询：personalized PageRank 匹配（HippoRAG 2 机制的领域化落地）。

        种子 = 企业画像类别节点（行业/规模/资质/区域），概率质量只从种子出发
        沿关系边扩散；多条路径可达的 Subsidy 累积更高分数（多跳关联发现），
        替代朴素一跳标签匹配。每个结果附带类别命中路径（溯源证据）。
        """
        cats = _enterprise_categories(enterprise)
        g = self._active()
        seeds = [c for c in cats if c in g]
        if not seeds:
            return []
        # 候选集 = 从种子出发可达（含逆向可达）的闭包：失效边断开可达性后，
        # 对应 Subsidy 自然从候选集中消失（无需额外过滤规则）
        reachable: set[str] = set(seeds)
        for c in seeds:
            reachable |= nx.descendants(g, c) | nx.ancestors(g, c)
        sub = g.subgraph(reachable)
        # personalization：概率质量均匀分布在种子节点上（HippoRAG 2 的 query-seed PPR）
        undirected = sub.to_undirected(as_view=True)
        nodes = list(undirected.nodes)
        pers = {n: (1.0 / len(seeds) if n in seeds else 0.0) for n in nodes}
        pr = nx.pagerank(undirected, alpha=0.85, personalization=pers, weight=None)
        seed_set = set(seeds)
        ranked = [
            (n, s) for n, s in pr.items() if g.nodes[n].get("type") == target_type and n not in seed_set
        ]
        ranked.sort(key=lambda x: -x[1])
        results = []
        for node, score in ranked[:top_k]:
            hit_cats = [c for c in seeds if g.has_edge(node, c) or g.has_edge(c, node)]
            policy = next(
                (u for u, _, d in g.in_edges(node, data=True) if d["relation"] == "HAS_SUBSIDY"),
                node if target_type == "Policy" else "",
            )
            evid = next(
                (d.get("evidence", "") for _, _, d in g.in_edges(node, data=True) if d.get("evidence")),
                "",
            )
            conflicts = [c["conflict_with"] for c in self.find_conflicts(node)]
            results.append(
                {
                    "subsidy_id": node,
                    "title": node.rsplit("#", 1)[-1],
                    "policy_id": policy,
                    "match_score": round(score, 6),
                    "hit_categories": hit_cats,
                    "evidence": evid,
                    "conflicts": conflicts,
                }
            )
        return results

    # ---------------------------------------------------------------- 持久化

    def save(self, path: Path = PERSIST_PATH) -> Path:
        data = nx.node_link_data(self.g)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path = PERSIST_PATH) -> "MemoryGraphStore":
        store = cls()
        if path.exists():
            store.g = nx.node_link_graph(json.loads(path.read_text(encoding="utf-8")))
        return store


def _enterprise_categories(ent: dict) -> list[str]:
    from policy_pilot.ontology.gb4754 import categories_for_match, normalize_industry

    cats = []
    if ent.get("industry_gb_code"):
        code = ent["industry_gb_code"]
        cats.append(f"行业:{code}")
        from policy_pilot.ontology.gb4754 import normalize_industry as _norm
        by_code = _norm(code)
        if by_code:
            cats.append(f"行业:{by_code[1]}")  # 代码->国标名双种子
    if ent.get("industry_name"):
        cats.extend(categories_for_match(ent["industry_name"]))  # 国标归一多路种子
        norm = normalize_industry(ent["industry_name"])
        if norm:
            cats.append(f"行业:{norm[0]}")
    if ent.get("size"):
        cats.append(f"规模:{ent['size']}")
    for q in ent.get("qualifications", []):
        cats.append(f"资质:{q}")
    if ent.get("region_code"):
        cats.append(f"区域:{ent['region_code']}")
    for t in ent.get("themes", []):
        cats.append(f"主题:{t}")
    return cats


def get_store(engine: str | None = None):
    """工厂：GRAPH_ENGINE=memory|neo4j（默认 memory）。

    memory 形态用 load() 从 data/kg/memory_graph.json 恢复图谱
    （常驻 MCP 服务进程启动时加载，重启服务即可刷新数据）。
    """
    import os

    engine = engine or os.getenv("GRAPH_ENGINE", "memory")
    if engine == "neo4j":
        from policy_pilot.graph import graph_store

        return graph_store  # 模块级函数接口
    return MemoryGraphStore.load()
