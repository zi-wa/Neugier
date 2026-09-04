---
name: research
description: Run a full Neugier research campaign — scout → survey → plan (interpretation lock, pre-registered credences and marking schemes) → explore (falsification-first, evolutionary search, conjecture repair) → prove (sketch tournament) → adversarial review (enforced information barrier, decoy lineups, k-of-k skeptics, blinded replication) → paper (provenance + disclosure appendices) — on a topic or on `auto` (scout picks a goldmine target). Enforces phase exit criteria via the Stop-hook gate and the judge's escalation ladder, and ends with a LaTeX paper and an honest, validated outcome class.
argument-hint: "[topic | auto] [--slug name] [--resume] [--workflow]"
effort: high
---

# /research — campaign orchestrator

You are the campaign orchestrator. Reason in English; report to the user in Korean. Read `CLAUDE.md` first.
`PY` below means `.venv/Scripts/python.exe` (Linux/macOS: `.venv/bin/python`). Arguments: `$ARGUMENTS`.

## 0. Bootstrap
1. If `.venv` or `bin/tectonic*` is missing: run `scripts/bootstrap.ps1` (Windows) or `scripts/bootstrap.sh`. `PY -m harness doctor --offline`
   must report no hard failure.
2. Slug: from `--slug`, else a short kebab-case name from the topic (or `auto-<date>`). If `campaigns/<slug>` exists or
   `--resume` is given, resume from its `campaign.json` phase; else `PY -m harness campaign create <slug> --title "<topic>"`
   (refused when the title matches `library/rejected.jsonl`; `--allow-rejected` only with a reason in `log.md`).
3. `PY -m harness campaign activate <slug>`. Read `campaigns/<slug>/HUMAN.md` (the human's policy; never edit it) and
   `PY -m harness campaign ack-human <slug>`. Consult `PY -m harness library list rejected`, `... list results`,
   `... lessons --query "<topic>"`, `... moves-stats`, `... list questions`.

## Phase loop
For each phase in order (skip phases already completed on resume), do:
```
PY -m harness campaign phase <slug> <phase>        # record entry (budgets.hours_per_phase are accounted from here)
echo <phase> > campaigns/<slug>/.gate               # open the gate: the Stop hook will not let the turn end until exit criteria pass
... re-read HUMAN.md; run the phase (below) ...
PY -m harness campaign check <slug>                 # must print "all criteria met"; read its advisories; otherwise keep working or write blocked.md
```
Phase procedures are specified in the sibling skills; follow them exactly:
`skills/scout/SKILL.md`, `skills/survey/SKILL.md`, `skills/plan-research/SKILL.md`, `skills/explore/SKILL.md`,
`skills/prove/SKILL.md`, `skills/adversarial-review/SKILL.md`, `skills/paper/SKILL.md`.
Spawn agents with the `Agent` tool using `subagent_type` = the agent's name (`scout`, `librarian`, `fetcher`, `strategist`,
`experimentalist`, `prover`, `skeptic`, `falsifier`, `novelty-checker`, `replicator`, `judge`, `writer`, `copyeditor`).
Give every agent: the slug, the exact files to read, the exact files to produce, and the budget. Never paste your own reasoning
about the mathematics into a referee's prompt (information barrier — the hooks log every referee access and the round fails
on an unwaived denial).

