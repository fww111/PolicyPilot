# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restricted entry script for the standard-change-impact skill.

Simulates the publication timeline for one standard: rebuild the pre-release
decision log from the old version view, diff the clause sets, analyze impact,
partially replay under the new version, and run the publication gate.
"""

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from competition.evolution import (  # noqa: E402
    DecisionLog,
    analyze_impact,
    diff_standards,
    publish,
    view_scenario,
)
from competition.pipeline import load_scenario  # noqa: E402


def run(job: dict, scenario_dir: Path) -> dict:
    standard_id = job.get("standard_id", "SPEC-D")
    old_version, new_version = job["old_version"], job["new_version"]

    scenario = load_scenario(scenario_dir)
    old_clauses = [c for c in scenario.clauses if c.standard_id == standard_id and c.version == old_version]
    new_clauses = [c for c in scenario.clauses if c.standard_id == standard_id and c.version == new_version]
    if not old_clauses or not new_clauses:
        raise ValueError(f"missing clauses for {standard_id} {old_version}->{new_version}")

    # Timeline: decision log before the new version was registered.
    t0 = view_scenario(scenario, {(standard_id, old_version)})
    batches = sorted({m.batch_no for m in scenario.measurements})
    log = DecisionLog.from_scenario(t0, batches)

    diffs = diff_standards(old_clauses, new_clauses, standard_id)
    impacts = analyze_impact(log.entries, diffs)
    outcome = publish(log, scenario, diffs, impacts)

    return {
        "publication": {
            "status": outcome.status,
            "reason": outcome.reason,
            "regression_result": outcome.changeset.regression_result if outcome.changeset else None,
            "affected_ids": outcome.changeset.affected_ids if outcome.changeset else [],
        },
        "impact": [
            {
                "decision_id": i.decision_id,
                "verdict": i.verdict,
                "path": i.path,
                "reason": i.reason,
            }
            for i in impacts
        ],
        "status_changes": [list(change) for change in (outcome.replay.status_changes if outcome.replay else [])],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="T2 standard change impact")
    parser.add_argument("--input", required=True, help="JSON job file")
    parser.add_argument("--scenario", required=True, help="scenario directory")
    parser.add_argument("--output", help="optional output file (default stdout)")
    args = parser.parse_args()

    job = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = run(job, Path(args.scenario))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
