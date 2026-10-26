# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Knowledge evolution: change sets, impact closure, partial replay (plan section 8)."""

from competition.evolution.changeset import ClauseDiff, diff_standards
from competition.evolution.impact import DecisionImpact, ImpactVerdict, analyze_impact
from competition.evolution.replay import (
    DecisionLog,
    LoggedDecision,
    PublishOutcome,
    publish,
    replay_affected,
    replay_full,
    view_scenario,
)

__all__ = [
    "ClauseDiff",
    "DecisionImpact",
    "DecisionLog",
    "ImpactVerdict",
    "LoggedDecision",
    "PublishOutcome",
    "analyze_impact",
    "diff_standards",
    "publish",
    "replay_affected",
    "replay_full",
    "view_scenario",
]
