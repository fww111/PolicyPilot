# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tests for restricted planning and gap-driven retrieval (plan sections 9.1/9.2)."""

from datetime import date
from pathlib import Path

import pytest

from competition.pipeline import evaluate_t1, load_scenario
from competition.planning import (
    Plan,
    PlanOp,
    PlanStep,
    apply_supplementary_calibration,
    derive_retrieval_tasks,
    execute_plan,
    t1_plan,
    validate_plan,
)

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "data" / "scenario_d"


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(SCENARIO_DIR)


# ------------------------------------------------------------ static validation

def test_plan_rejects_unregistered_op():
    plan = Plan(
        plan_id="BAD-1",
        goal="drop tables",
        steps=(PlanStep("s1", PlanOp.FIND_MEASUREMENTS, {"batch_no": "L-2026-10"}),),
    )
    issues = validate_plan(plan)
    assert any(issue.code == "shape" for issue in issues)


def test_plan_rejects_missing_and_unknown_args():
    steps = (
        PlanStep("s1", PlanOp.FIND_MEASUREMENTS, {"batch": "L-2026-10", "extra": 1}),
        PlanStep("s2", PlanOp.SELECT_CLAUSE, {"resolution": "per_measurement"}, ("s1",)),
        PlanStep("s3", PlanOp.CHECK_CALIBRATION, {"resolution": "per_measurement"}, ("s1",)),
        PlanStep("s4", PlanOp.CHECK_TOLERANCE, {"resolution": "per_measurement"}, ("s2", "s3")),
        PlanStep("s5", PlanOp.AGGREGATE_BATCH, (), ("s4",)),
        PlanStep("s6", PlanOp.EMIT_DECISION, (), ("s5",)),
    )
    codes = {issue.code for issue in validate_plan(Plan("BAD-2", "goal", steps))}
    assert "missing_arg" in codes and "unknown_arg" in codes


def test_plan_rejects_forward_dependency():
    steps = (
        PlanStep("s1", PlanOp.FIND_MEASUREMENTS, {"batch_no": "L-2026-10"}, ("s2",)),
        PlanStep("s2", PlanOp.SELECT_CLAUSE, {"resolution": "per_measurement"}, ("s1",)),
        PlanStep("s3", PlanOp.CHECK_CALIBRATION, {"resolution": "per_measurement"}, ("s1",)),
        PlanStep("s4", PlanOp.CHECK_TOLERANCE, {"resolution": "per_measurement"}, ("s2", "s3")),
        PlanStep("s5", PlanOp.AGGREGATE_BATCH, (), ("s4",)),
        PlanStep("s6", PlanOp.EMIT_DECISION, (), ("s5",)),
    )
    assert any(issue.code == "forward_dep" for issue in validate_plan(Plan("BAD-3", "goal", steps)))


def test_executor_rejects_invalid_plan_before_any_step(scenario):
    bad = Plan("BAD-4", "goal", (PlanStep("s1", PlanOp.FIND_MEASUREMENTS, {}),))
    trace = execute_plan(bad, scenario)
    assert trace.rejection is not None
    assert trace.decision is None
    assert trace.steps == []


# ------------------------------------------------------------ execution parity

def test_planned_execution_matches_direct_evaluation(scenario):
    trace = execute_plan(t1_plan("L-2026-10"), scenario)
    direct = evaluate_t1(scenario, "L-2026-10")
    assert trace.rejection is None
    assert trace.decision is not None
    assert trace.decision.status == direct.status == "supported"
    assert trace.decision.decision_id == direct.decision_id
    # Every emitted anchor exists in the scenario (traceability).
    emitted = {aid for step in trace.steps for aid in step.anchors_touched}
    assert all(aid in scenario.anchors for aid in emitted)


def test_trace_records_each_stage(scenario):
    trace = execute_plan(t1_plan("L-2026-13"), scenario)
    ops = [step.op for step in trace.steps]
    assert PlanOp.FIND_MEASUREMENTS in ops
    assert PlanOp.SELECT_CLAUSE in ops
    assert PlanOp.CHECK_CALIBRATION in ops
    assert PlanOp.CHECK_TOLERANCE in ops
    assert PlanOp.EMIT_DECISION in ops
    assert trace.decision.status == "refuted"  # v2 applies, 4.8um > 4um


def test_revocation_flows_through_executor(scenario):
    cal_anchor = next(c.anchor_id for c in scenario.calibrations if c.instrument_id == "M-07")
    trace = execute_plan(t1_plan("L-2026-10"), scenario, revoked_anchor_ids=frozenset({cal_anchor}))
    assert trace.decision is not None
    assert trace.decision.status == "unknown"
    assert cal_anchor not in {aid for step in trace.steps for aid in step.anchors_touched}


# ------------------------------------------------------------ gap-driven loop

def test_unknown_emits_typed_retrieval_tasks(scenario):
    trace = execute_plan(t1_plan("L-2026-11"), scenario)
    assert trace.decision is not None
    assert trace.decision.status == "unknown"
    tasks = derive_retrieval_tasks(trace.outcomes)
    calibration_tasks = [t for t in tasks if t.asset_kind == "calibration"]
    assert calibration_tasks, "expired calibration must produce a calibration gap task"
    task = calibration_tasks[0]
    assert task.target_object == "M-09"
    assert task.time_window == (date(2026, 10, 20), date(2026, 10, 20))
    assert "calibration" in task.purpose


def test_supplemented_evidence_unblocks_verdict():
    """The loop closes: unknown -> ingest missing certificate -> refuted."""

    fresh = load_scenario(SCENARIO_DIR)  # isolated scenario, no shared-state leakage
    trace_before = execute_plan(t1_plan("L-2026-11"), fresh)
    assert trace_before.decision is not None
    assert trace_before.decision.status == "unknown"

    apply_supplementary_calibration(
        fresh,
        instrument_id="M-09",
        certificate_no="CAL-M09-EXT",
        valid_from=date(2026, 9, 1),
        valid_to=date(2026, 12, 31),
    )
    trace_after = execute_plan(t1_plan("L-2026-11"), fresh)
    assert trace_after.decision is not None
    # 52um with a now-trustworthy instrument: credible exceedance -> refuted.
    assert trace_after.decision.status == "refuted"
    assert trace_after.decision.missing_items == []
    # The supplementary certificate is part of the new evidence pack.
    anchor_ids = {aid for item in trace_after.decision.evidence for aid in item.anchor_ids}
    assert "ANC-SUPP-CAL-M09-EXT" in anchor_ids
