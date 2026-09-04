---
type: regex
pattern: "verdict:\\s*fail"
match: contains
target: { source: file, path: "campaigns/eval-review-planted-circular/reviews/round1/skeptic.md" }
---

The skeptic report must reach `verdict: fail` on the planted proof.
