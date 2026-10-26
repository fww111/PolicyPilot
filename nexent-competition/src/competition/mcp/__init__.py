# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Domain MCP tool layer: registry, permission-aware service, FastMCP bridge."""

from competition.mcp.context import CallContext, CallJournal, ToolCallRecord
from competition.mcp.registry import ToolRegistry, ToolSpec
from competition.mcp.service import DomainService, build_domain_registry

__all__ = [
    "CallContext",
    "CallJournal",
    "DomainService",
    "ToolCallRecord",
    "ToolRegistry",
    "ToolSpec",
    "build_domain_registry",
]
