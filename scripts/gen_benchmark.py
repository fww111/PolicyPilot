"""正式评测集生成器：从图谱+语料程序化生成 200 题（四类题型）+ 人工校对清单。

四类题型对应三个创新点（每类都在考现有产品做不到的能力）：
  multi_hop  多跳匹配：企业画像 -> PPR 可达 Subsidy 集合（创新①图谱+PPR）
  validity   时效判断：SUPERSEDES 链 + 元数据时间（创新③级联失效）
  conflict   冲突检测：同主题/同类事项的互斥关系（创新①三维本体）
  traceable  溯源要求：答案必须附政策文号（创新②+三级溯源）

生成策略：题面程序化（seed=42 可复现），金标准来自图谱结构（B1 已人工校验的部分可信），
输出人工校对清单 docs/06 —— 队友判定"保留/修改/删除"后成为正式评测集。

用法：uv run python scripts/gen_benchmark.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policy_pilot.graph.memory_engine import MemoryGraphStore  # noqa: E402

random.seed(42)
OUT = ROOT / "data" / "eval" / "benchmark.json"
CHECK = ROOT / "docs" / "06-评测集校对.md"


def gen_multi_hop(store: MemoryGraphStore, n: int = 80) -> list[dict]:
    """多跳匹配题：采样类别节点 -> 构造画像 -> 金标准=PPR匹配结果。"""
    cats = [c for c in store.g.nodes if str(c).startswith(("行业:", "资质:"))]
    random.shuffle(cats)
    items = []
    used: set[str] = set()
    for cat in cats:
        if len(items) >= n:
            break
        key = cat.split(":", 1)[1]
        if key in used:
            continue
        used.add(key)
        kind = cat.split(":", 1)[0]
        ent = (
            {"industry_name": key, "size": random.choice(["小型", "中型", "微型"])}
            if kind == "行业"
            else {"industry_name": "综合", "qualifications": [key], "size": "小型"}
        )
        hits = store.match_policies_for(ent, top_k=8)
        if not hits:
            continue
        items.append({
            "q_type": "multi_hop",
            "question": f"我们是一家{ent.get('size', '')}{key}企业，目前在苏州/国家层面能申请哪些支持事项？",
            "enterprise": ent,
            "gold_ids": [h["subsidy_id"] for h in hits],
            "gold_answer": f"共{len(hits)}项（详见gold_ids，人工校对请抽查前2项）",
            "gold_policy_ids": sorted({h["policy_id"] for h in hits if h.get("policy_id")}),
            "difficulty": 2 if len(hits) > 3 else 1,
        })
    return items


def gen_validity(store: MemoryGraphStore) -> list[dict]:
    """时效题：全部 SUPERSEDES 链 + 元数据层按发布年构造老化题。"""
    items = []
    for u, v, d in store.g.edges(data=True):
        if d["relation"] != "SUPERSEDES":
            continue
        items.append({
            "q_type": "validity",
            "question": f"《{u}》所设立的支持事项现在还能申请吗？",
            "gold_answer": f"不能直接适用：《{u}》已由《{v}》废止替代（{d.get('evidence', '')[:30]}…）",
            "gold_policy_ids": [str(u), str(v)],
            "difficulty": 2,
        })
    # 元数据层：2020年前发布的财政类政策 -> "请核实时效"（多跳时效意识题）
    meta = [json.loads(x) for x in (ROOT / "data/raw/gov_metadata.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    old = [r for r in meta if r.get("pubtime", "2026") < "2022" and "财政" in (r.get("theme") or "")]
    for r in random.sample(old, min(12, len(old))):
        items.append({
            "q_type": "validity",
            "question": f"{r['pcode']}（{r['pubtime']}发布）的优惠措施现在还有效吗？",
            "gold_answer": "需核验：发布已超4年，存在被新文件替代的可能，系统应触发废止链核查（人工校对：确认图谱中是否有其 SUPERSEDES 记录）",
            "gold_policy_ids": [r["pcode"]],
            "difficulty": 3,
        })
    return items


def gen_conflict(store: MemoryGraphStore) -> list[dict]:
    """冲突题：显式 CONFLICTS_WITH + 同主题同形式事项的潜在冲突（人工判定）。"""
    items = []
    seen = set()
    for u, v, d in store.g.edges(data=True):
        if d["relation"] == "CONFLICTS_WITH" and (v, u) not in seen:
            seen.add((u, v))
            items.append({
                "q_type": "conflict",
                "question": f"已享受「{v}」的情况下，还能再申请「{u}」吗？",
                "gold_answer": "不能重复申领：两者互斥（就高不重复）",
                "gold_policy_ids": [str(u), str(v)],
                "difficulty": 3,
            })
    # 同主题（BELONGS_TO 同一主题）+ 同为补贴类 -> 潜在冲突对（人工判定金标准）
    theme_subs: dict[str, list] = {}
    for u, v, d in store.g.edges(data=True):
        if d["relation"] == "HAS_SUBSIDY" and "#" in str(v):
            for _, t, dd in store.g.out_edges(u, data=True):
                if dd["relation"] == "BELONGS_TO" and str(t).startswith("主题:"):
                    theme_subs.setdefault(str(t), []).append(str(v))
    pairs = 0
    for theme, subs in theme_subs.items():
        if len(subs) >= 2 and pairs < 18:
            a, b = random.sample(subs, 2)
            items.append({
                "q_type": "conflict",
                "question": f"同一企业已享受「{a}」，还能叠加申请「{b}」吗？",
                "gold_answer": "【人工判定】同属" + theme + "，请核对两份政策原文是否含'不得重复/就高'条款",
                "gold_policy_ids": [a.split("#")[0] if "#" in a else a, b.split("#")[0] if "#" in b else b],
                "difficulty": 3,
            })
            pairs += 1
    return items


def gen_traceable(store: MemoryGraphStore, n: int = 60) -> list[dict]:
    """溯源题：带 evidence 的三元组 -> 依据引用。"""
    items = []
    triples = [
        (u, v, d)
        for u, v, d in store.g.edges(data=True)
        if d.get("evidence") and len(d.get("evidence", "")) > 15 and d["relation"] in ("HAS_SUBSIDY", "APPLIES_TO", "ACCEPTED_BY", "ISSUED_BY")
    ]
    random.shuffle(triples)
    for u, v, d in triples:
        if len(items) >= n:
            break
        rel_cn = d.get("relation_cn", d["relation"])
        items.append({
            "q_type": "traceable",
            "question": f"「{str(u)[:26]}」{rel_cn}「{str(v)[:26]}」，依据是什么？",
            "gold_answer": f"依据：{d['evidence'][:60]}",
            "gold_policy_ids": [d.get("source") or str(u)],
            "difficulty": 1,
        })
    return items


def main() -> None:
    store = MemoryGraphStore.load()
    items = []
    for gen, tag in [
        (gen_multi_hop, "multi_hop"),
        (gen_validity, "validity"),
        (gen_conflict, "conflict"),
        (gen_traceable, "traceable"),
    ]:
        got = gen(store)
        print(f"{tag}: {len(got)} 题")
        items.extend(got)
    for i, it in enumerate(items, 1):
        it["item_id"] = f"{it['q_type'].upper()[:2]}-{i:04d}"
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"总计 {len(items)} 题 -> {OUT}")

    lines = [
        "# 评测集人工校对清单（生成 seed=42 可复现）",
        "",
        f"共 {len(items)} 题。请逐题判定：**保留** / **修改**（改写题面或金标准）/ **删除**（题面歧义或金标准错误）。",
        "金标准中标注【人工判定】的题目是设计上的半开放题（正是人机协同闭环的素材）。",
        "",
        "| # | 类型 | 题面 | 金标准 | 判定 |",
        "|---|---|---|---|---|",
    ]
    for it in items:
        q = it["question"].replace("|", "/")[:60]
        a = it["gold_answer"].replace("|", "/")[:50]
        lines.append(f"| {it['item_id']} | {it['q_type']} | {q} | {a} | |")
    CHECK.write_text("\n".join(lines), encoding="utf-8")
    print(f"校对清单 -> docs/06-评测集校对.md")


if __name__ == "__main__":
    main()
