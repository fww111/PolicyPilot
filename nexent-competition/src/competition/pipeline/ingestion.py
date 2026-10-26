# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scenario ingestion for the G1 closed loop.

Reads the synthetic scenario files, registers assets/revisions/anchors under
the section 5.2 contracts, and exposes structured records for the evaluator.

Anchor strategy: every extracted value locates back into the *original file
content* — CSV cells get table_cell locators, JSON scalars get char_span
locators resolved by searching the serialized needle, drawing refs and
standard clauses get clause locators. No anchor, no fact.

Business identity is separate from file names: assets carry business keys
parsed from content (part_no / standard_id+version), never the file name.
"""

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from competition.contracts.assets import Asset, AssetRevision
from competition.contracts.entities import Entity
from competition.contracts.evidence import EvidenceAnchor, Locator
from competition.contracts.ontology import StandardClause

INGEST_TIME = datetime(2026, 10, 24, 12, 0, 0)


@dataclass(frozen=True)
class MeasurementRecord:
    """One inspection row, values kept exactly as recorded."""

    batch_no: str
    part_no: str
    order_date: date
    feature_id: str
    measured_value: str
    unit: str
    measured_at: date
    instrument_id: str
    anchor_id: str
    row_no: int


@dataclass(frozen=True)
class CalibrationRecord:
    """One instrument calibration window."""

    instrument_id: str
    certificate_no: str
    valid_from: date
    valid_to: date
    anchor_id: str


@dataclass(frozen=True)
class ToleranceClause:
    """One standard clause as an executable tolerance spec."""

    standard_id: str
    version: str
    clause_no: str
    feature_id: str
    value_mm: float
    comparison: str
    scope: str
    effective_from: date
    anchor_id: str


@dataclass
class IngestedScenario:
    """Everything the evaluator needs, anchored back to source files."""

    assets: list[Asset] = field(default_factory=list)
    revisions: list[AssetRevision] = field(default_factory=list)
    anchors: dict[str, EvidenceAnchor] = field(default_factory=dict)
    entities: list[Entity] = field(default_factory=list)
    measurements: list[MeasurementRecord] = field(default_factory=list)
    calibrations: list[CalibrationRecord] = field(default_factory=list)
    clauses: list[ToleranceClause] = field(default_factory=list)
    standard_clauses: list[StandardClause] = field(default_factory=list)
    drawing_features: dict[str, str] = field(default_factory=dict)  # feature_id -> drawing_ref

    def revision_id_for_asset(self, asset_id: str) -> Optional[str]:
        for rev in self.revisions:
            if rev.asset_id == asset_id:
                return rev.revision_id
        return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _char_span_anchor(anchor_id: str, revision_id: str, text: str, needle: str, parser: str) -> EvidenceAnchor:
    """Locate a needle in the original text; refusal (not a guess) if absent."""

    pos = text.find(needle)
    if pos < 0:
        raise ValueError(f"anchor needle not found in source: {needle!r}")
    return EvidenceAnchor(
        anchor_id=anchor_id,
        revision_id=revision_id,
        locator=Locator(kind="char_span", char_start=pos, char_end=pos + len(needle)),
        raw_value=needle,
        parser_version=parser,
    )


# Standard record field -> canonical meaning. A second organization template
# maps its own column spellings onto these names via manifest inspection_columns.
DEFAULT_INSPECTION_COLUMNS = {
    "batch_no": "batch_no",
    "part_no": "part_no",
    "order_date": "order_date",
    "feature_id": "feature_id",
    "measured_value": "measured_value",
    "unit": "unit",
    "measured_at": "measured_at",
    "instrument_id": "instrument_id",
}


def _cell_anchor(
    anchor_id: str,
    revision_id: str,
    row: int,
    header_index: dict[str, int],
    file_header: str,
    value: str,
    parser: str,
) -> EvidenceAnchor:
    """Anchor a cell by the FILE's own header spelling and column order."""

    column = header_index[file_header]
    return EvidenceAnchor(
        anchor_id=anchor_id,
        revision_id=revision_id,
        locator=Locator(kind="table_cell", row=row, column=column, column_header=file_header),
        raw_value=value,
        parser_version=parser,
    )


def _d(value: str) -> date:
    return date.fromisoformat(value)


def load_scenario(data_dir: Path) -> IngestedScenario:
    """Load one scenario directory described by manifest.json."""

    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("synthetic", False):
        raise ValueError("only synthetic scenarios are loadable in G1")
    scenario = IngestedScenario()
    counter = 0

    def next_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-{counter:04d}"

    loaders: dict[str, Callable[[IngestedScenario, str, str, str, Callable[[str], str]], dict[str, str]]] = {
        "drawing": _load_drawing,
        "inspection_record": _load_inspections,
        "calibration": _load_calibrations,
        "standard": _load_standard,
    }

    for entry in manifest["files"]:
        category = entry["category"]
        if category not in loaders:
            raise ValueError(f"unknown category: {category}")
        path = data_dir / entry["file"]
        text = path.read_text(encoding="utf-8")
        revision_id = f"REV-{entry['asset_id']}"
        extra_kwargs: dict = {}
        if category == "inspection_record":
            # Declaring inspection_columns REPLACES the default mapping wholesale;
            # a template must map every standard field or loading fails loudly.
            declared = manifest.get("inspection_columns") or dict(DEFAULT_INSPECTION_COLUMNS)
            extra_kwargs["column_map"] = {file_header: standard for standard, file_header in declared.items()}
        business_keys = loaders[category](scenario, text, revision_id, entry["parser"], next_id, **extra_kwargs)
        scenario.assets.append(
            Asset(
                asset_id=entry["asset_id"],
                source_system="g1-synthetic",
                business_keys=business_keys,
                category=category,
                owner="synthetic",
            )
        )
        scenario.revisions.append(
            AssetRevision(
                revision_id=revision_id,
                asset_id=entry["asset_id"],
                file_name=entry["file"],
                content_digest=_digest(text),
                ingest_time=INGEST_TIME,
            )
        )
    return scenario


