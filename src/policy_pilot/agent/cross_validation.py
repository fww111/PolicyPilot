"""双通道互验仲裁 —— 独有创新①：把"检索-推理双驱动"从串联架构升级为互验机制。

现有做法（含我们此前的骨架）：检索 Agent 和推理 Agent 各出各的，拼接输出——
单通道错误直接流向用户，且系统不知道自己错了。

互验规则（政务场景"答错比不答严重"，拒答是特性）：
  ACCEPTED  两通道结论一致 且 各自有证据支撑       -> 高置信输出
  DEGRADED  结论一致 但 一方证据缺失               -> 低置信输出（附警示）
  RETRY     结论冲突                               -> 触发一次仲裁重查
  REJECTED  重查后仍冲突，或双通道均无结果          -> 拒答 + 给出分歧说明（可溯源到两通道各自依据）

对比实验位（benchmark.py 四系统）：Ours-full 用本模块；Ablation-1 跳过本模块直接拼接。
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class Verdict(str, Enum):
    ACCEPTED = "采纳"
    DEGRADED = "降置信采纳"
    RETRY = "仲裁重查"
    REJECTED = "拒答"


class ChannelResult(BaseModel):
    """单通道结果。ids=结论指向的政策/事项ID集合，evidences=证据（原文引用或图谱路径）。"""

    channel: str = Field(..., description="graph | rag")
    ids: list[str] = Field(default_factory=list)
    evidences: list[str] = Field(default_factory=list)

    @property
    def has_evidence(self) -> bool:
        return len(self.evidences) > 0


class CrossValidationResult(BaseModel):
    verdict: Verdict
    agreed_ids: list[str] = Field(default_factory=list)
    conflict: dict = Field(default_factory=dict, description="REJECTED 时的分歧说明")
    confidence: float = Field(0.0, ge=0.0, le=1.0)


def cross_validate(graph: ChannelResult, rag: ChannelResult, retry_once: ChannelResult | None = None) -> CrossValidationResult:
    """互验主入口。retry_once 为 RETRY 后的仲裁轮结果（若提供则按其再判一次）。"""
    if retry_once is not None:
        # 仲裁轮：以重查结果替换可靠性较低的通道（检索通道），再判
        return _decide(graph, retry_once, is_retry=True)
    return _decide(graph, rag, is_retry=False)


def _decide(a: ChannelResult, b: ChannelResult, is_retry: bool) -> CrossValidationResult:
    agreed = sorted(set(a.ids) & set(b.ids))
    only_a, only_b = sorted(set(a.ids) - set(b.ids)), sorted(set(b.ids) - set(a.ids))

    if not a.ids and not b.ids:
        return CrossValidationResult(verdict=Verdict.REJECTED, confidence=0.0,
                                     conflict={"reason": "双通道均无结论"})
    if agreed:
        both_evidence = a.has_evidence and b.has_evidence
        # 置信度：一致比例 × 证据完备度
        jaccard = len(agreed) / len(set(a.ids) | set(b.ids))
        conf = round(jaccard * (1.0 if both_evidence else 0.6), 4)
        return CrossValidationResult(
            verdict=Verdict.ACCEPTED if both_evidence else Verdict.DEGRADED,
            agreed_ids=agreed, confidence=conf,
        )
    # 无交集：冲突
    if not is_retry:
        return CrossValidationResult(verdict=Verdict.RETRY,
                                     conflict={"graph_only": only_a, "rag_only": only_b})
    return CrossValidationResult(
        verdict=Verdict.REJECTED, confidence=0.0,
        conflict={"reason": "仲裁重查后仍冲突", "graph_side": only_a, "rag_side": only_b,
                  "graph_evidence": a.evidences[:3], "rag_evidence": b.evidences[:3]},
    )
