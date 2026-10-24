"""创新 D：本体增量演化实验（docs/08-G4）——赛题"本体持续动态更新"的实证。

设计：把 B3 的 152 份抽取记录按采集顺序分 5 批重放，每批后统计本体 schema 的
累计元素（实体类型 / 关系类型 / Condition 字段），输出收敛曲线——
证明：① 新政策入库会自动发现新 schema 元素（新增侧演化）；② schema 趋于稳定
（后期批次新增收敛），说明本体设计合理且演化可控。

产出：docs/06 实验数据 JSON + 控制台收敛表。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = ROOT / "data/kg/b1_triples.json"
OUT = ROOT / "data/eval/exp4_ontology_evolution.json"


def schema_signature(records: list[dict]) -> dict:
    """当前批次的 schema 元素集合。"""
    entity_types: Counter = Counter()
    rel_types: Counter = Counter()
    cond_fields: set = set()
    for r in records:
        for t in r["triples"]:
            entity_types[t["subject_type"]] += 1
            entity_types[t["object_type"]] += 1
            rel_types[t["relation"]] += 1
            oid = t.get("object_id", "")
            if "field=" in oid:  # Condition 节点携带 field 信息
                import re
                m = re.search(r"field=(\w+)", oid)
                if m:
                    cond_fields.add(m.group(1))
    return {"entity_types": dict(entity_types), "rel_types": dict(rel_types), "cond_fields": sorted(cond_fields)}


def diff_schema(prev: dict, curr: dict) -> dict:
    """新增侧 diff：本批引入的新 schema 元素。"""
    def new_keys(prev_d: dict, curr_d: dict):
        return sorted(set(curr_d) - set(prev_d))
    return {
        "new_entity_types": new_keys(prev["entity_types"], curr["entity_types"]),
        "new_rel_types": new_keys(prev["rel_types"], curr["rel_types"]),
        "new_cond_fields": sorted(set(curr["cond_fields"]) - set(prev["cond_fields"])),
        "new_total": len(new_keys(prev["entity_types"], curr["entity_types"]))
        + len(new_keys(prev["rel_types"], curr["rel_types"]))
        + len(set(curr["cond_fields"]) - set(prev["cond_fields"])),
    }


def main() -> None:
    records = json.loads(SRC.read_text(encoding="utf-8"))
    # 只保留有产出的记录，按文件序稳定分 5 批
    records = [r for r in records if r["triples"]]
    n_batches = 5
    size = (len(records) + n_batches - 1) // n_batches
    batches = [records[i * size : (i + 1) * size] for i in range(n_batches)]
    batches = [b for b in batches if b]

    print(f"重放 {len(records)} 份 -> {len(batches)} 批（每批 ~{size} 份）")
    rows, prev_sig = [], {"entity_types": {}, "rel_types": {}, "cond_fields": []}
    cum_records: list[dict] = []
    for bi, batch in enumerate(batches, 1):
        cum_records.extend(batch)
        curr_sig = schema_signature(cum_records)
        d = diff_schema(prev_sig, curr_sig)
        rows.append({
            "batch": bi,
            "files": len(batch),
            "cum_files": len(cum_records),
            "triples": sum(len(r["triples"]) for r in cum_records),
            "entity_types": len(curr_sig["entity_types"]),
            "rel_types": len(curr_sig["rel_types"]),
            "cond_fields": len(curr_sig["cond_fields"]),
            "new_this_batch": d["new_total"],
            "new_detail": d,
        })
        prev_sig = curr_sig
        print(f"  批{bi}: 累计{len(cum_records)}份 | 实体类型{rows[-1]['entity_types']} "
              f"关系类型{rows[-1]['rel_types']} 条件字段{rows[-1]['cond_fields']} "
              f"| 本批新增schema元素: {d['new_total']} {d['new_rel_types'] or d['new_entity_types'] or ''}")

    first, last = rows[0], rows[-1]
    print("\n===== 本体演化结论 =====")
    print(f"实体类型: {first['entity_types']} -> {last['entity_types']} | "
          f"关系类型: {first['rel_types']} -> {last['rel_types']} | "
          f"条件字段: {first['cond_fields']} -> {last['cond_fields']}")
    print(f"新增收敛: {[r['new_this_batch'] for r in rows]}（后期趋缓 = 本体趋于稳定）")
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"数据 -> {OUT.name}")


if __name__ == "__main__":
    main()
