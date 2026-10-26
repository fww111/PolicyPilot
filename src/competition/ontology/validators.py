# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Constraint validation over seed + candidates (plan section 7.2 step 5).

Checks: unknown parent, inheritance cycles, relations referencing unknown
classes, and mutual-exclusion conflicts. Validation issues reject a candidate
before review — invalid structure never reaches an expert's queue.
"""

from dataclasses import dataclass

from competition.ontology.extractors import Candidate
from competition.ontology.model import SeedOntology


@dataclass(frozen=True)
class OntologyIssue:
    code: str
    detail: str


def validate_candidates(seed: SeedOntology, candidates: list[Candidate]) -> dict[int, list[OntologyIssue]]:
    """Validate each candidate; returns issues keyed by candidate index."""

    result: dict[int, list[OntologyIssue]] = {}
    known = seed.class_names()

    # Classes contributed by class-candidates (pre-approved view for relation checks).
    for candidate in candidates:
        if candidate.kind == "class":
            known.add(str(candidate.payload.get("name")))

    for index, candidate in enumerate(candidates):
        issues: list[OntologyIssue] = []
        if candidate.kind == "class":
            parent = candidate.payload.get("parent")
            if parent is not None and parent not in known:
                issues.append(OntologyIssue("unknown_parent", f"parent {parent!r} is not a known class"))
            if cycle_would_form(seed, candidates, candidate):
                issues.append(OntologyIssue("inheritance_cycle", f"adding {candidate.payload.get('name')!r} creates a cycle"))
            for exclusion in seed.exclusions:
                if parent == exclusion.class_a and str(candidate.payload.get("name")) == exclusion.class_b:
                    issues.append(
                        OntologyIssue("mutual_exclusion", f"{exclusion.class_a}/{exclusion.class_b}: {exclusion.reason}")
                    )
        elif candidate.kind == "relation":
            domain = candidate.payload.get("domain")
            range_ = candidate.payload.get("range")
            if domain not in known:
                issues.append(OntologyIssue("unknown_domain", f"domain {domain!r} is not a known class"))
            if range_ not in known:
                issues.append(OntologyIssue("unknown_range", f"range {range_!r} is not a known class"))
        elif candidate.kind == "alias":
            if "alias" not in candidate.payload or "canonical" not in candidate.payload:
                issues.append(OntologyIssue("malformed_alias", "alias candidates need alias and canonical"))
        if candidate.confidence < 0 or candidate.confidence > 1:
            issues.append(OntologyIssue("bad_confidence", "confidence must be within [0,1]"))
        if issues:
            result[index] = issues
    return result


def cycle_would_form(seed: SeedOntology, candidates: list[Candidate], new_class: Candidate) -> bool:
    """Walk the parent chain implied by seed + class candidates from the new class."""

    parents: dict[str, str] = {ontology_class.name: ontology_class.parent for ontology_class in seed.classes if ontology_class.parent}
    for candidate in candidates:
        if candidate.kind == "class":
            name = str(candidate.payload.get("name"))
            parent = candidate.payload.get("parent")
            if parent:
                parents[name] = str(parent)
    seen: set[str] = set()
    node = str(new_class.payload.get("name"))
    while node in parents:
        if node in seen:
            return True
        seen.add(node)
        node = parents[node]
        if node == str(new_class.payload.get("name")):
            return True
    return False


def check_instance_exclusions(seed: SeedOntology, entity_types: list[set[str]]) -> list[OntologyIssue]:
    """Mutual exclusion over entity instances (each entry = one entity's type set)."""

    issues: list[OntologyIssue] = []
    for types in entity_types:
        for exclusion in seed.exclusions:
            if exclusion.class_a in types and exclusion.class_b in types:
                issues.append(
                    OntologyIssue(
                        "instance_mutual_exclusion",
                        f"entity carries both {exclusion.class_a} and {exclusion.class_b}: {exclusion.reason}",
                    )
                )
    return issues
