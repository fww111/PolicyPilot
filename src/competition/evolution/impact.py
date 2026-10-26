# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Impact closure over historical decisions (plan section 8.2 step 3).

Two candidate paths, unioned:

1. Dependency propagation: decisions whose version set references the
   replaced standard version.
2. Predicate scan: decisions whose order date falls inside the NEW clause's
   applicability predicate — this catches objects that never referenced the
   old rule (plan: new clauses / widened scope / added exceptions must take
   path 2).

Verdicts per decision:
- needs_review: predicate covers it -> re-run under the new version set.
- applicable_unchanged: not covered by the new predicate -> keep as is.
- scope_uncertain: the new clause uses an unrecognized scope expression ->
  conservatively widen to needs_review (plan 8.3).
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from competition.evolution.changeset import ClauseDiff
from competition.evolution.replay import LoggedDecision

ImpactVerdict = Literal["needs_review", "applicable_unchanged", "scope_uncertain"]

_KNOWN_SCOPES = frozenset({"all_orders", "orders_on_or_after_effective"})


@dataclass(frozen=True)
class DecisionImpact:
    decision_id: str
    verdict: ImpactVerdict
    path: Literal["dependency_propagation", "predicate_scan", "both", "none"]
    reason: str


def _predicate_covers(new_effective_from: date, order_date: date) -> bool:
    # G1/G2 scope predicates both reduce to: order on/after effective_from.
    return order_date >= new_effective_from


def analyze_impact(
    history: list[LoggedDecision], diffs: list[ClauseDiff]
) -> list[DecisionImpact]:
    impacts: list[DecisionImpact] = []
    for logged in history:
        verdict, path, reason = _classify_decision(logged, diffs)
        impacts.append(DecisionImpact(logged.decision.decision_id, verdict, path, reason))
    return impacts


def _classify_decision(
    logged: LoggedDecision, diffs: list[ClauseDiff]
) -> tuple[ImpactVerdict, Literal["dependency_propagation", "predicate_scan", "both", "none"], str]:
    referenced = logged.decision.version_set.standard_versions  # e.g. {"SPEC-D": "v1"}
    dep_hit = False
    pred_hit = False
    uncertain = False
    reasons: list[str] = []

    for diff in diffs:
        if diff.is_cosmetic_only:
            continue
        replaced_version = diff.old.version if diff.old else None
        depends = any(
            sid == diff.standard_id and version == replaced_version
            for sid, version in referenced.items()
        )
        covered = diff.new is not None and _predicate_covers(diff.new.effective_from, logged.order_date)
        if depends:
            dep_hit = True
            reasons.append(f"references {diff.standard_id}@{replaced_version}")
        if covered:
            pred_hit = True
            reasons.append(
                f"order {logged.order_date} inside new predicate of {diff.standard_id}@{diff.new.version}"  # type: ignore[union-attr]
            )
        if diff.new is not None and diff.new.scope not in _KNOWN_SCOPES:
            uncertain = True
            reasons.append(f"unrecognized scope expression {diff.new.scope!r}")

    if uncertain:
        return "scope_uncertain", "both" if (dep_hit or pred_hit) else "predicate_scan", "; ".join(reasons)
    if dep_hit and pred_hit:
        return "needs_review", "both", "; ".join(reasons)
    if pred_hit:
        return "needs_review", "predicate_scan", "; ".join(reasons)
    if dep_hit:
        # Decision referenced the old version but the new predicate does not
        # cover its order date: keep the verdict (plan 3.3 item 4).
        return "applicable_unchanged", "dependency_propagation", "; ".join(reasons)
    return "applicable_unchanged", "none", "no dependency edge and outside new predicate"
