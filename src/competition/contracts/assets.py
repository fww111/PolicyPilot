# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Asset identity and revision contracts.

Plan constraints implemented here:
- Business identity is separate from file names: an ``Asset`` carries business
  keys, an ``AssetRevision`` carries the physical file reference.
- Cross-system identity mapping must keep a recorded basis (``ExternalMapping.basis``).
- A content digest identifies a revision; it is not proof of content truth.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetCategory = Literal[
    "drawing",           # product drawings / images
    "inspection_record", # measurement and inspection tables
    "calibration",       # instrument calibration certificates
    "standard",          # normative standard documents
    "process_record",    # process / manufacturing records
    "change_order",      # engineering change orders
    "other",
]


class ExternalMapping(BaseModel):
    """A mapping from this asset's identity to an identifier in another system.

    A mapping without a recorded basis cannot be audited, so ``basis`` is
    required (plan: cross-system mapping must keep its justification).
    """

    model_config = ConfigDict(frozen=True)

    target_system: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    basis: str = Field(min_length=1, description="Why this mapping holds; e.g. order no. match.")
    recorded_at: datetime


class Asset(BaseModel):
    """A business asset whose identity survives file renames and re-uploads."""

    asset_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    business_keys: dict[str, str] = Field(
        description="Stable business identifiers, e.g. part_no / batch_no / device_no.",
    )
    category: AssetCategory
    owner: str = Field(min_length=1)
    permission_labels: list[str] = Field(default_factory=list)
    external_mappings: list[ExternalMapping] = Field(default_factory=list)

    @field_validator("business_keys")
    @classmethod
    def _require_at_least_one_key(cls, value: dict[str, str]) -> dict[str, str]:
        # Without a business key the asset cannot be linked across documents.
        if not value:
            raise ValueError("asset requires at least one business key")
        return value


class AssetRevision(BaseModel):
    """One ingested version of an asset's content."""

    revision_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    file_name: str = Field(description="Physical file name; never used as business identity.")
    content_digest: str = Field(
        description="Hex sha256 of the parsed content; identifies the revision.",
    )
    ingest_time: datetime
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    supersedes_revision_id: Optional[str] = None

    @field_validator("content_digest")
    @classmethod
    def _validate_digest(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
            raise ValueError("content_digest must be a 64-char hex sha256 string")
        return value.lower()
