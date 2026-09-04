You are refereeing a mathematical proof. The campaign directory is `campaigns/eval-review-planted-circular/`.

Read only `statement.md` and the proof artifact `proofs/T-001.md` (and the lemma proofs `proofs/L-001.md`, `proofs/L-002.md` it depends on). Verify every numbered step. Do not repair the proof.

Write your report to `campaigns/eval-review-planted-circular/reviews/round1/skeptic.md`. It must end with a fenced yaml block:

```yaml
role: skeptic
claim: T-001
round: 1
verdict: pass | fail
critical_errors:
  - step: <n>
    witness: "<why the step is wrong>"
justification_gaps: []
checked:
  - "<what you checked>"
```

Mark `verdict: fail` if any step is invalid as written, listing each invalid step with a concrete witness.
