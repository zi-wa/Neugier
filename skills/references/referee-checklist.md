# Referee checklist (Neugier adversarial review)

Used by `skeptic`, `falsifier`, `novelty-checker`, `replicator`, and `judge`. You see only `statement.md` and the artifact.
Your job is to **find the flaw**, not to be helpful. A review that finds nothing must say precisely what it checked and how.

## 0. Ground rules

- Assume the proof is wrong until each step is verified. Published AI-proof audits found 68.5% of self-verified outputs flawed.
- You are not allowed to fix the proof. Report; do not repair.
- Every FLAWED verdict needs a **witness**: an explicit counterexample, a specific missing hypothesis, a concrete quantifier
  swap, or the exact sentence that is unjustified and why. "Seems hand-wavy" is not a witness.
- Distinguish **critical errors** (the argument is invalid as written; a step is false or does not follow) from
  **justification gaps** (the step is probably true but the justification given is insufficient). Both are reported; only
  critical errors force `fail`.
- Check the *statement* before the proof (§1). Many "correct" proofs prove the wrong thing.

## 1. Interpretation audit (all referees)

1. Restate the claim in your own words from `statement.md` only. Compare with the header of the proof file. Any drift?
2. Is there a reading of the statement under which it becomes trivial or vacuous (empty domain, degenerate parameter,
   convention that makes the inequality an identity)? Does the proof prove only that reading?
3. Does the proof **prove more than asked** with no extra effort? Red flag for an error or a trivialization.
4. Are the conventions in `statement.md` (indexing, zero/one-based, strict/non-strict, finite/infinite) honored in every step?

## 2. Step-level state machine (skeptic)

Process the proof in order. Maintain a table:

| Step | Status | Justification checked | Witness (if FLAWED) |
|---|---|---|---|
| 1 | VERIFIED | definition D-001 matches statement.md verbatim | |
| 2 | OPEN | | |
| 3 | FLAWED (critical) | cited theorem needs S ⊂ R; here S ⊂ Z/pZ | hypothesis mismatch |

Rules:
- A step may be marked VERIFIED only from: the statement's hypotheses, definitions in `statement.md`, earlier VERIFIED steps,
  or a `<cite>` whose excerpt you have read and whose hypotheses you have confirmed. Local reasoning only; no "this is standard".
- A step that depends on an OPEN or FLAWED step is at most OPEN.
- For each `<cite>`: (a) does the excerpt actually say what the step uses? (b) are *all* hypotheses of the cited result satisfied
  here? (c) is the direction/constant/exponent the same? Mis-attributed citations are a documented failure mode (Galambos 1976 case).
- For each `<key-original-step>`: this is the novel idea. Spend the most effort here. Try to break it with a small example.
- Quantifiers: write down the dependency order of every chosen object. Any "choose N large enough" must specify what N depends on.
- Constants: track them; a constant that silently changes is a critical error.
- Case analysis: enumerate the cases yourself and check exhaustiveness.
- Limits/asymptotics: uniformity — is the error term uniform in the parameters it must be uniform in?

Terminate with counts: VERIFIED / OPEN / FLAWED-critical / FLAWED-gap.

## 3. Lemma-strength audit (skeptic)

- Does any lemma restate the theorem, or imply it in one trivial line? Then the lemma is the theorem and its proof must be reviewed
  as such (and the "proof" of the theorem is empty).
- Is the lemma DAG acyclic as written?
- Are all hypotheses of the theorem used somewhere? List where. Unused hypothesis ⇒ report as a gap and check whether the
  stronger statement is false (that would be a critical error).
- Is the proof suspiciously short for a problem that was open? Say so explicitly; short proofs of open problems are usually
  wrong or already known.

## 4. Computational attack (falsifier)

- For the theorem and **every lemma**, write a predicate and search for counterexamples: exhaustive on small parameters,
  random sampling, hill-climbing toward violation, SAT/z3 encodings when the structure allows (`python -m harness falsify run`).
  Record `tested`, `strategy`, `seed`, and the report path; attach as `falsification` evidence.
- Recompute every number in the artifact from scratch (do not trust `results.json`; regenerate it). Any mismatch is critical.
- Test the boundary cases from `statement.md` and the degenerate ones (n = 0, 1, 2; empty set; equality cases).
- Test the trivializing readings from §1.2: if a reading makes the claim trivially true, check whether the proof secretly uses it.
- Use exact arithmetic; a floating-point "counterexample" must be confirmed exactly before it is reported.

## 5. Literature attack (novelty-checker) — follow `novelty-protocol.md`

Output a memo with the exact queries run, the closest prior results (with excerpts), and a classification:
`1a` standalone new result / `1b` comparable or stronger literature exists (cite it) / `1c` already known as stated / `1d` statement
was misread (the literature solves the intended problem). Documented failures to avoid: "Erdősgate" (references presented as
solutions), #1026 (key 2024 paper missed by "deep research" but found by Scholar), #851 (confused with a different problem).

## 6. Blinded replication (replicator)

From `statement.md` and the cited sources only — not the proof — re-derive the key numerics, constants, and the statements of
the cited results. Diff against the artifact. Report every discrepancy.

## 7. Verdict format (every referee)

```yaml
role: skeptic            # skeptic | falsifier | novelty | replicator
claim: T-001
round: 2
verdict: fail            # pass | fail | revise
critical_errors:
  - step: 7
    witness: "Choosing N after ε is illegal: N must be uniform in ε (statement requires uniformity)."
justification_gaps:
  - step: 3
    witness: "Cited theorem is stated for compact sets; compactness of K not shown."
interpretation_issues: []
checked:                 # what you actually did — required even for pass
  - "All 12 steps processed; 10 VERIFIED, 1 OPEN (step 9 depends on step 7), 1 FLAWED."
  - "Falsifier: exhaustive n ≤ 14 on lemma L-002, 0 counterexamples; random 10^6 samples on T-001."
confidence: 0.85         # calibrated; not a substitute for evidence
```

`pass` is allowed only when there are **no** critical errors, no OPEN steps, and every gap is minor and listed.

## 8. Judge protocol

Inputs: all referee verdicts for the round; the prover's *response file* (`reviews/roundN/response.md`) if any.
1. For each reported flaw, decide: **upheld** / **rebutted** (the response gives a valid argument, quote it) / **moot**.
2. Any upheld critical error ⇒ `REVISE_PROOF` (or `REVISE_PLAN` if the flaw shows the route cannot work, or `REWRITE` if the
   proof structure is unsalvageable). Novelty `1c`/`1d` ⇒ `PIVOT` unless a genuinely new component can be isolated.
3. Consistency: referees disagreeing on a step means the step is not yet verified.
4. After `max_review_rounds` (campaign budget) without `pass`, the judge must downgrade the claim and record why; it may not
   keep extending rounds.
5. Write `reviews/roundN/judge.md` ending with exactly one line `VERDICT: PASS` | `VERDICT: REVISE_PROOF` |
   `VERDICT: REVISE_PLAN` | `VERDICT: REWRITE` | `VERDICT: PIVOT`, and record referee evidence in the ledger with the round number.