def _load_drawing(scenario: IngestedScenario, text: str, revision_id: str, parser: str, next_id) -> dict[str, str]:
    doc = json.loads(text)
    for feature in doc["features"]:
        ref = feature["drawing_ref"]
        anchor = EvidenceAnchor(
            anchor_id=next_id("ANC"),
            revision_id=revision_id,
            locator=Locator(kind="clause", clause_no=ref),
            raw_value=f"{feature['feature_id']}:{feature['name']}",
            parser_version=parser,
        )
        scenario.anchors[anchor.anchor_id] = anchor
        scenario.drawing_features[feature["feature_id"]] = ref
    return {"part_no": doc["part_no"]}


def _load_inspections(
    scenario: IngestedScenario,
    text: str,
    revision_id: str,
    parser: str,
    next_id,
    column_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Load inspection rows using the template's own column spellings.

    ``column_map`` maps FILE HEADER -> standard field; anchors keep the file's
    header spelling and column order so evidence still points into the
    original table (migration never rewrites source files).
    """

    standard_to_file = (
        {standard: file_header for file_header, standard in column_map.items()}
        if column_map is not None
        else dict(DEFAULT_INSPECTION_COLUMNS)
    )
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        return {"part_no": "unknown"}
    file_headers = list(rows[0].keys())
    header_index = {header: index + 1 for index, header in enumerate(file_headers)}
    missing = [field for field in DEFAULT_INSPECTION_COLUMNS if field not in standard_to_file]
    if missing:
        raise ValueError(f"inspection column mapping misses standard fields: {missing}")

    part_nos = set()
    for offset, row in enumerate(rows):
        row_no = offset + 2  # header is row 1
        part_nos.add(row[standard_to_file["part_no"]])
        value_header = standard_to_file["measured_value"]
        value_anchor = _cell_anchor(
            next_id("ANC"), revision_id, row_no, header_index, value_header, row[value_header], parser
        )
        scenario.anchors[value_anchor.anchor_id] = value_anchor
        scenario.measurements.append(
            MeasurementRecord(
                batch_no=row[standard_to_file["batch_no"]],
                part_no=row[standard_to_file["part_no"]],
                order_date=_d(row[standard_to_file["order_date"]]),
                feature_id=row[standard_to_file["feature_id"]],
                measured_value=row[standard_to_file["measured_value"]],
                unit=row[standard_to_file["unit"]],
                measured_at=_d(row[standard_to_file["measured_at"]]),
                instrument_id=row[standard_to_file["instrument_id"]],
                anchor_id=value_anchor.anchor_id,
                row_no=row_no,
            )
        )
    return {"part_no": sorted(part_nos)[0] if len(part_nos) == 1 else "mixed"}


def _load_calibrations(scenario: IngestedScenario, text: str, revision_id: str, parser: str, next_id) -> dict[str, str]:
    doc = json.loads(text)
    for cert in doc["certificates"]:
        anchor = _char_span_anchor(next_id("ANC"), revision_id, text, cert["certificate_no"], parser)
        scenario.anchors[anchor.anchor_id] = anchor
        scenario.calibrations.append(
            CalibrationRecord(
                instrument_id=cert["instrument_id"],
                certificate_no=cert["certificate_no"],
                valid_from=_d(cert["valid_from"]),
                valid_to=_d(cert["valid_to"]),
                anchor_id=anchor.anchor_id,
            )
        )
    return {"certificate_set": doc.get("certificate_set", "default")}


def _load_standard(scenario: IngestedScenario, text: str, revision_id: str, parser: str, next_id) -> dict[str, str]:
    doc = json.loads(text)
    for clause in doc["clauses"]:
        anchor = EvidenceAnchor(
            anchor_id=next_id("ANC"),
            revision_id=revision_id,
            locator=Locator(kind="clause", clause_no=clause["clause_no"]),
            raw_value=f"{clause['parameter']}={clause['value_mm']}",
            parser_version=parser,
        )
        scenario.anchors[anchor.anchor_id] = anchor
        scenario.clauses.append(
            ToleranceClause(
                standard_id=doc["standard_id"],
                version=doc["version"],
                clause_no=clause["clause_no"],
                feature_id=clause["feature_id"],
                value_mm=float(clause["value_mm"]),
                comparison=clause["comparison"],
                scope=clause["scope"],
                effective_from=_d(clause["effective_from"]),
                anchor_id=anchor.anchor_id,
            )
        )
        scenario.standard_clauses.append(
            StandardClause(
                standard_id=doc["standard_id"],
                version=doc["version"],
                clause_no=clause["clause_no"],
                scope=clause["scope"],
                effective_from=datetime.combine(_d(clause["effective_from"]), datetime.min.time()),
                source_anchor_id=anchor.anchor_id,
                applicability_confirmed=False,  # confirmed by the applicability rule at decision time
            )
        )
    return {"standard_id": doc["standard_id"], "version": doc["version"]}
