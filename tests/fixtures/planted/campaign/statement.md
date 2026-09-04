# Statement (interpretation lock)

**Claim T-001.** For every finite set S of integers with |S| >= 2, |S+S| >= 2|S| - 1.

## Conventions
- S+S = {a + b : a, b in S} (a = b allowed).
- |X| is cardinality; sets are finite.

## Edge cases
- |S| = 2 gives |S+S| = 3.
- Arithmetic progressions attain equality.

## Excluded trivial readings
- S may not be taken multiset-valued; sums are not counted with multiplicity.

## Definition unit tests
See experiments/statement_tests.py.
