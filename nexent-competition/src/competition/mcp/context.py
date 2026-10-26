# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Call context, journal and permission model for domain MCP tools (plan 10.1).

Identity and visibility are injected SERVER-SIDE by the CallContext; tool
arguments never carry tenant/permission fields, and the registry rejects any
attempt to smuggle them (plan: the LLM may not widen its own permissions).

Unavailable-because-restricted evidence answers `not_found` — the response
must not leak that the asset exists at all (plan 3.3 item 5).
"""

import uuid
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class CallContext:
    """Server-side identity for one tool call chain."""

    tenant: str
    user: str
    permission_labels: frozenset[str]
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def can_see(self, asset_labels: set[str]) -> bool:
        # Empty label set = public asset; otherwise labels must be covered.
        return asset_labels.issubset(self.permission_labels)


@dataclass
class ToolCallRecord:
    tool: str
    run_id: str
    trace_id: str
    user: str
    input_summary: str
    status: Literal["ok", "error"]
    duration_ms: int = 0
    evidence_refs: list[str] = field(default_factory=list)
    retries: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class CallJournal:
    """Uniform per-call records (plan 10.1: run/trace ids, timing, evidence)."""

    def __init__(self) -> None:
        self.calls: list[ToolCallRecord] = []

    def record(self, record: ToolCallRecord) -> None:
        self.calls.append(record)

    def for_run(self, run_id: str) -> list[ToolCallRecord]:
        return [call for call in self.calls if call.run_id == run_id]

    def last(self) -> ToolCallRecord:
        return self.calls[-1]


def summarize(payload: object) -> str:
    text = repr(payload)
    return text if len(text) <= 120 else text[:117] + "..."
