"""复核反馈库与 Skill 版本回测（docs/10 §3.4，进化实证的核心链路）。

进化叙事的可演示链路：
    v1 审查 → 误报 → 复核人员结构化驳回（含理由）→ 反馈驱动策略约束 →
    v2 审查 → 历史回测（误报率下降且召回不降）

反馈结构（data/feedback/review_log.jsonl）：
    {case_id, article_id, related_id, verdict: confirmed|rejected,
     reason_code, reason, reviewer, ts}
    reason_code 枚举（驱动 v2 策略约束的依据）：
      authorized_refinement  下位法在上位法授权范围内的细化规定（非冲突）
      expired_reference      引用了已废止条款（真冲突）
      authority_violation    下位法超越上位法设定（真冲突）
      scope_mismatch         事项不在上位法调整范围（误报）
      other

用法：
    uv run python -m policy_pilot.feedback.review_loop demo   # 端到端演示
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
FEEDBACK_PATH = ROOT / "data" / "feedback" / "review_log.jsonl"


class ReviewRecord(BaseModel):
    case_id: str
    article_id: str
    related_id: str = ""
    verdict: str = Field(..., description="confirmed 确认冲突 | rejected 驳回误报")
    reason_code: str = Field("other", description="见模块 docstring 枚举")
    reason: str = ""
    reviewer: str = "法制审核人员"
    ts: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def append_review(rec: ReviewRecord) -> None:
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_PATH.open("a", encoding="utf-8") as f:
        f.write(rec.model_dump_json() + "\n")


def load_reviews() -> list[ReviewRecord]:
    if not FEEDBACK_PATH.exists():
        return []
    return [ReviewRecord.model_validate_json(x) for x in FEEDBACK_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------- 审查策略（Skill 的核心逻辑，v1/v2 版本化）

_AUTHORIZED_REFINEMENT_HINTS = ("在...基础上", "细化", "具体规定", "实施办法", "不低于", "不超过", "鼓励", "引导")


def detect_conflict_v1(article_text: str, superior_text: str, article_level: int, superior_level: int) -> dict:
    """v1 策略：仅依据"表述差异 + 层级不同"报冲突 → 会把授权细化误报为冲突。"""
    conflict = (article_level > superior_level) and (normalize_key(article_text) != normalize_key(superior_text))
    return {"version": "v1", "conflict": conflict,
            "reason": "下位条款表述与上位条款存在差异" if conflict else "表述一致或层级相同"}


def normalize_key(t: str) -> str:
    import re
    return re.sub(r"\s+", "", t)


def detect_conflict_v2(article_text: str, superior_text: str, article_level: int, superior_level: int,
                       feedback_rules: list[ReviewRecord] | None = None) -> dict:
    """v2 策略：v1 + 反馈驱动的授权细化豁免 + 越权检测。

    反馈注入的约束（来自 review_log 的 reason_code 统计）：
      - authorized_refinement 类驳回 >= 1 → 启用细化豁免（下位条款含细化特征词且
        未突破上位底线时，不报冲突）
      - 同时新增越权检测（下位条款设定了上位没有的处罚/许可 → 真冲突，召回不降）
    """
    rules = feedback_rules if feedback_rules is not None else load_reviews()
    refinement_enabled = any(
        r.verdict == "rejected" and r.reason_code == "authorized_refinement" for r in rules
    )
    is_inferior = article_level > superior_level
    differs = normalize_key(article_text) != normalize_key(superior_text)

    # 越权检测：下位条款出现上位条款没有的强制/处罚表述 → 真冲突（保证召回）
    mandatory_marks = ("应当", "必须", "不得", "处罚", "罚款", "吊销", "许可")
    superior_mandatory = any(m in superior_text for m in mandatory_marks)
    article_mandatory = any(m in article_text for m in mandatory_marks)
    ultra_vires = is_inferior and article_mandatory and not superior_mandatory and differs

    # 细化豁免：v1 误报场景——下位法在上位授权内的细化
    refinement_like = any(h.replace("...", "") in article_text or h in article_text for h in _AUTHORIZED_REFINEMENT_HINTS)
    authorized_refinement = refinement_enabled and is_inferior and differs and refinement_like and not ultra_vires

    if ultra_vires:
        conflict, reason = True, "下位条款设定了上位条款未设定的强制性/处罚性内容（越权）"
    elif authorized_refinement:
        conflict, reason = False, "下位条款属上位条款授权范围内的细化规定（反馈驱动豁免）"
    elif is_inferior and differs:
        conflict, reason = True, "下位条款表述与上位条款存在差异且无豁免特征"
    else:
        conflict, reason = False, "无层级差异或表述一致"

    return {"version": "v2", "conflict": conflict, "reason": reason,
            "refinement_enabled": refinement_enabled, "ultra_vires": ultra_vires}


def backtest(cases: list[dict], detector) -> dict:
    """历史回测：在带金标准的用例集上跑指定版本策略。

    cases: [{article_text, superior_text, article_level, superior_level, gold_conflict}]
    返回 {accuracy, fp, fn, confusion}。
    """
    tp = tn = fp = fn = 0
    for c in cases:
        pred = detector(c["article_text"], c["superior_text"], c["article_level"], c["superior_level"])["conflict"]
        gold = c["gold_conflict"]
        if pred and gold:
            tp += 1
        elif pred and not gold:
            fp += 1
        elif not pred and gold:
            fn += 1
        else:
            tn += 1
    total = max(len(cases), 1)
    return {"total": total, "accuracy": round((tp + tn) / total, 4),
            "false_positive": fp, "false_negative": fn, "true_positive": tp, "true_negative": tn}
