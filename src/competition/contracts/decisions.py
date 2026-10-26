# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Decision record contracts.

Plan constraints implemented here:
- Four-valued conclusions: supported / refuted / unknown / conflict. Retrieval
  finding nothing never means a proposition is false.
- Every key conclusion carries supporting and opposing evidence, the rules
  applied and the exact version set it was computed under.
- Two views coexist: "what was known at decision time" and "recalculated with
  current knowledge" (see ``recalculated_status``).
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

ConclusionStatus = Literal["supported", "refuted", "unknown", "conflict"]
DecisionStatus = Literal[
    "open",
    "issued",          # final output produced
    "needs_review",    # queued for human re-check, e.g. after a standard change
    "superseded",      # replaced by a newer decision
    "evidence_lost",   # a premise was withdrawn or lost permission
]


class EvidenceItem(BaseModel):
    """Evidence bundle entry: anchors plus whether it supports or opposes."""

    anchor_ids: list[str] = Field(min_length=1)
    supports: bool
    note: Optional[str] = None


class VersionSet(BaseModel):
    """The exact knowledge snapshot a decision was computed against."""

    ontology_release_id: str = Field(min_length=1)
    rule_ids: list[str] = Field(min_length=1)
    standard_versions: dict[str, str] = Field(
        description="standard_id -> version used at decision time.",
    )
    skill_release_id: Optional[str] = None
    asset_revision_ids: list[str] = Field(min_length=1)


class DecisionRecord(BaseModel):
    """A business decision with a replayable evidence dependency graph."""

    decision_id: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    status: ConclusionStatus
    decision_status: DecisionStatus = "open"
    premises: list[str] = Field(
        min_length=1,
        description="Assertion ids this conclusion depends on.",
    )
    evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="May be empty only for unknown conclusions with no usable evidence.",
    )
    rule_ids: list[str] = Field(default_factory=list)
    version_set: VersionSet
    missing_items: list[str] = Field(
        default_factory=list,
        description="Required-but-absent inputs; drives follow-up evidence collection.",
    )
    known_at: datetime
    recalculated_status: Optional[ConclusionStatus] = Field(
        default=None,
        description="Filled when re-evaluated under current knowledge; None means not yet replayed.",
    )
    created_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_conflict(self) -> "DecisionRecord":
        has_support = any(item.supports for item in self.evidence)
        has_oppose = any(not item.supports for item in self.evidence)
        if self.status == "conflict" and not (has_support and has_oppose):
            raise ValueError("conflict requires both supporting and opposing evidence")
        return self
