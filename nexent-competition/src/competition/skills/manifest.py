# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Skill manifest contract (plan section 10.3).

Nexent's SkillLoader only keeps name/description/allowed-tools/tags/
script_outputs from SKILL.md; versioning, permissions, limits, side effects,
acceptance and rollback therefore live in this SEPARATE manifest, and the
validator enforces them programmatically (plan 2.1: writing them into
SKILL.md alone must never count as enforcement).
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SideEffectLevel = Literal["read_only", "writes_candidate", "writes_published"]

_WRITE_SUFFIXES = ("write", "write_candidate", "write_published")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class Limits(BaseModel):
    max_loops: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    timeout_seconds: int = Field(ge=1)


class SkillManifest(BaseModel):
    """Executable contract of one skill release."""

    model_config = ConfigDict(frozen=True)

    skill_name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    nexent_tested_version: str = Field(min_length=1)
    tool_contract_version: str = Field(min_length=1)
    ontology_scope: list[str] = Field(min_length=1)
    standard_version_policy: dict[str, str] = Field(default_factory=dict)
    input_type: str = Field(min_length=1)
    output_type: str = Field(min_length=1)
    limits: Limits
    accessible_resources: list[str] = Field(min_length=1)
    side_effect_level: SideEffectLevel
    idempotency_policy: str = Field(min_length=1)
    failure_modes: list[str] = Field(min_length=1)
    approval_condition: str = Field(min_length=1)
    acceptance_set: list[str] = Field(min_length=1)
    rollback: str = Field(min_length=1)
    entry_script: str = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def _semver_like(cls, value: str) -> str:
        if not _VERSION_PATTERN.match(value):
            raise ValueError("version must be MAJOR.MINOR.PATCH")
        return value

    @model_validator(mode="after")
    def _side_effects_match_resources(self) -> "SkillManifest":
        write_actions = [
            resource
            for resource in self.accessible_resources
            if resource.split(":")[-1] in _WRITE_SUFFIXES
        ]
        if self.side_effect_level == "read_only" and write_actions:
            raise ValueError(f"read_only skill declares write resources: {write_actions}")
        if self.side_effect_level == "writes_published":
            # Publishing in place is never automated (plan 11.2); flag loudly.
            raise ValueError("writes_published is not allowed in a manifest; publication goes through ChangeSet gating")
        return self
