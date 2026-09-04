---
claim: CTRL-001
statement: "For every finite set S of integers with at least two elements, |S+S| >= 2|S| - 1."
depends_on: []
assumes: []
uses_hypotheses: [finite, "|S| >= 2"]
numerics: []
version: 1
technique: [extremal, double-counting]
---

## Proof

**Setup.** Let S be a finite set of integers with |S| >= 2, and write S+S = {a + b : a, b in S}.

**Step 1.** (hypothesis) Since S is finite and nonempty, m = min S and M = max S exist; since |S| >= 2, m < M.
**Step 2.** (Step 1) Order the elements s_1 < s_2 < ... < s_n of S, so n = |S| >= 2, s_1 = m and s_n = M.
**Step 3.** (Step 2) The n sums m + s_1 < m + s_2 < ... < m + s_n are strictly increasing, hence pairwise distinct.
**Step 4.** (Step 2) The n - 1 sums s_2 + M < s_3 + M < ... < s_n + M are strictly increasing, hence pairwise distinct.
**Step 5.** <key-original-step> Every sum in Step 4 exceeds every sum in Step 3: for 2 <= i <= n we have s_i + M > s_i + s_j whenever j < n, and s_i + M > m + s_n = m + M because s_i > m. </key-original-step>
**Step 6.** (Steps 3, 4, 5) The two families are disjoint and consist of n + (n - 1) = 2n - 1 distinct elements of S+S.
**Conclusion.** |S+S| >= 2n - 1 = 2|S| - 1.

## Edge cases checked
- |S| = 2, S = {a, b} with a < b: S+S = {2a, a+b, 2b} has 3 = 2·2 - 1 elements.
- S an arithmetic progression {a, a+d, ..., a+(n-1)d}: S+S = {2a, 2a+d, ..., 2a+2(n-1)d} has exactly 2n - 1 elements (equality).

## Self-check log
- Hypothesis use: finite → Step 1; |S| >= 2 → Step 1 (m < M) and Step 5 (s_i > m).
- No numerics are used.
