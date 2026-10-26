# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Decision log, partial replay and the publication gate (plan sections 8.2/8.3).

- ``view_scenario`` produces a timeline view: the same scenario with a
  filtered clause set, simulating "which versions were registered at time t".
  Re-importing an old file never revives a retired rule because clause
  selection is driven by effective_from, not arrival order.
- ``replay_affected`` recomputes ONLY needs_review decisions and keeps the
  rest verbatim; ``replay_full`` recomputes everything as the H2 reference.
- ``publish`` is verify-then-switch. Its decisive regression check is the
  IMPACT-LEAK detector: if a batch classified as unaffected changes status
  under full recomputation, the impact closure was incomplete and the
  publication must roll back (plan 8.3: propagation may be incomplete; verify
  against full recomputation).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal

from competition.contracts.changes import ChangeSet
from competition.contracts.decisions import DecisionRecord
from competition.evolution.changeset import ClauseDiff, build_changeset
from competition.pipeline.decision import evaluate_t1
from competition.pipeline.ingestion import IngestedScenario

if TYPE_CHECKING:
    from competition.evolution.impact import DecisionImpact

PUBLISH_TIME = datetime(2026, 11, 1, 9, 0, 0)


@dataclass(frozen=True)
class LoggedDecision:
    decision: DecisionRecord
    batch_no: str
    order_date: date


@dataclass
class DecisionLog:
    entries: list[LoggedDecision] = field(default_factory=list)

    @classmethod
    def from_scenario(cls, scenario: IngestedScenario, batches: list[str]) -> "DecisionLog":
        log = cls()
        for batch_no in batches:
            decision = evaluate_t1(scenario, batch_no)
            order_date = next(m.order_date for m in scenario.measurements if m.batch_no == batch_no)
            log.entries.append(LoggedDecision(decision, batch_no, order_date))
        return log

    def by_batch(self, batch_no: str) -> LoggedDecision:
        return next(entry for entry in self.entries if entry.batch_no == batch_no)


def view_scenario(scenario: IngestedScenario, include_versions: set[tuple[str, str]]) -> IngestedScenario:
    """Timeline view of a scenario with only the given standard versions registered."""

    clauses = [c for c in scenario.clauses if (c.standard_id, c.version) in include_versions]
    standard_clauses = [
        c for c in scenario.standard_clauses if (c.standard_id, c.version) in include_versions
    ]
    return replace(scenario, clauses=clauses, standard_clauses=standard_clauses)


@dataclass
class ReplayResult:
    recomputed: dict[str, DecisionRecord] = field(default_factory=dict)  # batch -> new record
    kept: set[str] = field(default_factory=set)
    status_changes: list[tuple[str, str, str]] = field(default_factory=list)  # (batch, old, new)


def replay_affected(log: DecisionLog, target: IngestedScenario, impacts: list[DecisionImpact]) -> ReplayResult:
    """Partial recomputation: only needs_review batches are re-evaluated."""

    result = ReplayResult()
    review_ids = {impact.decision_id for impact in impacts if impact.verdict == "needs_review"}
    for logged in log.entries:
        if logged.decision.decision_id in review_ids:
            new_record = evaluate_t1(target, logged.batch_no)
            result.recomputed[logged.batch_no] = new_record
            if new_record.status != logged.decision.status:
                result.status_changes.append(
                    (logged.batch_no, logged.decision.status, new_record.status)
                )
        else:
            result.kept.add(logged.batch_no)
    return result


def replay_full(log: DecisionLog, target: IngestedScenario) -> ReplayResult:
    """Reference recomputation of every batch (H2 comparison baseline)."""

    result = ReplayResult()
    for logged in log.entries:
        new_record = evaluate_t1(target, logged.batch_no)
        result.recomputed[logged.batch_no] = new_record
        if new_record.status != logged.decision.status:
            result.status_changes.append(
                (logged.batch_no, logged.decision.status, new_record.status)
            )
    return result


@dataclass
class PublishOutcome:
    status: Literal["published", "rolled_back"]
    changeset: ChangeSet | None = None
    new_log: DecisionLog | None = None
    replay: ReplayResult | None = None
    reason: str = ""

    @property
    def published(self) -> bool:
        return self.status == "published"


def publish(
    log: DecisionLog,
    target: IngestedScenario,
    diffs: list[ClauseDiff],
    impacts: list[DecisionImpact],
) -> PublishOutcome:
    """Verify-then-switch publication gate (plan 8.2 steps 5-8).

    Regression checks before the switch:
    1. every new clause anchor is available (a standard pointing at missing
       evidence cannot adjudicate);
    2. local (partial) replay agrees with full recomputation on reviewed
       batches;
    3. IMPACT LEAK: no batch classified as unaffected may change status under
       full recomputation — if it does, the closure was incomplete and we
       roll back instead of publishing a partially-updated state.
    """

    # Check 1: anchor availability of new clauses.
    for diff in diffs:
        if diff.new is not None and diff.new.anchor_id not in target.anchors:
            return PublishOutcome(
                status="rolled_back",
                reason=f"new clause {diff.standard_id}@{diff.new.version}#{diff.new.clause_no} "
                f"references missing anchor {diff.new.anchor_id}",
            )

    local = replay_affected(log, target, impacts)
    full = replay_full(log, target)

    # Check 2: partial and full replay agree on reviewed batches.
    for batch, local_record in local.recomputed.items():
        if local_record.status != full.recomputed[batch].status:
            return PublishOutcome(
                status="rolled_back",
                reason=f"partial replay disagrees with full replay on batch {batch}",
            )

    # Check 3: impact leak — unaffected batches must be stable under full replay.
    leaks = [change for change in full.status_changes if change[0] in local.kept]
    if leaks:
        batch, old_status, new_status = leaks[0]
        return PublishOutcome(
            status="rolled_back",
            reason=f"impact leak: batch {batch} classified unaffected but would change "
            f"{old_status} -> {new_status} under full recomputation",
        )

    non_cosmetic = [diff for diff in diffs if not diff.is_cosmetic_only]
    review_ids = sorted(
        impact.decision_id for impact in impacts if impact.verdict == "needs_review"
    )
    if not non_cosmetic:
        # Cosmetic-only publication: nothing to re-review, keep the log verbatim.
        changeset = build_changeset(diffs[0], [], "cosmetic publication", PUBLISH_TIME)
        return PublishOutcome(
            status="published",
            changeset=changeset.model_copy(update={"regression_result": "passed", "reviewer": "auto-gate"}),
            new_log=log,
            replay=local,
        )

    changeset = build_changeset(non_cosmetic[0], review_ids, "standard publication", PUBLISH_TIME)
    published_changeset = changeset.model_copy(
        update={"regression_result": "passed", "reviewer": "auto-gate"}
    )
    new_log = DecisionLog(
        entries=[
            LoggedDecision(local.recomputed.get(e.batch_no, e.decision), e.batch_no, e.order_date)
            if e.batch_no in local.recomputed
            else e
            for e in log.entries
        ]
    )
    return PublishOutcome(
        status="published",
        changeset=published_changeset,
        new_log=new_log,
        replay=local,
    )
