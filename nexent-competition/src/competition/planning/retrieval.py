# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Evidence-gap driven retrieval tasks (plan sections 9.1 / 9.4).

When reasoning hits an unevaluable premise it must NOT silently proceed; it
emits a typed, time-bounded, object-scoped retrieval task stating what asset
kind would unblock the decision and why. Feeding the requested evidence in
and re-running the plan closes the loop: unknown -> evaluable verdict.

Tasks are derived from structured ``MeasurementOutcome`` objects (not from
human-readable missing_items strings) so they stay exact.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from competition.contracts.evidence import EvidenceAnchor, Locator
from competition.contracts.assets import Asset, AssetRevision
from competition.pipeline.decision import MeasurementOutcome
from competition.pipeline.evaluation import TriBool
from competition.pipeline.ingestion import CalibrationRecord, IngestedScenario

AssetKind = Literal["calibration", "standard", "measurement"]


@dataclass(frozen=True)
class RetrievalTask:
    task_id: str
    asset_kind: AssetKind          # WHAT kind of asset is missing (typed constraint)
    target_object: str             # WHICH business object it must cover
    time_window: tuple[date, date] | None  # WHEN it must be valid (time constraint)
    purpose: str                   # WHY: which premise it unblocks


def derive_retrieval_tasks(outcomes: list[MeasurementOutcome]) -> list[RetrievalTask]:
    """Turn unevaluable premises into typed retrieval tasks."""

    tasks: list[RetrievalTask] = []
    for index, outcome in enumerate(outcomes):
        measurement = outcome.measurement
        if outcome.applicability.outcome is not TriBool.TRUE:
            tasks.append(
                RetrievalTask(
                    task_id=f"GAP-{index}-standard",
                    asset_kind="standard",
                    target_object=measurement.feature_id,
                    time_window=(measurement.order_date, measurement.order_date),
                    purpose="locate the standard version effective for this order date",
                )
            )
        if outcome.calibration.outcome is not TriBool.TRUE:
            tasks.append(
                RetrievalTask(
                    task_id=f"GAP-{index}-calibration",
                    asset_kind="calibration",
                    target_object=measurement.instrument_id,
                    time_window=(measurement.measured_at, measurement.measured_at),
                    purpose="verify instrument calibration at measurement time",
                )
            )
        if outcome.tolerance is not None and outcome.tolerance.outcome is TriBool.UNKNOWN:
            tasks.append(
                RetrievalTask(
                    task_id=f"GAP-{index}-measurement",
                    asset_kind="measurement",
                    target_object=measurement.batch_no,
                    time_window=None,
                    purpose="re-record the value with a recognized unit",
                )
            )
    return tasks


def apply_supplementary_calibration(
    scenario: IngestedScenario,
    instrument_id: str,
    certificate_no: str,
    valid_from: date,
    valid_to: date,
) -> CalibrationRecord:
    """Simulate ingesting a new calibration file for one instrument.

    Registers a synthetic asset + revision + anchor exactly like a real file
    ingest would, so the supplemented evidence keeps the same traceability.
    """

    asset_id = f"AST-CALIBRATION-SUPP-{certificate_no}"
    if any(asset.asset_id == asset_id for asset in scenario.assets):
        raise ValueError(f"supplementary calibration {certificate_no} already registered")
    revision_id = f"REV-{asset_id}"
    scenario.assets.append(
        Asset(
            asset_id=asset_id,
            source_system="g2-supplementary",
            business_keys={"instrument_id": instrument_id, "certificate_no": certificate_no},
            category="calibration",
            owner="synthetic",
        )
    )
    scenario.revisions.append(
        AssetRevision(
            revision_id=revision_id,
            asset_id=asset_id,
            file_name=f"{certificate_no}.json",
            content_digest="0" * 64,  # placeholder digest; real ingest hashes file content
            ingest_time=scenario.revisions[0].ingest_time,
        )
    )
    anchor = EvidenceAnchor(
        anchor_id=f"ANC-SUPP-{certificate_no}",
        revision_id=revision_id,
        locator=Locator(kind="clause", clause_no="validity"),
        raw_value=f"{valid_from.isoformat()}..{valid_to.isoformat()}",
        parser_version="synthetic-json@1",
    )
    scenario.anchors[anchor.anchor_id] = anchor
    record = CalibrationRecord(
        instrument_id=instrument_id,
        certificate_no=certificate_no,
        valid_from=valid_from,
        valid_to=valid_to,
        anchor_id=anchor.anchor_id,
    )
    scenario.calibrations.append(record)
    return record
