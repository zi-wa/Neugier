---
name: scout
description: Discover goldmine research targets — mine erdosproblems, formal-conjectures, the AlphaEvolve problem repository, OEIS, MathOverflow and recent arXiv; score with the goldmine rubric; run a pairwise tournament; write campaigns/<slug>/portfolio.md with a selected target, backups and kill criteria.
argument-hint: "[area or constraints] [--slug name]"
effort: high
---

# /scout — Phase 1

`PY` = `.venv/Scripts/python.exe`. Arguments: `$ARGUMENTS`.

1. Ensure a campaign exists and is active (`PY -m harness campaign list` / `create` / `activate`). Set phase `scout` and open the gate
   (`echo scout > campaigns/<slug>/.gate`).
2. Spawn the `scout` agent with: slug, the area/constraints from the arguments, the rubric path
   `skills/references/goldmine-rubric.md`, and the instruction to produce `campaigns/<slug>/portfolio.md` in the rubric's §4 format
   with ≥ 30 harvested candidates from ≥ 4 sources, rubric scores computed by a script, a tournament ranking, and an
   excerpt-backed premise check for the top 5.
3. Verify the deliverable yourself: open `portfolio.md`; confirm every "open" status and "best known" value has a verbatim excerpt
   with a locator; confirm the selected target has a verifier plan and kill criteria. If not, send the scout back with the specific gaps.
4. `PY -m harness campaign check <slug>` must pass. Summarize the selected target and the two backups to the user in Korean and
   ask nothing — proceed (the `/research` orchestrator continues to `/survey`).
