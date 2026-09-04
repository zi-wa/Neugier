"""Exact-arithmetic and rigorous-interval helpers.

These are the "trust nothing, check everything" primitives the harness uses
before a numeric claim is allowed into the ledger (CLAUDE.md rule R5): hashing
for provenance, exact rational arithmetic via :mod:`fractions`, rigorous
interval arithmetic via ``mpmath.iv``, and cheap high-precision spot checks
for candidate identities before they are trusted enough to prove.

Two arithmetic modes are used throughout:

* **exact** -- :class:`fractions.Fraction`. No rounding, ever. Floats are
  rejected unless the caller explicitly opts in (and even then the result is
  only as good as the float).
* **interval** -- ``mpmath.iv.mpf`` (aliased here as an "mpi"). An interval
  ``[a, b]`` is a *rigorous* enclosure: the true value is guaranteed to lie
  in ``[a, b]`` given correctly-rounded inputs. Comparisons on intervals are
  therefore conservative -- ``certify_bound`` only returns True when the
  claim holds for *every* point in both intervals.
"""
from __future__ import annotations

import hashlib
import random
import warnings
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

import mpmath
import sympy as sp
from mpmath import iv

Direction = Literal["<=", ">=", "<", ">"]


# --------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------


def sha256_file(path: str | Path) -> str:
    """SHA-256 hex digest of a file's contents, read in binary chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(s: str) -> str:
    """SHA-256 hex digest of a string, encoded as UTF-8."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Exact rationals
# --------------------------------------------------------------------------


def rational(x: Any, allow_float: bool = False) -> Fraction:
    """Coerce ``x`` to an exact :class:`~fractions.Fraction`.

    Accepts ``int``, ``str`` (``"3/4"``, ``"12"``, or a decimal string like
    ``"1.25"``), :class:`~fractions.Fraction`, and ``sympy.Rational``
    (which includes ``sympy.Integer``).

    Floats (Python ``float`` or ``sympy.Float``) are rejected by default --
    a float is already an approximation, and silently treating it as exact
    is exactly the kind of unverified arithmetic R5 forbids. Pass
    ``allow_float=True`` to opt in explicitly; the value is then converted
    via ``Fraction(x).limit_denominator(10**12)`` and a warning is issued so
    the loss of precision is never silent.
    """
    if isinstance(x, Fraction):
        return x
    if isinstance(x, bool):
        raise TypeError(f"rational(): refusing bool input {x!r}")
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, str):
        return Fraction(x)
    if isinstance(x, sp.Rational):
        return Fraction(int(x.p), int(x.q))
    if isinstance(x, (float, sp.Float)):
        if not allow_float:
            raise TypeError(
                f"rational(): refusing to silently convert float {x!r} to a "
                "Fraction; pass allow_float=True to opt in explicitly"
            )
        warnings.warn(
            f"rational(): converting float {x!r} to Fraction via "
            "limit_denominator(10**12); this loses precision and is not exact",
            stacklevel=2,
        )
        return Fraction(float(x)).limit_denominator(10**12)
    raise TypeError(f"rational(): unsupported type {type(x)!r} for value {x!r}")


# --------------------------------------------------------------------------
# Interval coercion
# --------------------------------------------------------------------------


def _as_interval(x: Any):
    """Coerce ``x`` into an ``mpmath.iv`` interval (an ``ivmpf``).

    Accepts an existing interval, a plain number, a :class:`Fraction`
    (converted exactly, at the interval context's current precision), a
    ``sympy.Rational``, or a string -- either ``"[a, b]"`` for an explicit
    interval, ``"p/q"`` for a rational, or a plain numeric literal.
    """
    if isinstance(x, mpmath.ctx_iv.ivmpf):
        return x
    if isinstance(x, bool):
        raise TypeError(f"cannot coerce bool {x!r} to an interval")
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("[") and s.endswith("]"):
            a_str, b_str = s[1:-1].split(",")
            return iv.mpf([mpmath.mpf(a_str.strip()), mpmath.mpf(b_str.strip())])
        if "/" in s:
            fr = Fraction(s)
            return iv.mpf(fr.numerator) / iv.mpf(fr.denominator)
        return iv.mpf(s)
    if isinstance(x, Fraction):
        return iv.mpf(x.numerator) / iv.mpf(x.denominator)
    if isinstance(x, sp.Rational):
        return iv.mpf(int(x.p)) / iv.mpf(int(x.q))
    if isinstance(x, (int, float)):
        return iv.mpf(x)
    raise TypeError(f"cannot coerce {x!r} of type {type(x)!r} to an interval")


