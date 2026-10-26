---
name: cross-document-check
description: Verify one batch against drawings, inspection records, calibration certificates and the applicable standard version, and emit a four-valued decision evidence pack with per-fact anchors.
allowed-tools:
  - search_assets
  - get_evidence
  - resolve_entity
  - check_constraints
tags:
  - quality
  - t1
  - evidence-pack
script_outputs:
  decision_pack: json
---

# Cross-document check (T1)

Execute the restricted T1 plan for one batch. Execution order follows the
retrieval-then-reasoning loop:

1. Parse the goal: batch number, feature, decision target.
2. Bind the version snapshot: ontology release, rules, standard versions.
3. Instantiate the registered T1 plan (find measurements -> select applicable
   clause -> check calibration -> check tolerance -> aggregate -> emit).
4. Retrieve candidate evidence through the asset/evidence tools; every fact
   must resolve to an anchor.
5. Deterministic rule evaluation; missing inputs yield `unknown`, never `false`.
6. Locate gaps/conflicts; emit typed retrieval tasks instead of guessing.
7. Output the decision pack (supported / refuted / unknown / conflict) or
   hand over to human review.

Never fabricate evidence; never pass a batch on a number alone when the
instrument calibration cannot be verified.
