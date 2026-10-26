# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exact business-key entity linking.

Plan constraint: same-name entities are never auto-merged. Linking uses exact
business keys only (part_no / batch_no / instrument_id); anything that needs
fuzzy matching must surface as a review candidate, which arrives in G2.
"""

from competition.contracts.entities import Entity
from competition.pipeline.ingestion import IngestedScenario

ENTITY_TYPES = ("Part", "Batch", "Instrument", "Standard")


class BusinessKeyIndex:
    """Registry of entities keyed by (entity_type, business_key)."""

    def __init__(self) -> None:
        self._entities: dict[tuple[str, str], Entity] = {}

    @classmethod
    def from_scenario(cls, scenario: IngestedScenario) -> "BusinessKeyIndex":
        index = cls()
        for feature_id in scenario.drawing_features:
            pass  # features are attributes, not standalone entities in G1
        # Parts and instruments appear in measurements; batches are decision objects.
        for record in scenario.measurements:
            index._register("Part", record.part_no)
            index._register("Batch", record.batch_no)
        for calibration in scenario.calibrations:
            index._register("Instrument", calibration.instrument_id)
        for record in scenario.measurements:
            index._register("Instrument", record.instrument_id)
        for clause in scenario.clauses:
            index._register("Standard", f"{clause.standard_id}@{clause.version}")
        scenario.entities.extend(index._entities.values())
        return index

    def _register(self, entity_type: str, key: str) -> None:
        # Exact key equality is the only merge rule in G1; distinct keys stay distinct.
        self._entities.setdefault(
            (entity_type, key),
            Entity(entity_id=f"{entity_type.upper()}-{key}", entity_type=entity_type, aliases=[key]),
        )

    def resolve(self, entity_type: str, key: str) -> Entity | None:
        return self._entities.get((entity_type, key))

    def all_entities(self) -> list[Entity]:
        return list(self._entities.values())
