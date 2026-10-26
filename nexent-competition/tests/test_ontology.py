# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tests for the low-resource ontology pipeline (plan section 7)."""

import dataclasses
from pathlib import Path

import pytest

from competition.ontology import (
    MANUFACTURING_SEED,
    AutoApprovePolicy,
    Candidate,
    OntologyRelation,
    ReviewDecision,
    RuleBasedExtractor,
    check_instance_exclusions,
    review_priority,
    run_competency_questions,
    run_ontology_pipeline,
    validate_candidates,
)
from competition.pipeline import load_scenario

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "data" / "scenario_d"


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(SCENARIO_DIR)


# ------------------------------------------------------------ seed sanity

def test_seed_is_internally_consistent():
    known = MANUFACTURING_SEED.class_names()
    for ontology_class in MANUFACTURING_SEED.classes:
        if ontology_class.parent:
            assert ontology_class.parent in known
    for relation in MANUFACTURING_SEED.relations:
        assert relation.domain in known and relation.range in known
    assert len(MANUFACTURING_SEED.competency_questions) >= 3


# ------------------------------------------------------------ extraction

def test_rule_extractor_discovers_missing_concepts(scenario):
    candidates = RuleBasedExtractor().extract(scenario, MANUFACTURING_SEED)
    kinds = {(c.kind, c.payload.get("name")) for c in candidates}
    assert ("class", "Feature") in kinds                    # absent from seed, present in data
    assert ("relation", "feature_of") in kinds
    assert ("relation", "governed_by") in kinds
    assert ("alias", "um") in kinds                         # unit alias with evidence
    for candidate in candidates:
        assert candidate.evidence, f"{candidate.payload} lacks evidence anchors"
        assert 0.0 <= candidate.confidence <= 1.0


# ------------------------------------------------------------ validation negatives

def test_unknown_parent_is_rejected():
    bad = [Candidate(kind="class", payload={"name": "Widget", "parent": "Nonexistent"})]
    issues = validate_candidates(MANUFACTURING_SEED, bad)
    assert issues[0][0].code == "unknown_parent"


def test_inheritance_cycle_is_rejected():
    cyclic = [
        Candidate(kind="class", payload={"name": "A", "parent": "B"}),
        Candidate(kind="class", payload={"name": "B", "parent": "A"}),
    ]
    issues = validate_candidates(MANUFACTURING_SEED, cyclic)
    assert any(issue.code == "inheritance_cycle" for issues_ in issues.values() for issue in issues_)


def test_unknown_domain_is_rejected():
    bad = [Candidate(kind="relation", payload={"name": "haunts", "domain": "Ghost", "range": "Part"})]
    issues = validate_candidates(MANUFACTURING_SEED, bad)
    assert issues[0][0].code == "unknown_domain"


def test_exclusion_between_part_and_standard():
    issues = check_instance_exclusions(MANUFACTURING_SEED, [{"Part", "Standard"}])
    assert issues and issues[0].code == "instance_mutual_exclusion"
    assert check_instance_exclusions(MANUFACTURING_SEED, [{"Part"}, {"Standard"}]) == []


# ------------------------------------------------------------ competency questions

def test_competency_questions_pass_on_scenario(scenario):
    results = run_competency_questions(scenario)
    assert all(result.passed for result in results), [r.answer_summary for r in results]
    cq2 = next(r for r in results if r.question.startswith("CQ2"))
    assert "L-2026-11@M-09" in cq2.answer_summary  # the uncalibrated-instrument batch


def test_cq_fails_when_calibration_evidence_missing(scenario):
    stripped = dataclasses.replace(scenario, calibrations=[])
    results = run_competency_questions(stripped)
    cq2 = next(r for r in results if r.question.startswith("CQ2"))
    assert not cq2.passed


# ------------------------------------------------------------ review queue

def test_review_queue_ranks_uncertainty_times_impact():
    uncertain_high_impact = Candidate(
        kind="class", payload={"name": "X"}, confidence=0.3, evidence=["a"] * 20
    )
    confident_low_impact = Candidate(
        kind="class", payload={"name": "Y"}, confidence=0.95, evidence=["b"]
    )
    assert review_priority(uncertain_high_impact) > review_priority(confident_low_impact)


# ------------------------------------------------------------ pipeline end to end

def test_pipeline_auto_approves_high_confidence_only(scenario):
    result = run_ontology_pipeline(scenario, MANUFACTURING_SEED, RuleBasedExtractor(), AutoApprovePolicy())
    statuses = {c.payload.get("name", c.kind): c.status for c in result.candidates}
    assert statuses["um"] == "approved"          # 0.95 confidence alias auto-approved
    assert statuses["Feature"] == "candidate"    # 0.85 stays in the human queue
    assert result.review_queue                   # queue is non-empty and ranked
    assert result.release.status == "candidate"  # undecided candidates block publication
    assert any("await review" in reason for reason in result.blocking_reasons)


def test_pipeline_publishes_once_every_candidate_is_decided(scenario):
    first = run_ontology_pipeline(scenario, MANUFACTURING_SEED, RuleBasedExtractor(), AutoApprovePolicy())
    decisions = {index: ReviewDecision("approve", "domain expert confirmed") for index in first.review_queue}
    result = run_ontology_pipeline(
        scenario, MANUFACTURING_SEED, RuleBasedExtractor(), AutoApprovePolicy(), human_decisions=decisions
    )

    assert result.release.status == "published"
    assert "Feature" in result.release.classes
    assert "feature_of" in result.release.relations
    # Every candidate has an explicit terminal status (plan 7.2 step 8).
    assert all(c.status in ("approved", "rejected") for c in result.candidates)
    assert result.blocking_reasons == []


def test_pipeline_keeps_rejection_reasons_as_hard_samples(scenario):
    first = run_ontology_pipeline(scenario, MANUFACTURING_SEED, RuleBasedExtractor(), AutoApprovePolicy())
    decisions = {
        index: ReviewDecision("reject", "expert: concept not used by any competency question")
        for index in first.review_queue
    }
    result = run_ontology_pipeline(
        scenario, MANUFACTURING_SEED, RuleBasedExtractor(), AutoApprovePolicy(), human_decisions=decisions
    )
    assert result.rejected_log  # reasons preserved for future hard samples
    assert all(reason for _, reason in result.rejected_log)
    # Rejected class candidates must not enter the release.
    assert "Feature" not in result.release.classes


def test_relation_candidates_use_ontology_relation_contract():
    relation = OntologyRelation(name="measured_by", domain="Measurement", range="Instrument")
    assert relation.cardinality == "1:N"
