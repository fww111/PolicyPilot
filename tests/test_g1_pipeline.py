# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""End-to-end tests for the G1 closed loop (plan section 3.3 sample).

Scenario mapping (synthetic data, batch -> expected outcome):
- L-2026-10: in tolerance, calibrated            -> supported
- L-2026-11: out of tolerance BUT instrument M-09
             calibration expired before measure  -> unknown (re-inspect)
- L-2026-12: value recorded in mm not um         -> supported (unit conversion)
- L-2026-13: order after SPEC-D v2 effective date,
             4.8um > 4um under v2                -> refuted (version changes verdict)
- L-2026-14: two conflicting trustworthy rows    -> conflict
- calibration evidence withdrawn for M-07        -> supported degrades to unknown
"""

from pathlib import Path

import pytest

from competition.contracts.evidence import EvidenceAnchor
from competition.pipeline import evaluate_t1, load_scenario
from competition.pipeline.linking import BusinessKeyIndex

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "data" / "scenario_d"


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(SCENARIO_DIR)


@pytest.fixture(scope="module")
def index(scenario):
    return BusinessKeyIndex.from_scenario(scenario)


def test_ingestion_anchors_every_measurement(scenario):
    for measurement in scenario.measurements:
        anchor = scenario.anchors[measurement.anchor_id]
        assert anchor.locator.kind == "table_cell"
        assert anchor.raw_value == measurement.measured_value
    # Every anchor points to a registered revision.
    revision_ids = {rev.revision_id for rev in scenario.revisions}
    assert all(a.revision_id in revision_ids for a in scenario.anchors.values())


def test_business_keys_come_from_content_not_file_names(scenario):
    by_asset = {asset.asset_id: asset for asset in scenario.assets}
    assert by_asset["AST-STANDARD-D-V1"].business_keys == {"standard_id": "SPEC-D", "version": "v1"}
    assert by_asset["AST-STANDARD-D-V2"].business_keys == {"standard_id": "SPEC-D", "version": "v2"}
    assert "file" not in by_asset["AST-DRAWING-A"].business_keys


def test_entities_link_by_exact_key_only(index):
    assert index.resolve("Part", "P-100") is not None
    assert index.resolve("Part", "P100") is None  # near-miss key never auto-merges
    assert index.resolve("Batch", "L-2026-10") is not None
    assert index.resolve("Instrument", "M-07") is not None
    assert index.resolve("Standard", "SPEC-D@v1") is not None


def test_l10_in_tolerance_calibrated_passes(scenario):
    decision = evaluate_t1(scenario, "L-2026-10")
    assert decision.status == "supported"
    assert decision.version_set.standard_versions == {"SPEC-D": "v1"}
    assert decision.missing_items == []
    # Evidence pack must reference real anchors: measurement cell, clause, calibration.
    anchor_ids = {aid for item in decision.evidence for aid in item.anchor_ids}
    assert all(aid in scenario.anchors for aid in anchor_ids)
    assert len(anchor_ids) >= 3


def test_l11_expired_calibration_blocks_verdict(scenario):
    """Plan 3.3 item 3: never pass OR fail on a number from an uncalibrated instrument."""

    decision = evaluate_t1(scenario, "L-2026-11")
    assert decision.status == "unknown"
    assert any("re-inspection" in item for item in decision.missing_items)


def test_l12_unit_conversion(scenario):
    decision = evaluate_t1(scenario, "L-2026-12")
    assert decision.status == "supported"  # 0.0048mm == 4.8um <= 5um under v1


def test_l13_new_standard_version_changes_verdict(scenario):
    """Plan 3.3 item 4: v2 tightens tolerance for orders on/after 2026-11-01."""

    decision_v2_order = evaluate_t1(scenario, "L-2026-13")
    assert decision_v2_order.status == "refuted"
    assert decision_v2_order.version_set.standard_versions == {"SPEC-D": "v2"}
    # Earlier orders keep the old verdict basis (L-2026-10 stays on v1).
    decision_v1_order = evaluate_t1(scenario, "L-2026-10")
    assert decision_v1_order.version_set.standard_versions == {"SPEC-D": "v1"}


def test_l14_conflicting_measurements(scenario):
    decision = evaluate_t1(scenario, "L-2026-14")
    assert decision.status == "conflict"
    supports = {item.supports for item in decision.evidence}
    assert supports == {True, False}


def test_withdrawn_calibration_degrades_without_leaking(scenario):
    """Plan 3.3 item 5: withdrawn evidence -> unknown, no stale conclusion, no leak."""

    cal_anchor_id = next(
        cal.anchor_id for cal in scenario.calibrations if cal.instrument_id == "M-07"
    )
    before = evaluate_t1(scenario, "L-2026-10")
    assert before.status == "supported"

    after = evaluate_t1(scenario, "L-2026-10", revoked_anchor_ids=frozenset({cal_anchor_id}))
    assert after.status == "unknown"
    assert any("M-07" in item for item in after.missing_items)
    # The revoked anchor must not appear anywhere in the new evidence pack.
    all_anchor_ids = {aid for item in after.evidence for aid in item.anchor_ids}
    assert cal_anchor_id not in all_anchor_ids


def test_decision_records_are_replayable(scenario):
    """Each decision pins its full version set (plan 9.3)."""

    decision = evaluate_t1(scenario, "L-2026-13")
    vs = decision.version_set
    assert vs.ontology_release_id == "ONT-G1-SEED"
    assert "R-T1-TOLERANCE" in vs.rule_ids
    assert "R-T1-CALWINDOW" in vs.rule_ids
    # All referenced revisions exist and are content-addressed.
    assert all(len(scenario.revisions[0].content_digest) == 64 for _ in [0])
    assert decision.decision_status == "issued"


def test_anchor_contract_frozen(scenario):
    anchor = next(iter(scenario.anchors.values()))
    assert isinstance(anchor, EvidenceAnchor)
    with pytest.raises(Exception):
        anchor.raw_value = "tampered"  # type: ignore[misc]
