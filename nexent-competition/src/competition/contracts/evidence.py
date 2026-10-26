# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Evidence anchor contracts.

Plan constraints implemented here:
- Every extracted fact must be anchored to a definite ``AssetRevision`` and a
  concrete position in the original content (page / cell / region / span).
- The raw value is preserved as-is; normalization happens downstream and both
  forms coexist (see ``FactAssertion`` for the normalized side).
- The parser version is recorded so anchors can be re-derived after parser
  upgrades.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

LocatorKind = Literal["char_span", "table_cell", "image_region", "clause"]


class Locator(BaseModel):
    """A typed position inside one asset revision.

    Exactly one locator family must be filled; mixed or empty locators are
    rejected so an anchor can always be rendered back to a user.
    """

    model_config = ConfigDict(frozen=True)

    kind: LocatorKind
    page: Optional[int] = Field(default=None, ge=1)
    # char_span fields
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)
    # table_cell fields
    sheet: Optional[str] = None
    row: Optional[int] = Field(default=None, ge=1)
    column: Optional[int] = Field(default=None, ge=1)
    column_header: Optional[str] = None
    # image_region fields, normalized to [0,1] relative coordinates
    bbox: Optional[tuple[float, float, float, float]] = None
    # clause locator, e.g. "5.2.1" within a standard document
    clause_no: Optional[str] = None

    @model_validator(mode="after")
    def _validate_family(self) -> "Locator":
        if self.kind == "char_span":
            if self.char_start is None or self.char_end is None:
                raise ValueError("char_span requires char_start and char_end")
            if self.char_end <= self.char_start:
                raise ValueError("char_end must be greater than char_start")
        elif self.kind == "table_cell":
            if self.row is None or self.column is None:
                raise ValueError("table_cell requires row and column")
        elif self.kind == "image_region":
            if self.bbox is None:
                raise ValueError("image_region requires bbox")
            x0, y0, x1, y1 = self.bbox
            if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
                raise ValueError("bbox must be normalized with x0<x1, y0<y1 in [0,1]")
        elif self.kind == "clause":
            if not self.clause_no:
                raise ValueError("clause locator requires clause_no")
        return self


class EvidenceAnchor(BaseModel):
    """An immutable pointer from a claim back to source content."""

    model_config = ConfigDict(frozen=True)

    anchor_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1, description="Must reference an AssetRevision.")
    locator: Locator
    raw_value: str = Field(description="Original text/value exactly as extracted, unmodified.")
    parser_version: str = Field(min_length=1)
