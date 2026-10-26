# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Skill package loader.

Mirrors Nexent's SkillLoader semantics for SKILL.md (YAML frontmatter, keys
filtered to the allowed set, extras tolerated but REPORTED so contracts never
hide in SKILL.md), then loads the companion manifest.json, schemas/, evals/
and CHANGELOG.md that make up the package layout of plan section 10.3.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from competition.skills.manifest import SkillManifest

# Exactly the keys Nexent's SkillLoader keeps; anything else is dropped there
# and flagged here.
ALLOWED_SKILL_MD_KEYS = frozenset({"name", "description", "allowed-tools", "tags", "script_outputs"})

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class SkillPackage:
    """One loaded skill package directory."""

    root: Path
    skill_md_meta: dict = field(default_factory=dict)
    skill_md_extra_keys: set[str] = field(default_factory=set)
    manifest: SkillManifest | None = None
    changelog_versions: list[str] = field(default_factory=list)
    schemas: dict[str, dict] = field(default_factory=dict)
    evals: dict[str, dict] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return str(self.skill_md_meta.get("name") or (self.manifest.skill_name if self.manifest else ""))


def load_skill_package(root: Path) -> SkillPackage:
    """Load one package; structural errors raise, semantic checks wait for the validator."""

    if not root.is_dir():
        raise FileNotFoundError(f"skill package not found: {root}")
    pkg = SkillPackage(root=root)

    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"SKILL.md missing in {root}")
    pkg.skill_md_meta, pkg.skill_md_extra_keys = _parse_skill_md(skill_md.read_text(encoding="utf-8"))

    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json missing in {root}")
    pkg.manifest = SkillManifest(**json.loads(manifest_path.read_text(encoding="utf-8")))

    changelog = root / "CHANGELOG.md"
    if changelog.is_file():
        pkg.changelog_versions = re.findall(r"^##\s*\[(\d+\.\d+\.\d+)\]", changelog.read_text(encoding="utf-8"), re.MULTILINE)

    for schema_file in sorted((root / "schemas").glob("*.json")):
        pkg.schemas[schema_file.name] = json.loads(schema_file.read_text(encoding="utf-8"))
    for eval_file in sorted((root / "evals").glob("*.json")):
        pkg.evals[eval_file.name] = json.loads(eval_file.read_text(encoding="utf-8"))

    return pkg


def _parse_skill_md(content: str) -> tuple[dict, set[str]]:
    """Parse frontmatter the way Nexent does: allowed keys kept, extras reported."""

    match = _FRONTMATTER.match(content)
    if match is None:
        raise ValueError("SKILL.md must start with YAML frontmatter delimited by ---")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    extra = {str(key) for key in meta} - ALLOWED_SKILL_MD_KEYS
    filtered = {key: meta[key] for key in meta if key in ALLOWED_SKILL_MD_KEYS}
    return filtered, extra
