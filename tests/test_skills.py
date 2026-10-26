# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tests for Nexent-native skill packages (plan sections 10.3/10.4).

Positive: both packages load, validate with zero issues, parse under Nexent's
real SkillLoader, and their eval cases execute live through the entry scripts.
Negative: unknown tools/ontologies/versions, schema/eval/script references,
contract keys hiding in SKILL.md, and forbidden side-effect levels.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from competition.skills import load_skill_package, validate_package

COMPETITION_ROOT = Path(__file__).resolve().parents[1]
NEXENT_ROOT = COMPETITION_ROOT.parent
SCENARIO_DIR = COMPETITION_ROOT / "data" / "scenario_d"
CDC_DIR = COMPETITION_ROOT / "skills" / "cross-document-check"
SCI_DIR = COMPETITION_ROOT / "skills" / "standard-change-impact"

AVAILABLE_TOOLS = {
    "search_assets", "get_evidence", "resolve_entity", "check_constraints", "analyze_change_impact",
}
REGISTERED_ONTOLOGIES = {"ONT-G1-SEED"}
REGISTERED_STANDARDS = {"SPEC-D": {"v1", "v2"}}


def _validate(pkg):
    return validate_package(
        pkg,
        available_tools=AVAILABLE_TOOLS,
        registered_ontologies=REGISTERED_ONTOLOGIES,
        registered_standards=REGISTERED_STANDARDS,
    )


@pytest.fixture(scope="module")
def cdc():
    return load_skill_package(CDC_DIR)


@pytest.fixture(scope="module")
def sci():
    return load_skill_package(SCI_DIR)


# ------------------------------------------------------------ positive

def test_packages_validate_clean(cdc, sci):
    for pkg in (cdc, sci):
        issues = _validate(pkg)
        assert issues == [], [f"{i.code}: {i.detail}" for i in issues]


def test_skill_md_uses_only_nexent_allowed_keys(cdc, sci):
    for pkg in (cdc, sci):
        assert pkg.skill_md_extra_keys == set()
        assert pkg.skill_md_meta["name"]
        assert pkg.skill_md_meta["description"]


def _load_real_nexent_skill_loader():
    """Load Nexent's SkillLoader without executing the sdk package __init__.

    The sdk's ``nexent/__init__.py`` pulls heavy runtime deps (httpx, ...);
    registering lightweight stub packages lets ``nexent.skills.skill_loader``
    import with only its own deps (yaml, charset_normalizer).
    """

    sdk = NEXENT_ROOT / "sdk"
    if not (sdk / "nexent" / "skills" / "skill_loader.py").is_file():
        return None
    try:
        import types

        if "nexent" not in sys.modules:
            top = types.ModuleType("nexent")
            top.__path__ = [str(sdk / "nexent")]
            sys.modules["nexent"] = top
        if "nexent.skills" not in sys.modules:
            sub = types.ModuleType("nexent.skills")
            sub.__path__ = [str(sdk / "nexent" / "skills")]
            sys.modules["nexent.skills"] = sub
        from nexent.skills.skill_loader import SkillLoader  # noqa: PLC0415

        return SkillLoader
    except Exception:
        return None


def test_skill_md_parses_with_real_nexent_loader(cdc, sci):
    """The strongest compatibility proof: Nexent's own SkillLoader parses our SKILL.md."""

    skill_loader_module = _load_real_nexent_skill_loader()
    if skill_loader_module is None:
        pytest.skip("nexent sdk skill_loader not importable in this environment")
    SkillLoader = skill_loader_module

    for pkg in (cdc, sci):
        meta = SkillLoader.parse((pkg.root / "SKILL.md").read_text(encoding="utf-8"))
        assert meta["name"] == pkg.skill_md_meta["name"]
        assert meta["description"] == pkg.skill_md_meta["description"]
        assert meta["allowed_tools"] == pkg.skill_md_meta["allowed-tools"]


def test_manifests_pin_versions_and_limits(cdc, sci):
    for pkg in (cdc, sci):
        manifest = pkg.manifest
        assert manifest is not None
        assert manifest.ontology_scope == ["ONT-G1-SEED"]
        assert manifest.limits.timeout_seconds >= 1
        assert manifest.side_effect_level != "writes_published"
        assert pkg.changelog_versions[0] == manifest.version


# ------------------------------------------------------------ live evals

