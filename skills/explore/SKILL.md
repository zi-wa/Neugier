---
name: explore
description: Computational exploration — falsification-first tests of every target and route, experiments in the project venv with every number recorded in experiments/results.json, evolutionary program search with an exact scorer for construction/bound targets (mutations proposed by cheap subagents, scored by the harness), OEIS pattern mining, and ledger evidence (numerically-supported / refuted).
argument-hint: "[target-id] [--evolve config.json] [--hours n]"
effort: high
---

# /explore — Phase 4

`PY` = `.venv/Scripts/python.exe`. Set phase `explore`; open the gate. Read `plan.md` for the experiment order and budgets.

1. Spawn `experimentalist` with: slug, `plan.md`, `ideas.md`, `questions.md`, targets, the results-key conventions, and the budget
   (including the detour fraction). It must run falsification first on every `conjectured` target and lemma, write a prediction
   before each experiment, log `## Surprise`/`## Detour` entries in `questions.md` (rule R6), then the planned experiments, and
   attach evidence. If it reports a 3/3 surprise, consider a `strategist` re-plan before continuing.
2. **Evolutionary search** (when `plan.md` says so). The loop is agent-driven so no API key is needed:
   ```
   PY -m harness evolve init --campaign <slug> --config experiments/evolve/<name>.json      # hashes the scorer, seeds the population
   loop for G generations:
     PY -m harness evolve next --campaign <slug> --config <cfg> --n 6 > proposals.json      # parents + artifacts + prompt template
     spawn 6 `fetcher`-class *sonnet* subagents in parallel ("mutator" role): each reads proposals.json, writes ONE child program
       to the path given, following the mutation prompt (small, targeted edits; keep the evaluator interface)
     PY -m harness evolve score --campaign <slug> --config <cfg>                             # evaluates children with timeouts, updates elites
   PY -m harness evolve status --campaign <slug> --config <cfg>                              # best verified score, elites per bin
   ```
   Use the plan's noise-floor rule; every record is re-verified exactly (`exact: true`) before it enters `results.json` and the ledger.
   Never edit the scorer after `init` (its hash is checked; write a new versioned scorer and re-init if you must).
3. Mine the elites: describe the structure of the best constructions precisely and add candidate lemmas (`conjectured`) to the
   ledger for the prove phase.
4. Verify yourself that `experiments/results.json` contains every number the log mentions, each with `source` and `exact` flags.
5. `PY -m harness campaign check <slug>` must pass (no untested conjectured target). Report in Korean: refuted vs supported targets,
   best verified scores vs the known bounds (by results key), dead routes, proposed lemmas.
