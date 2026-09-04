The campaign directory is `campaigns/eval-falsify-finds-counterexample/`. Lemma L-002 (see `proofs/L-002.md`) claims:

> For every finite set S of integers, every element of S+S is a+b for at most two ordered pairs (a, b).

Attack it computationally. A conjecture module is already at `experiments/falsify/L-002.py` (functions `predicate(S)`, `space()`, `describe(S)`); if the harness is available run

    .venv/Scripts/python.exe -m harness falsify run campaigns/eval-falsify-finds-counterexample/experiments/falsify/L-002.py --strategy exhaustive --time-limit 30 --out campaigns/eval-falsify-finds-counterexample/experiments/falsify/L-002.json

otherwise write an equivalent search yourself. Either way, produce `campaigns/eval-falsify-finds-counterexample/experiments/falsify/L-002.json` with the keys `counterexample_repr` (the failing S) and `counterexample` (a human-readable description), or `null` values if you found none.
