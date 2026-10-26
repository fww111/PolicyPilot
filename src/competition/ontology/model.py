# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ontology internal representation and manufacturing seed (plan section 7.1).

Deliberately small and derived from the competency questions of
``docs/g0-baseline/task-spec.md`` — NOT a "big universal graph" (plan 7.1:
derive the ontology from business problems). Classes, relations and
constraints use a lightweight internal model; RDF/OWL + SHACL export is a
later milestone (plan 5.3) and this model is the source of truth for it.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OntologyClass:
    name: str
    parent: str | None = None
    required_props: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class OntologyRelation:
    name: str
    domain: str
    range: str
    cardinality: str = "1:N"


@dataclass(frozen=True)
class MutualExclusion:
    """Two classes an entity may never carry at the same time."""

    class_a: str
    class_b: str
    reason: str


@dataclass(frozen=True)
class SeedOntology:
    classes: tuple[OntologyClass, ...]
    relations: tuple[OntologyRelation, ...]
    exclusions: tuple[MutualExclusion, ...] = ()
    competency_questions: tuple[str, ...] = ()

    def class_names(self) -> set[str]:
        return {ontology_class.name for ontology_class in self.classes}


# Concepts from plan 7.1: Asset, Part, Batch, Measurement, Instrument,
# Calibration, Standard, Clause, Decision. Feature arrives as a CANDIDATE —
# the pipeline must discover it from data, not from the seed.
MANUFACTURING_SEED = SeedOntology(
    classes=(
        OntologyClass("Asset", None, ("asset_id",)),
        OntologyClass("Part", "Asset", ("part_no",), aliases=("component",)),
        OntologyClass("Batch", None, ("batch_no",)),
        OntologyClass("Measurement", None, ("value", "unit", "measured_at")),
        OntologyClass("Instrument", None, ("instrument_id",)),
        OntologyClass("Calibration", None, ("certificate_no", "valid_from", "valid_to")),
        OntologyClass("Standard", "Asset", ("standard_id", "version")),
        OntologyClass("Clause", None, ("clause_no",)),
        OntologyClass("Decision", None, ("decision_id", "status")),
    ),
    relations=(
        OntologyRelation("batch_of", "Batch", "Part"),
        OntologyRelation("measured_by", "Measurement", "Instrument"),
        OntologyRelation("calibration_of", "Calibration", "Instrument"),
        OntologyRelation("clause_of", "Clause", "Standard"),
        OntologyRelation("decides_about", "Decision", "Batch"),
        OntologyRelation("evidence_from", "Decision", "Asset"),
    ),
    exclusions=(
        MutualExclusion("Part", "Standard", "a physical part is never a normative document"),
        MutualExclusion("Batch", "Instrument", "a production batch is never a measuring device"),
    ),
    competency_questions=(
        "CQ1: which standard version and rule apply to a measurement?",
        "CQ2: which batches share an instrument that was out of calibration at measurement time?",
        "CQ9: what are the value, unit and normalized value of a measurement, and where is the anchor?",
    ),
)


# Unit normalization table (deterministic, program-side — never model output).
UNIT_ALIASES: dict[str, str] = {
    "um": "mm", "μm": "mm", "micron": "mm", "mm": "mm",
}
UNIT_FACTORS_TO_CANONICAL: dict[str, float] = {"um": 1e-3, "mm": 1.0}
