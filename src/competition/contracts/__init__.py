# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Domain data contracts (plan section 5.2).

Each model maps to one row of the contract table in the improvement plan.
Contracts are transport-level schemas; behavioural constraints that need a
service (version gating, regression-before-publish, permission enforcement)
are documented on the models and implemented in later milestones.
"""

from competition.contracts.assets import Asset, AssetCategory, AssetRevision, ExternalMapping
from competition.contracts.changes import ChangeKind, ChangeSet, SkillRelease
from competition.contracts.decisions import (
    ConclusionStatus,
    DecisionRecord,
    DecisionStatus,
    EvidenceItem,
)
from competition.contracts.entities import Entity, EntityStatus, FactAssertion, FactStatus, MergeRecord
from competition.contracts.evidence import EvidenceAnchor, Locator, LocatorKind
from competition.contracts.ontology import Alignment, AlignmentMappingType, OntologyRelease, StandardClause
from competition.contracts.rules import Rule

__all__ = [
    "Alignment",
    "AlignmentMappingType",
    "Asset",
    "AssetCategory",
    "AssetRevision",
    "ChangeKind",
    "ChangeSet",
    "ConclusionStatus",
    "DecisionRecord",
    "DecisionStatus",
    "Entity",
    "EntityStatus",
    "EvidenceAnchor",
    "EvidenceItem",
    "ExternalMapping",
    "FactAssertion",
    "FactStatus",
    "Locator",
    "LocatorKind",
    "MergeRecord",
    "OntologyRelease",
    "Rule",
    "SkillRelease",
    "StandardClause",
]
