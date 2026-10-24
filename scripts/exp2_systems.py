"""四系统全量评测跑批（实验2）—— docs/01 第七节实验矩阵的执行器。

用法：
  冒烟（每题型2题，验证管线）：uv run python scripts/exp2_systems.py smoke
  全量（B2+人工校对后）：    uv run python scripts/exp2_systems.py full

指标：multi_hop 题型 -> 集合 P/R/F1 + 溯源命中率；validity -> 准确率。
系统：pure_rag / pure_graph / naive_dual / cross_validated（agent/runners.py）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from policy_pilot.agent.cross_validation import Verdict  # noqa: E402
from policy_pilot.agent.runners import get_runner  # noqa: E402
from policy_pilot.graph.memory_engine import MemoryGraphStore  # noqa: E402
from policy_pilot.parser.doc_parser import parse_any  # noqa: E402


def build_corpus() -> dict[str, str]:
    """全语料 {政策名: 正文}（RAG 系统的检索池）。"""
    corpus = {}
    for f in (ROOT / "data/raw").glob("sz_*.html"):
        doc = parse_any(f)
        if len(doc.full_text) > 400:
            corpus[doc.source_file[3:-5][:30]] = doc.full_text
    # 元数据层摘要入池（国家/部委政策可检索）
    meta = ROOT / "data/raw/gov_metadata.jsonl"
    if meta.exists():
        import json as _json
        for line in meta.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = _json.loads(line)
                if r.get("summary"):
                    corpus[r["pcode"]] = r["title"] + chr(10) + r["summary"]
    return corpus


def policy_key(s: str) -> str:
    """政策级归一：去掉事项编号和书名号（评测公平性：RAG 无编号体系）。"""
    return str(s).split("#")[0].replace("《", "").replace("》", "").replace("苏州市", "")


def set_scores(pred: list[str], gold: list[str]) -> dict:
    """双层评分：policy 级（宽松，各系统可比）+ subsidy 级（严格，图谱体系内）。"""
    def prf(ps, gs):
        tp = len(ps & gs)
        p = tp / len(ps) if ps else 0.0
        r = tp / len(gs) if gs else 0.0
        return round(2 * p * r / (p + r), 4) if p + r else 0.0
    return {
        "f1": prf({policy_key(x) for x in pred}, {policy_key(x) for x in gold}),  # 报告口径：政策级
        "f1_subsidy": prf(set(pred), set(gold)),  # 严格口径另存
    }


def cite_hit(answer_evidences: list[str], gold_policy_ids: list[str]) -> bool:
    return any(any(g and g in e for g in gold_policy_ids) for e in answer_evidences)


def eval_multi_hop(items: list[dict], corpus: dict, systems: list[str], limit: int) -> dict:
    store = MemoryGraphStore.load()
    results = {s: {"f1": [], "cite": [], "refused": 0, "detail": []} for s in systems}
    for it in items[:limit]:
        for sname in systems:
            runner = get_runner(sname, store)
            try:
                ans = runner.answer(it["question"], it.get("enterprise", {}), corpus)
            except Exception as e:
                results[sname]["detail"].append({"item": it["item_id"], "error": str(e)[:80]})
                continue
            sc = set_scores(ans.ids, it["gold_ids"])
            results[sname]["f1"].append(sc["f1"])
            results[sname]["cite"].append(cite_hit(ans.evidences, it["gold_policy_ids"]))
            results[sname]["refused"] += ans.refused
            results[sname]["detail"].append({
                "item": it["item_id"], "f1": sc["f1"], "refused": ans.refused,
                "verdict": ans.detail[:24], "n_pred": len(ans.ids), "n_gold": len(it["gold_ids"]),
            })
    return results


def summarize(results: dict, elapsed: dict) -> None:
    print("\n===== 实验2：四系统对比（multi_hop） =====")
    print(f"{'系统':<16} {'F1政策级':>9} {'溯源命中':>8} {'拒答数':>6} {'耗时s':>7}")
    for s, r in results.items():
        f1 = sum(r["f1"]) / len(r["f1"]) if r["f1"] else 0
        cite = sum(r["cite"]) / len(r["cite"]) if r["cite"] else 0
        print(f"{s:<16} {f1:>8.3f} {cite:>8.0%} {r['refused']:>6} {elapsed.get(s, 0):>7.1f}")


def main(mode: str = "smoke") -> None:
    bench = json.loads((ROOT / "data/eval/benchmark.json").read_text(encoding="utf-8"))
    multi = [x for x in bench if x["q_type"] == "multi_hop"]
    print(f"评测集: {len(bench)} 题 | multi_hop {len(multi)} 题 | 模式: {mode}")
    limit = 2 if mode == "smoke" else len(multi)
    corpus = build_corpus()
    print(f"RAG 检索池: {len(corpus)} 份全文")
    systems = ["pure_rag", "pure_graph", "naive_dual", "cross_validated"]
    t_all = time.time()
    elapsed = {}
    results = {}
    for s in systems:
        t0 = time.time()
        # 逐系统跑（避免 interleaving 计时干扰）
        results[s] = eval_multi_hop(multi, corpus, [s], limit)[s]
        elapsed[s] = time.time() - t0
    summarize(results, elapsed)
    print(f"总耗时 {time.time() - t_all:.0f}s")
    out = ROOT / "data/eval/exp2_smoke.json" if mode == "smoke" else ROOT / "data/eval/exp2_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细 -> {out.name}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "smoke")
