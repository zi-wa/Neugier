"""Falsification module for the planted false lemma L-002: the sum s in S+S is attained by at most two ordered pairs.

Counterexample: S = {0, 1, 2}, s = 2 is attained by (0,2), (1,1), (2,0) — three ordered pairs."""
from itertools import combinations


def space():
    for n in range(1, 6):
        for size in range(1, 4):
            for S in combinations(range(n + 1), size):
                yield tuple(S)


def predicate(S):
    counts = {}
    for a in S:
        for b in S:
            counts[a + b] = counts.get(a + b, 0) + 1
    return max(counts.values()) <= 2


def describe(S):
    counts = {}
    for a in S:
        for b in S:
            counts[a + b] = counts.get(a + b, 0) + 1
    s = max(counts, key=counts.get)
    return f"S={set(S)}: sum {s} attained by {counts[s]} ordered pairs"


def features(S):
    return {"size": len(S), "is_ap": len(S) < 3 or len({b - a for a, b in zip(S, S[1:])}) == 1}
