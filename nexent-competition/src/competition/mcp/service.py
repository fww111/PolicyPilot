# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Domain service: scenario state + per-asset permission labels + tool wiring.

Anchors inherit visibility from their asset: an anchor the caller cannot see
behaves exactly like withdrawn evidence (plan 8.1: permission changes alter
the available evidence set), so decision execution degrades to unknown
instead of leaking restricted content.
"""

from pathlib import Path
from typing import Callable

from competition.evolution import (
    DecisionLog,
    analyze_impact,
    diff_standards,
    view_scenario,
)
from competition.mcp.context import CallContext
from competition.mcp.registry import ToolRegistry, ToolSpec
from competition.pipeline import load_scenario
from competition.pipeline.ingestion import IngestedScenario
from competition.pipeline.linking import BusinessKeyIndex
from competition.planning import execute_plan, t1_plan
from competition.pipeline.decision import evaluate_t1


class DomainService:
    """Holds the scenario, permission labels and derived indexes."""

    def __init__(
        self,
        scenario: IngestedScenario,
        asset_labels: dict[str, set[str]] | None = None,
    ) -> None:
        self.scenario = scenario
        self.asset_labels = asset_labels or {}
        self.index = BusinessKeyIndex.from_scenario(scenario)
        self._anchor_assets: dict[str, str] = {}
        for revision in scenario.revisions:
            for anchor_id, anchor in scenario.anchors.items():
                if anchor.revision_id == revision.revision_id:
                    self._anchor_assets[anchor_id] = revision.asset_id

    @classmethod
    def from_dir(cls, data_dir: Path, asset_labels: dict[str, set[str]] | None = None) -> "DomainService":
        return cls(load_scenario(data_dir), asset_labels)

    def labels_of(self, asset_id: str) -> set[str]:
        return self.asset_labels.get(asset_id, set())

    def asset_visible(self, context: CallContext, asset_id: str) -> bool:
        return context.can_see(self.labels_of(asset_id))

    def anchor_visible(self, context: CallContext, anchor_id: str) -> bool:
        asset_id = self._anchor_assets.get(anchor_id)
        if asset_id is None:
            return False
        return self.asset_visible(context, asset_id)

    def visible_anchors(self, context: CallContext) -> frozenset[str]:
        return frozenset(
            anchor_id
            for anchor_id in self.scenario.anchors
            if self.anchor_visible(context, anchor_id)
        )

    def hidden_anchors(self, context: CallContext) -> frozenset[str]:
        return frozenset(self.scenario.anchors) - self.visible_anchors(context)


# ---------------------------------------------------------------- asset tools

def _tool_search_assets(service: DomainService) -> ToolSpec:
    def handler(context: CallContext, args: dict) -> dict:
        category = args.get("category")
        visible = [
            {
                "asset_id": asset.asset_id,
                "business_keys": asset.business_keys,
                "category": asset.category,
                "revision_id": service.scenario.revision_id_for_asset(asset.asset_id),
            }
            for asset in service.scenario.assets
            if (category is None or asset.category == category)
            and service.asset_visible(context, asset.asset_id)
        ]
        return {"assets": visible, "count": len(visible), "evidence_refs": []}

    return ToolSpec(
        name="search_assets",
        service="assets",
        description="List visible assets, optionally filtered by category.",
        required_args=frozenset(),
        optional_args=frozenset({"category"}),
        handler=handler,
    )


def _tool_get_evidence(service: DomainService) -> ToolSpec:
    def handler(context: CallContext, args: dict) -> dict:
        anchor_id = args["anchor_id"]
        anchor = service.scenario.anchors.get(anchor_id)
        # Restricted or unknown anchors answer identically: not found (no existence leak).
        if anchor is None or not service.anchor_visible(context, anchor_id):
            return {"found": False, "reason": "not_found"}
        return {
            "found": True,
            "anchor": anchor.model_dump(mode="json"),
            "evidence_refs": [anchor_id],
        }

    return ToolSpec(
        name="get_evidence",
        service="assets",
        description="Fetch one evidence anchor with locator and raw value.",
        required_args=frozenset({"anchor_id"}),
        handler=handler,
    )


def _tool_resolve_entity(service: DomainService) -> ToolSpec:
    def handler(context: CallContext, args: dict) -> dict:
        entity = service.index.resolve(args["entity_type"], args["key"])
        if entity is None:
            return {"found": False, "reason": "not_found"}
        return {"found": True, "entity": entity.model_dump(mode="json"), "evidence_refs": []}

    return ToolSpec(
        name="resolve_entity",
        service="assets",
        description="Resolve a business key to an entity (exact match only).",
        required_args=frozenset({"entity_type", "key"}),
        handler=handler,
    )


def _tool_read_table_region(service: DomainService) -> ToolSpec:
    def handler(context: CallContext, args: dict) -> dict:
        revision_id, row, column = args["revision_id"], args["row"], args["column"]
        for anchor_id, anchor in service.scenario.anchors.items():
            if anchor.revision_id != revision_id:
                continue
            if not service.anchor_visible(context, anchor_id):
                continue
            locator = anchor.locator
            if locator.kind == "table_cell" and locator.row == row and locator.column == column:
                return {
                    "found": True,
                    "raw_value": anchor.raw_value,
                    "column_header": locator.column_header,
                    "evidence_refs": [anchor_id],
                }
        return {"found": False, "reason": "not_found"}

    return ToolSpec(
        name="read_table_region",
        service="assets",
        description="Read one table cell from a visible revision.",
        required_args=frozenset({"revision_id", "row", "column"}),
        handler=handler,
    )


# ---------------------------------------------------------------- decision tools

def _tool_execute_plan(service: DomainService) -> ToolSpec:
    def handler(context: CallContext, args: dict) -> dict:
        trace = execute_plan(
            t1_plan(args["batch_no"]),
            service.scenario,
            revoked_anchor_ids=service.hidden_anchors(context),
        )
        if trace.rejection is not None:
            return {"error": "plan_rejected", "detail": trace.rejection}
        decision = trace.decision
        assert decision is not None
        return {
            "decision": decision.model_dump(mode="json"),
            "steps": [
                {"step_id": step.step_id, "op": step.op.value, "status": step.status}
                for step in trace.steps
            ],
            "evidence_refs": sorted(
                {ref for item in decision.evidence for ref in item.anchor_ids}
            ),
        }

    return ToolSpec(
        name="execute_plan",
        service="decision",
        description="Run the restricted T1 plan for one batch under caller visibility.",
        required_args=frozenset({"batch_no"}),
        handler=handler,
    )


def _tool_replay_decision(service: DomainService) -> ToolSpec:
    def handler(context: CallContext, args: dict) -> dict:
        decision = evaluate_t1(
            service.scenario,
            args["batch_no"],
            revoked_anchor_ids=service.hidden_anchors(context),
        )
        return {
            "current_status": decision.status,
            "previous_status": args.get("previous_status"),
            "changed": args.get("previous_status") not in (None, decision.status),
            "missing_items": decision.missing_items,
            "evidence_refs": sorted({ref for item in decision.evidence for ref in item.anchor_ids}),
        }

    return ToolSpec(
        name="replay_decision",
        service="decision",
        description="Re-evaluate a batch under current knowledge and visibility.",
        required_args=frozenset({"batch_no"}),
        optional_args=frozenset({"previous_status"}),
        handler=handler,
    )


# ---------------------------------------------------------------- ontology tools

def _tool_analyze_change_impact(service: DomainService) -> ToolSpec:
    def handler(context: CallContext, args: dict) -> dict:
        standard_id = args["standard_id"]
        old_clauses = [c for c in service.scenario.clauses if c.standard_id == standard_id and c.version == args["old_version"]]
        new_clauses = [c for c in service.scenario.clauses if c.standard_id == standard_id and c.version == args["new_version"]]
        if not old_clauses or not new_clauses:
            return {"error": "versions_not_found", "detail": f"{standard_id} {args['old_version']}->{args['new_version']}"}
        t0 = view_scenario(service.scenario, {(standard_id, args["old_version"])})
        batches = sorted({m.batch_no for m in service.scenario.measurements})
        log = DecisionLog.from_scenario(t0, batches)
        diffs = diff_standards(old_clauses, new_clauses, standard_id)
        impacts = analyze_impact(log.entries, diffs)
        return {
            "impacts": [
                {
                    "decision_id": i.decision_id,
                    "verdict": i.verdict,
                    "path": i.path,
                    "reason": i.reason,
                }
                for i in impacts
            ],
            "diff_kinds": sorted({kind for diff in diffs for kind in diff.kinds}),
            "evidence_refs": [c.anchor_id for c in new_clauses],
        }

    return ToolSpec(
        name="analyze_change_impact",
        service="ontology",
        description="Dual-path impact closure for one standard publication.",
        required_args=frozenset({"standard_id", "old_version", "new_version"}),
        handler=handler,
    )


def build_domain_registry(service: DomainService) -> ToolRegistry:
    registry = ToolRegistry()
    for factory in (
        _tool_search_assets,
        _tool_get_evidence,
        _tool_resolve_entity,
        _tool_read_table_region,
        _tool_execute_plan,
        _tool_replay_decision,
        _tool_analyze_change_impact,
    ):
        registry.register(factory(service))
    return registry
