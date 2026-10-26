# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Controlled self-evolution: diagnose, patch, verify, release (plan section 11)."""

from competition.adaptation.diagnose import Diagnosis, Layer, diagnose_failure
from competition.adaptation.gating import (
    PROPOSED_FACTORS,
    VerificationReport,
    release_skill_patch,
    rollback_release,
    verify_patch,
)
from competition.adaptation.patches import (
    AuditIssue,
    PatchKind,
    SkillConfig,
    SkillPatch,
    apply_patch,
    audit_patch,
)

__all__ = [
    "AuditIssue",
    "Diagnosis",
    "Layer",
    "PROPOSED_FACTORS",
    "PatchKind",
    "SkillConfig",
    "SkillPatch",
    "VerificationReport",
    "apply_patch",
    "audit_patch",
    "diagnose_failure",
    "release_skill_patch",
    "rollback_release",
    "verify_patch",
]
