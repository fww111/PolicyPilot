# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restricted entry script for the cross-document-check skill.

Reads a JSON job (batch_no, optional revoked anchor ids), evaluates the batch
against the ingested scenario and prints the decision evidence pack as JSON.
Deliberately narrow: no shell, no network, no writes outside the process.
"""

import argparse
import json
import sys
from pathlib import Path

# Allow running directly from the package directory.
_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from competition.pipeline import evaluate_t1, load_scenario  # noqa: E402


def run(job: dict, scenario_dir: Path) -> dict:
    scenario = load_scenario(scenario_dir)
    decision = evaluate_t1(
        scenario,
        job["batch_no"],
        revoked_anchor_ids=frozenset(job.get("revoked_anchor_ids", [])),
    )
    return decision.model_dump(mode="json")


def main() -> int:
    parser = argparse.ArgumentParser(description="T1 cross-document check")
    parser.add_argument("--input", required=True, help="JSON job file")
    parser.add_argument("--scenario", required=True, help="scenario directory")
    parser.add_argument("--output", help="optional output file (default stdout)")
    args = parser.parse_args()

    job = json.loads(Path(args.input).read_text(encoding="utf-8"))
    pack = run(job, Path(args.scenario))
    rendered = json.dumps(pack, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
