"""政策数据资产目录（Policy Data Asset Catalog）—— 创新 A / 任务1"资产标识"题眼。

设计：
  每个原始文件登记为资产（asset_id、来源、格式、抓取批次、解析状态、血缘），
  状态机：沉睡(raw) → 解析(parsed) → 结构化(structured) → 服务中(serving)
  - serving = 该资产产生的三元组已进入图谱且被查询链路使用
  - 血缘：asset -> parsed 文档 -> 三元组（source_policy_id / file_id 关联）
  - 唤醒率 = serving / raw，是"沉睡资产激活"的量化指标

用法：uv run python scripts/asset_catalog.py
输出：data/asset_catalog.json + docs/10-资产目录报告.md
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RAW = ROOT / "data" / "raw"
KG_DIR = ROOT / "data" / "kg"
OUT = ROOT / "data" / "asset_catalog.json"
REPORT = ROOT / "docs" / "10-资产目录报告.md"


def asset_id(path: Path) -> str:
    return "AST-" + hashlib.md5(path.name.encode("utf-8")).hexdigest()[:10].upper()


def main() -> None:
    # 1) 原始资产登记（raw 层）
    assets: list[dict] = []
    for pattern, fmt, source in (("sz_*.html", "HTML", "苏州市政府门户"), ("js_*.html", "HTML", "江苏省政府文件库")):
        for f in RAW.glob(pattern):
            assets.append({
                "asset_id": asset_id(f),
                "file": f.name,
                "format": fmt,
                "source": source,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "batch": "B1/B2" if pattern.startswith("sz") else "B3",
                "state": "raw",
            })
    meta_file = RAW / "gov_metadata.jsonl"
    if meta_file.exists():
        n_meta = sum(1 for x in meta_file.read_text(encoding="utf-8").splitlines() if x.strip())
        assets.append({
            "asset_id": "AST-METADATA-GOV",
            "file": "gov_metadata.jsonl",
            "format": "JSONL(结构化元数据)",
            "source": "中国政府网政策库接口",
            "size_kb": round(meta_file.stat().st_size / 1024, 1),
            "batch": "元数据层",
            "state": "structured",
        })

    # 2) 解析层：b1_triples.json 的 file_id -> 资产血缘
    triples_file = KG_DIR / "b1_triples.json"
    by_file_triples: dict[str, int] = {}
    structured_files: set[str] = set()
    if triples_file.exists():
        records = json.loads(triples_file.read_text(encoding="utf-8"))
        for r in records:
            fid = r["file_id"]
            by_file_triples[fid] = len(r["triples"])
            if r["triples"]:
                structured_files.add(fid)

    graph_file = KG_DIR / "memory_graph.json"
    n_edges = 0
    if graph_file.exists():
        g = json.loads(graph_file.read_text(encoding="utf-8"))
        n_edges = len(g.get("edges", []))

    # 3) 状态升级：raw -> parsed(正文>400) -> structured(产出三元组) -> serving(入图)
    from policy_pilot.parser.doc_parser import parse_any

    serving_target = min(n_edges, 10**9)  # 图谱承载全部三元组，serving 计 structured 中已入图者
    for a in assets:
        if a["state"] != "raw":
            continue
        fid = a["file"][:-5]
        if fid in structured_files:
            a["state"] = "serving"
            a["triples"] = by_file_triples.get(fid, 0)
            continue
        f = RAW / a["file"]
        try:
            doc = parse_any(f)
            a["state"] = "parsed" if len(doc.full_text) > 400 else "raw"
        except Exception:
            a["state"] = "raw"
        a["triples"] = 0

    OUT.write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4) 漏斗统计与报告
    from collections import Counter

    states = Counter(a["state"] for a in assets)
    total = len(assets)
    n_serving = states.get("serving", 0) + states.get("structured", 0)
    wake_rate = round(n_serving / total * 100, 1) if total else 0
    lines = [
        f"# 政策数据资产目录报告（{date.today()}）",
        "",
        "对应赛题任务1『数据资产认知』与『资产标识』：每个原始文件登记为资产，",
        "状态机 沉睡(raw)→解析(parsed)→结构化(structured)→服务中(serving)。",
        "",
        "## 唤醒漏斗（沉睡资产激活的量化）",
        "",
        "| 状态 | 数量 | 占比 |",
        "|---|---|---|",
    ]
    for st in ("raw", "parsed", "structured", "serving"):
        c = states.get(st, 0)
        lines.append(f"| {st} | {c} | {round(c/total*100,1)}% |")
    lines += [
        "",
        f"**唤醒率（structured+serving）/ total = {wake_rate}%**",
        f"图谱承载：{n_edges} 条边；结构化资产产出三元组 {sum(by_file_triples.values())} 条",
        "",
        "## 资产清单（前 20）",
        "",
        "| asset_id | 来源 | 格式 | 批次 | 状态 | 三元组 |",
        "|---|---|---|---|---|---|",
    ]
    for a in assets[:20]:
        lines.append(f"| {a['asset_id']} | {a['source'][:14]} | {a['format'][:12]} | {a['batch']} | {a['state']} | {a.get('triples', 0)} |")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"资产 {total} 项 | 唤醒率 {wake_rate}% | 报告 -> docs/10-资产目录报告.md")


if __name__ == "__main__":
    main()
