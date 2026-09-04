# Referee checklist (Neugier adversarial review)

Used by `skeptic`, `falsifier`, `novelty-checker`, `replicator`, and `judge`. You see only `statement.md`, the artifact(s)
named in your task, the pre-registered marking scheme (`proofs/<ID>.rubric.md`) and ledger facts with excerpts. The
**information barrier is enforced by a hook**: every file access is checked against `reviews/roundN/barrier.json` and logged
to `access.log`; a denied access is not a hint to try another way — it is recorded and the round fails if it is not waived.
Your job is to **find the flaw**, not to be helpful. A review that finds nothing must say precisely what it checked and how.

## 0. Ground rules

- Assume the proof is wrong until each step is verified. Published AI-proof audits found 68.5% of self-verified outputs flawed.
- You are not allowed to fix the proof. Report; do not repair.
- Every FLAWED verdict needs a **witness**: an explicit counterexample, a specific missing hypothesis, a concrete quantifier
  swap, or the exact sentence that is unjustified and why. "Seems hand-wavy" is not a witness.
- Distinguish **critical errors** (the argument is invalid as written; a step is false or does not follow) from
  **justification gaps** (the step is probably true but the justification given is insufficient). Both are reported; only
  critical errors force `fail`. (Typed defect classes follow the IMO-grade verifier of Huang & Yang, arXiv 2507.15855.)
- Check the *statement* before the proof (§1). Many "correct" proofs prove the wrong thing.
- The marking scheme (§10) was written before the proof existed; its items are mandatory rows of your `checked` list.

## 1. Interpretation audit (all referees)

1. Restate the claim in your own words from `statement.md` only. Compare with the header of the proof file. Any drift?
2. Is there a reading of the statement under which it becomes trivial or vacuous (empty domain, degenerate parameter,
   convention that makes the inequality an identity)? Does the proof prove only that reading?
3. Does the proof **prove more than asked** with no extra effort? Red flag for an error or a trivialization.
4. Are the conventions in `statement.md` (indexing, zero/one-based, strict/non-strict, finite/infinite) honored in every step?

## 2. Step-level state machine (skeptic)

Process the proof in order. Maintain a table (it is machine-read for the coverage metric — keep the four columns):

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
  The excerpt must be a *verified* ledger excerpt (`verified: true`); an unverified one is a justification gap at best.
- For each `<key-original-step>`: this is the novel idea. Spend the most effort here. Try to break it with a small example.
- Quantifiers: write down the dependency order of every chosen object. Any "choose N large enough" must specify what N depends on.
- Constants: track them; a constant that silently changes is a critical error.
- Case analysis: enumerate the cases yourself and check exhaustiveness.
- Limits/asymptotics: uniformity — is the error term uniform in the parameters it must be uniform in?
- Technique pitfalls: for every `technique:` tag in the artifact's frontmatter, walk the corresponding section of
  `skills/references/technique-pitfalls.md` and record each pitfall as a `checked` row (or a FLAWED row with the witness shape it asks for).

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
  Record `tested`, `strategy`, `seed`, and the report path; attach as `falsification` evidence. For inequalities also implement
  `equality(x)` so the report carries the *touch number* (how often the bound is attained).
- Recompute every number in the artifact from scratch (do not trust `results.json`; regenerate it). Any mismatch is critical.
- Test the boundary cases from `statement.md` and the degenerate ones (n = 0, 1, 2; empty set; equality cases).
- Test the trivializing readings from §1.2: if a reading makes the claim trivially true, check whether the proof secretly uses it.
- Use exact arithmetic; a floating-point "counterexample" must be confirmed exactly before it is reported.

## 5. Literature attack (novelty-checker) — follow `novelty-protocol.md`

Output a memo with the exact queries run, the closest prior results (with excerpts), a **`## Final-statement queries`** section
(searches for the exact final statement and its numbers — the result may have appeared after the topic search was done), and a
classification: `1a` standalone new result / `1b` comparable or stronger literature exists (cite it) / `1c` already known as
stated / `1d` statement was misread (the literature solves the intended problem). The verdict block carries `class:`,
`citation_hops:` and `artifact_sha256:` (sha256 of the artifact you classified — proves the memo is post-proof). Documented
failures to avoid: "Erdősgate" (references presented as solutions), #1026 (key 2024 paper missed by "deep research" but found
by Scholar), #851 (confused with a different problem), and the clique-avoiding-codes case (a bound that had appeared three
years earlier, found only when the final statement was searched).

## 6. Blinded replication (replicator)

Stage A — from `statement.md` and the cited sources only, **not the proof**: re-derive the key numerics, constants, and the
statements of the cited results into `reviews/roundN/replicate/values.json`, then seal them:
`python -m harness review commit-blind --campaign <slug> --round N --file reviews/roundN/replicate/values.json`.
Stage B — only after the commit the barrier opens the artifact: diff against it and report every discrepancy. The verdict
block lists what you reproduced under `reproduced: [results.json#key, …]`. Use `n/a` when there is genuinely nothing to
replicate (say why).

