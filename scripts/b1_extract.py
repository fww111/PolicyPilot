"""B1 批次实验：全量抽取现有政策语料，产出三件套。

产出：
  1. data/kg/b1_triples.json      全部三元组（含置信度/证据/来源）
  2. data/kg/human_review_queue.jsonl  低置信(<0.75)人工复核队列
  3. docs/04-B1人工校验表.md       全量人工校验清单（对/错/改 三列，量化人工工作量的载体）

用法：cd PolicyPilot && uv run python scripts/b1_extract.py
失败自动续跑：跳过已完成文件（b1_triples.json 里已有的 file_id）。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from policy_pilot.extraction.triple_extractor import (  # noqa: E402
    CONFIDENCE_THRESHOLD,
    append_review_queue,
    extract_triples,
    split_by_confidence,
)
from policy_pilot.parser.doc_parser import parse_any  # noqa: E402

KG_DIR = ROOT / "data" / "kg"
OUT_JSON = KG_DIR / "b1_triples.json"


def load_done() -> dict:
    if OUT_JSON.exists():
        return {r["file_id"]: r for r in json.loads(OUT_JSON.read_text(encoding="utf-8"))}
    return {}


def main() -> None:
    from policy_pilot.ontology.policy_ontology import Triple

    KG_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted((ROOT / "data" / "raw").glob("sz_*.html")) + sorted((ROOT / "data" / "raw").glob("js_*.html"))
    results = load_done()
    print(f"语料 {len(files)} 份 | 已完成 {len(results)} 份，开始增量抽取...")
    for i, f in enumerate(files, 1):
        fid = f.stem
        if fid in results:
            continue
        doc = parse_any(f)
        if len(doc.full_text) < 400:
            print(f"[{i:02d}] 跳过(正文不足): {fid[:40]}")
            continue
        try:
            r = extract_triples(doc.full_text, file_id=fid)
        except Exception as e:
            print(f"[{i:02d}] 失败 {fid[:36]}: {type(e).__name__}: {str(e)[:60]}")
            time.sleep(5)
            continue
        auto, review = split_by_confidence(r)
        results[fid] = {
            "file_id": fid,
            "source_file": f.name,
            "model": r.model,
            "latency_s": r.latency_s,
            "usage_tokens": r.usage_tokens,
            "invalid_items": r.invalid_items,
            "triples": [t.model_dump(mode="json") for t in r.triples],
        }
        OUT_JSON.write_text(json.dumps(list(results.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[{i:02d}/{len(files)}] {fid[:34]} -> {len(r.triples)}条 "
            f"(自动{len(auto)}/复核{len(review)}) {r.latency_s}s"
        )
    # 汇总 + 生成校验表
    all_triples = [t for r in results.values() for t in r["triples"]]
    low = [t for t in all_triples if t.get("confidence", 1.0) < CONFIDENCE_THRESHOLD]
    total_tokens = sum(r["usage_tokens"] for r in results.values())
    total_min = round(sum(r["latency_s"] for r in results.values()) / 60, 1)
    print("\n===== B1 批次汇总 =====")
    print(f"文件数: {len(results)} | 三元组: {len(all_triples)} | 低置信: {len(low)}")
    print(f"总tokens: {total_tokens} | 总耗时: {total_min}min | 阈值: {CONFIDENCE_THRESHOLD}")

    append_review_queue([Triple.model_validate(t) for t in low], KG_DIR)
    (KG_DIR / "human_review_queue.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in low), encoding="utf-8"
    )
    write_checklist(results, all_triples)


def write_checklist(results: dict, all_triples: list[dict]) -> None:
    lines = [
        f"# B1 人工校验表（{date.today()}）",
        "",
        "> 每条三元组人工判定：正确✓ / 错误✗ / 需改（在修正列写正确值）。",
        "> 统计：总条数 N，人工耗时 M 分钟 —— 这是'半自动 vs 纯人工'成本对比的分母。",
        "",
        "| # | 来源文件 | 主语 | 关系 | 宾语 | 置信 | 证据摘录 | 判定 | 修正 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, t in enumerate(all_triples, 1):
        ev = (t.get("evidence") or "").replace("|", "/").replace("\n", " ")[:40]
        lines.append(
            f"| {i} | {t.get('source_policy_id','')[:16]} | {t['subject_id'][:20]} "
            f"| {t['relation']} | {t['object_id'][:24]} | {t.get('confidence',0):.2f} | {ev} | | |"
        )
    (ROOT / "docs" / "04-B1人工校验表.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"校验表已生成: docs/04-B1人工校验表.md ({len(all_triples)} 条待人工判定)")


if __name__ == "__main__":
    main()
