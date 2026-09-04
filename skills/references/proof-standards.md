# Proof standards (Neugier)

These are the rules a proof artifact must satisfy before it may enter adversarial review. The prover writes
for a hostile referee who sees *only* `statement.md`, the marking scheme and the proof file. Nothing else is available to them.
`python -m harness proof check proofs/<ID>.md --campaign <slug>` enforces §1–§6 mechanically; `ledger promote … proof-drafted`
refuses an artifact that fails it.

## 1. Artifact format

One file per claim: `campaigns/<slug>/proofs/<CLAIM-ID>.md`.

```markdown
---
claim: L-003
statement: "For every finite S ⊂ Z with |S| ≥ 2, |S+S| ≥ 2|S| - 1."
depends_on: [D-001, F-002]        # ledger ids used (definitions, cited facts, earlier lemmas)
assumes: []                        # ledger ids of UNPROVEN claims this proof relies on (conjectures) — must be empty for a theorem
uses_hypotheses: [finite, "|S| >= 2"]  # every hypothesis of the statement; each must be used in some step (see §4); quote math-heavy items
numerics: [results.json#sumset_small_cases]   # keys in experiments/results.json referenced below
technique: [extremal, double-counting]        # tags from skills/references/technique-pitfalls.md (the marking scheme uses them)
version: 2
---

## Proof

**Setup.** ...

**Step 1.** (definition D-001) ...
**Step 2.** (algebra) ...
**Step 3.** <cite id="Ruzsa1994" claim="F-002" excerpt-hash="3fa1…"> Plünnecke–Ruzsa gives ... </cite>
**Step 4.** <key-original-step> ... the new idea ... </key-original-step>
**Step 5.** (Steps 2, 4) ...
**Conclusion.** ...

## Edge cases checked
- |S| = 2: ...
- S symmetric / arithmetic progression (extremal case): ...

## Self-check log
- Hypothesis use: finite → Step 2; |S| ≥ 2 → Step 4.
- Numeric spot-check: results.json#sumset_small_cases (n ≤ 12) — consistent.
```

The YAML header is machine-read: `assumes` must be empty for anything promoted to `referee-passed`; `technique` selects the
pitfalls the skeptic must walk; `excerpt-hash` is the 12-hex prefix printed by `harness ledger show F-002` for a verified excerpt.

## 2. Steps

- **Every step is numbered** and names its justification in parentheses: `(definition D-001)`, `(algebra)`,
  `(Step k)`, `(cited: <bibkey>)`, `(computation: results.json#key)`, or `<key-original-step>`. The justification kind is
  what the coverage metric reports (definition / algebra / computation / derived / cited / key / synthesis).
- A step contains **one inference**. If a referee could ask "why?" twice, split it.
- Quantifiers are explicit. Say which variable is fixed, which is arbitrary, and in which order they were chosen.
  A step that silently swaps ∀/∃ order is a critical error.
- Constants are tracked. `C` must be defined the first time it appears; `O(·)` must say what it depends on.
- Case analyses list all cases and say why they are exhaustive.
- An inequality chain shows each comparison separately if the justifications differ.

## 3. Citations (rule R5a)

- A cited result may be used only through `<cite id="bibkey" claim="F-xxx" excerpt-hash="…">`, where `F-xxx` is a ledger
  claim with status `known-in-literature` carrying a **verified** verbatim excerpt (found in the cached source text).
- State the cited theorem in your own words *with all its hypotheses*, then show each hypothesis holds here.
  "By [X]" without hypotheses check is a justification gap; if a hypothesis fails, it is a critical error.
- Never cite from memory. If the excerpt is not in the ledger, obtain it (librarian: `harness lit fetch`, then
  `harness ledger add --status known-in-literature --source-id … --excerpt …`) or mark the step `UNVERIFIED-CITATION`
  and leave the claim at `proof-drafted`.

## 4. Hypothesis and lemma discipline

- Every hypothesis in the statement must be used in at least one step, and the self-check log must say where.
  An unused hypothesis means either the proof is wrong or the statement is weaker than it should be — investigate before submitting.
- A lemma must be **strictly weaker** than the theorem it serves. A lemma that restates the theorem, or from which the theorem
  follows in one trivial line, is circular and will be rejected by the lemma-strength audit.
