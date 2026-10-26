---
name: standard-change-impact
description: Compare two standard versions, compute the impact closure over historical decisions, replay affected batches only, and emit re-review lists plus a gated ChangeSet candidate.
allowed-tools:
  - search_assets
  - analyze_change_impact
tags:
  - quality
  - t2
  - change-impact
script_outputs:
  impact_report: json
---

# Standard change impact (T2)

1. Diff the old and new clause sets (add/replace/retire/attribute/scope).
2. Build the impact closure over the decision log via BOTH paths: dependency
   propagation and new-predicate scan; unrecognized scope expressions widen
   the review set conservatively.
3. Replay only needs-review decisions under the new version set; keep the
   rest verbatim.
4. Gate the publication: anchor availability, local==full equivalence, and
   the impact-leak detector must all pass; otherwise roll back and keep the
   old state.
5. Emit re-review lists (must-review / unaffected / uncertain) and the
   ChangeSet candidate. Publication itself always requires human approval.
