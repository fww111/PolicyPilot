# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Candidate extraction for ontology learning (plan section 7.2 step 2).

``CandidateExtractor`` is the seam where an LLM extractor plugs in later; the
rule-based extractor here works offline from ingested structured records and
always attaches evidence anchors (plan: every candidate carries its source).
Confidence is a RANKING signal for the review queue, never a calibrated
probability (plan 7.3).
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from competition.ontology.model import UNIT_ALIASES, SeedOntology
from competition.pipeline.ingestion import IngestedScenario

CandidateKind = Literal["class", "relation", "alias"]
CandidateStatus = Literal["candidate", "approved", "rejected"]


@dataclass
class Candidate:
    kind: CandidateKind
    payload: dict = field(default_factory=dict)
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)  # anchor ids
    status: CandidateStatus = "candidate"
    review_reason: str = ""

    @property
    def impact(self) -> int:
        """Cheap impact proxy: how much ingested evidence backs the candidate."""

        return len(self.evidence)


class CandidateExtractor(Protocol):
    def extract(self, scenario: IngestedScenario, seed: SeedOntology) -> list[Candidate]:
        ...


class RuleBasedExtractor:
    """Offline extractor: derives candidates from structured records only."""

    def extract(self, scenario: IngestedScenario, seed: SeedOntology) -> list[Candidate]:
        candidates: list[Candidate] = []
        known = seed.class_names()

        # New class: features referenced by measurements/drawings but absent in seed.
        features = {m.feature_id for m in scenario.measurements} | set(scenario.drawing_features)
        if features and "Feature" not in known:
            candidates.append(
                Candidate(
                    kind="class",
                    payload={"name": "Feature", "parent": None, "required_props": ("feature_id",)},
                    confidence=0.85,
                    evidence=[
                        anchor_id
                        for anchor_id, anchor in scenario.anchors.items()
                        if anchor.locator.kind == "clause" and anchor.raw_value.startswith("F-")
                    ],
                )
            )

        # New relations over known classes: feature_of (Feature->Part) and
        # feature_governed_by (Feature->Clause) observed from the data.
        if "Feature" not in known:
            candidates.append(
                Candidate(
                    kind="relation",
                    payload={"name": "feature_of", "domain": "Feature", "range": "Part"},
                    confidence=0.7,
                    evidence=[m.anchor_id for m in scenario.measurements[:3]],
                )
            )
            candidates.append(
                Candidate(
                    kind="relation",
                    payload={"name": "governed_by", "domain": "Feature", "range": "Clause"},
                    confidence=0.7,
                    evidence=[clause.anchor_id for clause in scenario.clauses[:2]],
                )
            )

        # Alias candidates: unit spellings observed in measurements.
        observed_units = {m.unit for m in scenario.measurements}
        for unit in sorted(observed_units):
            canonical = UNIT_ALIASES.get(unit.lower())
            if canonical and unit.lower() != canonical:
                candidates.append(
                    Candidate(
                        kind="alias",
                        payload={"name": unit, "alias": unit, "canonical": canonical, "scope": "unit"},
                        confidence=0.95,
                        evidence=[m.anchor_id for m in scenario.measurements if m.unit == unit],
                    )
                )

        return candidates