## 7. Verdict format (every referee)

```yaml
role: skeptic            # skeptic | falsifier | novelty | replicator
claim: T-001
round: 2
agent_id: SK-3f9a1c      # skeptics: the id given in your task (fresh context)
item: B                  # lineup mode only: which lineup item this block judges (one block per item)
artifact_sha256: "…"     # novelty memo: sha256 of the artifact classified
verdict: fail            # pass | fail | revise   (replicator may also answer n/a)
critical_errors:
  - step: 7
    witness: "Choosing N after ε is illegal: N must be uniform in ε (statement requires uniformity)."
justification_gaps:
  - step: 3
    witness: "Cited theorem is stated for compact sets; compactness of K not shown."
interpretation_issues: []
reproduced: []           # replicator: results.json keys re-derived blind
checked:                 # what you actually did — required even for pass; marking-scheme items appear here
  - "All 12 steps processed; 10 VERIFIED, 1 OPEN (step 9 depends on step 7), 1 FLAWED."
  - "M1 (marking scheme): 2|S|-1 distinct sums exhibited in Step 5."
confidence: 0.85         # calibrated; not a substitute for evidence
```

`pass` is allowed only when there are **no** critical errors, no OPEN steps, and every gap is minor and listed. The SubagentStop
hook refuses to let you finish without this block.

## 8. Judge protocol

Inputs: all referee verdicts for the round; `lineup_score.*.json` (after `harness review score-lineup`) and the unsealed lineup
(`harness review lineup unseal`) when a lineup exists; the prover's *response file* (`reviews/roundN/response.md`) if any.
1. Use only **admissible** skeptic verdicts (lineup reliability ≥ `budgets.lineup_min_recall`); an inadmissible skeptic is
   respawned by the orchestrator, never argued with.
2. For each reported flaw, decide: **upheld** / **rebutted** (the response gives a valid argument — quote ≥ 40 characters of it) /
   **moot** (only for gaps and interpretation issues; a critical error is never moot).
3. Any upheld critical error ⇒ `REVISE_PROOF` (or `REVISE_PLAN` if the flaw shows the route cannot work, or `REWRITE` if the
   proof structure is unsalvageable). Novelty `1c`/`1d` ⇒ `PIVOT` unless a genuinely new component can be isolated.
4. Consistency: referees disagreeing on a step means the step is not yet verified. The regime for the claim's stakes decides
   how many skeptic passes are needed (`harness review regime`); tier 2 also needs the final-statement re-check.
5. After `max_review_rounds` (campaign budget) without `pass`, the judge must downgrade the claim and record why; it may not
   keep extending rounds.
6. Write `reviews/roundN/judge.md` containing the structured block and ending with exactly one `VERDICT:` line:

```yaml
role: judge
claim: T-001
round: 2
upheld:
  - {role: skeptic, agent_id: SK-3f9a1c, step: 7}
rebutted:
  - {role: falsifier, step: 4, quote: "the module tested n ≤ 12 with the wrong parity convention; with statement.md's convention the predicate holds"}
moot:
  - {role: skeptic, agent_id: SK-3f9a1c, step: 3, reason: "gap closed by the added hypothesis check"}
verdict: REVISE_PROOF
```

`VERDICT: PASS` | `VERDICT: REVISE_PROOF` | `VERDICT: REVISE_PLAN` | `VERDICT: REWRITE` | `VERDICT: PIVOT`. Record referee evidence
in the ledger with the round number (skeptics with `--agent-id` and `--reliability` from the lineup score); `harness review check`
refuses a round whose block leaves a critical error neither upheld nor rebutted.

## 9. Lineup mode (skeptic)

When your task points at `reviews/roundN/lineup/`, you receive several items (`A.md`, `B.md`, …): the real proof, mutants of it
with one planted flaw each, and possibly a control proof of a different statement. You do not know which is which.
- Review **every** item with the full §1–§3 procedure and emit one §7 block per item (`item: <letter>`, `agent_id: <yours>`).
- Never diff items against each other, never read `proofs/`, never guess which is real; the hook denies both and logs it.
- Your reliability is the recall on the planted flaws (step must match, witness must name the flaw) minus false alarms on the
  control; below `lineup_min_recall` your verdict on the real item is discarded. A `pass` on a mutant is a miss.

## 10. Marking scheme (all referees)

`proofs/<ID>.rubric.md` (frozen at statement lock) lists what a correct proof must establish, the hypotheses it must use, the
anticipated hard step and the technique pitfalls. Each `must_establish` item and each pitfall is a mandatory `checked` row.
A proof that establishes everything on the scheme can still be wrong; a proof that skips an item is at least a gap.
