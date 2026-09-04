---
name: scout
description: Discover goldmine research targets — mine erdosproblems, formal-conjectures, the AlphaEvolve problem repository, OEIS, MathOverflow, recent arXiv and the harness's own cross-campaign memory (open questions, lessons, rejected topics); score with the goldmine rubric; run a pairwise tournament; write campaigns/<slug>/portfolio.md with a selected target, stakes hint, backups and kill criteria.
argument-hint: "[area or constraints] [--slug name]"
effort: high
---

# /scout — Phase 1

`PY` = `.venv/Scripts/python.exe`. Arguments: `$ARGUMENTS`.

1. Ensure a campaign exists and is active (`PY -m harness campaign list` / `create` / `activate`), then
   `PY -m harness campaign phase <slug> scout --gate` (records the phase and opens the gate owned by this session).
2. Spawn the `scout` agent with: slug, the area/constraints from the arguments, the rubric path
   `skills/references/goldmine-rubric.md`, the cross-campaign memory (`PY -m harness library list questions`, `... lessons`,
   `... list rejected`, `... list results`), and the instruction to produce `campaigns/<slug>/portfolio.md` in the rubric's §4 format
   with ≥ 30 harvested candidates from ≥ 4 sources (our own open questions count as a source), rubric scores computed by a script,
   a tournament ranking, an excerpt-backed premise check for the top 5, and for the selected target a `- Statement (informal):` line
   and a `- Known best result (excerpt, source):` line (the harness parses them for the rejected-topic check and the stakes hint).
3. Verify the deliverable yourself: open `portfolio.md`; confirm every "open" status and "best known" value has a verbatim excerpt
   with a locator; confirm the selected target has a verifier plan and kill criteria; `PY -m harness campaign suggest-stakes <slug>`
   agrees with the scout's stakes assessment (or the portfolio says why not). If not, send the scout back with the specific gaps.
4. `PY -m harness campaign check <slug>` must pass (a selected target matching `library/rejected.jsonl` needs a `Rejected-override:` line).
   Summarize the selected target, its stakes tier and the two backups to the user in Korean and ask nothing — proceed
   (the `/research` orchestrator continues to `/survey`).
