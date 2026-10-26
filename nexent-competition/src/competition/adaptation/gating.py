# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Isolated verification and release gating for skill patches (plan 11.2 steps 3-7).

Double gate before any release:
1. NEW TASK GAIN: the failing case that motivated the patch must now pass.
2. ZERO REGRESSION: every baseline case must keep its exact status under the
   patched config — ANY status change (even 'improvement') counts as a
   regression, because an unrelated case changing means the patch has
   side effects beyond its claimed scope.

A failed gate keeps the previous SkillRelease verbatim (bad-update
interception, plan 11.3); drift monitoring may roll back later releases the
same way.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from competition.adaptation.patches import SkillConfig, SkillPatch, apply_patch, audit_patch
from competition.contracts.changes import SkillRelease
from competition.pipeline.decision import evaluate_t1
from competition.pipeline.ingestion import IngestedScenario

RELEASE_CLOCK = datetime(2026, 10, 25, 18, 0, 0)

# Draft factors the optimizer may propose for a new alias (from optimization
# set context only — never from locked test answers).
PROPOSED_FACTORS: dict[str, float] = {"micron": 1e-3}

StatusResolver = Callable[[SkillConfig, str], str]


@dataclass
class VerificationReport:
    patch_id: str
    target_case_fixed: bool = False
    regressions: list[tuple[str, str, str]] = field(default_factory=list)  # (case, old, new)
    rejected_reason: str = ""
    passed: bool = False


def verify_patch(
    patch: SkillPatch,
    baseline_cases: dict[str, str],  # case(batch) -> expected status under current config
    target_scenario: IngestedScenario,
    target_batch: str,
    locked_case_ids: frozenset[str],
    baseline_resolver: StatusResolver,
) -> VerificationReport:
    """Audit + isolate + double-gate; returns the report for the release decision."""

    issues = audit_patch(patch, locked_case_ids)
    if issues:
        return VerificationReport(
            patch.patch_id, rejected_reason="; ".join(f"{i.code}: {i.detail}" for i in issues)
        )

    config = SkillConfig.from_defaults()
    patched = apply_patch(config, patch)

    # Gate 1: new task gain.
    new_decision = evaluate_t1(target_scenario, target_batch, unit_factors=patched.unit_factors)
    fixed = new_decision.status != "unknown" and not new_decision.missing_items

    # Gate 2: zero regression on every baseline case.
    regressions: list[tuple[str, str, str]] = []
    for case, expected_status in baseline_cases.items():
        observed = baseline_resolver(patched, case)
        if observed != expected_status:
            regressions.append((case, expected_status, observed))

    report = VerificationReport(
        patch.patch_id,
        target_case_fixed=fixed,
        regressions=regressions,
        passed=fixed and not regressions,
    )
    if not fixed:
        report.rejected_reason = "target case still fails under the patched config"
    elif regressions:
        report.rejected_reason = f"{len(regressions)} baseline case(s) changed status"
    return report


def release_skill_patch(
    current: SkillRelease,
    patch: SkillPatch,
    report: VerificationReport,
) -> tuple[SkillRelease | None, str]:
    """Publish a verified patch as a new immutable release; None keeps the old one."""

    if not report.passed:
        return None, report.rejected_reason or "verification failed"
    new_release = SkillRelease(
        release_id=f"SKR-{patch.skill_name}-{patch.patch_id}",
        skill_name=patch.skill_name,
        version=_bump_minor(current.version),
        tool_contract_version=current.tool_contract_version,
        ontology_scope=list(current.ontology_scope),
        rule_versions=list(current.rule_versions),
        acceptance_set_id=current.acceptance_set_id,
        supersedes_release_id=current.release_id,
        published_at=RELEASE_CLOCK,
    )
    return new_release, ""


def rollback_release(current: SkillRelease, previous: SkillRelease) -> SkillRelease:
    """Drift response: restore the previous release verbatim (plan 11.2 step 7)."""

    return previous.model_copy(update={"published_at": RELEASE_CLOCK})


def _bump_minor(version: str) -> str:
    major, minor, patch_level = (int(part) for part in version.split("."))
    return f"{major}.{minor + 1}.0"
