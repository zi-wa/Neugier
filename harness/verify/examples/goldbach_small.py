"""Goldbach's conjecture, small range: every even n >= 4 is a sum of two primes.

An **exhaustive-search** example for :func:`harness.verify.falsify.run`. No
counterexample is known (Goldbach's conjecture is open in general, but
verified computationally far beyond this range) -- running this module
should exhaust ``space()`` with no counterexample found. It exists to
exercise the exhaustive strategy end-to-end on a fast, real example.
"""
from __future__ import annotations

from typing import Iterable

_MAX_N = 20_000


def _sieve(limit: int) -> list[bool]:
    is_prime = [True] * (limit + 1)
    is_prime[0:2] = [False, False]
    for i in range(2, int(limit**0.5) + 1):
        if is_prime[i]:
            for j in range(i * i, limit + 1, i):
                is_prime[j] = False
    return is_prime


_IS_PRIME = _sieve(_MAX_N)
_PRIMES = [i for i, p in enumerate(_IS_PRIME) if p]


def predicate(n: int) -> bool:
    """True iff n can be written as p + q with p, q both prime."""
    if n > _MAX_N:
        raise ValueError(f"goldbach_small only sieved primes up to {_MAX_N}, got n={n}")
    for p in _PRIMES:
        if p > n - p:
            break
        if _IS_PRIME[n - p]:
            return True
    return False


def space() -> Iterable[int]:
    """Even integers from 4 up to (but excluding) 20000."""
    return range(4, _MAX_N, 2)


def describe(n: int) -> str:
    return f"n={n} has no representation as a sum of two primes"
