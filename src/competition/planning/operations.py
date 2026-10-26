# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restricted plan representation (plan section 9.2).

A plan is a sequence of REGISTERED operations only — the LLM (or a template)
instantiates a plan, it never invents operations or free-form queries. Plans
are validated BEFORE execution:

- every operation is registered with its required argument keys;
- dependency references exist and contain no cycles;
- the step count stays within budget;
- the step shape matches a known template (G1/G2 use the fixed T1 shape;
  free DAG planning over arbitrary ops arrives with the graph service).

Dynamic bindings (e.g. which clause applies to which measurement) are resolved
by the executor from prior step outputs, never from plan arguments.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PlanOp(str, Enum):
    FIND_MEASUREMENTS = "find_measurements"
    SELECT_CLAUSE = "select_applicable_clause"
    CHECK_CALIBRATION = "check_calibration"
    CHECK_TOLERANCE = "check_tolerance"
    AGGREGATE_BATCH = "aggregate_batch"
    EMIT_DECISION = "emit_decision"


# Required argument keys per operation; unknown keys are rejected as typos.
OP_SIGNATURES: dict[PlanOp, frozenset[str]] = {
    PlanOp.FIND_MEASUREMENTS: frozenset({"batch_no"}),
    PlanOp.SELECT_CLAUSE: frozenset({"resolution"}),
    PlanOp.CHECK_CALIBRATION: frozenset({"resolution"}),
    PlanOp.CHECK_TOLERANCE: frozenset({"resolution"}),
    PlanOp.AGGREGATE_BATCH: frozenset(),
    PlanOp.EMIT_DECISION: frozenset(),
}

# Allowed "resolution" values: how an op fans out over prior-step outputs.
RESOLUTIONS = frozenset({"per_measurement"})

MAX_STEPS = 12


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    op: PlanOp
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    plan_id: str
    goal: str
    steps: tuple[PlanStep, ...]


# The T1 template shape: find -> per-measurement checks -> aggregate -> emit.
T1_SHAPE: tuple[PlanOp, ...] = (
    PlanOp.FIND_MEASUREMENTS,
    PlanOp.SELECT_CLAUSE,
    PlanOp.CHECK_CALIBRATION,
    PlanOp.CHECK_TOLERANCE,
    PlanOp.AGGREGATE_BATCH,
    PlanOp.EMIT_DECISION,
)


def t1_plan(batch_no: str) -> Plan:
    """Instantiate the validated T1 template for one batch."""

    return Plan(
        plan_id=f"PLAN-T1-{batch_no}",
        goal=f"T1 tolerance check for batch {batch_no}",
        steps=(
            PlanStep("s1", PlanOp.FIND_MEASUREMENTS, {"batch_no": batch_no}, ()),
            PlanStep("s2", PlanOp.SELECT_CLAUSE, {"resolution": "per_measurement"}, ("s1",)),
            PlanStep("s3", PlanOp.CHECK_CALIBRATION, {"resolution": "per_measurement"}, ("s1",)),
            PlanStep("s4", PlanOp.CHECK_TOLERANCE, {"resolution": "per_measurement"}, ("s2", "s3")),
            PlanStep("s5", PlanOp.AGGREGATE_BATCH, (), ("s4",)),
            PlanStep("s6", PlanOp.EMIT_DECISION, (), ("s5",)),
        ),
    )


@dataclass(frozen=True)
class PlanIssue:
    code: str
    detail: str


def validate_plan(plan: Plan) -> list[PlanIssue]:
    """Static validation; a plan with any issue must never reach execution."""

    issues: list[PlanIssue] = []
    if len(plan.steps) > MAX_STEPS:
        issues.append(PlanIssue("budget", f"{len(plan.steps)} steps exceed budget {MAX_STEPS}"))

    step_ids = [step.step_id for step in plan.steps]
    if len(step_ids) != len(set(step_ids)):
        issues.append(PlanIssue("duplicate_step_id", "step ids must be unique"))

    seen: set[str] = set()
    for step in plan.steps:
        if step.op not in OP_SIGNATURES:
            issues.append(PlanIssue("unregistered_op", f"{step.step_id}: {step.op} is not registered"))
            continue
        required = OP_SIGNATURES[step.op]
        missing = required - set(step.args)
        if missing:
            issues.append(PlanIssue("missing_arg", f"{step.step_id}: missing args {sorted(missing)}"))
        unknown = set(step.args) - required
        if unknown:
            issues.append(PlanIssue("unknown_arg", f"{step.step_id}: unknown args {sorted(unknown)}"))
        if "resolution" in step.args and step.args["resolution"] not in RESOLUTIONS:
            issues.append(PlanIssue("bad_resolution", f"{step.step_id}: resolution must be one of {sorted(RESOLUTIONS)}"))
        for dep in step.depends_on:
            if dep not in step_ids:
                issues.append(PlanIssue("unknown_dep", f"{step.step_id}: depends on unknown step {dep}"))
        # Cycles: dependencies may only point backwards in step order.
        if any(dep not in seen for dep in step.depends_on if dep in step_ids):
            issues.append(PlanIssue("forward_dep", f"{step.step_id}: dependencies must precede it"))
        seen.add(step.step_id)

    if tuple(step.op for step in plan.steps) != T1_SHAPE:
        issues.append(PlanIssue("shape", f"step shape must match the registered T1 template"))
    return issues