def _load_entry_module(script: Path):
    spec = importlib.util.spec_from_file_location(script.stem, script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cdc_evals_execute(cdc):
    module = _load_entry_module(cdc.root / cdc.manifest.entry_script)
    for case_name, case in cdc.evals.items():
        pack = module.run(case["input"], SCENARIO_DIR)
        expected = case["expected"]
        assert pack["status"] == expected["status"], case_name
        if expected.get("standard_version"):
            assert pack["version_set"]["standard_versions"]["SPEC-D"] == expected["standard_version"]
        if expected.get("missing_items_empty"):
            assert pack["missing_items"] == []
        if expected.get("missing_contains"):
            assert any(expected["missing_contains"] in item for item in pack["missing_items"])


def test_sci_eval_executes(sci):
    module = _load_entry_module(sci.root / sci.manifest.entry_script)
    for case_name, case in sci.evals.items():
        report = module.run(case["input"], SCENARIO_DIR)
        expected = case["expected"]
        assert report["publication"]["status"] == expected["publication_status"], case_name
        assert report["publication"]["regression_result"] == expected["regression_result"]
        assert len(report["publication"]["affected_ids"]) == expected["affected_count"]
        changes = {tuple(c) for c in report["status_changes"]}
        for expected_change in expected["status_changes"]:
            assert tuple(expected_change) in changes
        verdict_by_reason = " ".join(i["reason"] for i in report["impact"])
        assert verdict_by_reason  # impact entries carry justifications


def test_entry_script_runs_as_subprocess(cdc, tmp_path):
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"batch_no": "L-2026-10"}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(CDC_DIR / "scripts" / "run_check.py"), "--input", str(job), "--scenario", str(SCENARIO_DIR)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    pack = json.loads(result.stdout)
    assert pack["status"] == "supported"


# ------------------------------------------------------------ negative

def test_unknown_tool_is_rejected(cdc):
    cdc.skill_md_meta["allowed-tools"] = ["search_assets", "nonexistent_tool"]
    issues = _validate(cdc)
    codes = {issue.code for issue in issues}
    assert "unknown_tool" in codes
    cdc.skill_md_meta["allowed-tools"] = ["search_assets", "get_evidence", "resolve_entity", "check_constraints"]


def test_unknown_ontology_is_rejected(cdc):
    original = cdc.manifest
    cdc.manifest = original.model_copy(update={"ontology_scope": ["ONT-NOPE"]})
    issues = _validate(cdc)
    assert any(issue.code == "unknown_ontology" for issue in issues)
    cdc.manifest = original


def test_unpinned_standard_version_is_rejected(cdc):
    original = cdc.manifest
    cdc.manifest = original.model_copy(update={"standard_version_policy": {"SPEC-D": "pinned:v1,v9"}})
    issues = _validate(cdc)
    assert any(issue.code == "unknown_standard_version" for issue in issues)
    cdc.manifest = original


def test_version_drift_against_changelog_is_rejected(cdc):
    original = cdc.changelog_versions
    cdc.changelog_versions = ["9.9.9"]
    issues = _validate(cdc)
    assert any(issue.code == "version_drift" for issue in issues)
    cdc.changelog_versions = original


def test_contract_keys_in_skill_md_raise_warning(cdc):
    original = cdc.skill_md_extra_keys
    cdc.skill_md_extra_keys = {"max_loops", "side_effect_level"}
    issues = _validate(cdc)
    warning = [i for i in issues if i.code == "skill_md_extra_keys"]
    assert warning and warning[0].severity == "warning"
    assert "manifest.json" in warning[0].detail
    cdc.skill_md_extra_keys = original


def test_missing_manifest_raises(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\nbody", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        load_skill_package(tmp_path)


def test_skill_md_without_frontmatter_raises(tmp_path):
    (tmp_path / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(ValueError, match="frontmatter"):
        load_skill_package(tmp_path)


def test_writes_published_side_effect_is_forbidden():
    from competition.skills.manifest import Limits, SkillManifest

    base = json.loads((CDC_DIR / "manifest.json").read_text(encoding="utf-8"))
    base.update(
        side_effect_level="writes_published",
        accessible_resources=["assets:read", "knowledge:write_published"],
    )
    with pytest.raises(ValidationError, match="writes_published"):
        SkillManifest(**base)


def test_read_only_with_write_resource_is_forbidden():
    from competition.skills.manifest import SkillManifest

    base = json.loads((CDC_DIR / "manifest.json").read_text(encoding="utf-8"))
    base.update(side_effect_level="read_only")  # manifest.json declares decisions:write_candidate
    with pytest.raises(ValidationError, match="read_only"):
        SkillManifest(**base)
