---
name: research
description: Run a full Neugier research campaign — scout → survey → plan (interpretation lock) → explore (falsification-first, evolutionary search) → prove → adversarial review (information barrier) → paper — on a topic or on `auto` (scout picks a goldmine target). Enforces phase exit criteria via the Stop-hook gate and the judge's escalation ladder, and ends with a LaTeX paper and an honest outcome class.
argument-hint: "[topic | auto] [--slug name] [--resume]"
effort: high
---

# /research — campaign orchestrator

You are the campaign orchestrator. Reason in English; report to the user in Korean. Read `CLAUDE.md` first.
`PY` below means `.venv/Scripts/python.exe` (Linux/macOS: `.venv/bin/python`). Arguments: `$ARGUMENTS`.

## 0. Bootstrap
1. If `.venv` or `bin/tectonic*` is missing: run `scripts/bootstrap.ps1` (Windows) or `scripts/bootstrap.sh`.
2. Slug: from `--slug`, else a short kebab-case name from the topic (or `auto-<date>`). If `campaigns/<slug>` exists or
   `--resume` is given, resume from its `campaign.json` phase; else `PY -m harness campaign create <slug> --title "<topic>"`.
3. `PY -m harness campaign activate <slug>`. Consult `PY -m harness library list rejected` and `... list results`.

## Phase loop
For each phase in order (skip phases already completed on resume), do:
```
PY -m harness campaign phase <slug> <phase>        # record entry
echo <phase> > campaigns/<slug>/.gate               # open the gate: the Stop hook will not let the turn end until exit criteria pass
... run the phase (below) ...
PY -m harness campaign check <slug>                 # must print "all criteria met"; otherwise keep working or write blocked.md
```
Phase procedures are specified in the sibling skills; follow them exactly:
`skills/scout/SKILL.md`, `skills/survey/SKILL.md`, `skills/plan-research/SKILL.md`, `skills/explore/SKILL.md`,
`skills/prove/SKILL.md`, `skills/adversarial-review/SKILL.md`, `skills/paper/SKILL.md`.
Spawn agents with the `Agent` tool using `subagent_type` = the agent's name (`scout`, `librarian`, `fetcher`, `strategist`,
`experimentalist`, `prover`, `skeptic`, `falsifier`, `novelty-checker`, `replicator`, `judge`, `writer`, `copyeditor`).
Give every agent: the slug, the exact files to read, the exact files to produce, and the budget. Never paste your own reasoning
about the mathematics into a referee's prompt (information barrier).

| Phase | Agents | Exit criteria (checked by the CLI) |
|---|---|---|
| scout | scout (skip if topic given and user wants it; still write `portfolio.md` with the premise check) | portfolio.md |
| survey | librarian (+ fetcher) | survey.md, refs.bib ≥ 3 resolved, ≥ 3 known-in-literature facts with excerpts |
| plan | strategist → skeptic (statement audit) → novelty-checker (pre-check) | statement.md locked, plan.md, ideas.md ≥ 5 routes, questions.md ≥ 3 questions, ≥ 1 conjectured target, budgets |
| explore | experimentalist (+ sonnet mutators for evolve) | every conjectured target has falsification/computation evidence; results.json |
| prove | prover ×1–4 (persona lenses) → judge (tournament) | ≥ 1 claim proof-drafted |
| review | skeptic ∥ falsifier ∥ novelty-checker ∥ replicator → judge (→ prover response → next round) | round files complete; ≥ 1 referee-passed or `VERDICT: PIVOT` |
| write | writer → copyeditor | main.pdf, check.json ok |
| done | you | outcome class set; `## Outcome` in log.md; library updated |

## Curiosity loop (rule R6, `skills/references/curiosity.md`)
The phase table is the set of guardrails, not the itinerary. After **every** phase (and whenever an agent reports a 3/3 surprise):
1. Read `campaigns/<slug>/questions.md`. List the open questions by curiosity score and note new `## Surprise` entries.
2. Decide by expected information gain what to do next: continue the phase order, spawn a short **detour** (any agent, within
   `budgets.curiosity_fraction` of the phase budget — default 30%), or ask the `strategist` to re-plan around the surprise
   (targets may be reordered or replaced; the interpretation lock is not touched).
3. Log the decision in `log.md` as `decision: … — because …`.
Agents may take detours on their own within the budget; you only need to account for them. Curiosity never skips a gate.

## Escalation ladder (from `reviews/roundN/judge.md`)
- `PASS` → write phase. `REVISE_PROOF`/`REWRITE` → prover (same claim, next round, with the referee reports) → review again,
  up to `budgets.max_review_rounds`. `REVISE_PLAN` → strategist re-plans routes → explore/prove again.
- `PIVOT` → strategist pivots to a backup target (or the judge's downgrade stands): record the rejected target in the library
  (`PY -m harness library add-rejected ...`), then continue from explore with the new target. If no backup remains, go to write
  with the honest outcome class (`partial`, `negative`, `literature-find`, or `rediscovery`).

## 8. Finish
1. Set the outcome class (Python one-liner editing `campaign.json`: `autonomous-new-result | partial | rediscovery | literature-find | negative`)
   strictly from the ledger: `autonomous-new-result` requires a referee-passed claim with novelty `1a`/`1b`.
2. Append `## Outcome` to `log.md` (what was proven, what was not, dead routes, time spent) and
   `PY -m harness library add-result --campaign <slug> --title ... --outcome ... --claims-json <file> --paper campaigns/<slug>/paper/main.pdf`.
3. `PY -m harness campaign phase <slug> done`, remove `.gate`, and report to the user in Korean: outcome class, paper path,
   asserted claims, and the honest list of gaps.

## Rules
- Never skip a phase's exit criteria; if a phase is genuinely blocked, write `campaigns/<slug>/blocked.md` and tell the user.
- Budget discipline: respect `campaign.json` budgets; long computations run with timeouts and checkpoints.
- Log every phase transition and decision in `campaigns/<slug>/log.md` with a timestamp.
