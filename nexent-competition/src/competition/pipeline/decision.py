# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""T1 decision pack assembly.

Aggregation rules (quality-conservative, asymmetric by design):

- A batch is ``supported`` (passes) only when EVERY measurement is trustworthy
  (calibration valid, applicable standard found, unit convertible) and within
  tolerance. One unevaluable measurement blocks release — it might hide a
  problem (plan 3.3 item 3: never pass on a number alone).
- A batch is ``refuted`` (fails) when at least ONE trustworthy measurement is
  out of tolerance. A credible exceedance is enough to block.
- ``supported`` and ``refuted`` directions coexisting means conflicting
  evidence → ``conflict``.
- Otherwise, any unevaluable premise → ``unknown`` with concrete missing
  items; withdrawn anchors never leak into the evidence pack (plan 3.3 item 5).

EvidenceItem.supports refers to the pass proposition "batch meets tolerance",
so conflict detection in the DecisionRecord contract aligns naturally.
"""

from dataclasses import dataclass
from typing import Literal

from competition.contracts.decisions import DecisionRecord, EvidenceItem, VersionSet
from competition.pipeline.evaluation import (
    G1_RULES,
    CheckResult,
    TriBool,
    check_calibration,
    check_tolerance,
    select_clause,
)
from competition.pipeline.ingestion import INGEST_TIME, IngestedScenario, MeasurementRecord, ToleranceClause

Direction = Literal["supported", "refuted", "unknown"]

ONTOLOGY_SEED_RELEASE = "ONT-G1-SEED"


@dataclass(frozen=True)
class MeasurementOutcome:
    measurement: MeasurementRecord
    clause: ToleranceClause | None
    applicability: CheckResult
    calibration: CheckResult
    tolerance: CheckResult | None
    direction: Direction


def _measurement_direction(outcome_applicability: CheckResult, calibration: CheckResult, tolerance: CheckResult) -> Direction:
    if outcome_applicability.outcome is not TriBool.TRUE:
        return "unknown"
    if calibration.outcome is not TriBool.TRUE:
        return "unknown"
    if tolerance.outcome is TriBool.UNKNOWN:
        return "unknown"
    return "supported" if tolerance.outcome is TriBool.TRUE else "refuted"


def evaluate_measurement(
    measurement: MeasurementRecord,
    scenario: IngestedScenario,
    available_anchor_ids: frozenset[str],
    unit_factors: dict[str, float] | None = None,
) -> MeasurementOutcome:
    clause, applicability = select_clause(scenario.clauses, measurement.feature_id, measurement.order_date)
    calibration = check_calibration(measurement, scenario.calibrations, available_anchor_ids)
    if clause is None or applicability.outcome is not TriBool.TRUE:
        return MeasurementOutcome(measurement, None, applicability, calibration, None, "unknown")
    tolerance = check_tolerance(measurement, clause, unit_factors)
    direction = _measurement_direction(applicability, calibration, tolerance)
    return MeasurementOutcome(measurement, clause, applicability, calibration, tolerance, direction)


def evaluate_t1(
    scenario: IngestedScenario,
    batch_no: str,
    *,
    revoked_anchor_ids: frozenset[str] = frozenset(),
    unit_factors: dict[str, float] | None = None,
) -> DecisionRecord:
    """Evaluate one batch against T1 and return its decision evidence pack."""

    all_anchor_ids = frozenset(scenario.anchors) - revoked_anchor_ids
    batch_measurements = [m for m in scenario.measurements if m.batch_no == batch_no]
    if not batch_measurements:
        raise ValueError(f"no measurements ingested for batch {batch_no}")

    usable, missing_items = [], []
    for measurement in batch_measurements:
        if measurement.anchor_id in revoked_anchor_ids:
            missing_items.append(f"measurement row {measurement.row_no} unavailable (evidence withdrawn)")
        else:
            usable.append(measurement)
    if not usable:
        return _pack_unknown_all_revoked(scenario, batch_no, missing_items)

    outcomes = [
        evaluate_measurement(m, scenario, all_anchor_ids, unit_factors) for m in usable
    ]
    return build_decision_record(batch_no, outcomes, missing_items, scenario, all_anchor_ids)


def build_decision_record(
    batch_no: str,
    outcomes: list[MeasurementOutcome],
    missing_items: list[str],
    scenario: IngestedScenario,
    all_anchor_ids: frozenset[str],
) -> DecisionRecord:
    """Aggregate measurement outcomes into the final decision evidence pack.

    Shared by the direct evaluation path and the planned execution path so
    both produce identical packs for identical inputs.
    """

    directions = {outcome.direction for outcome in outcomes}

    if "supported" in directions and "refuted" in directions:
        status: Direction = "conflict"
    elif "refuted" in directions:
        status = "refuted"
    elif "supported" in directions and "unknown" not in directions:
        status = "supported"
    else:
        status = "unknown"

    for outcome in outcomes:
        for result in (outcome.applicability, outcome.calibration, outcome.tolerance):
            if result is not None:
                missing_items.extend(result.missing)

    evidence = []
    selected_version: dict[str, str] = {}
    used_revisions: set[str] = set()
    for outcome in outcomes:
        anchor_ids = [outcome.measurement.anchor_id]
        used_revisions.add(_anchor_revision(scenario, outcome.measurement.anchor_id))
        if outcome.clause is not None:
            anchor_ids.append(outcome.clause.anchor_id)
            used_revisions.add(_anchor_revision(scenario, outcome.clause.anchor_id))
            selected_version[outcome.clause.standard_id] = outcome.clause.version
        matching_calibrations = [
            c
            for c in scenario.calibrations
            if c.instrument_id == outcome.measurement.instrument_id and c.anchor_id in all_anchor_ids
        ]
        covering = [
            c
            for c in matching_calibrations
            if c.valid_from <= outcome.measurement.measured_at <= c.valid_to
        ]
        chosen = covering[0] if covering else (matching_calibrations[0] if matching_calibrations else None)
        if chosen is not None:
            anchor_ids.append(chosen.anchor_id)
            used_revisions.add(_anchor_revision(scenario, chosen.anchor_id))
        evidence.append(
            EvidenceItem(
                anchor_ids=anchor_ids,
                # supports refers to the pass proposition "batch meets tolerance"
                supports=outcome.direction == "supported",
                note=f"row {outcome.measurement.row_no}: {outcome.tolerance.reason if outcome.tolerance else outcome.applicability.reason}",
            )
        )

    return DecisionRecord(
        decision_id=f"DEC-T1-{batch_no}",
        conclusion=f"Batch {batch_no} feature {outcomes[0].measurement.feature_id} tolerance check",
        status=status,
        decision_status="issued",
        premises=[f"measurement:{o.measurement.batch_no}@row{o.measurement.row_no}" for o in outcomes],
        evidence=evidence,
        rule_ids=[rule.rule_id for rule in G1_RULES],
        version_set=VersionSet(
            ontology_release_id=ONTOLOGY_SEED_RELEASE,
            rule_ids=[rule.rule_id for rule in G1_RULES],
            standard_versions=selected_version,
            asset_revision_ids=sorted(used_revisions),
        ),
        missing_items=missing_items,
        known_at=INGEST_TIME,
        created_by="g1-pipeline",
    )


def _anchor_revision(scenario: IngestedScenario, anchor_id: str) -> str:
    return scenario.anchors[anchor_id].revision_id


def _pack_unknown_all_revoked(
    scenario: IngestedScenario, batch_no: str, missing_items: list[str]
) -> DecisionRecord:
    """All measurement anchors revoked: unknown, with inspection-file revision still referenced."""

    inspection_revision = scenario.revision_id_for_asset("AST-INSPECTION-B") or scenario.revisions[0].revision_id
    return DecisionRecord(
        decision_id=f"DEC-T1-{batch_no}",
        conclusion=f"Batch {batch_no} tolerance check",
        status="unknown",
        decision_status="issued",
        premises=[f"measurement:{batch_no}@revoked"],
        evidence=[],
        rule_ids=[rule.rule_id for rule in G1_RULES],
        version_set=VersionSet(
            ontology_release_id=ONTOLOGY_SEED_RELEASE,
            rule_ids=[rule.rule_id for rule in G1_RULES],
            standard_versions={},
            asset_revision_ids=[inspection_revision],
        ),
        missing_items=missing_items or ["all measurement evidence unavailable"],
        known_at=INGEST_TIME,
        created_by="g1-pipeline",
    )
