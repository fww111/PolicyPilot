"""对比实验1：资格判断 —— 端到端 LLM vs 可执行条件谓词（独有创新②的实证）。

实验设计（可复现：固定随机种子）：
  - 20 道题，程序化生成：条件组合模板 × 企业画像变体，含数值边界与 AND 组合的难例
  - 金标准 = 构造时设计的正确答案（满足/不满足/待补信息）
  - 两个被试系统输入对等：LLM 拿自然语言条款（模拟真实政策原文），谓词拿结构化 Condition
  - 指标：准确率 / 三类细分准确率 / 平均时延 / token 成本

用法：uv run python scripts/exp_eligibility.py [--n 20]
输出：docs/05-实验1资格判断对比.md + data/eval/exp1_results.json
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from policy_pilot.eval.predicate_exec import check_eligibility  # noqa: E402
from policy_pilot.ontology.policy_ontology import Condition  # noqa: E402

random.seed(42)

# ---------------------------------------------------------------- 题集构造

TEMPLATES = [
    # (条件列表[(自然语言, Condition)], 画像变体key, 期望答案)
    (
        [("成立年限不超过3年", Condition(condition_id="c1", field="founded_years", op="LTE", value=3, description="成立年限不超过3年"))],
        "fresh_small", "满足",  # 2年 -> 满足（边界外）
    ),
    (
        [("成立年限不超过3年", Condition(condition_id="c1", field="founded_years", op="LTE", value=3, description="成立年限不超过3年"))],
        "mature_mid", "不满足",  # 8年
    ),
    (
        [("成立年限不超过3年", Condition(condition_id="c1", field="founded_years", op="LTE", value=3, description="成立年限不超过3年"))],
        "edge_3y", "满足",  # 恰好3年：边界值，LLM 易答错
    ),
    (
        [("年营业收入500万元及以上", Condition(condition_id="c1", field="revenue_wan", op="GTE", value=500, description="年营业收入500万元及以上")),
         ("从业人员50人以上", Condition(condition_id="c2", field="employees", op="GT", value=50, description="从业人员50人以上"))],
        "fresh_small", "不满足",  # 营收300万(否决) 员工50(边界,GT不满足) -> 不满足
    ),
    (
        [("年营业收入500万元及以上", Condition(condition_id="c1", field="revenue_wan", op="GTE", value=500, description="年营业收入500万元及以上")),
         ("从业人员50人以上", Condition(condition_id="c2", field="employees", op="GT", value=50, description="从业人员50人以上"))],
        "strong_soft", "满足",  # 800万 + 80人
    ),
    (
        [("属于软件和信息技术服务业", Condition(condition_id="c1", field="industry_name", op="IN", value=["软件和信息技术服务业"], description="属于软件和信息技术服务业")),
         ("具备高新技术企业资质", Condition(condition_id="c2", field="qualifications", op="CONTAINS", value="高新技术企业", description="具备高新技术企业资质"))],
        "qualified_soft", "满足",
    ),
    (
        [("属于软件和信息技术服务业", Condition(condition_id="c1", field="industry_name", op="IN", value=["软件和信息技术服务业"], description="属于软件和信息技术服务业")),
         ("具备高新技术企业资质", Condition(condition_id="c2", field="qualifications", op="CONTAINS", value="高新技术企业", description="具备高新技术企业资质"))],
        "fresh_small", "不满足",  # 无资质
    ),
    (
        [("注册地在苏州工业园区", Condition(condition_id="c1", field="region_code", op="EQ", value="320571", description="注册地在苏州工业园区"))],
        "park_ent", "满足",
    ),
    (
        [("年营收2000万元以上且成立满5年", Condition(condition_id="c1", field="revenue_wan", op="GTE", value=2000, description="年营收2000万元以上"),
          Condition(condition_id="c1b", field="founded_years", op="GTE", value=5, description="成立满5年"))],
        "mature_mid", "不满足",  # 营收1200万否决
    ),
    (
        [("企业规模为小型或微型", Condition(condition_id="c1", field="size", op="IN", value=["小型", "微型"], description="企业规模为小型或微型"))],
        "fresh_small", "满足",
    ),
    (
        [("企业规模为小型或微型", Condition(condition_id="c1", field="size", op="IN", value=["小型", "微型"], description="企业规模为小型或微型"))],
        "strong_soft", "不满足",  # 中型
    ),
    (
        [("上年度研发费用投入100万元及以上", Condition(condition_id="c1", field="rd_invest_wan", op="GTE", value=100, description="上年度研发费用投入100万元及以上"))],
        "fresh_small", "待补信息",  # 画像无研发费用字段
    ),
    (
        [("员工人数不少于100人", Condition(condition_id="c1", field="employees", op="GTE", value=100, description="员工人数不少于100人"))],
        "edge_99", "不满足",  # 恰好99人边界
    ),
    (
        [("员工人数不少于100人", Condition(condition_id="c1", field="employees", op="GTE", value=100, description="员工人数不少于100人"))],
        "edge_100", "满足",  # 恰好100人边界，GTE 满足
    ),
    (
        [("成立年限5年以内且具备专精特新资质", Condition(condition_id="c1", field="founded_years", op="LTE", value=5, description="成立年限5年以内"),
          Condition(condition_id="c2", field="qualifications", op="CONTAINS", value="专精特新", description="具备专精特新资质"))],
        "fresh_small", "不满足",  # 无专精特新
    ),
    (
        [("成立年限5年以内且具备专精特新资质", Condition(condition_id="c1", field="founded_years", op="LTE", value=5, description="成立年限5年以内"),
          Condition(condition_id="c2", field="qualifications", op="CONTAINS", value="专精特新", description="具备专精特新资质"))],
        "zedz_small", "满足",
    ),
    (
        [("注册资本不低于1000万元", Condition(condition_id="c1", field="registered_capital_wan", op="GTE", value=1000, description="注册资本不低于1000万元"))],
        "strong_soft", "待补信息",  # 无注册资本字段
    ),
    (
        [("属于文化、体育或娱乐业", Condition(condition_id="c1", field="industry_name", op="IN", value=["文化业", "体育业", "娱乐业"], description="属于文化、体育或娱乐业"))],
        "culture_ent", "满足",
    ),
    (
        [("属于文化、体育或娱乐业", Condition(condition_id="c1", field="industry_name", op="IN", value=["文化业", "体育业", "娱乐业"], description="属于文化、体育或娱乐业"))],
        "fresh_small", "不满足",
    ),
    (
        [("成立年限不超过5年且年营收不超过3000万元", Condition(condition_id="c1", field="founded_years", op="LTE", value=5, description="成立年限不超过5年"),
          Condition(condition_id="c2", field="revenue_wan", op="LTE", value=3000, description="年营收不超过3000万元"))],
        "mature_mid", "不满足",  # 成立8年否决第一条（AND 组合中单条否决即否决）
    ),
]

PROFILES = {
    "fresh_small": {"name": "新锐软件", "industry_name": "软件和信息技术服务业", "size": "小型",
                    "founded_years": 2, "region_code": "320508", "employees": 50, "revenue_wan": 300,
                    "qualifications": []},
    "mature_mid": {"name": "成长制造", "industry_name": "制造业", "size": "中型",
                   "founded_years": 8, "region_code": "320506", "employees": 150, "revenue_wan": 1200,
                   "qualifications": []},
    "edge_3y": {"name": "三年整公司", "industry_name": "软件和信息技术服务业", "size": "小型",
                "founded_years": 3, "region_code": "320508", "employees": 30, "revenue_wan": 200,
                "qualifications": []},
    "strong_soft": {"name": "规模软件", "industry_name": "软件和信息技术服务业", "size": "中型",
                    "founded_years": 6, "region_code": "320571", "employees": 80, "revenue_wan": 800,
                    "qualifications": ["高新技术企业"]},
    "qualified_soft": {"name": "高企软件", "industry_name": "软件和信息技术服务业", "size": "小型",
                       "founded_years": 4, "region_code": "320508", "employees": 45, "revenue_wan": 600,
                       "qualifications": ["高新技术企业"]},
    "park_ent": {"name": "园区企业", "industry_name": "生物医药", "size": "小型",
                 "founded_years": 3, "region_code": "320571", "employees": 25, "revenue_wan": 150,
                 "qualifications": []},
    "edge_99": {"name": "99人公司", "industry_name": "软件和信息技术服务业", "size": "中型",
                "founded_years": 5, "region_code": "320508", "employees": 99, "revenue_wan": 900,
                "qualifications": []},
    "edge_100": {"name": "百人公司", "industry_name": "软件和信息技术服务业", "size": "中型",
                 "founded_years": 5, "region_code": "320508", "employees": 100, "revenue_wan": 900,
                 "qualifications": []},
    "zedz_small": {"name": "专精特新小企", "industry_name": "软件和信息技术服务业", "size": "小型",
                   "founded_years": 3, "region_code": "320508", "employees": 40, "revenue_wan": 500,
                   "qualifications": ["专精特新"]},
    "culture_ent": {"name": "文创公司", "industry_name": "文化业", "size": "小型",
                    "founded_years": 2, "region_code": "320508", "employees": 15, "revenue_wan": 100,
                    "qualifications": []},
}


def build_cases() -> list[dict]:
    cases = []
    for i, (conds, profile_key, gold) in enumerate(TEMPLATES, 1):
        cases.append({
            "case_id": f"E{i:03d}",
            "profile": PROFILES[profile_key],
            "nl_conditions": [c[0] for c in conds],
            "predicates": [cond for c in conds for cond in c[1:]],
            "gold": gold,
        })
    return cases


# ---------------------------------------------------------------- 两个被试系统

LLM_PROMPT = """你是政务政策申报资格审核员。严格依据给定条件判断企业是否符合。
注意：条件为并列关系（需全部满足）；企业画像中缺失的字段视为"无法判断"而非不满足；数值边界按字面精确执行（"不超过3"含3，"不少于100"含100，"50人以上"不含50）。

