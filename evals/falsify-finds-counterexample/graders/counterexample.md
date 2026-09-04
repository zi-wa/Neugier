---
type: regex
pattern: "\"counterexample_repr\":\\s*\"[^\"]+\""
match: contains
target: { source: file, path: "campaigns/eval-falsify-finds-counterexample/experiments/falsify/L-002.json" }
---

The falsification report records a non-null counterexample (S = {0, 1, 2} refutes the lemma).
