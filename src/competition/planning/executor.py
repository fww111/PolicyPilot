# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Plan executor with per-step traces (plan section 9.2).

Executes a validated plan against a scenario under an explicit availability
window (permission/revocation is injected here, never read from plan args).
Every step leaves a trace entry: status, summary, anchors touched. The final
EMIT_DECISION reuses ``build_decision_record`` so planned execution and direct
evaluation produce identical decision packs.
"""

from dataclasses import dataclass, field
from typing import Literal

from competition.contracts.decisions import DecisionRecord
from competition.pipeline.decision import (
    MeasurementOutcome,
    build_decision_record,
    evaluate_measurement,
)
from competition.pipeline.ingestion import IngestedScenario
from competition.planning.operations import Plan, PlanOp, PlanStep, validate_plan

StepStatus = Literal["ok", "failed", "rejected"]


@dataclass(frozen=True)
class StepTrace:
    step_id: str
    op: PlanOp
    status: StepStatus
    summary: str
    anchors_touched: tuple[str, ...] = ()


@dataclass
class ExecutionTrace:
    plan_id: str
    goal: str
    steps: list[StepTrace] = field(default_factory=list)
    decision: DecisionRecord | None = None
    outcomes: list[MeasurementOutcome] = field(default_factory=list)
    rejection: str | None = None


def execute_plan(
    plan: Plan,
    scenario: IngestedScenario,
    *,
    revoked_anchor_ids: frozenset[str] = frozenset(),
) -> ExecutionTrace:
    """Validate then execute; invalid plans are rejected before any step runs."""

    issues = validate_plan(plan)
    if issues:
        return ExecutionTrace(
            plan_id=plan.plan_id,
            goal=plan.goal,
            rejection="; ".join(f"{issue.code}: {issue.detail}" for issue in issues),
        )

    all_anchor_ids = frozenset(scenario.anchors) - revoked_anchor_ids
    trace = ExecutionTrace(plan_id=plan.plan_id, goal=plan.goal)

    batch_no = _batch_from_find_step(plan.steps[0])
    batch_measurements = [m for m in scenario.measurements if m.batch_no == batch_no]
    usable = [m for m in batch_measurements if m.anchor_id in all_anchor_ids]
    trace.steps.append(
        StepTrace(
            "s1",
            PlanOp.FIND_MEASUREMENTS,
            "ok" if usable else "failed",
            f"{len(usable)}/{len(batch_measurements)} measurement rows usable",
            tuple(m.anchor_id for m in usable),
        )
    )

    missing_items: list[str] = []
    if not usable:
        for m in batch_measurements:
            missing_items.append(f"measurement row {m.row_no} unavailable (evidence withdrawn)")

    outcomes = [evaluate_measurement(m, scenario, all_anchor_ids) for m in usable]
    for outcome in outcomes:
        anchors = [outcome.measurement.anchor_id]
        if outcome.clause is not None:
            anchors.append(outcome.clause.anchor_id)
        trace.steps.append(
            StepTrace(
                "s2",
                PlanOp.SELECT_CLAUSE,
                "ok",
                f"row {outcome.measurement.row_no}: {outcome.applicability.reason}",
                tuple(anchors),
            )
        )
        trace.steps.append(
            StepTrace(
                "s3",
                PlanOp.CHECK_CALIBRATION,
                "ok",
                f"row {outcome.measurement.row_no}: {outcome.calibration.reason}",
                (),
            )
        )
        trace.steps.append(
            StepTrace(
                "s4",
                PlanOp.CHECK_TOLERANCE,
                "ok" if outcome.tolerance is not None else "failed",
                f"row {outcome.measurement.row_no}: {outcome.tolerance.reason if outcome.tolerance else 'no applicable clause'}",
                (),
            )
        )
    trace.outcomes = outcomes

    directions = {outcome.direction for outcome in outcomes} or {"unknown"}
    trace.steps.append(
        StepTrace("s5", PlanOp.AGGREGATE_BATCH, "ok", f"directions observed: {sorted(directions)}", ())
    )

    if outcomes:
        decision = build_decision_record(batch_no, outcomes, missing_items, scenario, all_anchor_ids)
    else:
        decision = _revoked_decision(scenario, batch_no, missing_items)
    trace.decision = decision
    trace.steps.append(
        StepTrace(
            "s6",
            PlanOp.EMIT_DECISION,
            "ok",
            f"status={decision.status}, evidence items={len(decision.evidence)}",
            tuple(aid for item in decision.evidence for aid in item.anchor_ids),
        )
    )
    return trace


def _batch_from_find_step(step: PlanStep) -> str:
    return str(step.args["batch_no"])


def _revoked_decision(scenario: IngestedScenario, batch_no: str, missing_items: list[str]) -> DecisionRecord:
    """All measurements revoked: revoking every anchor yields the all-revoked pack."""

    from competition.pipeline.decision import evaluate_t1  # local import avoids cycle at module load

    return evaluate_t1(scenario, batch_no, revoked_anchor_ids=frozenset(scenario.anchors))
