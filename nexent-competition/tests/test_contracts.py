# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Contract tests for the domain data objects (plan section 5.2).

Each test pins one constraint from the improvement plan so the contract
cannot silently drift from the documented behaviour.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from competition.contracts.assets import Asset, AssetRevision, ExternalMapping
from competition.contracts.changes import ChangeSet, SkillRelease
from competition.contracts.decisions import DecisionRecord, EvidenceItem, VersionSet
from competition.contracts.entities import Entity, FactAssertion, MergeRecord
from competition.contracts.evidence import EvidenceAnchor, Locator
from competition.contracts.ontology import Alignment, OntologyRelease, StandardClause
from competition.contracts.rules import Rule

T = datetime(2026, 10, 24, 12, 0, 0)
DIGEST = "a" * 64


# ---------------------------------------------------------------- assets

def test_asset_requires_business_key():
    with pytest.raises(ValidationError, match="at least one business key"):
        Asset(
            asset_id="AST-1",
            source_system="mes",
            business_keys={},
            category="inspection_record",
            owner="qa",
        )


def test_external_mapping_requires_basis():
    with pytest.raises(ValidationError):
        ExternalMapping(target_system="erp", target_id="E-9", basis="", recorded_at=T)


def test_asset_revision_rejects_malformed_digest():
    with pytest.raises(ValidationError, match="sha256"):
        AssetRevision(
            revision_id="REV-1",
            asset_id="AST-1",
            file_name="report.pdf",
            content_digest="nothex",
            ingest_time=T,
        )
    rev = AssetRevision(
        revision_id="REV-1",
        asset_id="AST-1",
        file_name="report.pdf",
        content_digest=DIGEST.upper(),
        ingest_time=T,
    )
    assert rev.content_digest == DIGEST  # normalized to lowercase


# ---------------------------------------------------------------- evidence

def test_table_cell_locator_requires_row_and_column():
    with pytest.raises(ValidationError, match="row and column"):
        Locator(kind="table_cell", page=3)
    Locator(kind="table_cell", page=3, row=2, column=5, column_header="tolerance")


def test_char_span_requires_ordered_bounds():
    with pytest.raises(ValidationError, match="greater than"):
        Locator(kind="char_span", char_start=10, char_end=10)


def test_image_region_requires_normalized_bbox():
    with pytest.raises(ValidationError, match="normalized"):
        Locator(kind="image_region", bbox=(0.5, 0.1, 0.2, 0.9))  # x0 >= x1
    Locator(kind="image_region", bbox=(0.1, 0.1, 0.5, 0.5))


def test_clause_locator_requires_clause_no():
    with pytest.raises(ValidationError, match="clause_no"):
        Locator(kind="clause", page=2)


def test_evidence_anchor_is_frozen():
    anchor = EvidenceAnchor(
        anchor_id="ANC-1",
        revision_id="REV-1",
        locator=Locator(kind="char_span", char_start=0, char_end=8),
        raw_value="0.05 mm",
        parser_version="docling@0.3",
    )
    with pytest.raises(ValidationError):
        anchor.raw_value = "0.5 mm"  # type: ignore[misc]


# ---------------------------------------------------------------- entities

def test_merge_record_requires_basis():
    with pytest.raises(ValidationError):
        MergeRecord(action="merge", counterpart_entity_id="E-2", basis="", recorded_at=T)


def test_unmerge_is_first_class_action():
    record = MergeRecord(action="unmerge", counterpart_entity_id="E-2", basis="audit fix", recorded_at=T)
    entity = Entity(entity_id="E-1", entity_type="Part", merge_history=[record])
    assert entity.merge_history[0].action == "unmerge"


def test_fact_requires_evidence_anchor():
    with pytest.raises(ValidationError):
        FactAssertion(
            assertion_id="F-1",
            subject_entity_id="E-1",
            predicate="has_tolerance",
            object_value="0.05",
            unit="mm",
            source_anchors=[],
        )


def test_fact_object_is_value_or_entity_not_both():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        FactAssertion(
            assertion_id="F-1",
            subject_entity_id="E-1",
            predicate="linked_to",
            object_value="x",
            object_entity_id="E-2",
            source_anchors=["ANC-1"],
        )


def test_numeric_fact_requires_unit():
    with pytest.raises(ValidationError, match="unit"):
        FactAssertion(
            assertion_id="F-1",
            subject_entity_id="E-1",
            predicate="has_tolerance",
            object_value="0.05",
            source_anchors=["ANC-1"],
        )


def test_confidence_is_bounded():
    with pytest.raises(ValidationError):
        FactAssertion(
            assertion_id="F-1",
            subject_entity_id="E-1",
            predicate="has_tolerance",
            object_value="0.05",
            unit="mm",
            source_anchors=["ANC-1"],
            extraction_confidence=1.5,
        )


