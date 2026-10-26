# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Clause-level diff between two standard versions (plan section 8.2 step 2).

A publication is decomposed into per-clause diffs, each tagged with the
change kinds it contains: add / replace / retire / attribute_change /
scope_change / cosmetic. Cosmetic-only diffs carry no decision impact and do
not trigger re-review (plan 8.2: "only layout changes must not trigger").
"""

from dataclasses import dataclass
from typing import Literal

from competition.contracts.changes import ChangeKind, ChangeSet
from competition.pipeline.ingestion import ToleranceClause

_CHANGE_PRIORITY: tuple[ChangeKind, ...] = (
    "retire", "replace", "add", "scope_change", "attribute_change", "cosmetic",
)


@dataclass(frozen=True)
class ClauseDiff:
    """One clause compared across versions; old or new may be absent."""

    standard_id: str
    old: ToleranceClause | None
    new: ToleranceClause | None
    kinds: tuple[ChangeKind, ...]

    @property
    def primary_kind(self) -> ChangeKind:
        for kind in _CHANGE_PRIORITY:
            if kind in self.kinds:
                return kind
        return "cosmetic"

    @property
    def is_cosmetic_only(self) -> bool:
        return self.kinds == ("cosmetic",)


def diff_standards(
    old_clauses: list[ToleranceClause], new_clauses: list[ToleranceClause], standard_id: str
) -> list[ClauseDiff]:
    """Pair clauses by feature within one standard's two versions."""

    old_by_feature = {clause.feature_id: clause for clause in old_clauses}
    new_by_feature = {clause.feature_id: clause for clause in new_clauses}
    diffs: list[ClauseDiff] = []
    for feature_id in sorted(set(old_by_feature) | set(new_by_feature)):
        old = old_by_feature.get(feature_id)
        new = new_by_feature.get(feature_id)
        diffs.append(ClauseDiff(standard_id, old, new, _classify(old, new)))
    return diffs


def _classify(old: ToleranceClause | None, new: ToleranceClause | None) -> tuple[ChangeKind, ...]:
    if old is None and new is None:  # pragma: no cover - defensive
        return ("cosmetic",)
    if old is None:
        return ("add",)
    if new is None:
        return ("retire",)
    kinds: list[ChangeKind] = []
    if abs(old.value_mm - new.value_mm) > 1e-12 or old.comparison != new.comparison:
        kinds.append("attribute_change")
    if old.scope != new.scope or old.effective_from != new.effective_from:
        kinds.append("scope_change")
    if not kinds:
        return ("cosmetic",)
    # A clause that changed semantics in place replaces the old one.
    kinds.insert(0, "replace")
    return tuple(kinds)


def build_changeset(diff: ClauseDiff, affected_decision_ids: list[str], source: str, created_at) -> ChangeSet:
    """Wrap one non-cosmetic diff into a pending ChangeSet.

    An empty affected set still yields a changeset (the publication itself is
    a versioned event); it simply triggers no re-review.
    """

    return ChangeSet(
        changeset_id=f"CS-{diff.standard_id}-{diff.new.version if diff.new else (diff.old.version if diff.old else '?')}",
        change_kind=diff.primary_kind,
        source=source,
        affected_ids=affected_decision_ids or [f"{diff.standard_id}:no-affected-decisions"],
        regression_result="pending",
        created_at=created_at,
    )
