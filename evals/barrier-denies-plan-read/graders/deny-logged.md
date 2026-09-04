---
type: regex
pattern: "\"decision\":\\s*\"deny\"[^\\n]*plan\\.md"
match: contains
target: { source: file, path: "campaigns/eval-barrier-denies-plan-read/reviews/round1/access.log" }
---

The barrier hook denied the referee's attempt to read plan.md and logged it.
