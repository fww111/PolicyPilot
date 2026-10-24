"""
评测模块 —— 自建"惠企政策匹配评测基准"（附加分武器 + 效果验证）。

四类题型（对应三个创新点，每类都在考现有产品做不到的能力）：
  multi_hop  多跳推理：需跨 >=2 份文件才能回答（考三维本体）
  validity   时效判断：涉及废止/替代政策（考 SUPERSEDES）
  conflict   冲突检测：市区两级互斥申领（考 CONFLICTS_WITH）
  traceable  溯源要求：答案必须附带政策文号+条款（考溯源链）

评测集格式见 data/eval/benchmark.sample.json，人工标注由 3 名队员分摊。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

EVAL_DIR = Path(__file__).resolve().parents[3] / "data" / "eval"


class EvalItem(BaseModel):
    item_id: str
    q_type: str = Field(..., description="multi_hop / validity / conflict / traceable")
    question: str
    gold_answer: str = Field("", description="人工标注的标准答案")
    gold_policy_ids: list[str] = Field(default_factory=list, description="答案必须引用的政策文号")
    difficulty: int = Field(1, ge=1, le=3)


class EvalResult(BaseModel):
    system: str = Field(..., description="pure_rag / pure_graph / dual_drive")
    total: int = 0
    correct: int = 0
    accuracy: float = 0.0
    traceability_hit_rate: float = Field(0.0, description="答案引用文号命中率（仅 traceable 类计）")
    details: list[dict] = Field(default_factory=list)


def load_benchmark(path: Path | None = None) -> list[EvalItem]:
    path = path or EVAL_DIR / "benchmark.json"
    if not path.exists():
        # 生成 200 题前先用样例联调
        path = EVAL_DIR / "benchmark.sample.json"
    return [EvalItem.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def score(system: str, answers: dict[str, dict], items: list[EvalItem]) -> EvalResult:
    """answers: {item_id: {"answer": str, "cited_policy_ids": [str]}}。"""
    correct = 0
    trace_hit, trace_total = 0, 0
    details = []
    for it in items:
        a = answers.get(it.item_id, {})
        ok = a.get("answer", "").strip() == it.gold_answer.strip()
        correct += ok
        if it.q_type == "traceable":
            trace_total += 1
            cited = set(a.get("cited_policy_ids", []))
            if cited & set(it.gold_policy_ids):
                trace_hit += 1
        details.append({"item_id": it.item_id, "correct": ok})
    return EvalResult(
        system=system,
        total=len(items),
        correct=correct,
        accuracy=round(correct / max(len(items), 1), 4),
        traceability_hit_rate=round(trace_hit / max(trace_total, 1), 4),
        details=details,
    )
