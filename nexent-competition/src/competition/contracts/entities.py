# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Entity and fact assertion contracts.

Plan constraints implemented here:
- Entities with the same name are never auto-merged; every merge/split must be
  a recorded ``MergeRecord`` with a basis, and unmerge is a first-class action.
- One proposition may carry conflicting sources; assertions keep their status
  instead of silently overwriting each other.
- Extraction confidence is a ranking signal, not a calibrated probability.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

EntityStatus = Literal["active", "merged", "split", "retired"]
FactStatus = Literal["candidate", "confirmed", "contradicted", "superseded", "withdrawn"]


class TimePeriod(BaseModel):
    """Bitemporal window: business validity, independent of record time."""

    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    @field_validator("valid_to")
    @classmethod
    def _validate_order(cls, value: Optional[datetime], info) -> Optional[datetime]:
        start = info.data.get("valid_from")
        if value is not None and start is not None and value < start:
            raise ValueError("valid_to must not be earlier than valid_from")
        return value


class MergeRecord(BaseModel):
    """Audit entry for entity merge / split / unmerge actions."""

    action: Literal["merge", "split", "unmerge"]
    counterpart_entity_id: str = Field(min_length=1)
    basis: str = Field(min_length=1, description="Recorded justification; never auto-merged silently.")
    recorded_at: datetime


class Entity(BaseModel):
    """A business object with a stable identity across documents."""

    entity_id: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    status: EntityStatus = "active"
    merge_history: list[MergeRecord] = Field(default_factory=list)


class FactAssertion(BaseModel):
    """One proposition extracted or asserted about entities.

    ``source_anchors`` must reference at least one ``EvidenceAnchor`` so every
    fact can be traced back to original content (plan: no free-floating facts).
    """

    assertion_id: str = Field(min_length=1)
    subject_entity_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    # Object side: either a raw value (with unit) or a reference to another entity.
    object_value: Optional[str] = None
    object_entity_id: Optional[str] = None
    unit: Optional[str] = None
    normalized_value: Optional[str] = Field(
        default=None,
        description="Program-converted value; raw_value in the anchor stays authoritative.",
    )
    condition: Optional[str] = None
    valid_period: Optional[TimePeriod] = None
    source_anchors: list[str] = Field(min_length=1)
    status: FactStatus = "candidate"
    extraction_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_object(self) -> "FactAssertion":
        if self.object_value is None and self.object_entity_id is None:
            raise ValueError("fact assertion requires object_value or object_entity_id")
        if self.object_value is not None and self.object_entity_id is not None:
            raise ValueError("object_value and object_entity_id are mutually exclusive")
        if self.object_value is not None and self.unit is None:
            # Only enforce units for numeric-looking values; textual objects may omit them.
            try:
                float(self.object_value)
            except ValueError:
                pass
            else:
                raise ValueError("numeric object_value requires a unit")
        return self
