"""建图：B1 抽取结果 -> 内存图谱（后续切 Neo4j 同接口）。

用法：uv run python scripts/build_graph.py
幂等：重复跑会全量重建（load b1_triples.json -> upsert -> save）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policy_pilot.graph.memory_engine import MemoryGraphStore  # noqa: E402
from policy_pilot.ontology.policy_ontology import Triple  # noqa: E402

KG = ROOT / "data" / "kg" / "b1_triples.json"


def main() -> None:
    if not KG.exists():
        print("无 b1_triples.json，先跑 scripts/b1_extract.py")
        return
    results = json.loads(KG.read_text(encoding="utf-8"))
    store = MemoryGraphStore()
    n_files, n_triples = 0, 0
    for r in results:
        triples = [Triple.model_validate(t) for t in r["triples"]]
        if not triples:
            continue
        n_files += 1
        n_triples += store.upsert_triples(triples)

    # 本体对齐：cond_ 前缀条件节点规范化为类别节点（行业:/资质:/区域:）
    # TODO(W2-B2): 在 ONTOLOGY_PROMPT 源头规范 APPLIES_TO 指向，本层保留为兜底
    import networkx as nx

    from policy_pilot.ontology.gb4754 import normalize_industry

    mapping = {}
    for n in list(store.g.nodes):
        if n.startswith("cond_industry_"):
            mapping[n] = f"行业:{n[len('cond_industry_'):]}"
        elif n.startswith("cond_qual_"):
            mapping[n] = f"资质:{n[len('cond_qual_'):]}"
        elif n.startswith("cond_region_"):
            mapping[n] = f"区域:{n[len('cond_region_'):]}"
    # GB/T 4754 国标对齐：自由行业类别节点归一到国标名（与画像侧同规范）
    # 注意先应用前序 cond_ 映射得到当前名，再做归一判断
    for n in list(store.g.nodes):
        current = mapping.get(n, n)
        if isinstance(current, str) and current.startswith("行业:"):
            norm = normalize_industry(current.split(":", 1)[1])
            if norm and len(norm[1]) > 2 and f"行业:{norm[1]}" != current:
                mapping[n] = f"行业:{norm[1]}"
    nx.relabel_nodes(store.g, mapping, copy=False)
    path = store.save()
    print(f"入图: {n_files} 份文件 -> {store.g.number_of_nodes()} 节点 / {n_triples} 边，已存 {path.name}")

    # 概览统计：关系类型分布
    from collections import Counter

    dist = Counter(d["relation"] for _, _, d in store.g.edges(data=True))
    print("关系分布:", dict(dist.most_common()))

    # 示例查询 1：互斥
    subsidies = [n for n, t in store.g.nodes(data=True) if t.get("type") == "Subsidy"]
    for s in subsidies[:2]:
        cf = store.find_conflicts(s)
        print(f"互斥查询 {s[-18:]}: {cf if cf else '(无)'}")

    # 示例查询 2：PPR 匹配（文旅行业小企业画像）
    ent = {"industry_name": "旅游业", "size": "小型", "qualifications": [], "region_code": "320508"}
    hits = store.match_policies_for(ent)
    print(f"PPR匹配(旅游业/小型): {[(h['subsidy_id'][-14:], round(h['match_score'], 3)) for h in hits[:5]]}")

    # 示例查询 3：废止链（若数据含 SUPERSEDES）
    sup = [u for u, _, d in store.g.edges(data=True) if d["relation"] == "SUPERSEDES"]
    print(f"SUPERSEDES 边: {len(sup)} 条", store.trace_supersede_chain(sup[0]) if sup else "(暂无数据)")


if __name__ == "__main__":
    main()
