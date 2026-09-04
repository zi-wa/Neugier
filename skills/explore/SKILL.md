---
name: explore
description: Computational exploration — falsification-first tests of every target and route (predict before you measure), experiments in the project venv with every number recorded in experiments/results.json, evolutionary program search with an exact frozen scorer (cheap subagents propose mutations; the harness rejects near-duplicates, runs cascades, collects meta-recommendations, mines elites), counterexample-guided conjecture repair, OEIS pattern mining, and ledger evidence (numerically-supported / refuted).
argument-hint: "[target-id] [--evolve config.json] [--hours n]"
effort: high
---

# /explore — Phase 4

`PY` = `.venv/Scripts/python.exe`. `PY -m harness campaign phase <slug> explore --gate` (records the phase and opens this session's gate). Read `plan.md` for the experiment order and budgets;
`PY -m harness questions next --campaign <slug>` for the highest-information-gain question.

1. Spawn `experimentalist` with: slug, `plan.md`, `ideas.md`, `questions.md`, targets, the results-key conventions
   (`{key: {value, source, args, seed, exact}}`), and the budget (including the detour fraction). It must run falsification first on
   every `conjectured` target and lemma, write a **prediction before each experiment** and record the pair
   (`harness questions surprise … --as-prediction` / `## Surprise` on deviation — the gate needs ≥ 1 recorded pair), then the
   planned experiments, and attach evidence. A 3/3 surprise → consider a `strategist` re-plan before continuing.
2. **Refutations are inputs.** When a target or lemma is `refuted`: `PY -m harness ledger repair <id>` writes
   `experiments/repair/<id>.json` (counterexamples with features, the regression set, the three operators). The experimentalist
   proposes ≤ 3 child conjectures (`ledger add --repaired-from <id> --repair-op add-hypothesis|weaken-bound|absorb-and-regenerate`),
   runs `harness falsify run … --regression experiments/falsify/<id>.regression.json` on each (truth test; bounds need `touch_number ≥ 1`),
   and records a `significance:` note before promoting a child to `numerically-supported`.
3. **Evolutionary search** (when `plan.md` says so). The loop is agent-driven so no API key is needed:
   ```
   PY -m harness evolve init --campaign <slug> --config experiments/evolve/<name>.json   # hashes + freezes the scorer, seeds the population (refuses re-init; --new-version for a new run)
   loop for G generations:
     PY -m harness evolve next --campaign <slug> --config <cfg> --n 6 > proposals.json   # parents + artifacts + prompt + meta-recommendations; retry slots first
     spawn 6 `fetcher`-class *sonnet* subagents in parallel ("mutator" role): each reads proposals.json, writes ONE child program
       to the path given, following the mutation prompt (small, targeted edits; keep the evaluator interface; children flagged "must differ" must)
     PY -m harness evolve score --campaign <slug> --config <cfg>                          # rejects near-duplicates, runs cascade stages, evaluates with timeouts, updates elites
     every `meta_interval` generations: the harness writes meta_request.json → spawn ONE top-model agent to write meta.md (≤ 5 recommendations)
   PY -m harness evolve status --campaign <slug> --config <cfg>                           # best score (exact?), elites per bin, needs_exact_verification
   PY -m harness evolve checkpoint … / resume …                                           # long runs
   ```
   Use the plan's noise-floor rule (`noise_floor` in the config; also applied to elites); a record counts only when `exact: true`
   before it enters `results.json` and the ledger. Never edit the scorer after `init` (hash + frozen-file hook).
4. Mine the elites: `PY -m harness evolve mine --campaign <slug> --config <cfg> --top 5` writes `mine.md` (elite code, feature
   vectors, artifacts, OEIS lookups of integer sequences); describe the structure of the best constructions precisely and add
   candidate lemmas (`conjectured`, with credences) to the ledger for the prove phase.
5. Verify yourself that `experiments/results.json` contains every number the log mentions, each with `source`, `args`, `seed` and
   `exact` flags (the paper's reproduce commands are generated from them).
6. `PY -m harness campaign check <slug>` must pass (no untested conjectured target; a recorded prediction). Report in Korean:
   refuted vs supported targets (and repaired children), best verified scores vs the known bounds (by results key), dead routes,
   surprises, proposed lemmas.
