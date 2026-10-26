# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Semi-automatic ontology pipeline (plan section 7.2, all eight steps).

1-2. Expert seed + candidate extraction (injectable extractor).
3.   Normalization (aliases/canonical units folded deterministically).
4.   Mapping candidates: skipped in the offline minimum (needs standard
     concept registries); the Alignment contract already exists.
5.   Constraint validation: invalid candidates are rejected BEFORE review.
6.   Competency questions must pass against the scenario.
7.   Review: auto-approve high-confidence valid candidates, rank the rest by
     uncertainty x impact (plan 7.3), human decisions recorded with reasons.
8.   Publish only when every candidate has an explicit status and all CQs
     pass; otherwise the release stays a candidate with blocking reasons.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from competition.contracts.ontology import OntologyRelease
from competition.ontology.competency import CQResult, run_competency_questions
from competition.ontology.extractors import Candidate, CandidateExtractor
from competition.ontology.model import OntologyClass, SeedOntology
from competition.ontology.validators import validate_candidates
from competition.pipeline.ingestion import IngestedScenario

PUBLISH_CLOCK = datetime(2026, 10, 25, 12, 0, 0)


@dataclass(frozen=True)
class ReviewDecision:
    action: Literal["approve", "reject"]
    reason: str


class ReviewPolicy(Protocol):
    def auto_decide(self, candidate: Candidate, has_issues: bool) -> ReviewDecision | None:
        """None = needs a human (goes to the ranked queue)."""


@dataclass
class AutoApprovePolicy:
    """Approve clean, high-confidence candidates; defer the rest to humans."""

    threshold: float = 0.9

    def auto_decide(self, candidate: Candidate, has_issues: bool) -> ReviewDecision | None:
        if has_issues:
            return ReviewDecision("reject", "failed constraint validation")
        if candidate.confidence >= self.threshold:
            return ReviewDecision("approve", f"confidence {candidate.confidence} >= {self.threshold}")
        return None  # uncertain -> human review, regardless of impact


def review_priority(candidate: Candidate) -> float:
    """High uncertainty x real impact first (plan 7.3).

    A deterministic, explainable ranking — no learned policy until the
    experiment justifies one.
    """

    return (1.0 - candidate.confidence) * math.log1p(candidate.impact)


@dataclass
class OntologyPipelineResult:
    release: OntologyRelease
    candidates: list[Candidate]
    review_queue: list[int] = field(default_factory=list)
    cq_results: list[CQResult] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    rejected_log: list[tuple[int, str]] = field(default_factory=list)


def run_ontology_pipeline(
    scenario: IngestedScenario,
    seed: SeedOntology,
    extractor: CandidateExtractor,
    policy: ReviewPolicy,
    human_decisions: dict[int, ReviewDecision] | None = None,
) -> OntologyPipelineResult:
    """Steps 2-8; returns a release (published or candidate) plus full audit state."""

    human_decisions = human_decisions or {}
    candidates = extractor.extract(scenario, seed)
    issues_map = validate_candidates(seed, candidates)

    review_queue: list[int] = []
    for index, candidate in enumerate(candidates):
        issues = issues_map.get(index, [])
        decision = policy.auto_decide(candidate, bool(issues))
        if decision is not None:
            _apply(candidate, decision)
            if decision.action == "reject":
                pass  # logged below from candidate.review_reason
        elif index in human_decisions:
            _apply(candidate, human_decisions[index])
        else:
            review_queue.append(index)  # still undecided

    # Rank undecided candidates for the expert queue (high uncertainty x impact first).
    review_queue.sort(key=lambda index: review_priority(candidates[index]), reverse=True)

    cq_results = run_competency_questions(scenario)

    classes = list(seed.classes)
    relations = list(seed.relations)
    for candidate in candidates:
        if candidate.status == "approved" and candidate.kind == "class":
            classes.append(
                OntologyClass(
                    name=str(candidate.payload["name"]),
                    parent=candidate.payload.get("parent"),
                    required_props=tuple(candidate.payload.get("required_props", ())),
                )
            )
        if candidate.status == "approved" and candidate.kind == "relation":
            from competition.ontology.model import OntologyRelation  # local: keep import list tidy

            relations.append(
                OntologyRelation(
                    name=str(candidate.payload["name"]),
                    domain=str(candidate.payload["domain"]),
                    range=str(candidate.payload["range"]),
                )
            )

    undecided = [index for index, candidate in enumerate(candidates) if candidate.status == "candidate"]
    cq_failed = [cq.question for cq in cq_results if not cq.passed]
    blocking: list[str] = []
    if undecided:
        blocking.append(f"{len(undecided)} candidates await review: {[candidates[i].kind for i in undecided]}")
    if cq_failed:
        blocking.append(f"competency questions failed: {cq_failed}")

    release = OntologyRelease(
        release_id=f"ONT-{'PUB' if not blocking else 'CAND'}-{len(classes):03d}",
        version=f"0.{len(classes)}.{len(relations)}",
        classes=[ontology_class.name for ontology_class in classes],
        relations=[relation.name for relation in relations],
        constraints=[exclusion.reason for exclusion in seed.exclusions],
        competency_questions=[cq.question for cq in cq_results],
        status="published" if not blocking else "candidate",
        created_at=PUBLISH_CLOCK,
    )

    rejected_log = [
        (index, candidate.review_reason or "unspecified")
        for index, candidate in enumerate(candidates)
        if candidate.status == "rejected"
    ]
    return OntologyPipelineResult(
        release=release,
        candidates=candidates,
        review_queue=review_queue,
        cq_results=cq_results,
        blocking_reasons=blocking,
        rejected_log=rejected_log,
    )


def _apply(candidate: Candidate, decision: ReviewDecision) -> None:
    if decision.action == "approve":
        candidate.status = "approved"
    else:
        candidate.status = "rejected"
    candidate.review_reason = decision.reason  # kept as future hard-sample material (plan 7.2 step 7)
