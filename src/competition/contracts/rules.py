# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Executable rule contract.

Plan constraints recorded here:
- A rule references the standard clauses it is derived from.
- Missing inputs must produce ``unknown`` rather than ``False``; that behaviour
  belongs to the rule evaluator (three-valued logic) and is stated here as the
  contract the evaluator must satisfy.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

MissingInputBehavior = Literal["unknown"]
TimeSemantics = Literal["record", "business"]


class Rule(BaseModel):
    """A deterministic, executable business rule.

    ``expression`` references a registered, parameterized function — never
    free-form SQL or model-generated code (plan section 9.2).
    """

    rule_id: str = Field(min_length=1)
    input_types: list[str] = Field(min_length=1)
    preconditions: list[str] = Field(default_factory=list)
    expression_ref: str = Field(
        min_length=1,
        description="Registry key of the executable function, not inline code.",
    )
    unit_semantics: Optional[str] = None
    time_semantics: Optional[TimeSemantics] = Field(
        default=None,
        description="'record' evaluates at record time, 'business' at business time.",
    )
    standard_basis: list[str] = Field(
        min_length=1,
        description="StandardClause keys ('standard_id@version#clause_no') grounding this rule.",
    )
    missing_input_behavior: MissingInputBehavior = "unknown"
