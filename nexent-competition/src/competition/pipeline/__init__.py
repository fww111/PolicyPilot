# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""G1 minimal closed loop: ingestion -> linking -> evaluation -> decision pack.

This package implements the first end-to-end pipeline over the synthetic
acceptance sample of plan section 3.3. Real parsers (Docling/PaddleOCR, task
N05) replace the synthetic adapters later; the anchor contracts stay stable.
"""

from competition.pipeline.decision import evaluate_t1
from competition.pipeline.ingestion import IngestedScenario, load_scenario
from competition.pipeline.linking import BusinessKeyIndex

__all__ = ["BusinessKeyIndex", "IngestedScenario", "evaluate_t1", "load_scenario"]
