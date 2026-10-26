# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Skill package validator (plan section 10.4: adapter that actually checks
dependencies and permissions, with negative tests).

Checks performed before a package may be registered:
- SKILL.md carries only Nexent-allowed keys (extras are warnings: contracts
  hiding in SKILL.md are silently dropped by Nexent's loader);
- every allowed tool exists in the registered tool contract;
- every ontology scope entry is a registered ontology release;
- pinned standard versions exist;
- referenced schemas exist and look like JSON Schema;
- acceptance set files exist; entry script exists;
- manifest version matches the newest CHANGELOG entry.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from competition.skills.loader import SkillPackage

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Severity
    detail: str


def validate_package(
    pkg: SkillPackage,
    *,
    available_tools: set[str],
    registered_ontologies: set[str],
    registered_standards: dict[str, set[str]],
) -> list[ValidationIssue]:
    """Return all issues; a package is registrable only with zero errors."""

    issues: list[ValidationIssue] = []
    manifest = pkg.manifest
    assert manifest is not None  # loader guarantees manifest presence

    # SKILL.md key discipline.
    if pkg.skill_md_extra_keys:
        issues.append(
            ValidationIssue(
                "skill_md_extra_keys",
                "warning",
                f"Nexent drops these SKILL.md keys: {sorted(pkg.skill_md_extra_keys)}; "
                f"contracts belong in manifest.json",
            )
        )
    if not pkg.skill_md_meta.get("name") or not pkg.skill_md_meta.get("description"):
        issues.append(ValidationIssue("skill_md_required_fields", "error", "SKILL.md needs name and description"))

    # Tool dependency check.
    allowed_tools = pkg.skill_md_meta.get("allowed-tools") or []
    if not isinstance(allowed_tools, list):
        allowed_tools = [allowed_tools]
    for tool in allowed_tools:
        if tool not in available_tools:
            issues.append(ValidationIssue("unknown_tool", "error", f"allowed-tools references unregistered tool {tool!r}"))

    # Ontology scope check.
    for ontology in manifest.ontology_scope:
        if ontology not in registered_ontologies:
            issues.append(ValidationIssue("unknown_ontology", "error", f"ontology_scope references unregistered release {ontology!r}"))

    # Standard version pin check: "pinned:v1,v2" -> {v1, v2}.
    for standard_id, policy in manifest.standard_version_policy.items():
        if not policy.startswith("pinned:"):
            issues.append(ValidationIssue("bad_standard_policy", "error", f"{standard_id}: policy must start with 'pinned:'"))
            continue
        pinned = {v for v in policy[len("pinned:") :].split(",") if v}
        missing = pinned - registered_standards.get(standard_id, set())
        if missing:
            issues.append(
                ValidationIssue("unknown_standard_version", "error", f"{standard_id}: unregistered versions {sorted(missing)}")
            )

    # Schema files: referenced, present, JSON-Schema-shaped.
    for ref in (manifest.input_type, manifest.output_type):
        if ref not in pkg.schemas:
            issues.append(ValidationIssue("missing_schema", "error", f"referenced schema not found: {ref}"))
    for name, schema in pkg.schemas.items():
        if not (isinstance(schema, dict) and ("type" in schema or "properties" in schema or "$schema" in schema)):
            issues.append(ValidationIssue("invalid_schema", "error", f"{name} does not look like a JSON Schema"))

    # Acceptance set + entry script existence.
    for case_ref in manifest.acceptance_set:
        if case_ref not in pkg.evals:
            issues.append(ValidationIssue("missing_eval", "error", f"acceptance_set references missing eval {case_ref}"))
    if not (pkg.root / manifest.entry_script).is_file():
        issues.append(ValidationIssue("missing_entry_script", "error", f"entry script not found: {manifest.entry_script}"))

    # Version coherence with CHANGELOG.
    if pkg.changelog_versions and manifest.version != pkg.changelog_versions[0]:
        issues.append(
            ValidationIssue(
                "version_drift",
                "error",
                f"manifest version {manifest.version} != newest CHANGELOG entry {pkg.changelog_versions[0]}",
            )
        )

    return issues
