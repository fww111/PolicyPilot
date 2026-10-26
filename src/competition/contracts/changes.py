# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Skill release and change set contracts.

Plan constraints implemented here:
- ``SkillRelease`` is frozen: a published skill is never edited in place;
  any change produces a new release with a new version.
- ``ChangeSet`` follows verify-then-switch: publication requires a passed
  regression result, and a failed regression keeps the previous release.
  The gate itself is a service behaviour; the contract records its inputs.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChangeKind = Literal[
    "add",
    "replace",
    "retire",
    "attribute_change",
    "scope_change",
    "cosmetic",
]
RegressionResult = Literal["pending", "passed", "failed"]


class SkillRelease(BaseModel):
    """An immutable versioned skill package publication record."""

    model_config = ConfigDict(frozen=True)

    release_id: str = Field(min_length=1)
    skill_name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    tool_contract_version: str = Field(min_length=1)
    ontology_scope: list[str] = Field(min_length=1)
    rule_versions: list[str] = Field(min_length=1)
    acceptance_set_id: str = Field(min_length=1)
    supersedes_release_id: Optional[str] = None
    published_at: Optional[datetime] = None


class ChangeSet(BaseModel):
    """A unit of knowledge change with its impact set and regression state."""

    changeset_id: str = Field(min_length=1)
    change_kind: ChangeKind
    source: str = Field(min_length=1, description="Originating event, e.g. 'standard D v2 published'.")
    affected_ids: list[str] = Field(
        min_length=1,
        description="Dependency closure: rules, facts, assets, skills, decisions hit by this change.",
    )
    migration_plan: Optional[str] = None
    regression_result: RegressionResult = "pending"
    reviewer: Optional[str] = None
    supersedes_changeset_id: Optional[str] = None
    created_at: datetime

    @model_validator(mode="after")
    def _validate_publish_gate(self) -> "ChangeSet":
        # A reviewer can only be recorded alongside a finished regression run.
        if self.reviewer is not None and self.regression_result == "pending":
            raise ValueError("reviewer requires a completed regression result")
        return self
