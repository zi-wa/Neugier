---
name: plan-research
description: Build the research program — interpretation lock (statement.md with conventions, edge cases, excluded trivial readings, executable definition tests), ledger targets, ≥5 divergent attack routes plus one unconventional route with cheap falsification tests, budgets and kill/pivot rules; audited by the skeptic and pre-checked for novelty before any proof effort.
argument-hint: "[--targets n] [--max-review-rounds n]"
effort: xhigh
---

# /plan-research — Phase 3

`PY` = `.venv/Scripts/python.exe`. Set phase `plan`; open the gate.

1. Spawn `strategist` with: slug, `portfolio.md`, `survey.md`, `skills/references/creative-moves.md`, and the deliverables:
   `statement.md` + `experiments/statement_tests.py` (run, results into `results.json`), ledger targets (3–7, `conjectured`),
   `ideas.md` (≥ 5 routes + 1 unconventional per target, exact route format), `questions.md` (≥ 3 open `## Q-` entries with
   expectation and cheapest test; targets phrased as questions — rule R6), `plan.md` (experiments, evolve spec, lemma DAG
   candidates, budgets incl. `max_review_rounds` and `curiosity_fraction`, kill/pivot rules). It must **not** lock the statement yet.
2. **Statement audit** (information barrier): spawn `skeptic` in statement-audit mode with only `statement.md`,
   `experiments/statement_tests.py`, and the ledger facts. It writes `reviews/statement-audit.md` (`verdict: pass|revise`).
   On `revise`, return the concrete edits to the strategist; repeat once.
3. **Novelty pre-check**: spawn `novelty-checker` with only `statement.md` and `refs.bib` (45-minute timebox, short memo into
   `survey.md` §Novelty or `reviews/round0/novelty.md`). Class `1c`/`1d` ⇒ the target is `known-in-literature`; pivot to a backup
   from `portfolio.md` (record the rejection in the library) and redo steps 1–3.
4. Lock: `PY -m harness campaign lock-statement <slug>`. From now on `statement.md` is immutable (hash-checked).
5. Run every route's cheap falsification test now if it takes < 5 minutes (else leave for explore); mark routes in `ideas.md`.
6. `PY -m harness campaign check <slug>` must pass. Report in Korean: targets with ids, the routes (one line each), budgets,
   kill criteria.
