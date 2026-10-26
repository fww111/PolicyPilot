# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tests for controlled self-evolution (plan section 11, hypothesis H3).

Story: an optimization-set batch recorded in 'micron' fails with unknown ->
diagnosis blames unit normalization -> a restricted alias patch is proposed,
audited, verified in isolation (new gain + zero regression) and released as
skill 0.2.0. Anti-cheat: answer smuggling, locked-test sourcing and
regression-inducing factors are all intercepted before release.
"""

from datetime import datetime
from pathlib import Path

import pytest

from competition.adaptation import (
    PROPOSED_FACTORS,
    SkillConfig,
    SkillPatch,
    diagnose_failure,
    release_skill_patch,
    rollback_release,
    verify_patch,
)
from competition.contracts.changes import SkillRelease
from competition.pipeline import evaluate_t1, load_scenario

BASE_DIR = Path(__file__).resolve().parents[1] / "data" / "scenario_d"
OPT_DIR = Path(__file__).resolve().parents[1] / "data" / "scenario_d_opt"

LOCKED_CASES = frozenset({"LOCK-T1-001", "LOCK-T1-002"})
BASELINE = {
    "L-2026-10": "supported",
    "L-2026-11": "unknown",
    "L-2026-12": "supported",
    "L-2026-13": "refuted",
    "L-2026-14": "conflict",
}


@pytest.fixture(scope="module")
def base():
    return load_scenario(BASE_DIR)


@pytest.fixture(scope="module")
def opt():
    return load_scenario(OPT_DIR)


def _current_release() -> SkillRelease:
    return SkillRelease(
        release_id="SKR-CDC-0",
        skill_name="cross-document-check",
        version="0.1.0",
        tool_contract_version="tc@1",
        ontology_scope=["ONT-G1-SEED"],
        rule_versions=["R-T1-APPLICABILITY", "R-T1-TOLERANCE", "R-T1-CALWINDOW"],
        acceptance_set_id="ACC-CDC",
    )


def _micron_patch() -> SkillPatch:
    return SkillPatch(
        patch_id="P1",
        skill_name="cross-document-check",
        kind="unit_alias",
        payload={"alias": "micron", "factor_to_mm": PROPOSED_FACTORS["micron"]},
        rationale="optimization batch L-2026-16 recorded in micron spelling",
        source_case="OPT-L-2026-16",
        created_at=datetime(2026, 10, 25, 16, 0, 0),
    )


def _resolver(base_scenario):
    def resolve(config: SkillConfig, batch: str) -> str:
        return evaluate_t1(base_scenario, batch, unit_factors=config.unit_factors).status

    return resolve


# ------------------------------------------------------------ failure & diagnosis

def test_micron_batch_fails_with_unknown(opt):
    decision = evaluate_t1(opt, "L-2026-16")
    assert decision.status == "unknown"
    assert any("cannot convert" in item and "micron" in item for item in decision.missing_items)


def test_diagnosis_blames_unit_layer_and_proposes_patch(opt):
    decision = evaluate_t1(opt, "L-2026-16")
    diagnosis = diagnose_failure(decision, "OPT-L-2026-16")
    assert diagnosis.responsible_layer == "unit_normalization"
    assert diagnosis.suggested_patch is not None
    assert diagnosis.suggested_patch.kind == "unit_alias"


def test_data_problems_do_not_become_skill_patches(base):
    """Plan 11.2 step 2: missing calibration is a data problem, not a prompt fix."""

    decision = evaluate_t1(base, "L-2026-11")
    diagnosis = diagnose_failure(decision, "OPT-L-2026-11")
    assert diagnosis.responsible_layer == "calibration_evidence"
    assert diagnosis.suggested_patch is None


# ------------------------------------------------------------ verification gate

def test_good_patch_passes_double_gate(base, opt):
    report = verify_patch(
        _micron_patch(),
        baseline_cases=BASELINE,
        target_scenario=opt,
        target_batch="L-2026-16",
        locked_case_ids=LOCKED_CASES,
        baseline_resolver=_resolver(base),
    )
    assert report.passed, report.rejected_reason
    assert report.target_case_fixed
    assert report.regressions == []


def test_release_bumps_version_and_supersedes():
    current = _current_release()
    report = verify_patch(
        _micron_patch(),
        baseline_cases=BASELINE,
        target_scenario=load_scenario(OPT_DIR),
        target_batch="L-2026-16",
        locked_case_ids=LOCKED_CASES,
        baseline_resolver=_resolver(load_scenario(BASE_DIR)),
    )
    released, reason = release_skill_patch(current, _micron_patch(), report)
    assert released is not None, reason
    assert released.version == "0.2.0"
    assert released.supersedes_release_id == current.release_id
    assert released.published_at is not None


# ------------------------------------------------------------ anti-cheat & interception

def test_answer_smuggling_patch_is_rejected(base, opt):
    smuggler = SkillPatch(
        patch_id="P2",
        skill_name="cross-document-check",
        kind="unit_alias",
        payload={"alias": "micron", "factor_to_mm": 1e-3, "verdict": "supported"},
        rationale="make the case pass",
        source_case="OPT-L-2026-16",
        created_at=datetime(2026, 10, 25, 16, 0, 0),
    )
    report = verify_patch(
        smuggler, BASELINE, opt, "L-2026-16", LOCKED_CASES, _resolver(base)
    )
    assert not report.passed
    assert "answer_smuggling" in report.rejected_reason


def test_locked_test_sourced_patch_is_rejected(base, opt):
    leaky = SkillPatch(
        patch_id="P3",
        skill_name="cross-document-check",
        kind="unit_alias",
        payload={"alias": "micron", "factor_to_mm": 1e-3},
        rationale="derived from locked test",
        source_case="LOCK-T1-001",
        created_at=datetime(2026, 10, 25, 16, 0, 0),
    )
    report = verify_patch(
        leaky, BASELINE, opt, "L-2026-16", LOCKED_CASES, _resolver(base)
    )
    assert not report.passed
    assert "locked_test_source" in report.rejected_reason


def test_regression_inducing_patch_is_intercepted(base, opt):
    """A wrong factor flips a baseline batch: zero-regression gate blocks release."""

    bad_factor = SkillPatch(
        patch_id="P4",
        skill_name="cross-document-check",
        kind="unit_alias",
        payload={"alias": "um", "factor_to_mm": 100.0},  # um treated as decimetres
        rationale="mistaken factor",
        source_case="OPT-L-2026-16",
        created_at=datetime(2026, 10, 25, 16, 0, 0),
    )
    report = verify_patch(
        bad_factor, BASELINE, opt, "L-2026-16", LOCKED_CASES, _resolver(base)
    )
    assert not report.passed
    regressed = {case for case, _, _ in report.regressions}
    assert "L-2026-10" in regressed  # 4.8um misread as 480mm -> supported flips

    released, reason = release_skill_patch(_current_release(), bad_factor, report)
    assert released is None  # old skill version kept verbatim


def test_rollback_restores_previous_release():
    current = _current_release()
    successor = current.model_copy(
        update={"release_id": "SKR-CDC-1", "version": "0.2.0", "supersedes_release_id": current.release_id}
    )
    restored = rollback_release(successor, current)
    assert restored.version == current.version
    assert restored.release_id == current.release_id
