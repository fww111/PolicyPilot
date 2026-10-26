# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Failure diagnosis: locate the responsible layer first (plan 11.2 step 2).

A failure must never be "fixed" by tweaking prompts when the actual problem
is missing data or a broken parser. The diagnoser maps missing items from a
decision pack to a layer, and only layers a skill patch CAN fix produce a
patch suggestion; evidence-side problems route back to retrieval tasks.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from competition.adaptation.patches import SkillPatch
from competition.pipeline.decision import DecisionRecord

Layer = Literal[
    "parsing",
    "entity_linking",
    "unit_normalization",
    "calibration_evidence",
    "standard_applicability",
    "planning",
]


@dataclass(frozen=True)
class Diagnosis:
    case_id: str
    responsible_layer: Layer
    suggested_patch: SkillPatch | None
    note: str


def diagnose_failure(decision: DecisionRecord, case_id: str) -> Diagnosis:
    """Map a decision pack's missing items to the responsible layer."""

    missing = " | ".join(decision.missing_items)

    if "cannot convert" in missing and "mm" in missing:
        unit = _extract_unit(missing)
        patch = SkillPatch(
            patch_id=f"PATCH-{case_id}-unit",
            skill_name="cross-document-check",
            kind="unit_alias",
            payload={"alias": unit, "factor_to_mm": None},  # factor filled by the optimizer step
            rationale=f"measurement recorded in unrecognized unit {unit!r}",
            source_case=case_id,
            created_at=datetime(2026, 10, 25, 12, 0, 0),
        )
        return Diagnosis(case_id, "unit_normalization", patch, "deterministic conversion table gap")
    if "calibration" in missing:
        # Data problem: fetch the certificate; a prompt/param patch cannot fix it.
        return Diagnosis(case_id, "calibration_evidence", None, "route to retrieval, not to a skill patch")
    if "standard version" in missing or "applicable clause" in missing:
        return Diagnosis(case_id, "standard_applicability", None, "route to standard registration")
    return Diagnosis(case_id, "planning", None, "unclassified failure: manual triage")


def _extract_unit(missing_text: str) -> str:
    # missing item format: "cannot convert 4.8 micron to mm"
    parts = missing_text.split(" ")
    for index, token in enumerate(parts):
        if token == "convert" and index + 2 < len(parts):
            return parts[index + 2]
    return "unknown"
