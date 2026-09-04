---
name: plan-research
description: Build the research program — interpretation lock (statement.md with conventions, edge cases, excluded trivial readings, executable definition tests), ledger targets with stakes tiers and pre-registered credences, ≥5 divergent attack routes plus one unconventional route each with a cheap falsification test and a credence, pre-registered marking schemes (rubrics) for every active target, budgets and kill/pivot rules; audited by the skeptic and pre-checked for novelty before any proof effort.
argument-hint: "[--targets n] [--max-review-rounds n]"
effort: xhigh
---

# /plan-research — Phase 3

`PY` = `.venv/Scripts/python.exe`. `PY -m harness campaign phase <slug> plan --gate` (records the phase and opens this session's gate).

1. Spawn `strategist` with: slug, `portfolio.md`, `survey.md`, `questions.md`, `skills/references/creative-moves.md`,
   `skills/references/technique-pitfalls.md`, the outputs of `PY -m harness library lessons --query "<topic>"` and
   `PY -m harness library moves-stats`, and the deliverables:
   - `statement.md` + `experiments/statement_tests.py` (run it; record `results.json["statement_tests"] = {passed, n, source}`);
   - ledger targets (3–7, `conjectured`, each with `--stakes` — use `PY -m harness campaign suggest-stakes <slug>` as a hint) and a
     **pre-registered credence** on each (`PY -m harness ledger credence <ID> --role strategist --p-true … --p-budget … --why … [--panel …]`);
     `PY -m harness campaign targets <slug> --set <ids>`;
   - `ideas.md` (≥ 5 routes + 1 unconventional per target, exact route format incl. `- Credence:`; `PY -m harness ideas dedup` clean);
   - `questions.md` (≥ 3 open `## Q-` entries with expectation, cheapest test and credence; targets phrased as questions — rule R6);
   - a **marking scheme** `proofs/<ID>.rubric.md` for every active target (what a correct proof must establish, required hypotheses,
     hard step, technique tags + pitfalls) — written *before* any proof exists, no route hints;
   - `plan.md` (experiments, evolve spec, lemma DAG candidates, kill/pivot rules) and the budgets:
     `PY -m harness campaign budget <slug> --set hours_total=… --set hours_per_phase.explore=… --set max_review_rounds=… --set curiosity_fraction=0.3`.
   It must **not** lock the statement yet.
2. **Statement audit** (information barrier): spawn `skeptic` in statement-audit mode with only `statement.md`,
   `experiments/statement_tests.py`, and the ledger facts. It writes `reviews/statement-audit.md` (`verdict: pass|revise`).
   On `revise`, return the concrete edits to the strategist; repeat once.
3. **Novelty pre-check**: spawn `novelty-checker` with only `statement.md` and `refs.bib` (45-minute timebox, short memo into
   `survey.md` §Novelty or `reviews/round0/novelty.md`; `harness lit cite-walk` for the seeds). Class `1c`/`1d` ⇒ the target is
   `known-in-literature`; pivot to a backup from `portfolio.md` (record the rejection in the library) and redo steps 1–3.
4. Lock: `PY -m harness campaign lock-statement <slug>` — freezes `statement.md` **and** every `proofs/*.rubric.md` (hash-checked;
   the frozen-file hook denies edits from now on). `PY -m harness campaign freeze <slug> experiments/<verifier>.py …` for verifiers.
5. Run every route's cheap falsification test now if it takes < 5 minutes (else leave for explore); update `- Status:` in `ideas.md`.
6. `PY -m harness campaign check <slug>` must pass (statement tests, credences, rubrics, budgets). Report in Korean: targets with ids,
   stakes tiers and credences, the routes (one line each), budgets, kill criteria.
