# Proof standards (Neugier)

These are the rules a proof artifact must satisfy before it may enter adversarial review. The prover writes
for a hostile referee who sees *only* `statement.md` and the proof file. Nothing else is available to them.

## 1. Artifact format

One file per claim: `campaigns/<slug>/proofs/<CLAIM-ID>.md`.

```markdown
---
claim: L-003
statement: "For every finite S ⊂ Z with |S| ≥ 2, |S+S| ≥ 2|S| - 1."
depends_on: [D-001, F-002]        # ledger ids used (definitions, cited facts, earlier lemmas)
assumes: []                        # ledger ids of UNPROVEN claims this proof relies on (conjectures) — must be empty for a theorem
uses_hypotheses: [finite, |S|>=2]  # every hypothesis of the statement; each must be used in some step (see §4)
numerics: [results.json#sumset_small_cases]   # keys in experiments/results.json referenced below
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

The YAML header is machine-read by the review skill: `assumes` must be empty for anything promoted to `referee-passed`.

## 2. Steps

- **Every step is numbered** and names its justification in parentheses: `(definition D-001)`, `(algebra)`,
  `(Step k)`, `(cited: <bibkey>)`, `(computation: results.json#key)`, or `<key-original-step>`.
- A step contains **one inference**. If a referee could ask "why?" twice, split it.
- Quantifiers are explicit. Say which variable is fixed, which is arbitrary, and in which order they were chosen.
  A step that silently swaps ∀/∃ order is a critical error.
- Constants are tracked. `C` must be defined the first time it appears; `O(·)` must say what it depends on.
- Case analyses list all cases and say why they are exhaustive.
- An inequality chain shows each comparison separately if the justifications differ.

## 3. Citations (rule R5a)

- A cited result may be used only through `<cite id="bibkey" claim="F-xxx" excerpt-hash="…">`, where `F-xxx` is a ledger
  claim with status `known-in-literature` carrying a **verbatim excerpt** of the cited statement.
- State the cited theorem in your own words *with all its hypotheses*, then show each hypothesis holds here.
  "By [X]" without hypotheses check is a justification gap; if a hypothesis fails, it is a critical error.
- Never cite from memory. If the excerpt is not in the ledger, obtain it (librarian) or mark the step `UNVERIFIED-CITATION`
  and leave the claim at `proof-drafted`.

## 4. Hypothesis and lemma discipline

- Every hypothesis in the statement must be used in at least one step, and the self-check log must say where.
  An unused hypothesis means either the proof is wrong or the statement is weaker than it should be — investigate before submitting.
- A lemma must be **strictly weaker** than the theorem it serves. A lemma that restates the theorem, or from which the theorem
  follows in one trivial line, is circular and will be rejected by the lemma-strength audit.
- The lemma DAG (ledger `depends_on`) must be acyclic. Do not use Lemma B in the proof of Lemma A if B depends on A.
- If a step needs a claim you cannot prove, list it under `assumes:`; the final result then becomes a *conditional* theorem and
  the paper must say so.

## 5. Computation (rule R5b)

- No arithmetic in prose. Anything numeric — a bound, a constant, a check of small cases, a determinant — is produced by a script
  in `experiments/` whose output is written to `experiments/results.json` under a named key, and the proof refers to that key.
- Exact arithmetic where the claim is exact (`fractions.Fraction`, sympy, `harness.verify.exact`); interval arithmetic where
  real numbers are compared (`interval_eval`, `certify_bound`). Floating-point equality is never a proof.
- Small-case verification is evidence, not proof; label it as such.

## 6. Forbidden phrases

`clearly`, `obviously`, `it is easy to see`, `well known`, `standard argument`, `trivially`, `one can show`, `by a routine
computation`. Replace each with the actual argument, a `<cite>`, or a `results.json` key. The copyeditor lints for these.

## 7. Before submitting to review

1. Re-read `statement.md`. Does the proof prove *that* statement under *those* conventions? (Aletheia failure mode: a quarter of
   "correct" proofs solved a different reading.)
2. Check the extremal / degenerate cases listed in `statement.md` explicitly.
3. Run the falsifier on every lemma (`python -m harness falsify run ...`) and record the reports as evidence.
4. Attach the proof as evidence: `python -m harness ledger evidence <ID> --type proof --path proofs/<ID>.md --summary "..."`.
5. Promote: `python -m harness ledger promote <ID> proof-drafted`. The promotion fails if dependencies are unproven or the file is missing.
6. Do **not** include motivation, exploration history, or confidence statements in the proof file. Referees must not be primed.

## 8. Levels of rigor (be explicit which you deliver)

| Level | Meaning | Ledger status ceiling |
|---|---|---|
| Sketch | main ideas, gaps acknowledged | `conjectured` |
| Complete informal proof | every step justified per §2–§5 | `proof-drafted` → `referee-passed` |
| Formal | Lean 4 proof compiles with no `sorry`, statement checked against `statement.md` | `formalized` |
