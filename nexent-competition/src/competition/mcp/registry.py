# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tool registry with per-tool schemas and privilege-smuggling protection.

Every tool declares its argument schema (required + optional keys). Dispatch:
1. rejects unknown tools;
2. rejects unknown ARGUMENT keys — including tenant/labels/permissions, so a
   model can never widen its own visibility (plan 10.1);
3. runs the handler with a server-injected CallContext;
4. journals one record per call with timing and evidence references.
"""

import time
from dataclasses import dataclass
from typing import Callable

from competition.mcp.context import CallContext, CallJournal, ToolCallRecord, summarize

Handler = Callable[[CallContext, dict], dict]

# Argument keys that would let a caller forge identity; always rejected.
_FORBIDDEN_ARG_KEYS = frozenset({"tenant", "user", "labels", "permissions", "permission_labels", "run_id", "trace_id"})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    service: str  # logical service boundary (assets / ontology / decision)
    description: str
    required_args: frozenset[str]
    optional_args: frozenset[str] = frozenset()
    handler: Handler = None  # type: ignore[assignment]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": spec.name,
                "service": spec.service,
                "description": spec.description,
                "required_args": sorted(spec.required_args),
                "optional_args": sorted(spec.optional_args),
            }
            for spec in self._tools.values()
        ]

    def dispatch(
        self, context: CallContext, journal: CallJournal, tool: str, args: dict
    ) -> dict:
        started = time.perf_counter()
        status: str = "ok"
        result: dict = {}
        try:
            spec = self._tools.get(tool)
            if spec is None:
                status = "error"
                result = {"error": "unknown_tool", "detail": f"{tool!r} is not registered"}
                return result
            unknown = set(args) - spec.required_args - spec.optional_args
            if unknown:
                status = "error"
                smuggled = sorted(unknown & _FORBIDDEN_ARG_KEYS)
                result = {
                    "error": "unknown_arguments",
                    "detail": f"unexpected argument keys: {sorted(unknown)}",
                    "privilege_smuggling": smuggled or None,
                }
                return result
            missing = spec.required_args - set(args)
            if missing:
                status = "error"
                result = {"error": "missing_arguments", "detail": f"missing keys: {sorted(missing)}"}
                return result
            result = spec.handler(context, args)
            return result
        finally:
            record = ToolCallRecord(
                tool=tool,
                run_id=context.run_id,
                trace_id=context.trace_id,
                user=f"{context.tenant}/{context.user}",
                input_summary=summarize(args),
                status=status,  # type: ignore[arg-type]
                duration_ms=int((time.perf_counter() - started) * 1000),
                evidence_refs=result.get("evidence_refs", []) if isinstance(result, dict) else [],
            )
            journal.record(record)
