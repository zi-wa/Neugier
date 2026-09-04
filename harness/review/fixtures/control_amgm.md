---
claim: CTRL-002
statement: "For all real numbers x, y >= 0, (x + y)/2 >= sqrt(x y), with equality if and only if x = y."
depends_on: []
assumes: []
uses_hypotheses: ["x >= 0", "y >= 0"]
numerics: []
version: 1
technique: [algebra]
---

## Proof

**Setup.** Let x, y be real numbers with x >= 0 and y >= 0.

**Step 1.** (hypothesis) Since x >= 0 and y >= 0, the real numbers a = sqrt(x) and b = sqrt(y) exist, are >= 0, and satisfy a^2 = x, b^2 = y.
**Step 2.** (algebra) (a - b)^2 = a^2 - 2ab + b^2 >= 0, because a square of a real number is nonnegative.
**Step 3.** (Step 2) Rearranging, a^2 + b^2 >= 2ab, that is, x + y >= 2 sqrt(x) sqrt(y) = 2 sqrt(x y) (Step 1, and sqrt(x) sqrt(y) = sqrt(x y) for x, y >= 0).
**Step 4.** <key-original-step> Dividing Step 3 by 2 gives (x + y)/2 >= sqrt(x y); equality in Step 2 holds exactly when a - b = 0, i.e. sqrt(x) = sqrt(y), i.e. x = y. </key-original-step>
**Conclusion.** (x + y)/2 >= sqrt(x y), with equality if and only if x = y.

## Edge cases checked
- x = 0: the inequality reads y/2 >= 0, true; equality iff y = 0 = x.
- x = y: both sides equal x, equality holds.

## Self-check log
- Hypothesis use: x >= 0 → Step 1; y >= 0 → Step 1.
- No numerics are used.
