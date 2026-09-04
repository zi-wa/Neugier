"""Template for a Neugier falsification conjecture module.

Copy this file (``python -m harness falsify template OUT_PATH``) and fill in
the pieces below, deleting whichever optional ones you don't need. The
resulting file is loaded by path via :func:`harness.verify.falsify.run` --
it does not need to be part of any package, just a `.py` file that defines
some subset of the functions described here.

REQUIRED
--------
predicate(x) -> bool
    Return True if the conjecture HOLDS on instance `x`, False if `x` is a
    counterexample. `run()` stops at the first False it finds.

AT LEAST ONE OF `space` / `sample` IS REQUIRED
-----------------------------------------------
space() -> Iterable
    Yield every instance to check, for *exhaustive* search over a finite
    (or deliberately truncated) domain. Delete this if the domain is too
    large to enumerate -- use `sample` instead.

sample(rng: random.Random) -> instance
    Draw one random instance, for *random* / *hillclimb* search over a
    domain too large (or infinite) to enumerate. Always draw randomness
    from the given `rng`, not the global `random` module -- that's what
    makes runs reproducible under a fixed `--seed`.

OPTIONAL
--------
neighbors(x) -> Iterable
    Instances "close to" `x` (e.g. one small perturbation away), used by
    the `hillclimb` strategy for local search. Without this, `hillclimb`
    degrades to random restarts.

score(x) -> float
    Lower = closer to violating the conjecture. `hillclimb` walks from
    neighbor to neighbor, always moving to a strictly lower score, until it
    either finds a counterexample or reaches a local optimum (then
    restarts from a fresh random sample). Without `score` (even if
    `neighbors` is defined), `hillclimb` also degrades to random restarts.

describe(x) -> str
    Human-readable rendering of `x`, used for the report's `counterexample`
    field (e.g. "n=5: F_5 = 4294967297 = 641 * 6700417"). Without it,
    `repr(x)` is used.
"""
from __future__ import annotations

import random
from typing import Iterable


def predicate(x) -> bool:
    """Return True if the conjecture holds on x, False if x refutes it."""
    raise NotImplementedError("fill this in")


def space() -> Iterable:
    """Exhaustive enumeration of instances to check.

    Delete this function entirely if you're using `sample` instead.
    """
    raise NotImplementedError("fill this in, or delete this function and define sample() instead")


def sample(rng: random.Random) -> object:
    """Draw one random instance, using `rng` for all randomness.

    Delete this function entirely if you're using `space` instead.
    """
    raise NotImplementedError("fill this in, or delete this function and define space() instead")


# --- everything below is optional; delete what you don't use ---


def neighbors(x) -> Iterable:
    """Instances 'close to' x, for hillclimb local search."""
    raise NotImplementedError("fill this in, or delete this function")


def score(x) -> float:
    """Lower = closer to violating the conjecture. Used by hillclimb."""
    raise NotImplementedError("fill this in, or delete this function")


def describe(x) -> str:
    """Human-readable rendering of x, used in falsification reports."""
    return repr(x)
