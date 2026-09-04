"""A deliberately false conjecture: "F_n = 2**(2**n) + 1 is prime for all n".

These are the Fermat numbers. Fermat conjectured all F_n are prime; Euler
showed F_5 = 4294967297 = 641 * 6700417 is composite. This module exists to
exercise the counterexample-found path of :func:`harness.verify.falsify.run`
-- exhaustive search over ``space() == range(0, 8)`` must find the
counterexample at n=5 (and, since exhaustive search stops at the first
counterexample, never needs to evaluate the enormous F_6/F_7).
"""
from __future__ import annotations

from typing import Iterable


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def predicate(n: int) -> bool:
    """True iff F_n = 2**(2**n) + 1 is prime."""
    return _is_prime(2 ** (2**n) + 1)


def space() -> Iterable[int]:
    return range(0, 8)


def describe(n: int) -> str:
    value = 2 ** (2**n) + 1
    return f"n={n}: F_{n} = {value} is not prime"
