# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tests for the domain MCP tool layer (plan section 10.1).

Covers: three logical service boundaries, server-injected identity,
permission filtering (no existence leak), privilege smuggling rejection,
permission-aware decision execution, and uniform call journaling.
"""

from pathlib import Path

import pytest

from competition.mcp import CallContext, CallJournal, DomainService, build_domain_registry
from competition.pipeline import load_scenario

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "data" / "scenario_d"
RESTRICTED = {"AST-CALIBRATION-C": {"qa-restricted"}}


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(SCENARIO_DIR)


@pytest.fixture(scope="module")
def service(scenario):
    return DomainService(scenario, asset_labels=RESTRICTED)


@pytest.fixture(scope="module")
def registry(service):
    return build_domain_registry(service)


@pytest.fixture()
def public_ctx():
    return CallContext(tenant="plant-a", user="engineer", permission_labels=frozenset())


@pytest.fixture()
def restricted_ctx():
    return CallContext(tenant="plant-a", user="qa-lead", permission_labels=frozenset({"qa-restricted"}))


@pytest.fixture()
def journal():
    return CallJournal()


def _call(registry, journal, ctx, tool, **args):
    return registry.dispatch(ctx, journal, tool, args)


# ------------------------------------------------------------ registry shape

def test_registry_exposes_three_service_boundaries(registry):
    services = {meta["service"] for meta in registry.list_tools()}
    assert services == {"assets", "ontology", "decision"}
    names = {meta["name"] for meta in registry.list_tools()}
    assert {"search_assets", "get_evidence", "resolve_entity", "read_table_region",
            "execute_plan", "replay_decision", "analyze_change_impact"} <= names


# ------------------------------------------------------------ assets & permissions

def test_search_assets_hides_restricted(registry, journal, public_ctx, restricted_ctx):
    public = _call(registry, journal, public_ctx, "search_assets")
    privileged = _call(registry, journal, restricted_ctx, "search_assets")
    public_ids = {asset["asset_id"] for asset in public["assets"]}
    privileged_ids = {asset["asset_id"] for asset in privileged["assets"]}
    assert "AST-CALIBRATION-C" not in public_ids
    assert "AST-CALIBRATION-C" in privileged_ids

    by_category = _call(registry, journal, public_ctx, "search_assets", category="standard")
    assert {asset["asset_id"] for asset in by_category["assets"]} == {
        "AST-STANDARD-D-V1", "AST-STANDARD-D-V2"
    }


def test_get_evidence_does_not_leak_existence(registry, journal, public_ctx, scenario):
    cal_anchor = next(c.anchor_id for c in scenario.calibrations)

    visible = _call(registry, journal, public_ctx, "get_evidence", anchor_id=cal_anchor)
    missing = _call(registry, journal, public_ctx, "get_evidence", anchor_id="ANC-NOPE")
    assert visible == {"found": False, "reason": "not_found"}
    assert missing == visible  # restricted and unknown are indistinguishable


def test_resolve_entity_exact_key(registry, journal, public_ctx):
    hit = _call(registry, journal, public_ctx, "resolve_entity", entity_type="Part", key="P-100")
    miss = _call(registry, journal, public_ctx, "resolve_entity", entity_type="Part", key="P100")
    assert hit["found"] and hit["entity"]["entity_id"] == "PART-P-100"
    assert not miss["found"]


def test_read_table_region(registry, journal, public_ctx, service):
    revision_id = service.scenario.revision_id_for_asset("AST-INSPECTION-B")
    cell = _call(registry, journal, public_ctx, "read_table_region",
                revision_id=revision_id, row=2, column=5)
    assert cell["found"] and cell["raw_value"] == "4.8"
    assert cell["column_header"] == "measured_value"
    assert cell["evidence_refs"]


# ------------------------------------------------------------ security

def test_privilege_smuggling_is_rejected(registry, journal, public_ctx):
    result = _call(registry, journal, public_ctx, "search_assets",
                   labels=["qa-restricted"], tenant="admin")
    assert result["error"] == "unknown_arguments"
    assert result["privilege_smuggling"] == ["labels", "tenant"]


def test_unknown_tool_is_rejected(registry, journal, public_ctx):
    result = _call(registry, journal, public_ctx, "drop_tables")
    assert result["error"] == "unknown_tool"
    assert journal.last().status == "error"


# ------------------------------------------------------------ decision tools

def test_execute_plan_privileged_view_passes(registry, journal, restricted_ctx):
    result = _call(registry, journal, restricted_ctx, "execute_plan", batch_no="L-2026-10")
    assert result["decision"]["status"] == "supported"
    assert result["evidence_refs"]
    assert journal.last().evidence_refs == result["evidence_refs"]


def test_execute_plan_restricted_calibration_degrades(registry, journal, public_ctx, scenario):
    """Restricted calibration behaves like withdrawn evidence: unknown, no leak."""

    result = _call(registry, journal, public_ctx, "execute_plan", batch_no="L-2026-10")
    decision = result["decision"]
    assert decision["status"] == "unknown"
    assert any("M-07" in item for item in decision["missing_items"])
    all_refs = {ref for item in decision["evidence"] for ref in item["anchor_ids"]}
    cal_anchor = next(c.anchor_id for c in scenario.calibrations if c.instrument_id == "M-07")
    assert cal_anchor not in all_refs  # restricted anchor never enters the pack


def test_replay_decision_reports_change(registry, journal, restricted_ctx):
    result = _call(registry, journal, restricted_ctx, "replay_decision",
                   batch_no="L-2026-13", previous_status="supported")
    assert result["current_status"] == "refuted"
    assert result["changed"] is True


# ------------------------------------------------------------ ontology tools

def test_analyze_change_impact(registry, journal, public_ctx):
    result = _call(registry, journal, public_ctx, "analyze_change_impact",
                   standard_id="SPEC-D", old_version="v1", new_version="v2")
    verdicts = [i["verdict"] for i in result["impacts"]]
    assert verdicts.count("needs_review") == 2
    assert "replace" in result["diff_kinds"]


# ------------------------------------------------------------ journaling

def test_journal_records_every_call(registry, journal, public_ctx):
    _call(registry, journal, public_ctx, "search_assets")
    _call(registry, journal, public_ctx, "resolve_entity", entity_type="Part", key="P-100")
    records = journal.for_run(public_ctx.run_id)
    assert len(records) == 2
    assert all(record.ok for record in records)
    assert all(record.duration_ms >= 0 for record in records)
    assert {record.tool for record in records} == {"search_assets", "resolve_entity"}


# ------------------------------------------------------------ FastMCP bridge

def test_fastmcp_bridge_mounts_and_calls():
    """Protocol-level smoke test: the server a running Nexent would mount works."""

    fastmcp = pytest.importorskip("fastmcp")
    import asyncio
    import json as json_module

    from competition.mcp.server import create_mcp_server

    server = create_mcp_server()
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "search_assets", "get_evidence", "resolve_entity", "read_table_region",
        "execute_plan", "replay_decision", "analyze_change_impact",
    }

    payload = json_module.dumps({"entity_type": "Part", "key": "P-100"})
    result = asyncio.run(server.call_tool("resolve_entity", {"payload": payload}))
    body = json_module.loads(result.content[0].text)
    assert body["found"] and body["entity"]["entity_id"] == "PART-P-100"
