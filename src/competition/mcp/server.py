# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FastMCP stdio adapter for the domain tool registry.

Optional dependency: install with `uv sync --extra mcp`. The protocol-neutral
registry in ``service.py`` remains fully testable without FastMCP; this file
only bridges registered tools onto the MCP protocol so a running Nexent can
mount them. Identity is still built SERVER-SIDE from environment/request
context — tool arguments never carry it.
"""

from pathlib import Path
import json

from competition.mcp.context import CallContext, CallJournal
from competition.mcp.registry import ToolRegistry
from competition.mcp.service import DomainService, build_domain_registry

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "scenario_d"


def create_mcp_server(service: DomainService | None = None) -> "object":
    """Build a FastMCP server exposing the domain tools.

    Each MCP tool takes one explicit ``payload`` JSON string — FastMCP needs
    concrete signatures, and a single string argument keeps the protocol-side
    surface minimal while the registry validates every key server-side.
    """

    try:
        from fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "fastmcp is required for the MCP server bridge; install with `uv sync --extra mcp`"
        ) from exc

    service = service or DomainService.from_dir(DEFAULT_DATA_DIR)
    registry: ToolRegistry = build_domain_registry(service)
    journal = CallJournal()
    server = FastMCP("nexent-domain-mcp")

    for spec_meta in registry.list_tools():
        tool_name = spec_meta["name"]
        arg_doc = (
            f"Arguments (JSON): required {spec_meta['required_args']}, "
            f"optional {spec_meta['optional_args']}."
        )

        def _make(tool_name: str, arg_doc: str):
            def tool_handler(payload: str = "{}") -> dict:
                context = CallContext(tenant="demo", user="agent", permission_labels=frozenset())
                try:
                    args = json.loads(payload) if payload else {}
                except json.JSONDecodeError:
                    return {"error": "bad_payload", "detail": "payload must be a JSON object"}
                return registry.dispatch(context, journal, tool_name, dict(args))

            tool_handler.__name__ = tool_name
            tool_handler.__doc__ = f"{spec_meta['description']} {arg_doc}"
            return tool_handler

        server.tool()(_make(tool_name, arg_doc))

    return server


def main() -> None:  # pragma: no cover - process entry
    import argparse

    parser = argparse.ArgumentParser(description="nexent-domain-mcp server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                        help="stdio for local use; http for container-side Nexent access")
    parser.add_argument("--host", default="0.0.0.0", help="bind host for http transport")
    parser.add_argument("--port", type=int, default=8765, help="bind port for http transport")
    args = parser.parse_args()

    server = create_mcp_server()
    if args.transport == "http":
        # Containers reach this via http://host.docker.internal:<port>/mcp
        server.run(transport="http", host=args.host, port=args.port)
    else:
        server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
