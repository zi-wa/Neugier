from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from harness.verify import cli, exact, falsify

EXAMPLES = Path(__file__).resolve().parent.parent / "harness" / "verify" / "examples"


# ---------- exact ----------

def test_rational_rejects_float_by_default():
    assert exact.rational("3/7") == Fraction(3, 7)
    assert exact.rational(5) == Fraction(5)
    with pytest.raises(Exception):
        exact.rational(0.1)
    assert exact.rational(0.5, allow_float=True) == Fraction(1, 2)


def test_certify_bound_exact_and_interval():
    assert exact.certify_bound(Fraction(1, 3), Fraction(1, 2), "<=")
    assert not exact.certify_bound(Fraction(2, 3), Fraction(1, 2), "<=")
    assert exact.certify_bound(Fraction(1, 2), Fraction(1, 2), "<=")
    assert not exact.certify_bound(Fraction(1, 2), Fraction(1, 2), "<")
    iv = exact.interval_eval("sqrt(2)", {}, prec=40)
    assert exact.certify_bound(iv, "1.5", "<=", exact=False)
    assert not exact.certify_bound(iv, "1.4", "<=", exact=False)


def test_random_check_identity_true_and_false():
    ok = exact.random_check_identity("(x+y)**2", "x**2+2*x*y+y**2", ["x", "y"], n=50)
    assert ok["ok"] and ok["failing_point"] is None
    bad = exact.random_check_identity("(x+y)**2", "x**2+y**2", ["x", "y"], n=50)
    assert not bad["ok"] and bad["failing_point"] is not None


def test_exact_polynomial_check():
    assert exact.exact_polynomial_check("(x+1)**2 - x**2 - 2*x - 1", ["x"])
    assert not exact.exact_polynomial_check("(x+1)**2 - x**2", ["x"])


def test_sha256_helpers(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    assert exact.sha256_file(p) == exact.sha256_text("hello")


# ---------- falsify ----------

def test_false_conjecture_finds_fermat_counterexample():
    rep = falsify.run(EXAMPLES / "false_conjecture.py", strategy="exhaustive", time_limit=30)
    assert rep.counterexample is not None and "5" in rep.counterexample
    assert rep.error is None


def test_goldbach_small_exhausts_without_counterexample():
    rep = falsify.run(EXAMPLES / "goldbach_small.py", strategy="exhaustive", time_limit=60)
    assert rep.counterexample is None and rep.exhausted and rep.tested > 1000


def test_time_limit_respected_on_infinite_random_space(tmp_path):
    mod = tmp_path / "inf.py"
    mod.write_text(
        "import random\n"
        "def predicate(x):\n    return x >= 0\n"
        "def sample(rng):\n    return rng.randint(0, 10**9)\n"
        "def describe(x):\n    return str(x)\n",
        encoding="utf-8",
    )
    rep = falsify.run(mod, strategy="random", time_limit=1.0)
    assert rep.counterexample is None and rep.seconds < 5.0 and rep.tested > 0


def test_hillclimb_uses_score(tmp_path):
    # conjecture "x*x != 1_000_000 for integers" is false at x = 1000; score guides the walk there
    mod = tmp_path / "hc.py"
    mod.write_text(
        "def predicate(x):\n    return x * x != 1_000_000\n"
        "def sample(rng):\n    return rng.randint(0, 5000)\n"
        "def neighbors(x):\n    return [x - 1, x + 1, x - 10, x + 10]\n"
        "def score(x):\n    return abs(x * x - 1_000_000)\n"
        "def describe(x):\n    return f'x={x}'\n",
        encoding="utf-8",
    )
    rep = falsify.run(mod, strategy="hillclimb", time_limit=20, seed=1)
    assert rep.counterexample == "x=1000"


def test_cli_exit_codes(capsys):
    assert cli.main(["run", str(EXAMPLES / "false_conjecture.py"), "--strategy", "exhaustive", "--time-limit", "30"]) == 3
    capsys.readouterr()
    assert cli.main(["run", str(EXAMPLES / "goldbach_small.py"), "--strategy", "exhaustive", "--time-limit", "60"]) == 0


def test_sat_and_z3():
    sat = falsify.sat_check([[1, 2], [-1], [2]])
    assert sat["sat"] is True and 2 in sat["model"]
    unsat = falsify.sat_check([[1], [-1]])
    assert unsat["sat"] is False
    import z3

    def build(s: z3.Solver) -> None:
        x, y = z3.Ints("x y")
        s.add(x + y == 10, x > y, x > 0, y > 0)

    res = falsify.z3_check(build, time_limit_ms=5000)
    assert res["result"] == "sat" and res["model"] is not None
