---
name: prove
description: Proof development for a ledger claim — persona provers write SKETCHES first, the falsifier attacks every sketch lemma, judge-class raters rank sketches pairwise (plausibility / clarity / novelty) into an Elo tournament that selects who gets the full-proof budget; then complete numbered citation-anchored proof artifacts per proof-standards.md, lemma DAG in the ledger, lemma-bank lookups, falsifier runs on every lemma, the proof linter, pre-registered p_pass credences, promotion to proof-drafted.
argument-hint: "<claim-id> [--personas n] [--route k] [--workflow]"
effort: max
---

# /prove — Phase 5

`PY` = `.venv/Scripts/python.exe`. `PY -m harness campaign phase <slug> prove --gate` (records the phase and opens this session's gate). Claim: first token of `$ARGUMENTS` (else the primary target).
Read `proofs/<ID>.rubric.md` (the pre-registered marking scheme) — it says what a correct proof must establish.

1. Decide the number of parallel provers from the budget (1 for a small lemma; `budgets.sketch_personas` persona lenses for the main
   target: combinatorialist / analyst / algebraist / experimentalist, each on a *different* surviving route from `ideas.md`).
   Before any lemma is created: `PY -m harness library find-lemma "<statement>"` (goal cache) — reuse hits.
2. **Sketch round** (≥ 2 provers): spawn the `prover` agents in SKETCH mode with slug, claim id, persona + route, the rubric, and the
   output path `proofs/<ID>.sketch.<persona>.md` (frontmatter `kind: sketch`, lemma list with a cheapest falsification each; no ledger writes).
   Then spawn `falsifier` once to attack every sketch lemma cheaply (≤ 5 min each) → `reviews/tournament-<ID>/falsify/<persona>-<label>.json`.
3. **Rating**: for every unordered pair of sketches spawn one `judge` in RATER mode per axis (plausibility, clarity, novelty) — fresh
   context, both sketches + falsification results, output `reviews/tournament-<ID>/match-<a>-<b>-<axis>-pairwise.json`. Run
   `PY -m harness prove elo --campaign <slug> --claim <ID>`; for the top `budgets.debate_top` sketches add multi-turn `debate` matches
   (the rater sees both sketches and the pairwise rationales) and re-run `prove elo`. `tournament.json` lists the selected sketches
   (`budgets.full_proofs`), vetoes sketches with a falsified lemma, and records cross-pollination notes.
4. **Full proofs**: spawn the selected provers (each with its cross-pollination notes) to expand their sketch into
   `proofs/<ID>.<persona>.md` (single prover: `proofs/<ID>.md`) per `skills/references/proof-standards.md`. They create lemma claims
   in the ledger with `depends_on`, run the falsifier on every lemma, run `PY -m harness proof check`, record `--p-pass`, and attach proof evidence.
5. If more than one full artifact: spawn `judge` in tournament mode on the artifacts → `reviews/tournament-<ID>.md`; then spawn one
   prover to merge the winner with the useful components into `proofs/<ID>.md` and attach it as the proof evidence; discard nothing.
6. Check the artifact yourself: `PY -m harness proof check proofs/<ID>.md --campaign <slug>` passes; `assumes:` empty (else the
   theorem is conditional and the paper must say so); every `<cite>` resolves to a verified excerpt; exactly one `<key-original-step>`.
7. `PY -m harness ledger promote <ID> proof-drafted --campaign <slug>` (the prover normally does this; verify — the CLI refuses
   artifacts that fail the linter). Every proof-drafted lemma must have falsification evidence (the gate's advisories say which lack it).
8. Answer or park the prover's open questions (`harness questions answer|park`). `PY -m harness campaign check <slug>` must pass.
   Report in Korean: tournament ranking, route that succeeded, lemma DAG, what is new, residual doubts. Then proceed to `/review`.

## `--workflow`
With `--workflow` and the `Workflow` tool available, call the saved workflow `neugier-prove` twice: first with
`args = {slug, claim, personas: [{name, route}, …]}` (Sketch → Falsify → Rate), then after `prove elo` with
`args = {slug, claim, selected: tournament.json.selected, isolation?: 'worktree'}` (Prove). With worktree isolation, collect the
results with `PY -m harness prove collect --campaign <slug> --claim <ID> --commits <sha,…>` (replays the provers' `ledger-ops.jsonl`).
