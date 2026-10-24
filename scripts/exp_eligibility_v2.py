"""对比实验1-V2：资格判断难题版 —— 找到谓词执行 vs 端到端 LLM 的适用边界。

V1 结论（诚实记录）：20 道单层 AND 简单题上两者准确率打平（均100%），
差异在时延（0ms vs 4.5s，10^3 倍）与成本（0 vs 8890 token）。

V2 假设：真实政策条款的复杂形态会让 LLM 出错——
  H1 多条件长列表（6-8条 AND，注意力和计数问题）
  H2 数值区间链（500≤营收≤3000 的双边界）
  H3 例外条款（"...但已获得市级同类补贴的除外" 的 NOT 语义）
  H4 边界值叠加（恰好压线 + 例外条款同时出现）
用法：uv run python scripts/exp_eligibility_v2.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from exp_eligibility import PROFILES, run_llm_judge, run_predicate_judge  # noqa: E402
from policy_pilot.ontology.policy_ontology import Condition  # noqa: E402

P = PROFILES["fresh_small"].copy()      # 软件小型：2年/50人/300万/I65/无资质
P2 = PROFILES["strong_soft"].copy()     # 软件中型：6年/80人/800万/高企
P3 = P2 | {"qualifications": ["高新技术企业", "市级研发补贴已获"]}

C = lambda cid, f, op, v, d: Condition(condition_id=cid, field=f, op=op, value=v, description=d)  # noqa: E731

CASES = [
    # H1: 六条件长列表（P 满足全部：软件/小型/2年/50人/GTE50/300万区间内）
    dict(case_id="V2-H1a", profile=P, gold="满足", nl=[
        "属于软件和信息技术服务业", "企业规模为小型", "成立年限不超过3年",
        "从业人员不少于50人", "年营业收入不低于300万元", "注册地在苏州市",
    ], predicates=[
        C("c1", "industry_name", "IN", ["软件和信息技术服务业"], "软件业"),
        C("c2", "size", "EQ", "小型", "小型"),
        C("c3", "founded_years", "LTE", 3, "成立≤3年"),
        C("c4", "employees", "GTE", 50, "人员≥50"),
        C("c5", "revenue_wan", "GTE", 300, "营收≥300万"),
        C("c6", "region_code", "CONTAINS", "3205", "苏州"),
    ]),
    # H1b: 同列表但 80 人（GTE50 ✓）与营收 800（✓）——满足；陷阱是规模"中型" vs 条件"小型"否决
    dict(case_id="V2-H1b", profile=P2, gold="不满足", nl=[
        "属于软件和信息技术服务业", "企业规模为小型", "成立年限不超过3年",
        "从业人员不少于50人", "年营业收入不低于300万元", "注册地在苏州市",
    ], predicates=[
        C("c1", "industry_name", "IN", ["软件和信息技术服务业"], "软件业"),
        C("c2", "size", "EQ", "小型", "小型"),
        C("c3", "founded_years", "LTE", 3, "成立≤3年"),
        C("c4", "employees", "GTE", 50, "人员≥50"),
        C("c5", "revenue_wan", "GTE", 300, "营收≥300万"),
        C("c6", "region_code", "CONTAINS", "3205", "苏州"),
    ]),
    # H2: 数值区间链双边界——营收恰好3000万（LTE3000 含边界 -> 满足）
    dict(case_id="V2-H2a", profile=P2 | {"revenue_wan": 3000}, gold="满足", nl=[
        "上年度营业收入在500万元至3000万元之间（含边界）",
    ], predicates=[
        C("c1", "revenue_wan", "GTE", 500, "营收≥500万"),
        C("c2", "revenue_wan", "LTE", 3000, "营收≤3000万"),
    ]),
    # H2b: 区间链下边界恰好500（含）但人数不满足的组合
    dict(case_id="V2-H2b", profile=P2 | {"revenue_wan": 499.9, "employees": 200}, gold="不满足", nl=[
        "上年度营业收入在500万元至3000万元之间（含边界），且从业人员不超过300人",
    ], predicates=[
        C("c1", "revenue_wan", "GTE", 500, "营收≥500万"),
        C("c2", "revenue_wan", "LTE", 3000, "营收≤3000万"),
        C("c3", "employees", "LTE", 300, "人员≤300"),
    ]),
    # H3: 例外条款——高企✓营收✓ 但已获市级同类补贴 -> 除外否决
    dict(case_id="V2-H3a", profile=P3, gold="不满足", nl=[
        "具备高新技术企业资质且年营业收入不低于500万元，但已获得市级同类研发补贴的除外",
    ], predicates=[
        C("c1", "qualifications", "CONTAINS", "高新技术企业", "高企"),
        C("c2", "revenue_wan", "GTE", 500, "营收≥500万"),
        C("c3", "qualifications", "NOT_CONTAINS", "市级研发补贴已获", "已获同类补贴除外"),
    ]),
    # H3b: 同条款，无已获补贴 -> 满足
    dict(case_id="V2-H3b", profile=P2, gold="满足", nl=[
        "具备高新技术企业资质且年营业收入不低于500万元，但已获得市级同类研发补贴的除外",
    ], predicates=[
        C("c1", "qualifications", "CONTAINS", "高新技术企业", "高企"),
        C("c2", "revenue_wan", "GTE", 500, "营收≥500万"),
        C("c3", "qualifications", "NOT_CONTAINS", "市级研发补贴已获", "已获同类补贴除外"),
    ]),
    # H4: 八条件 + 区间 + 例外全叠加（P 全满足）
    dict(case_id="V2-H4a", profile=P | {"employees": 60, "revenue_wan": 600, "qualifications": ["科技型中小企业"]}, gold="满足", nl=[
        "属于软件和信息技术服务业", "注册地在苏州", "成立不超过3年", "规模为小型或微型",
        "从业人员50人以上", "年营收在500万至3000万之间（含边界）", "具备科技型中小企业或高新技术企业资质",
        "已列入严重失信名单的除外",
    ], predicates=[
        C("c1", "industry_name", "IN", ["软件和信息技术服务业"], "软件业"),
        C("c2", "region_code", "CONTAINS", "3205", "苏州"),
        C("c3", "founded_years", "LTE", 3, "成立≤3年"),
        C("c4", "size", "IN", ["小型", "微型"], "小微"),
        C("c5", "employees", "GT", 50, "人员>50"),
        C("c6", "revenue_wan", "GTE", 500, "营收≥500万"),
        C("c7", "revenue_wan", "LTE", 3000, "营收≤3000万"),
        C("c8", "qualifications", "NOT_CONTAINS", "严重失信", "失信除外"),
    ]),
    # H4b: 同款，人员恰好50（GT不含50否决）
    dict(case_id="V2-H4b", profile=P | {"employees": 50, "revenue_wan": 600, "qualifications": ["科技型中小企业"]}, gold="不满足", nl=[
        "属于软件和信息技术服务业", "注册地在苏州", "成立不超过3年", "规模为小型或微型",
        "从业人员50人以上", "年营收在500万至3000万之间（含边界）", "具备科技型中小企业或高新技术企业资质",
        "已列入严重失信名单的除外",
    ], predicates=[
        C("c1", "industry_name", "IN", ["软件和信息技术服务业"], "软件业"),
        C("c2", "region_code", "CONTAINS", "3205", "苏州"),
        C("c3", "founded_years", "LTE", 3, "成立≤3年"),
        C("c4", "size", "IN", ["小型", "微型"], "小微"),
        C("c5", "employees", "GT", 50, "人员>50"),
        C("c6", "revenue_wan", "GTE", 500, "营收≥500万"),
        C("c7", "revenue_wan", "LTE", 3000, "营收≤3000万"),
        C("c8", "qualifications", "NOT_CONTAINS", "严重失信", "失信除外"),
    ]),
    # H4c: 缺研发投入字段的长列表（待补信息——LLM 常把缺失当满足/不满足）
    dict(case_id="V2-H4c", profile=P, gold="待补信息", nl=[
        "属于软件和信息技术服务业", "成立不超过5年",
        "上年度研发费用投入占营收比例不低于5%",
    ], predicates=[
        C("c1", "industry_name", "IN", ["软件和信息技术服务业"], "软件业"),
        C("c2", "founded_years", "LTE", 5, "成立≤5年"),
        C("c3", "rd_ratio", "GTE", 5, "研发占比≥5%"),
    ]),
    # H1c: 重复否决项埋在中部（成立 8 年）长列表
    dict(case_id="V2-H1c", profile=PROFILES["mature_mid"], gold="不满足", nl=[
        "属于制造业或软件业", "注册地在苏州", "成立年限不超过5年", "从业人员不少于100人",
        "年营业收入不低于500万元", "规模不限", "近三年无重大安全处罚",
    ], predicates=[
        C("c1", "industry_name", "IN", ["制造业", "软件和信息技术服务业"], "制造或软件"),
        C("c2", "region_code", "CONTAINS", "3205", "苏州"),
        C("c3", "founded_years", "LTE", 5, "成立≤5年"),
        C("c4", "employees", "GTE", 100, "人员≥100"),
        C("c5", "revenue_wan", "GTE", 500, "营收≥500万"),
    ]),
]


def main() -> None:
    print(f"V2 题集: {len(CASES)} 道难题（长列表/区间链/例外条款/边界叠加）")
    # 金标准自检
    for c in CASES:
        pred_ans, _ = run_predicate_judge({"predicates": c["predicates"], "profile": c["profile"]})
        assert pred_ans == c["gold"], f"{c['case_id']} 谓词={pred_ans} 金标准={c['gold']} 不一致!"
    print("谓词金标准自检通过")

    rows, llm_ok, pred_ok, lat, tokens = [], 0, 0, [], 0
    for i, c in enumerate(CASES, 1):
        pred_ans, ms = run_predicate_judge({"predicates": c["predicates"], "profile": c["profile"]})
        pred_ok += pred_ans == c["gold"]
        llm_ans, s, tk = run_llm_judge({"profile": c["profile"], "nl_conditions": c["nl"]})
        ok = llm_ans == c["gold"]
        llm_ok += ok
        lat.append(s)
        tokens += tk
        print(f"[{i:02d}/{len(CASES)}] {c['case_id']} 金={c['gold']:4s} LLM={llm_ans:5s}{'✓' if ok else '✗✗✗'} 谓词={pred_ans}{'✓' if pred_ans==c['gold'] else '✗'} ({s:.0f}s)")
        rows.append({"case_id": c["case_id"], "gold": c["gold"], "llm": llm_ans, "llm_ok": ok,
                     "pred": pred_ans, "hypothesis": c["case_id"].rsplit("-", 1)[0]})
    n = len(CASES)
    print(f"\n===== 实验1-V2（难题版） =====")
    print(f"端到端LLM : {llm_ok}/{n} ({llm_ok/n:.0%}) | 平均 {sum(lat)/n:.1f}s | {tokens} tokens")
    print(f"条件谓词  : {pred_ok}/{n} ({pred_ok/n:.0%}) | 0ms | 0 token")
    out = ROOT / "data" / "eval" / "exp1_v2_results.json"
    out.write_text(json.dumps({"cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    append_report(rows, llm_ok, pred_ok, n, tokens, lat)


def append_report(rows, llm_ok, pred_ok, n, tokens, lat) -> None:
    wrong = [r for r in rows if not r["llm_ok"]]
    hyp_fail = {}
    for r in wrong:
        h = r["hypothesis"]
        hyp_fail[h] = hyp_fail.get(h, 0) + 1
    with open(ROOT / "docs" / "05-实验1资格判断对比.md", "a", encoding="utf-8") as f:
        f.write(f"""
## V2 难题版结果（{time.strftime('%Y-%m-%d')}）

V1 结论修正：简单单层 AND 条件上大模型已 100% 正确——谓词的优势当时只剩时延（10^3 倍）与零成本。
V2 加入真实政策的复杂形态（六~八条件长列表、数值区间双边界、例外条款 NOT 语义、边界叠加）：

| 系统 | 准确率 | 平均时延 | token |
|---|---|---|---|
| 端到端 LLM | {llm_ok}/{n} ({llm_ok/n:.0%}) | {sum(lat)/n:.1f}s | {tokens} |
| **条件谓词** | **{pred_ok}/{n} ({pred_ok/n:.0%})** | **<1ms** | **0** |

LLM 错题分布（按假设分类）: {json.dumps(hyp_fail, ensure_ascii=False) or "无"}
""")
    print("已追加至 docs/05")


if __name__ == "__main__":
    main()