- The lemma DAG (ledger `depends_on`) must be acyclic. Do not use Lemma B in the proof of Lemma A if B depends on A.
- Before creating a lemma, look it up: `harness library find-lemma "<statement>"` (goal cache across campaigns) — a hit means
  reuse the proof path, do not re-prove.
- If a step needs a claim you cannot prove, list it under `assumes:` and tag the ledger claim `assumes:<id>`; the final
  result then becomes a *conditional* theorem (the paper must use the `conditional` environment).

## 5. Computation (rule R5b)

- No arithmetic in prose. Anything numeric — a bound, a constant, a check of small cases, a determinant — is produced by a script
  in `experiments/` whose output is written to `experiments/results.json` under a named key, and the proof refers to that key.
- Exact arithmetic where the claim is exact (`fractions.Fraction`, sympy, `harness.verify.exact`); interval arithmetic where
  real numbers are compared (`interval_eval`, `certify_bound`). Floating-point equality is never a proof.
- Small-case verification is evidence, not proof; label it as such.

## 6. Forbidden phrases

`clearly`, `obviously`, `it is easy to see`, `well known`, `standard argument`, `trivially`, `one can show`, `by a routine
computation`. Replace each with the actual argument, a `<cite>`, or a `results.json` key. Also forbidden anywhere in the
artifact: priming/confidence language (`we believe`, `we expect`, `it seems`, `probably`, `should work`, `after much
experimentation`). Referees must not be primed; the linter rejects both.

## 7. Before submitting to review

1. Re-read `statement.md`. Does the proof prove *that* statement under *those* conventions? (Aletheia failure mode: a quarter of
   "correct" proofs solved a different reading.)
2. Check the extremal / degenerate cases listed in `statement.md` explicitly.
3. Run the falsifier on every lemma (`python -m harness falsify run …`) and record the reports as evidence (the prove gate
   flags proof-drafted lemmas without falsification evidence).
4. `python -m harness proof check proofs/<ID>.md --campaign <slug>` must pass.
5. Attach the proof as evidence: `python -m harness ledger evidence <ID> --type proof --path proofs/<ID>.md --summary "..."`.
6. Pre-register your credence: `python -m harness ledger credence <ID> --role prover --p-pass 0.7 --round N --why "..."`.
7. Promote: `python -m harness ledger promote <ID> proof-drafted`. The promotion fails if dependencies are unproven, the file is
   missing, or the linter fails.
8. Do **not** include motivation, exploration history, or confidence statements in the proof file.

## 8. Levels of rigor (be explicit which you deliver)

| Level | Meaning | Ledger status ceiling |
|---|---|---|
| Sketch | main ideas, gaps acknowledged (`proofs/<ID>.sketch.<persona>.md`, §9) | `conjectured` |
| Complete informal proof | every step justified per §2–§5 | `proof-drafted` → `referee-passed` |
| Formal | Lean 4 proof compiles with no `sorry`, statement checked against `statement.md` | `formalized` (reserved; the Lean lane is not shipped yet) |

## 9. Sketch tournament (parallel provers)

When several persona provers attack one claim, they first write **sketches**, not proofs:

```markdown
---
kind: sketch
claim: T-001
persona: analyst
route: 3
key_idea: order S and exhibit two monotone families of sums
lemmas:
  - label: S1
    statement: "the sums min+s (s in S) are pairwise distinct"
    needs: [D-001]
    cheapest_falsification: "brute force |S| <= 6"
---
S1, S2 -> T-001 by counting.
```

The falsifier attacks every sketch lemma cheaply (`reviews/tournament-<ID>/falsify/<persona>-<label>.json`); judge-class raters
compare sketches pairwise on **plausibility, clarity, novelty** and write `reviews/tournament-<ID>/match-<a>-<b>-<axis>-<tier>.json`
(`tier: pairwise` for single-turn comparisons, `debate` for the multi-turn matches among the top `budgets.debate_top`);
`python -m harness prove elo --campaign <slug> --claim <ID>` aggregates Elo (init 1200, K 32) with a P-UCB exploration bonus,
vetoes sketches with a falsified lemma and selects `budgets.full_proofs` sketches for full proofs. Losers' useful components are
listed as cross-pollination notes for the winners. (Precedents: DeepMind arXiv 2605.22763 — sketch ratings on plausibility /
clarity / novelty, Elo, P-UCB; AI co-scientist arXiv 2502.18864 — Elo 1200 start, debates only for top pairs.)
