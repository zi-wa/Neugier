---
name: prove
description: Proof development for a ledger claim — parallel persona provers on different routes, tournament judged for cross-pollination, lemma DAG in the ledger, complete numbered citation-anchored proof artifacts per proof-standards.md, falsifier runs on every lemma, promotion to proof-drafted.
argument-hint: "<claim-id> [--personas n] [--route k]"
effort: max
---

# /prove — Phase 5

`PY` = `.venv/Scripts/python.exe`. Set phase `prove`; open the gate. Claim: first token of `$ARGUMENTS` (else the primary target).

1. Decide the number of parallel provers from the budget (1 for a small lemma; 2–4 persona lenses for the main target:
   combinatorialist / analyst / algebraist / experimentalist, each on a *different* surviving route from `ideas.md`).
2. Spawn the `prover` agents in parallel with: slug, claim id, persona + route, `skills/references/proof-standards.md`, and the
   output path `proofs/<ID>.<persona>.md` (single prover: `proofs/<ID>.md`). They create lemma claims in the ledger with
   `depends_on`, falsify lemmas, and attach proof evidence.
3. If more than one artifact: spawn `judge` in tournament mode on the artifacts → `reviews/tournament-<ID>.md`; then spawn one
   prover to merge the winner with the useful components (cross-pollination) into `proofs/<ID>.md` and attach it as the proof
   evidence; discard nothing (keep alternates for the record).
4. Check the artifact header yourself: `assumes:` empty (else the theorem is conditional and the paper must say so),
   `uses_hypotheses` complete, every `<cite>` has a ledger fact with an excerpt, `<key-original-step>` present.
5. `PY -m harness ledger promote <ID> proof-drafted --campaign <slug>` (the prover normally does this; verify).
6. `PY -m harness campaign check <slug>` must pass. Report in Korean: route that succeeded, lemma DAG, what is new, residual doubts.
   Then proceed to `/review`.