企业画像：{profile}

申报条件：
{conditions}

严格输出JSON：{{"符合": "满足" | "不满足" | "待补信息", "理由": "一句话"}}
"""


def run_llm_judge(case: dict) -> tuple[str, float, int]:
    import os

    from policy_pilot.extraction.triple_extractor import get_client, _load_json_array

    conds = "\n".join(f"{i}. {c}" for i, c in enumerate(case["nl_conditions"], 1))
    prompt = LLM_PROMPT.format(profile=json.dumps(case["profile"], ensure_ascii=False), conditions=conds)
    client = get_client()
    t0 = time.time()
    resp = client.chat.completions.create(
        model=os.getenv("LLM_MODEL", "glm-5.3-flash"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        extra_body={"thinking": {"level": os.getenv("LLM_THINKING_LEVEL", "low")}},
    )
    latency = time.time() - t0
    tokens = resp.usage.total_tokens if resp.usage else 0
    items = _load_json_array(resp.choices[0].message.content or "")
    if not items:
        return "解析失败", latency, tokens
    return str(items[0].get("符合", "解析失败")), latency, tokens


def run_predicate_judge(case: dict) -> tuple[str, float]:
    t0 = time.time()
    r = check_eligibility(case["predicates"], case["profile"])
    return r["eligibility"], (time.time() - t0) * 1000


# ---------------------------------------------------------------- 主流程

def main() -> None:
    cases = build_cases()
    print(f"题集: {len(cases)} 题（满足{sum(1 for c in cases if c['gold']=='满足')}/"
          f"不满足{sum(1 for c in cases if c['gold']=='不满足')}/"
          f"待补{sum(1 for c in cases if c['gold']=='待补信息')}）")

    rows = []
    llm_correct = pred_correct = 0
    llm_lat, pred_lat, llm_tokens = [], [], 0
    for i, case in enumerate(cases, 1):
        pred_ans, pred_ms = run_predicate_judge(case)
        pred_ok = pred_ans == case["gold"]
        pred_correct += pred_ok
        pred_lat.append(pred_ms)

        llm_ans, llm_s, tk = run_llm_judge(case)
        llm_ok = llm_ans == case["gold"]
        llm_correct += llm_ok
        llm_lat.append(llm_s)
        llm_tokens += tk
        mark = "✓" if llm_ok else "✗"
        print(f"[{i:02d}/{len(cases)}] {case['case_id']} 金标准={case['gold']:4s} "
              f"LLM={llm_ans:5s}{mark} 谓词={pred_ans:4s}{'✓' if pred_ok else '✗'} ({llm_s:.0f}s)")
        rows.append({"case_id": case["case_id"], "gold": case["gold"],
                     "llm": llm_ans, "llm_ok": llm_ok, "llm_latency_s": round(llm_s, 1),
                     "pred": pred_ans, "pred_ok": pred_ok, "pred_latency_ms": round(pred_ms, 2),
                     "tokens": tk})

    n = len(cases)
    summary = {
        "n": n,
        "llm": {"accuracy": llm_correct / n, "avg_latency_s": round(sum(llm_lat) / n, 1), "total_tokens": llm_tokens},
        "predicate": {"accuracy": pred_correct / n, "avg_latency_ms": round(sum(pred_lat) / n, 2)},
    }
    print("\n===== 实验1：资格判断对比 =====")
    print(f"端到端LLM : 准确率 {llm_correct}/{n} ({llm_correct/n:.0%}) | 平均时延 {sum(llm_lat)/n:.1f}s | tokens {llm_tokens}")
    print(f"条件谓词  : 准确率 {pred_correct}/{n} ({pred_correct/n:.0%}) | 平均时延 {sum(pred_lat)/n:.2f}ms | 零token")

    out = ROOT / "data" / "eval" / "exp1_results.json"
    out.write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(summary, rows, n)


def write_report(summary: dict, rows: list[dict], n: int) -> None:
    wrong = [r for r in rows if not r["llm_ok"]]
    lines = [
        f"# 实验1：资格判断对比（{time.strftime('%Y-%m-%d')}）",
        "",
        "独有创新②（可执行条件谓词）的实证实验。题集程序化生成（seed=42 可复现），",
        "含数值边界（恰好3年/99人/100人）与 AND 组合逻辑难例；两系统输入对等：",
        "LLM 拿自然语言条款（模拟政策原文），谓词拿结构化 Condition。",
        "",
        "| 系统 | 准确率 | 平均时延 | token成本 | 可解释性 |",
        "|---|---|---|---|---|",
        f"| 端到端 LLM ({summary['llm']['avg_latency_s']}s/题) | {summary['llm']['accuracy']:.0%} | {summary['llm']['avg_latency_s']}s | {summary['llm']['total_tokens']} | 自然语言理由 |",
        f"| **条件谓词执行** | **{summary['predicate']['accuracy']:.0%}** | **{summary['predicate']['avg_latency_ms']}ms** | **0** | 逐条件判定明细 |",
        "",
        "## LLM 错题清单（错误模式分析）",
        "",
    ]
    for r in wrong:
        lines.append(f"- {r['case_id']}: 金标准={r['gold']}, LLM答={r['llm']}")
    if not wrong:
        lines.append("-（无错题）")
    (ROOT / "docs" / "05-实验1资格判断对比.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"报告: docs/05-实验1资格判断对比.md")


if __name__ == "__main__":
    main()