# --------------------------------------------------------------------------
# Bound certification
# --------------------------------------------------------------------------


def certify_bound(value: Any, target: Any, direction: Direction, exact: bool = True) -> bool:
    """Certify that ``value <direction> target``.

    If ``exact`` (default): ``value`` and ``target`` are coerced to
    :class:`Fraction` via :func:`rational` (floats are rejected -- pass
    already-converted values if you really mean it) and compared exactly.

    If not ``exact``: ``value`` and ``target`` are coerced to rigorous
    ``mpmath.iv`` intervals. The comparison is conservative: it only holds
    when it is guaranteed for *every* point of both intervals, e.g. ``<=``
    holds iff ``value.b <= target.a`` (the worst case of ``value`` is still
    at most the best case of ``target``).
    """
    if direction not in ("<=", ">=", "<", ">"):
        raise ValueError(f"certify_bound: unknown direction {direction!r}")

    if exact:
        v = value if isinstance(value, Fraction) else rational(value)
        t = target if isinstance(target, Fraction) else rational(target)
        if direction == "<=":
            return v <= t
        if direction == ">=":
            return v >= t
        if direction == "<":
            return v < t
        return v > t

    v = _as_interval(value)
    t = _as_interval(target)
    if direction == "<=":
        return v.b <= t.a
    if direction == ">=":
        return v.a >= t.b
    if direction == "<":
        return v.b < t.a
    return v.a > t.b


# --------------------------------------------------------------------------
# Interval evaluation of a symbolic expression
# --------------------------------------------------------------------------

# mpmath.iv only implements a subset of elementary functions natively; the
# rest are expressed rigorously in terms of that subset (interval operations
# remain sound enclosures under +, -, *, / and monotone composition).


def _iv_tanh(z):
    e2 = iv.exp(2 * z)
    return (e2 - 1) / (e2 + 1)


def _iv_sinh(z):
    return (iv.exp(z) - iv.exp(-z)) / 2


def _iv_cosh(z):
    return (iv.exp(z) + iv.exp(-z)) / 2


def _iv_atan(z):
    return iv.atan2(z, iv.mpf(1))


_IV_FUNCS = {
    sp.sin: iv.sin,
    sp.cos: iv.cos,
    sp.tan: iv.tan,
    sp.cot: iv.cot,
    sp.sec: iv.sec,
    sp.csc: iv.csc,
    sp.exp: iv.exp,
    sp.log: iv.log,
    sp.Abs: iv.fabs,
    sp.atan: _iv_atan,
    sp.sinh: _iv_sinh,
    sp.cosh: _iv_cosh,
    sp.tanh: _iv_tanh,
    sp.acot: iv.acot,
    sp.asec: iv.asec,
    sp.acsc: iv.acsc,
}


def _eval_iv_node(node: sp.Basic, values: dict[str, Any]):
    if node.is_Symbol:
        try:
            return values[node.name]
        except KeyError:
            raise ValueError(
                f"interval_eval: no substitution provided for symbol {node.name!r}"
            ) from None
    if node is sp.pi:
        return iv.pi
    if node is sp.E:
        return iv.e
    if node.is_Integer:
        return iv.mpf(int(node))
    if node.is_Rational:
        return iv.mpf(int(node.p)) / iv.mpf(int(node.q))
    if node.is_Float:
        return iv.mpf(float(node))
    if isinstance(node, sp.Add):
        args = [_eval_iv_node(a, values) for a in node.args]
        result = args[0]
        for a in args[1:]:
            result = result + a
        return result
    if isinstance(node, sp.Mul):
        args = [_eval_iv_node(a, values) for a in node.args]
        result = args[0]
        for a in args[1:]:
            result = result * a
        return result
    if isinstance(node, sp.Pow):
        base = _eval_iv_node(node.base, values)
        exp_node = node.exp
        if exp_node.is_Integer:
            return base ** int(exp_node)
        if exp_node.is_Rational:
            p, q = int(exp_node.p), int(exp_node.q)
            return base ** (iv.mpf(p) / iv.mpf(q))
        exp_val = _eval_iv_node(exp_node, values)
        return base**exp_val
    func_type = type(node)
    if func_type in _IV_FUNCS:
        arg = _eval_iv_node(node.args[0], values)
        return _IV_FUNCS[func_type](arg)
    if node.is_number:
        # Fallback for exotic constants (not rigorous beyond `prec` digits,
        # but better than refusing outright).
        return iv.mpf(str(sp.N(node, 40)))
    raise NotImplementedError(f"interval_eval: unsupported node {node!r} ({func_type})")


