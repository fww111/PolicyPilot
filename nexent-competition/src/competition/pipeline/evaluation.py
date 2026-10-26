# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Three-valued rule evaluation (plan sections 9.2 / 8.2).

Design rules:
- Missing input yields UNKNOWN, never False (rule contract ``missing_input_behavior``).
- Unit conversion is deterministic table lookup, not model output.
- Standard applicability is a scope predicate evaluated per order date;
  no applicable version means "do not adjudicate" (UNKNOWN).
- Calibration validity gates the *trust* of a measurement: an out-of-tolerance
  reading from an uncalibrated instrument is still UNKNOWN, because the
  reading itself is not trustworthy evidence (plan 3.3 item 3).
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from competition.contracts.rules import Rule
from competition.pipeline.ingestion import CalibrationRecord, MeasurementRecord, ToleranceClause

# Deterministic unit conversion into millimetres.
UNIT_TO_MM = {"um": 1e-3, "μm": 1e-3, "mm": 1.0}


class TriBool(Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CheckResult:
    outcome: TriBool
    reason: str
    missing: tuple[str, ...] = ()


RULE_APPLICABILITY = Rule(
    rule_id="R-T1-APPLICABILITY",
    input_types=["Order", "StandardClause"],
    expression_ref="t1.select_clause",
    time_semantics="business",
    standard_basis=["SPEC-D@v1#5.2", "SPEC-D@v2#5.2"],
)

RULE_TOLERANCE = Rule(
    rule_id="R-T1-TOLERANCE",
    input_types=["MeasurementRecord", "ToleranceClause"],
    expression_ref="t1.check_tolerance",
    standard_basis=["SPEC-D@v1#5.2", "SPEC-D@v2#5.2"],
)

RULE_CALIBRATION = Rule(
    rule_id="R-T1-CALWINDOW",
    input_types=["MeasurementRecord", "CalibrationRecord"],
    expression_ref="t1.check_calibration",
    standard_basis=["CAL@2026#window"],
)

G1_RULES = (RULE_APPLICABILITY, RULE_TOLERANCE, RULE_CALIBRATION)


def to_mm(value: str, unit: str, unit_factors: dict[str, float] | None = None) -> float | None:
    """Deterministic conversion; unhandled units return None (UNKNOWN upstream).

    ``unit_factors`` allows verification runs to inject a patched table
    (isolated copy) instead of mutating the module-level default.
    """

    factors = unit_factors if unit_factors is not None else UNIT_TO_MM
    factor = factors.get(unit.lower())
    if factor is None:
        return None
    try:
        return float(value) * factor
    except ValueError:
        return None


def select_clause(
    clauses: list[ToleranceClause], feature_id: str, order_date: date
) -> tuple[ToleranceClause | None, CheckResult]:
    """Pick the clause in force for one order date.

    Scope predicates (G1): 'all_orders' applies from effective_from onwards;
    'orders_on_or_after_effective' likewise. Earlier orders keep older
    versions, which is how plan 3.3 item 4 constrains re-review scope.
    """

    candidates = [
        clause
        for clause in clauses
        if clause.feature_id == feature_id and order_date >= clause.effective_from
    ]
    if not candidates:
        return None, CheckResult(
            TriBool.UNKNOWN,
            "no standard version effective for the order date",
            missing=("applicable standard version",),
        )
    # Latest effective_from wins; ties are a data conflict surfaced by the caller.
    winner = max(candidates, key=lambda clause: clause.effective_from)
    overlapping = [c for c in candidates if c.effective_from == winner.effective_from and c is not winner]
    if overlapping:
        return winner, CheckResult(
            TriBool.UNKNOWN,
            "multiple clauses share the same effective date",
            missing=("unique applicable clause",),
        )
    return winner, CheckResult(
        TriBool.TRUE, f"{winner.standard_id}@{winner.version}#{winner.clause_no} applies"
    )


def check_calibration(
    measurement: MeasurementRecord,
    calibrations: list[CalibrationRecord],
    available_anchor_ids: frozenset[str],
) -> CheckResult:
    """Check the instrument was calibrated at measurement time.

    A calibration whose anchor is revoked is treated as unavailable: the
    decision must degrade to UNKNOWN instead of reusing a cached conclusion
    (plan 3.3 item 5). Revoked anchors never appear in the evidence pack.
    """

    usable = [c for c in calibrations if c.instrument_id == measurement.instrument_id and c.anchor_id in available_anchor_ids]
    if not usable:
        return CheckResult(
            TriBool.UNKNOWN,
            f"calibration evidence for {measurement.instrument_id} unavailable",
            missing=(f"usable calibration certificate for {measurement.instrument_id}",),
        )
    for calibration in usable:
        if calibration.valid_from <= measurement.measured_at <= calibration.valid_to:
            return CheckResult(
                TriBool.TRUE,
                f"{calibration.certificate_no} valid {calibration.valid_from}..{calibration.valid_to}",
            )
    return CheckResult(
        TriBool.UNKNOWN,
        f"measurement {measurement.measured_at} outside calibration window of {measurement.instrument_id}",
        missing=("re-inspection: measurement outside calibration validity",),
    )


def check_tolerance(
    measurement: MeasurementRecord,
    clause: ToleranceClause,
    unit_factors: dict[str, float] | None = None,
) -> CheckResult:
    """Compare the measurement against the clause after unit conversion."""

    value_mm = to_mm(measurement.measured_value, measurement.unit, unit_factors)
    if value_mm is None:
        return CheckResult(
            TriBool.UNKNOWN,
            f"cannot convert {measurement.measured_value} {measurement.unit} to mm",
            missing=(f"cannot convert {measurement.measured_value} {measurement.unit} to mm",),
        )
    if clause.comparison != "<=":
        return CheckResult(TriBool.UNKNOWN, f"unsupported comparison {clause.comparison}")
    if value_mm <= clause.value_mm:
        return CheckResult(TriBool.TRUE, f"{value_mm}mm <= {clause.value_mm}mm")
    return CheckResult(TriBool.FALSE, f"{value_mm}mm > {clause.value_mm}mm")