| Phase | Agents | Exit criteria (checked by the CLI) |
|---|---|---|
| scout | scout (skip if topic given and user wants it; still write `portfolio.md` with the premise check) | portfolio.md; selected target not in `library/rejected.jsonl` |
| survey | librarian (+ fetcher) | survey.md, refs.bib ≥ 3 resolved, ≥ 3 known-in-literature facts with **verified** excerpts (cached sources) |
| plan | strategist → skeptic (statement audit) → novelty-checker (pre-check) | statement.md locked, plan.md, ideas.md ≥ 5 routes each with `- Credence:`, questions.md ≥ 3, ≥ 1 conjectured target with `p_true`, `budgets.hours_total`, `experiments/statement_tests.py` passed, a frozen `proofs/<target>.rubric.md` per active target |
| explore | experimentalist (+ sonnet mutators for evolve; strategist for repairs) | every conjectured target has falsification/computation evidence; results.json; ≥ 1 recorded prediction/observation pair |
| prove | prover ×1–4 (sketches → tournament → full proofs) → judge (rater) | ≥ 1 claim proof-drafted; artifacts pass `harness proof check`; no open prover questions |
| review | skeptic ×k ∥ falsifier ∥ novelty-checker ∥ replicator → judge (→ prover response → next round) | round manifest + access log clean; ≥ 1 referee-passed or `VERDICT: PIVOT`; round cap |
| write | writer → copyeditor | main.pdf, check.json ok, audit.json labeled, novelty memo present |
| done | you | `campaign outcome` validated; `## Outcome` and `## Lessons` in log.md; `campaign finish` |

`--workflow`: for the review and prove phases you may run the saved deterministic scripts instead of spawning agents by hand
(`Workflow` tool, names `neugier-review` / `neugier-prove`; the skills say what to run before and after). Default is the manual path.

## Curiosity loop (rule R6, `skills/references/curiosity.md`)
The phase table is the set of guardrails, not the itinerary. After **every** phase (and whenever an agent reports a 3/3 surprise):
1. `PY -m harness questions next --campaign <slug>`: the open questions ranked by expected information gain (credence-weighted),
   with calibration warnings; read new `## Surprise` entries.
2. Decide by expected information gain what to do next: continue the phase order, spawn a short **detour** (any agent, within
   `budgets.curiosity_fraction` of the phase budget — default 30%), or ask the `strategist` to re-plan around the surprise
   (targets may be reordered or replaced; the interpretation lock is not touched).
3. Log the decision in `log.md` as `decision: … — because …`.
4. A question only the human can answer cheaply → `PY -m harness questions for-human …` (budgeted; never blocks).
Agents may take detours on their own within the budget; you only need to account for them. Curiosity never skips a gate.

## Escalation ladder (from `reviews/roundN/judge.md`)
- `PASS` → write phase. `REVISE_PROOF`/`REWRITE` → prover (same claim, next round, with the referee reports) → review again,
  up to `budgets.max_review_rounds`. `REVISE_PLAN` → strategist re-plans routes → explore/prove again.
- `PIVOT` → strategist pivots to a backup target (or the judge's downgrade stands): record the rejected target in the library
  (`PY -m harness library add-rejected ...`), then continue from explore with the new target. If no backup remains, go to write
  with the honest outcome class (`partial`, `negative`, `literature-find`, or `rediscovery`).
- A refuted target is not the end: `PY -m harness ledger repair <id>` and the experimentalist's repair loop may yield a
  publishable child conjecture.

## 8. Finish
1. Ask the judge and strategist for a `## Lessons` block in `log.md` (which referee caught what, which creative moves produced the
   key step, why routes died — one bullet each with `— evidence: … — moves: … — tags: …`), and write `## Outcome`
   (what was proven, what was not, dead routes, time spent, what we still do not know).
2. `PY -m harness campaign outcome <slug> <class>` — the class is **validated** against the ledger and the novelty memo
   (`autonomous-new-result` needs a referee-passed claim and class 1a/1b; 1c forces rediscovery/literature-find).
3. `PY -m harness campaign finish <slug>` — records the result, open questions, calibration and lessons in `library/`, sets phase
   `done`, releases the gate. Then report to the user in Korean: outcome class, paper path, asserted claims with their
   verification levels (from the disclosure), the honest list of gaps, and the calibration summary.

## Rules
- Never skip a phase's exit criteria; if a phase is genuinely blocked, write `campaigns/<slug>/blocked.md` and tell the user.
- Budget discipline: `campaign.json` budgets are read by the gates (a phase that overran needs a `## Budget overrun (<phase>)` note);
  long computations run with timeouts and checkpoints.
- Log every phase transition and decision in `campaigns/<slug>/log.md` with a timestamp.
- Frozen files (scorers, verifiers, `statement.md`, rubrics, `HUMAN.md`) are protected by a hook during explore/prove/review; do not work around it.