def interval_eval(expr: str, subs: dict[str, float | str], prec: int = 50):
    """Evaluate ``expr`` (a sympy-parseable string) as a rigorous interval.

    ``subs`` maps free symbol names to either a plain number/numeric string
    (treated as a degenerate point interval) or an explicit interval string
    ``"[a, b]"``. Evaluation is done at ``prec`` decimal digits of working
    precision using ``mpmath.iv`` (rigorous directed rounding), so the
    returned interval is a guaranteed enclosure of the true value at that
    precision.
    """
    old_dps = iv.dps
    iv.dps = prec
    try:
        parsed = sp.sympify(expr)
        values = {name: _as_interval(val) for name, val in subs.items()}
        return _eval_iv_node(parsed, values)
    finally:
        iv.dps = old_dps


# --------------------------------------------------------------------------
# Random high-precision spot checks
# --------------------------------------------------------------------------


def random_check_identity(
    lhs: str,
    rhs: str,
    symbols: list[str],
    n: int = 200,
    seed: int = 0,
    domain: tuple[float, float] = (-10, 10),
    prec: int = 60,
) -> dict[str, Any]:
    """Numerically spot-check ``lhs == rhs`` at ``n`` random points.

    This is a *cheap falsification pass*, not a proof: it samples a mix of
    random rationals (small denominators) and random floats in ``domain``
    for each symbol, evaluates both sides at ``prec`` decimal digits via
    mpmath, and reports the worst discrepancy seen. A large discrepancy is
    conclusive evidence the identity is false; a tiny one (rounding-noise
    scale) is evidence -- not proof -- that it may be true.

    Returns ``{"ok": bool, "max_abs_err": float, "failing_point": list[str] | None}``,
    where ``failing_point`` (when present) is the sampled point with the
    largest observed error, as strings in the same order as ``symbols``.
    """
    rng = random.Random(seed)
    lhs_expr = sp.sympify(lhs)
    rhs_expr = sp.sympify(rhs)

    old_dps = mpmath.mp.dps
    mpmath.mp.dps = prec
    try:
        lhs_f = sp.lambdify(symbols, lhs_expr, modules=["mpmath"])
        rhs_f = sp.lambdify(symbols, rhs_expr, modules=["mpmath"])

        lo, hi = float(domain[0]), float(domain[1])
        threshold = mpmath.mpf(10) ** (-(max(prec - 10, 1)))

        worst_err = mpmath.mpf(-1)
        worst_point: list[Any] | None = None

        for i in range(n):
            point: list[Any] = []
            for _ in symbols:
                if i % 2 == 0:
                    denom = rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 12])
                    numer = rng.randint(int(round(lo * denom)), int(round(hi * denom)))
                    point.append(mpmath.mpf(numer) / mpmath.mpf(denom))
                else:
                    point.append(mpmath.mpf(rng.uniform(lo, hi)))
            try:
                lv = mpmath.mpc(lhs_f(*point))
                rv = mpmath.mpc(rhs_f(*point))
                err = abs(lv - rv)
            except (ZeroDivisionError, ValueError):
                continue
            if err > worst_err:
                worst_err = err
                worst_point = point

        ok = worst_point is None or worst_err <= threshold
        return {
            "ok": bool(ok),
            "max_abs_err": float(worst_err) if worst_point is not None else 0.0,
            "failing_point": None if ok else [mpmath.nstr(p, 20) for p in worst_point],
        }
    finally:
        mpmath.mp.dps = old_dps


# --------------------------------------------------------------------------
# Exact symbolic check
# --------------------------------------------------------------------------


def exact_polynomial_check(expr: str, symbols: list[str]) -> bool:
    """True iff ``expr`` (typically ``lhs - rhs``) simplifies exactly to 0.

    ``symbols`` fixes which names are treated as free symbolic variables
    (kept for API symmetry with the other helpers here; sympy will infer
    the same symbols from ``expr`` on its own).
    """
    sp.symbols(symbols)
    parsed = sp.sympify(expr)
    return sp.simplify(parsed) == 0
