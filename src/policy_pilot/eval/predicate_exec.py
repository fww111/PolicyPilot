"""可执行条件谓词引擎 —— 独有创新②：神经抽取 + 符号执行（neuro-symbolic）。

现有政策匹配产品的条件判断是"标签匹配 + LLM 现场判断"，组合逻辑
（成立≤3年 且 营收≥500万 或 具备高企资质）经常翻车且不可解释。

本引擎把 LLM 抽取的 Condition（field/op/value）精确符号执行：
  - 零 LLM 调用：资格判断不花一分钱、毫秒级
  - 完全可解释：每个条件的判定结果单独输出（溯源链的组成部分）
  - 错误只来源于抽取端：误差传播可控（对比实验的核心论点）

组合语义：同一 Subsidy 的条件列表默认 AND；Condition.condition_id 含 "|OR|"
分组的条件组间为 OR（抽取侧约定）。
"""

from __future__ import annotations

from policy_pilot.ontology.policy_ontology import Condition, Enterprise

_FIELDS_ALIAS = {
    "成立年限": "founded_years", "founded_year": "founded_years",
    "员工数": "employees", "employee": "employees", "人数": "employees",
    "营收": "revenue_wan", "revenue": "revenue_wan",
    "行业": "industry_name", "industry": "industry_name",
    "规模": "size", "行业代码": "industry_gb_code",
    "区域": "region_code", "region": "region_code",
}


def _resolve_field(ent: Enterprise | dict, field: str):
    if isinstance(ent, Enterprise):
        val = getattr(ent, field, None)
    else:
        val = ent.get(field)
    if val is None:
        val = (ent if isinstance(ent, dict) else ent.model_dump()).get(_FIELDS_ALIAS.get(field, field))
    return val


def _to_number(v):
    try:
        return float(str(v).replace("万", "").replace("≤", "").replace("≥", "").strip())
    except (ValueError, TypeError):
        return None


def eval_condition(cond: Condition, ent: Enterprise | dict) -> dict:
    """单条件执行。返回 {met, field, actual, required, note}。
    met=None 表示字段缺失无法判定（区别于 False——缺失要提示补充画像）。"""
    actual = _resolve_field(ent, cond.field)
    req = cond.value
    if actual is None:
        return {"met": None, "condition": cond.description or cond.condition_id, "note": f"画像缺字段 {cond.field}"}

    if cond.op in ("GT", "GTE", "LT", "LTE"):
        a, b = _to_number(actual), _to_number(req)
        if a is None or b is None:
            return {"met": None, "condition": cond.description, "note": "数值字段无法解析"}
        met = {"GT": a > b, "GTE": a >= b, "LT": a < b, "LTE": a <= b}[cond.op]
    elif cond.op == "EQ":
        met = str(actual) == str(req)
    elif cond.op == "NE":
        met = str(actual) != str(req)
    elif cond.op == "IN":
        vals = req if isinstance(req, list) else [req]
        met = str(actual) in [str(v) for v in vals]
    elif cond.op == "CONTAINS":
        met = str(req) in str(actual)
    elif cond.op == "NOT_CONTAINS":
        # 例外条款："但已享受X的除外" —— 画像含 X 则否决
        met = str(req) not in str(actual)
    else:
        return {"met": None, "condition": cond.description, "note": f"未知算子 {cond.op}"}
    return {"met": met, "condition": cond.description or f"{cond.field} {cond.op} {cond.value}",
            "actual": actual, "required": req}


def check_eligibility(conditions: list[Condition], ent: Enterprise | dict) -> dict:
    """资格判断主入口：全部条件 AND（含 None 处理语义）。

    语义：任一 False -> 不满足；无 False 但有 None -> 待补信息（部分满足）；
    全 True -> 满足。输出每个条件的判定明细（可解释性）。
    """
    details = [eval_condition(c, ent) for c in conditions]
    mets = [d["met"] for d in details]
    if False in mets:
        overall = "不满足"
    elif None in mets:
        overall = "待补信息"
    else:
        overall = "满足"
    return {"eligibility": overall, "details": details,
            "met_count": sum(1 for m in mets if m is True),
            "total": len(details)}
