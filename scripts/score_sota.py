"""LightRAG 评测打分 → SOTA 对比表（docs/09 E2）。

评分口径（自动化近似，人工校对为终版）：
  - multi_hop：政策级 F1（回答中出现的 gold 政策名/文号 集合 vs gold_ids）
  - validity：结论正确性（是否给出正确的废止/失效判断——提及 gold 废止对象）
  - 溯源命中率：回答是否包含 gold_policy_ids 的文号或政策名
  - 拒答/知识截止声明：政务场景 "无法实时查询" 视为无效回答（决策系统不可用）

输出：data/eval/sota_comparison.json + docs/05 追加章节
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def norm_policy_key(s: str) -> str:
    """政策名归一（去书名号/城市前缀/空白）用于子串匹配。"""
    return (str(s).replace("《", "").replace("》", "").replace("苏州市", "")
            .replace("江苏省", "").replace(" ", "").strip())


def hit_policy(answer: str, gold_ids: list[str]) -> list[str]:
    """回答中命中的 gold 政策（文号或政策名子串匹配）。"""
    a = norm_policy_key(answer)
    hits = []
    for g in gold_ids:
        key = norm_policy_key(g)
        if key and key in a:
            hits.append(g)
    return hits


def score_lightrag() -> dict:
    results = json.loads((ROOT / "data/eval/sota_lightrag_results.json").read_text(encoding="utf-8"))
    bench = {x["item_id"]: x for x in json.loads((ROOT / "data/eval/benchmark.json").read_text(encoding="utf-8"))}

    rows, f1s, cite_hits, validity_ok, invalid_answers = [], [], 0, 0, 0
    for r in results:
        it = bench.get(r["item_id"], {})
        ans = str(r.get("answer", ""))
        gold_ids = it.get("gold_policy_ids", [])
        gold_answer = it.get("gold_answer", "")

        # 无效回答判定（知识截止声明 / 拒答 / 无上下文）
        invalid = ("not able" in ans[:80] or "no-context" in ans[:60]
                   or "无法实时查询" in ans or "知识有截止" in ans or ans.strip() == "None")
        if invalid:
            invalid_answers += 1
            rows.append({"item_id": r["item_id"], "q_type": it.get("q_type"),
                         "verdict": "invalid（知识截止声明/拒答）", "f1": 0.0, "cite": False})
            f1s.append(0.0)
            continue

        # 政策级 F1（multi_hop 有集合型 gold_ids）
        hits = hit_policy(ans, gold_ids)
        p_set = {norm_policy_key(h) for h in hits}
        g_set = {norm_policy_key(g) for g in gold_ids if g}
        tp = len(p_set & g_set)
        f1 = (2 * tp / (len(p_set) + len(g_set))) if (p_set or g_set) else 0.0
        f1s.append(round(f1, 4))

        # 溯源命中
        cite = bool(hits)
        cite_hits += cite

        # validity 结论正确性：金标准结论关键词（废止/失效）是否被正确给出
        if it.get("q_type") == "validity":
            correct = ("废止" in ans or "已由" in ans or "失效" in ans) and not invalid
            validity_ok += correct
            rows.append({"item_id": r["item_id"], "q_type": "validity",
                         "verdict": "correct" if correct else "wrong（未给出有效时效判断）",
                         "f1": round(f1, 4), "cite": cite})
        else:
            rows.append({"item_id": r["item_id"], "q_type": it.get("q_type"),
                         "verdict": "answered", "f1": round(f1, 4), "cite": cite})

    n = max(len(results), 1)
    return {
        "n_questions": len(results),
        "policy_f1_avg": round(sum(f1s) / n, 4),
        "traceability_hit_rate": round(cite_hits / n, 4),
        "validity_correct": validity_ok,
        "invalid_answers": invalid_answers,
        "rows": rows,
    }


if __name__ == "__main__":
    r = score_lightrag()
    (ROOT / "data/eval/sota_comparison.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print("===== LightRAG（港大 SOTA）在 PolicyBench 上的表现 =====")
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}, ensure_ascii=False, indent=2))
