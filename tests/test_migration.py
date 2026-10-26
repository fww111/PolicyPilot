# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Migration experiment: second product family / organization template (plan 3.4, task N18).

Organization B records shafts under SPEC-E with its own column spellings
(lot_no/article/reading/...), gauge numbering and native mm values. The whole
T1/T2 chain must run with ZERO template-specific code — the only additions
are the scenario files plus a column-mapping block in their manifest.
"""

import importlib.util
from pathlib import Path

import pytest

from competition.evolution import DecisionLog, analyze_impact, diff_standards, view_scenario
from competition.pipeline import evaluate_t1, load_scenario

COMPETITION_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_B_DIR = COMPETITION_ROOT / "data" / "scenario_e"
BATCHES_B = ["N-1001", "N-1002", "N-1003", "N-1004"]


@pytest.fixture(scope="module")
def scenario_b():
    return load_scenario(TEMPLATE_B_DIR)


# ------------------------------------------------------------ ingestion via mapping

def test_loads_organization_b_columns(scenario_b):
    assert len(scenario_b.measurements) == 4
    first = scenario_b.measurements[0]
    assert first.batch_no == "N-1001"
    assert first.part_no == "SHF-200"
    assert first.unit == "mm"
    # Anchors keep the template's OWN header spelling and column order.
    anchor = scenario_b.anchors[first.anchor_id]
    assert anchor.locator.kind == "table_cell"
    assert anchor.locator.column_header == "reading"   # file spelling, not 'measured_value'
    assert anchor.locator.column == 5
    # Standard assets carry their own identity.
    standard = next(a for a in scenario_b.assets if a.asset_id == "AST-STANDARD-E-V1")
    assert standard.business_keys == {"standard_id": "SPEC-E", "version": "v1"}


def test_missing_mapping_column_is_rejected(tmp_path):
    src = TEMPLATE_B_DIR
    target = tmp_path / "broken"
    target.mkdir()
    for name in ("drawing_e.json", "inspection_e.csv", "calibration_e.json",
                 "standard_e_v1.json", "standard_e_v2.json"):
        (target / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")
    import json

    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    del manifest["inspection_columns"]["measured_value"]  # mapping now misses a field
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="misses standard fields"):
        load_scenario(target)


# ------------------------------------------------------------ T1 on template B

def test_t1_all_batches(scenario_b):
    expected = {
        "N-1001": "supported",  # 0.0072 <= 0.010, gauge INS-31 calibrated
        "N-1002": "refuted",    # 0.0125 > 0.010
        "N-1003": "unknown",    # INS-32 calibration ended 09-30, measured 10-08
        "N-1004": "refuted",    # order 11-20 under SPEC-E v2 (0.008); 0.0090 exceeds
    }
    for batch, status in expected.items():
        decision = evaluate_t1(scenario_b, batch)
        assert decision.status == status, f"{batch}: expected {status}, got {decision.status}"


def test_version_applicability_changes_verdict_on_template_b(scenario_b):
    t0 = view_scenario(scenario_b, {("SPEC-E", "v1")})
    historical = evaluate_t1.__wrapped__ if False else evaluate_t1(t0, "N-1004")
    assert historical.status == "supported"          # 0.0090 <= 0.010 under v1
    current = evaluate_t1(scenario_b, "N-1004")
    assert current.status == "refuted"               # v2 applies from 2026-11-15
    assert current.version_set.standard_versions == {"SPEC-E": "v2"}


# ------------------------------------------------------------ T2 on template B

def test_t2_impact_analysis_on_new_standard(scenario_b):
    t0 = view_scenario(scenario_b, {("SPEC-E", "v1")})
    log = DecisionLog.from_scenario(t0, BATCHES_B)
    v1 = [c for c in scenario_b.clauses if c.version == "v1"]
    v2 = [c for c in scenario_b.clauses if c.version == "v2"]
    diffs = diff_standards(v1, v2, "SPEC-E")
    impacts = analyze_impact(log.entries, diffs)

    by_batch = {entry.batch_no: impact for entry, impact in zip(log.entries, impacts)}
    assert by_batch["N-1004"].verdict == "needs_review"          # order 11-20 >= 11-15
    for batch in ("N-1001", "N-1002", "N-1003"):
        assert by_batch[batch].verdict == "applicable_unchanged"


# ------------------------------------------------------------ zero template-specific code

def test_no_template_specific_code_in_core_modules():
    """Hard proof of reuse: core sources contain none of template B's literals."""

    forbidden = ("SHF-200", "N-1001", "SPEC-E", "lot_no", "INS-31", "RUN-1")
    for source_file in (COMPETITION_ROOT / "src").rglob("*.py"):
        text = source_file.read_text(encoding="utf-8")
        for literal in forbidden:
            assert literal not in text, f"{source_file.name} references template-B literal {literal!r}"


def test_skill_entry_point_is_reusable_for_template_b():
    """The cross-document-check skill script runs unchanged on the new template."""

    script = COMPETITION_ROOT / "skills" / "cross-document-check" / "scripts" / "run_check.py"
    spec = importlib.util.spec_from_file_location("run_check_migration", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pack = module.run({"batch_no": "N-1001"}, TEMPLATE_B_DIR)
    assert pack["status"] == "supported"
    assert pack["version_set"]["standard_versions"] == {"SPEC-E": "v1"}
