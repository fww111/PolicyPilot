# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ontology, standard clause and alignment contracts.

Plan constraints implemented here:
- Same standard name with different versions are separate ``StandardClause``
  objects; unconfirmed applicability cannot be used for adjudication (kept as
  an explicit status).
- Alignment mapping types distinguish equivalent / broader / narrower /
  related / unmappable; "related" never implies equivalence (enum level).
- Ontology releases and graph instance releases version independently; the
  compatibility relation is recorded on the release.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

AlignmentMappingType = Literal["equivalent", "broader", "narrower", "related", "unmappable"]
AlignmentReviewStatus = Literal["candidate", "approved", "rejected"]
OntologyReleaseStatus = Literal["candidate", "published", "retired"]


class StandardClause(BaseModel):
    """A clause of one definite version of a standard document."""

    model_config = dict(frozen=True)

    standard_id: str = Field(min_length=1, description="Standard identifier, e.g. 'GB/T 1234'.")
    version: str = Field(min_length=1, description="Version label; same standard, different version = separate object.")
    clause_no: str = Field(min_length=1)
    scope: Optional[str] = Field(default=None, description="Applicability scope stated by the clause.")
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    source_anchor_id: str = Field(min_length=1, description="EvidenceAnchor into the standard revision.")
    applicability_confirmed: bool = Field(
        default=False,
        description="False until applicability is verified; unconfirmed clauses cannot adjudicate.",
    )


class Alignment(BaseModel):
    """A mapping between a local ontology concept and a standard concept."""

    local_concept: str = Field(min_length=1)
    target_standard_id: str = Field(min_length=1)
    target_version: str = Field(min_length=1)
    target_clause_no: Optional[str] = None
    mapping_type: AlignmentMappingType
    rationale: str = Field(min_length=1)
    review_status: AlignmentReviewStatus = "candidate"
    reviewed_by: Optional[str] = None


class OntologyRelease(BaseModel):
    """An immutable, versioned ontology publication candidate or release."""

    model_config = dict(frozen=True)

    release_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    classes: list[str] = Field(min_length=1)
    relations: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    competency_questions: list[str] = Field(min_length=1)
    alignments: list[Alignment] = Field(default_factory=list)
    compatible_instance_releases: list[str] = Field(
        default_factory=list,
        description="Graph instance release versions this ontology can govern.",
    )
    status: OntologyReleaseStatus = "candidate"
    created_at: datetime
