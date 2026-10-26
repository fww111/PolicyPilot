# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Executable competency questions (plan section 7.2 step 6).

A release candidate must support the key queries AND must not turn any
historically correct answer into a wrong one. The three executable CQs from
the seed run against the ingested scenario through the SAME evaluation code
the decision pipeline uses — the ontology is tested by behaviour, not by
node counts (plan 13.4: more nodes is not better).
"""

from dataclasses import dataclass
from typing import Callable

from competition.pipeline.evaluation import select_clause
from competition.pipeline.ingestion import IngestedScenario

CQRunner = Callable[[IngestedScenario], "CQResult"]


@dataclass(frozen=True)
class CQResult:
    question: str
    passed: bool
    answer_summary: str


def cq1_applicable_standard(scenario: IngestedScenario) -> CQResult:
    """Which standard version and rule apply to a measurement?"""

    measurement = scenario.measurements[0]
    clause, result = select_clause(scenario.clauses, measurement.feature_id, measurement.order_date)
    passed = clause is not None and result.outcome.value == "true"
    return CQResult(
        "CQ1: which standard version and rule apply to a measurement?",
        passed,
        result.reason,
    )


def cq2_batches_on_uncalibrated_instrument(scenario: IngestedScenario) -> CQResult:
    """Which batches shared an instrument that was out of calibration at measurement time?"""

    hits = []
    for measurement in scenario.measurements:
        calibrations = [c for c in scenario.calibrations if c.instrument_id == measurement.instrument_id]
        covered = any(c.valid_from <= measurement.measured_at <= c.valid_to for c in calibrations)
        if calibrations and not covered:
            hits.append(f"{measurement.batch_no}@{measurement.instrument_id}")
    # L-2026-11 on M-09 must be discovered for the question to pass.
    passed = "L-2026-11@M-09" in hits
    return CQResult(
        "CQ2: which batches share an instrument out of calibration at measurement time?",
        passed,
        "; ".join(hits) or "none found",
    )


def cq9_value_unit_anchor(scenario: IngestedScenario) -> CQResult:
    """What are the value, unit, normalized value of a measurement, and where is the anchor?"""

    measurement = next(m for m in scenario.measurements if m.batch_no == "L-2026-12")  # mm row
    anchor = scenario.anchors[measurement.anchor_id]
    locator = anchor.locator
    normalized_ok = measurement.measured_value == "0.0048" and measurement.unit == "mm"
    anchored_ok = locator.kind == "table_cell" and locator.row is not None and locator.column is not None
    return CQResult(
        "CQ9: value, unit, normalized value and anchor of a measurement?",
        normalized_ok and anchored_ok,
        f"row {measurement.row_no}: {measurement.measured_value} {measurement.unit} at {locator.kind}",
    )


EXECUTABLE_CQS: tuple[CQRunner, ...] = (cq1_applicable_standard, cq2_batches_on_uncalibrated_instrument, cq9_value_unit_anchor)


def run_competency_questions(scenario: IngestedScenario) -> list[CQResult]:
    return [runner(scenario) for runner in EXECUTABLE_CQS]
