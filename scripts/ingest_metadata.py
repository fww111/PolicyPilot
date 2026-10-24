"""元数据层入图：gov.cn 结构化元数据 -> 三元组（不经 LLM，零成本零幻觉）。

这是"多模态异构数据统一识别"的结构化示范层：
  API 元数据直接产出 Policy 实体 + ISSUED_BY（机关）+ BELONGS_TO（主题分类）关系，
  与 LLM 抽取层（苏州全文）在同一张图谱上融合。

用法：uv run python scripts/ingest_metadata.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policy_pilot.graph.memory_engine import MemoryGraphStore  # noqa: E402
from policy_pilot.ontology.policy_ontology import RelationType, Triple  # noqa: E402

SRC = ROOT / "data" / "raw" / "gov_metadata.jsonl"


def main() -> None:
    records = [json.loads(x) for x in SRC.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"读取元数据 {len(records)} 条")

    store = MemoryGraphStore.load()  # 与全文层图谱融合
    n_before = store.g.number_of_edges()
    triples: list[Triple] = []
    for r in records:
        pid = r["pcode"]
        if not pid:
            continue
        # Policy -> 发布机关
        if r.get("puborg"):
            triples.append(Triple(subject_id=pid, subject_type="Policy",
                                  relation=RelationType.ISSUED_BY, object_id=r["puborg"],
                                  object_type="Department", confidence=1.0,
                                  evidence=f"接口元数据：发布机关={r['puborg']}", source_policy_id=pid))
        # Policy -> 主题分类（BELONGS_TO：层级维，主题即分类体系节点）
        theme = (r.get("theme") or "").split("\\")[0].strip()
        if theme:
            triples.append(Triple(subject_id=pid, subject_type="Policy",
                                  relation=RelationType.BELONGS_TO, object_id=f"主题:{theme}",
                                  object_type="Policy", confidence=1.0,
                                  evidence=f"接口元数据：主题分类={theme}", source_policy_id=pid))
    n = store.upsert_triples(triples)
    path = store.save()
    dist = Counter(d["relation"] for _, _, d in store.g.edges(data=True))
    print(f"入图 {n} 条边（元数据层），图总计 {store.g.number_of_nodes()} 节点 / {store.g.number_of_edges()} 边")
    print("关系分布:", dict(dist.most_common()))

    # 主题节点可作 PPR 种子扩展验证：金融类企业画像匹配
    ent = {"industry_name": "财政", "size": "小型", "qualifications": [], "region_code": "3205"}
    hits = store.match_policies_for(ent, top_k=5)
    print(f"验证（主题种子'财政'）: 匹配 {len(hits)} 条")
    for h in hits[:3]:
        print(f"  {h['subsidy_id'][:30]} score={h['match_score']:.4f}")
    print(f"已保存 {path.name}")


if __name__ == "__main__":
    main()
