# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restricted skill patches and their audit rules (plan sections 11.1/11.3).

What may evolve automatically (plan 11.1): narrow, low-risk adjustments —
unit aliases, domain config, prompt fragments, retrieval parameters.
What may NEVER be patched: permission/side-effect manifests, tool contracts,
acceptance sets (the scorer), data splits, and rule semantics (verdicts).

Audit enforces three anti-cheat rules (plan 11.3):
- only whitelisted patch kinds;
- the patch must originate from an optimization/dev case, never a locked
  test case (no test-answer leakage into "experience");
- payload must not embed answer-shaped content (verdict/status/conclusion).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from competition.pipeline.evaluation import UNIT_TO_MM

PatchKind = Literal["unit_alias", "domain_config", "prompt_fragment", "retrieval_parameter"]

_ALLOWED_KINDS = frozenset({"unit_alias", "domain_config", "prompt_fragment", "retrieval_parameter"})

# Payload keys that smell like smuggling an answer instead of a behaviour fix.
_FORBIDDEN_PAYLOAD_KEYS = frozenset({"verdict", "status", "conclusion", "expected", "answer"})


@dataclass(frozen=True)
class SkillPatch:
    patch_id: str
    skill_name: str
    kind: PatchKind
    payload: dict
    rationale: str
    source_case: str  # must belong to the optimization set, never the locked set
    created_at: datetime


@dataclass(frozen=True)
class AuditIssue:
    code: str
    detail: str


def audit_patch(patch: SkillPatch, locked_case_ids: frozenset[str]) -> list[AuditIssue]:
    """A patch with any issue is rejected before verification."""

    issues: list[AuditIssue] = []
    if patch.kind not in _ALLOWED_KINDS:
        issues.append(AuditIssue("forbidden_kind", f"kind {patch.kind!r} is not patchable automatically"))
    if patch.source_case in locked_case_ids:
        issues.append(AuditIssue("locked_test_source", f"patch derived from locked case {patch.source_case!r}"))
    leaked = _FORBIDDEN_PAYLOAD_KEYS & set(patch.payload)
    if leaked:
        issues.append(AuditIssue("answer_smuggling", f"payload embeds answer-shaped keys: {sorted(leaked)}"))
    if patch.kind == "unit_alias":
        alias = patch.payload.get("alias")
        factor = patch.payload.get("factor_to_mm")
        if not alias or not isinstance(factor, (int, float)) or factor <= 0:
            issues.append(AuditIssue("malformed_unit_alias", "unit_alias needs alias and positive factor_to_mm"))
    return issues


@dataclass(frozen=True)
class SkillConfig:
    """Isolated view of the tunable configuration a patch may touch.

    Verification runs against a copied config; the module-level defaults are
    never mutated (plan 11.2 step 5: verify in isolation first).
    """

    unit_factors: dict[str, float]

    @classmethod
    def from_defaults(cls) -> "SkillConfig":
        return cls(unit_factors=dict(UNIT_TO_MM))


def apply_patch(config: SkillConfig, patch: SkillPatch) -> SkillConfig:
    """Return a NEW config with the patch applied; never mutates in place."""

    if patch.kind == "unit_alias":
        factors = dict(config.unit_factors)
        factors[str(patch.payload["alias"]).lower()] = float(patch.payload["factor_to_mm"])
        return SkillConfig(unit_factors=factors)
    # Other whitelisted kinds do not affect the offline evaluator yet.
    return SkillConfig(unit_factors=dict(config.unit_factors))
