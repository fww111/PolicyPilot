"""创新 A：政策数据资产目录（docs/08-G3）——"沉睡资产激活"的具象化。

赛题题眼："数据资产认知智能体"“挖掘行业沉睡存量数据资产”“资产标识"。
本模块把全 pipeline 的数据物登记为资产台账：

  资产类型：raw_policy(原始文件) / parsed_doc(解析正文) / triple(三元组)
            / graph(图谱) / benchmark(评测集) / feedback(复核反馈)
  资产状态：dormant(沉睡) / parsed(已解析) / structured(已结构化) / serving(服务中)
  血缘：raw --解析--> parsed --抽取--> triple --入图--> graph --服务--> 回答

产出：data/asset_catalog.json（台账）+ 唤醒漏斗统计（沉睡→服务中的转化率）。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "data" / "asset_catalog.json"


def _aid(kind: str, key: str) -> str:
    return f"AST-{kind[:3].upper()}-{hashlib.md5(key.encode()).hexdigest()[:8]}"


def build_catalog() -> dict:
    assets: list[dict] = []

    # ---- 原始政策文件（沉睡 → 已解析）----
    raw_files = sorted((ROOT / "data/raw").glob("*.html"))
    triples_by_file: dict[str, list] = {}
    kg_path = ROOT / "data/kg/b1_triples.json"
    if kg_path.exists():
        for r in json.loads(kg_path.read_text(encoding="utf-8")):
            triples_by_file[r["file_id"]] = r["triples"]

    graph_edges = 0
    mg = ROOT / "data/kg/memory_graph.json"
    if mg.exists():
        g = json.loads(mg.read_text(encoding="utf-8"))
        graph_edges = len(g.get("edges", []))

    for f in raw_files:
        fid = f.stem
        has_text = f.stat().st_size > 5000
        has_triples = fid in triples_by_file and triples_by_file[fid]
        assets.append({
            "asset_id": _aid("raw", fid),
            "kind": "raw_policy",
            "name": fid[:50],
            "file": f.name,
            "format": "html",
            "status": "structured" if has_triples else ("parsed" if has_text else "dormant"),
            "n_triples": len(triples_by_file.get(fid, [])),
            "lineage": {"stage": "raw→parsed→structured", "graph_edges_contributed": len(triples_by_file.get(fid, []))},
        })

    # ---- 图谱（服务中）----
    if mg.exists():
        assets.append({
            "asset_id": _aid("kg", "memory_graph"),
            "kind": "knowledge_graph",
            "name": "政策知识图谱（memory 引擎）",
            "status": "serving",
            "n_nodes": len(g.get("nodes", [])),
            "n_edges": graph_edges,
            "lineage": {"stage": "structured→graph→serving", "serves": ["query_policy_graph", "check_policy_validity", "check_eligibility"]},
        })

    # ---- 评测基准 ----
    bench = ROOT / "data/eval/benchmark.json"
    if bench.exists():
        n = len(json.loads(bench.read_text(encoding="utf-8")))
        assets.append({
            "asset_id": _aid("bench", "policybench"),
            "kind": "benchmark",
            "name": f"PolicyBench 评测基准（{n} 题）",
            "status": "serving",
            "n_items": n,
            "lineage": {"stage": "graph→benchmark", "serves": ["E1/E2 实验", "智能体评估"]},
        })

    # ---- 复核反馈 ----
    fb = ROOT / "data/feedback/review_log.jsonl"
    if fb.exists():
        n = len([x for x in fb.read_text(encoding="utf-8").splitlines() if x.strip()])
        assets.append({
            "asset_id": _aid("fb", "review_log"),
            "kind": "human_feedback",
            "name": "复核反馈库（进化燃料）",
            "status": "serving",
            "n_records": n,
            "lineage": {"stage": "review→strategy_v2", "serves": ["review_loop v2 策略约束"]},
        })

    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "assets": assets}


def funnel(assets: list[dict]) -> dict:
    """唤醒漏斗：沉睡 → 已解析 → 已结构化 → 服务中。"""
    raw = [a for a in assets if a["kind"] == "raw_policy"]
    stages = {"dormant": 0, "parsed": 0, "structured": 0}
    for a in raw:
        stages[a["status"]] = stages.get(a["status"], 0) + 1
    total = max(len(raw), 1)
    serving = stages["structured"]
    return {
        "raw_total": len(raw),
        "dormant": stages["dormant"],
        "parsed": stages["parsed"],
        "structured": stages["structured"],
        "awakening_rate": round(serving / total, 4),
        "note": "awakening_rate = 沉睡文件中被激活为图谱知识（可服务）的占比",
    }


if __name__ == "__main__":
    catalog = build_catalog()
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    f = funnel(catalog["assets"])
    print(f"资产台账: {len(catalog['assets'])} 项 -> {OUT.name}")
    by_kind: dict = {}
    for a in catalog["assets"]:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
    print("按类型:", by_kind)
    print("唤醒漏斗:", json.dumps(f, ensure_ascii=False, indent=2))