# ---------------------------------------------------------------- ontology

def test_standard_versions_are_separate_objects():
    v1 = StandardClause(
        standard_id="D", version="v1", clause_no="5.2",
        source_anchor_id="ANC-D1", effective_from=T,
    )
    v2 = StandardClause(
        standard_id="D", version="v2", clause_no="5.2",
        source_anchor_id="ANC-D2", effective_from=T,
    )
    assert v1 != v2
    assert v1.applicability_confirmed is False  # cannot adjudicate until confirmed


def test_alignment_rejects_unknown_mapping_type():
    with pytest.raises(ValidationError):
        Alignment(
            local_concept="FlatnessTolerance",
            target_standard_id="D",
            target_version="v1",
            mapping_type="same_as",  # not in the enum
            rationale="n/a",
        )


def test_ontology_release_requires_competency_questions():
    with pytest.raises(ValidationError):
        OntologyRelease(
            release_id="ONT-1",
            version="0.1",
            classes=["Part"],
            competency_questions=[],
            created_at=T,
        )


# ---------------------------------------------------------------- rules

def test_rule_requires_standard_basis():
    with pytest.raises(ValidationError):
        Rule(
            rule_id="R-1",
            input_types=["Measurement"],
            expression_ref="tolerance.check",
            standard_basis=[],
        )


def test_rule_missing_input_defaults_to_unknown():
    rule = Rule(
        rule_id="R-1",
        input_types=["Measurement"],
        expression_ref="tolerance.check",
        standard_basis=["D@v1#5.2"],
    )
    assert rule.missing_input_behavior == "unknown"


# ---------------------------------------------------------------- decisions

def _version_set() -> VersionSet:
    return VersionSet(
        ontology_release_id="ONT-1",
        rule_ids=["R-1"],
        standard_versions={"D": "v1"},
        asset_revision_ids=["REV-1"],
    )


def _decision(status: str, evidence: list[EvidenceItem]) -> DecisionRecord:
    return DecisionRecord(
        decision_id="DEC-1",
        conclusion="Batch L passes tolerance check",
        status=status,
        premises=["F-1"],
        evidence=evidence,
        rule_ids=["R-1"],
        version_set=_version_set(),
        known_at=T,
        created_by="agent",
    )


def test_four_valued_conclusion_statuses():
    ok = _decision("supported", [EvidenceItem(anchor_ids=["ANC-1"], supports=True)])
    assert ok.status == "supported"
    unknown = _decision("unknown", [EvidenceItem(anchor_ids=["ANC-1"], supports=True)])
    assert unknown.recalculated_status is None


def test_conflict_requires_both_sides():
    one_sided = [EvidenceItem(anchor_ids=["ANC-1"], supports=True)]
    with pytest.raises(ValidationError, match="both supporting and opposing"):
        _decision("conflict", one_sided)
    both = [
        EvidenceItem(anchor_ids=["ANC-1"], supports=True),
        EvidenceItem(anchor_ids=["ANC-2"], supports=False),
    ]
    assert _decision("conflict", both).status == "conflict"


def test_decision_records_missing_items():
    dec = _decision("unknown", [EvidenceItem(anchor_ids=["ANC-1"], supports=True)])
    dec.missing_items.append("calibration certificate for instrument M")
    assert dec.decision_status == "open"


# ---------------------------------------------------------------- changes

def test_skill_release_is_immutable():
    release = SkillRelease(
        release_id="SKR-1",
        skill_name="cross-document-check",
        version="0.1.0",
        tool_contract_version="tc@1",
        ontology_scope=["ONT-1"],
        rule_versions=["R-1"],
        acceptance_set_id="ACC-1",
    )
    with pytest.raises(ValidationError):
        release.version = "0.2.0"  # type: ignore[misc]


def test_changeset_reviewer_requires_finished_regression():
    with pytest.raises(ValidationError, match="completed regression"):
        ChangeSet(
            changeset_id="CS-1",
            change_kind="replace",
            source="standard D v2 published",
            affected_ids=["R-1", "DEC-1"],
            regression_result="pending",
            reviewer="expert-a",
            created_at=T,
        )


def test_changeset_failed_regression_keeps_gate_closed():
    cs = ChangeSet(
        changeset_id="CS-2",
        change_kind="scope_change",
        source="standard D v2 scope widened",
        affected_ids=["DEC-9"],
        regression_result="failed",
        reviewer="expert-a",
        created_at=T,
    )
    assert cs.regression_result == "failed"  # service layer must retain old release
