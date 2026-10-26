# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tests for knowledge evolution (plan section 8, task T2, hypothesis H2).

Timeline driven by the SPEC-D v1 -> v2 publication:
- t0: only v1 registered. Late orders (L-13/L-14, November) pass under v1.
- publication: v2 tightens tolerance to 4um for orders on/after 2026-11-01.
- impact: November batches need review; September batches keep verdicts.
- replay: partial recomputation equals full recomputation; unaffected
  decisions keep their records verbatim.
- gate: missing anchors and impact leaks roll the publication back.
"""

import dataclasses
from pathlib import Path

import pytest

from competition.evolution import (
    ClauseDiff,
    DecisionLog,
    analyze_impact,
    diff_standards,
    publish,
    replay_full,
    view_scenario,
)
from competition.pipeline import evaluate_t1, load_scenario

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "data" / "scenario_d"
BATCHES = ["L-2026-10", "L-2026-11", "L-2026-12", "L-2026-13", "L-2026-14"]


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(SCENARIO_DIR)


@pytest.fixture(scope="module")
def t0_log(scenario):
    t0 = view_scenario(scenario, {("SPEC-D", "v1")})
    return DecisionLog.from_scenario(t0, BATCHES)


@pytest.fixture(scope="module")
def diffs(scenario):
    v1 = [c for c in scenario.clauses if c.version == "v1"]
    v2 = [c for c in scenario.clauses if c.version == "v2"]
    return diff_standards(v1, v2, "SPEC-D")


def test_t0_view_uses_v1_for_late_orders(t0_log):
    """Before v2 exists, November orders pass under v1 (4.8um <= 5um)."""

    assert t0_log.by_batch("L-2026-13").decision.status == "supported"
    assert t0_log.by_batch("L-2026-14").decision.status == "supported"
    assert t0_log.by_batch("L-2026-13").decision.version_set.standard_versions == {"SPEC-D": "v1"}
    # Calibration problem at t0 is orthogonal to the standard change.
    assert t0_log.by_batch("L-2026-11").decision.status == "unknown"


def test_diff_detects_replacement_and_scope_change(diffs):
    assert len(diffs) == 1
    diff = diffs[0]
    assert "replace" in diff.kinds
    assert "attribute_change" in diff.kinds   # 0.005 -> 0.004
    assert "scope_change" in diff.kinds       # all_orders -> post-effective orders
    assert not diff.is_cosmetic_only


def test_impact_classification(t0_log, diffs):
    impacts = analyze_impact(t0_log.entries, diffs)
    by_batch = {e.batch_no: i for e, i in zip(t0_log.entries, impacts)}

    for batch in ("L-2026-10", "L-2026-11", "L-2026-12"):
        assert by_batch[batch].verdict == "applicable_unchanged"
        assert by_batch[batch].path == "dependency_propagation"
    for batch in ("L-2026-13", "L-2026-14"):
        assert by_batch[batch].verdict == "needs_review"
        assert by_batch[batch].path == "both"


def test_publish_partial_replay_matches_full(scenario, t0_log, diffs):
    impacts = analyze_impact(t0_log.entries, diffs)
    outcome = publish(t0_log, scenario, diffs, impacts)
    assert outcome.published, outcome.reason

    full = replay_full(t0_log, scenario)
    # Partial replay touched exactly the reviewed batches and nothing else.
    assert set(outcome.replay.recomputed) == {"L-2026-13", "L-2026-14"}
    assert outcome.replay.kept == {"L-2026-10", "L-2026-11", "L-2026-12"}
    # Equivalence with full recomputation on every batch.
    for batch in BATCHES:
        full_status = full.recomputed[batch].status
        if batch in outcome.replay.recomputed:
            assert outcome.replay.recomputed[batch].status == full_status
        else:
            old = t0_log.by_batch(batch).decision.status
            assert old == full_status  # unaffected batches stable under full replay


def test_publish_status_changes_and_record_identity(scenario, t0_log, diffs):
    impacts = analyze_impact(t0_log.entries, diffs)
    outcome = publish(t0_log, scenario, diffs, impacts)
    assert outcome.published

    changes = {(b, old, new) for b, old, new in outcome.replay.status_changes}
    assert ("L-2026-13", "supported", "refuted") in changes
    assert ("L-2026-14", "supported", "conflict") in changes

    # Unaffected batches keep their original record objects verbatim.
    for batch in ("L-2026-10", "L-2026-11", "L-2026-12"):
        assert outcome.new_log.by_batch(batch).decision is t0_log.by_batch(batch).decision
    # Reviewed batches carry the new version in their pack.
    assert outcome.new_log.by_batch("L-2026-13").decision.version_set.standard_versions == {"SPEC-D": "v2"}

    assert outcome.changeset is not None
    assert outcome.changeset.regression_result == "passed"
    assert outcome.changeset.reviewer == "auto-gate"
    assert set(outcome.changeset.affected_ids) == {
        t0_log.by_batch(b).decision.decision_id for b in ("L-2026-13", "L-2026-14")
    }


def test_publish_rolls_back_on_missing_anchor(scenario, t0_log, diffs):
    v2 = diffs[0].new
    bad_new = dataclasses.replace(v2, anchor_id="ANC-DOES-NOT-EXIST")
    bad_diff = ClauseDiff("SPEC-D", diffs[0].old, bad_new, diffs[0].kinds)
    impacts = analyze_impact(t0_log.entries, [bad_diff])

    outcome = publish(t0_log, scenario, [bad_diff], impacts)
    assert not outcome.published
    assert "missing anchor" in outcome.reason
    assert outcome.new_log is None


def test_publish_rolls_back_on_impact_leak(scenario, t0_log, diffs):
    """Incomplete closure: L-13 wrongly classified unaffected -> leak -> rollback."""

    impacts = analyze_impact(t0_log.entries, diffs)
    sabotaged = [
        dataclasses.replace(i, verdict="applicable_unchanged", path="none")
        if i.decision_id == t0_log.by_batch("L-2026-13").decision.decision_id
        else i
        for i in impacts
    ]
    outcome = publish(t0_log, scenario, diffs, sabotaged)
    assert not outcome.published
    assert "impact leak" in outcome.reason
    assert "L-2026-13" in outcome.reason
    # The old log is untouched: no partially-updated state leaked out.
    assert outcome.new_log is None


def test_unknown_scope_expression_widens_review(t0_log, diffs):
    weird_new = dataclasses.replace(diffs[0].new, scope="regions_per_market_appendix")
    weird = ClauseDiff("SPEC-D", diffs[0].old, weird_new, diffs[0].kinds)
    impacts = analyze_impact(t0_log.entries, [weird])
    # Conservative widening: unrecognized scope forces review territory.
    assert all(i.verdict in ("scope_uncertain", "needs_review") for i in impacts)


def test_reimported_old_version_does_not_revive():
    """Plan 8.3: re-uploading v1 must not resurrect it for November orders."""

    fresh = load_scenario(SCENARIO_DIR)  # isolated copy, no shared-state leakage
    v1_clause = next(c for c in fresh.clauses if c.version == "v1")
    fresh.clauses.append(dataclasses.replace(v1_clause, anchor_id="ANC-REIMPORT-V1"))

    decision = evaluate_t1(fresh, "L-2026-13")
    assert decision.status == "refuted"  # v2 still governs the November order
    assert decision.version_set.standard_versions == {"SPEC-D": "v2"}
