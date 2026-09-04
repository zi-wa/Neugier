"""Round-2 Step 23: counterexample-guided conjecture repair (X3) — falsifier hooks, repair request, child promotion."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.ledger.cli as ledger_cli
from harness.ledger.ledger import LedgerError, LedgerStore
from harness.ledger.repair import build_request, counterexamples_of
from harness.ledger.schema import Evidence
from harness.verify import falsify
from harness.verify import cli as falsify_cli

# "every n <= 12 has n*n + n + 41 prime" — false at n = 40 is outside the space; a bound-shaped module with equality cases
PARENT = '''
def predicate(x):
    n = x
    return n < 5 or n % 2 == 1  # fails for even n >= 6

def space():
    return range(1, 12)

def features(x):
    return {"parity": "even" if x % 2 == 0 else "odd", "size": x}

def equality(x):
    return x % 5 == 0

def describe(x):
    return f"n={x}"
'''

CHILD_OK = '''
def predicate(x):
    if x % 2 == 0:
        return True   # even n are outside the restricted statement (add-hypothesis: n odd)
    return x % 2 == 1

def space():
    return range(1, 12, 2)

def equality(x):
    return x % 5 == 0
'''

CHILD_BAD = '''
def predicate(x):
    return x < 8

def space():
    return range(1, 12)
'''


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_falsify_regression_touch_and_features(tmp_path):
    mod = _write(tmp_path / "parent.py", PARENT)
    rep = falsify.run(mod, strategy="exhaustive", time_limit=5)
    assert rep.counterexample_repr == "6" and rep.features == {"parity": "even", "size": 6}
    assert rep.touch_number is None  # counterexample found: no touch pass
    reg = _write(tmp_path / "parent.regression.json", json.dumps({"instances": ["6", "8"]}))
    child_ok = _write(tmp_path / "child_ok.py", CHILD_OK)
    rep2 = falsify.run(child_ok, strategy="exhaustive", time_limit=5, regression_path=reg)
    assert rep2.regression_set == ["6", "8"] and rep2.regression_failures == [] and rep2.counterexample_repr is None
    assert rep2.touch_number == 1 and rep2.touch_examples == ["5"]
    child_bad = _write(tmp_path / "child_bad.py", CHILD_BAD)
    rep3 = falsify.run(child_bad, strategy="exhaustive", time_limit=5, regression_path=reg)
    assert rep3.regression_failures == ["8"] and rep3.counterexample_repr == "8"
    assert falsify_cli.main(["run", str(child_bad), "--regression", str(reg), "--time-limit", "2"]) == 3
    assert falsify_cli.main(["run", str(child_ok), "--regression", str(reg), "--time-limit", "2", "--no-touch"]) == 0
    bad_reg = _write(tmp_path / "bad.json", json.dumps({"instances": ["not python ("]}))
    rep4 = falsify.run(child_ok, strategy="exhaustive", time_limit=2, regression_path=bad_reg)
    assert rep4.error and "could not be parsed" in rep4.error and rep4.regression_failures


def test_repair_request_and_child_promotion(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(ledger_cli, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")
    d = tmp_path / "campaigns" / "demo"
    d.mkdir(parents=True)
    store = LedgerStore(d / "ledger.json", campaign="demo")
    parent = store.add(kind="bound", statement="For every n, f(n) is odd.", status="conjectured")
    with pytest.raises(LedgerError, match="only refuted"):
        build_request(store, parent.id, d)
    mod = _write(d / "experiments" / "falsify" / "parent.py", PARENT)
    rep = falsify.run(mod, strategy="exhaustive", time_limit=5, out_json=d / "experiments" / "falsify" / f"{parent.id}.json")
    store.add_evidence(parent.id, Evidence(type="falsification", path=f"experiments/falsify/{parent.id}.json", summary="n=6"), d)
    store.promote(parent.id, "refuted", d)
    assert counterexamples_of(store, parent.id, d)[0]["repr"] == "6"
    req = build_request(store, parent.id, d)
    assert req["regression_size"] == 1 and set(req["operators"]) == {"add-hypothesis", "weaken-bound", "absorb-and-regenerate"}
    assert (d / "experiments" / "repair" / f"{parent.id}.json").exists()
    reg = d / req["regression_path"]
    assert json.loads(reg.read_text(encoding="utf-8"))["instances"] == ["6"]
    assert ledger_cli.main(["--campaign", "demo", "repair", parent.id]) == 0

    child = store.add(kind="bound", statement="For every odd n, f(n) is odd.", status="conjectured",
                      repaired_from=parent.id, repair_op="add-hypothesis")
    # truth test: a run without --regression does not count
    cmod = _write(d / "experiments" / "falsify" / "child.py", CHILD_OK)
    falsify.run(cmod, strategy="exhaustive", time_limit=5, out_json=d / "experiments" / "falsify" / f"{child.id}.noreg.json")
    store.add_evidence(child.id, Evidence(type="falsification", path=f"experiments/falsify/{child.id}.noreg.json"), d)
    with pytest.raises(LedgerError, match="truth test"):
        store.promote(child.id, "numerically-supported", d)
    falsify.run(cmod, strategy="exhaustive", time_limit=5, regression_path=reg, out_json=d / "experiments" / "falsify" / f"{child.id}.json")
    store.add_evidence(child.id, Evidence(type="falsification", path=f"experiments/falsify/{child.id}.json"), d)
    with pytest.raises(LedgerError, match="significance"):
        store.promote(child.id, "numerically-supported", d)
    store.add_evidence(child.id, Evidence(type="note", summary="significance: no known fact implies the odd case; touch at n=5"), d)
    assert store.promote(child.id, "numerically-supported", d).status == "numerically-supported"
    req2 = build_request(store, parent.id, d)
    assert req2["prior_children"] == [child.id]
    # a bound child whose report has touch_number 0 fails the sharpness test
    flat = _write(d / "experiments" / "falsify" / "flat.py", CHILD_OK.replace("return x % 5 == 0", "return False"))
    child2 = store.add(kind="bound", statement="For every odd n, f(n) is odd or n < 3.", status="conjectured",
                       repaired_from=parent.id, repair_op="weaken-bound")
    falsify.run(flat, strategy="exhaustive", time_limit=5, regression_path=reg, out_json=d / "experiments" / "falsify" / f"{child2.id}.json")
    store.add_evidence(child2.id, Evidence(type="falsification", path=f"experiments/falsify/{child2.id}.json"), d)
    store.add_evidence(child2.id, Evidence(type="note", summary="significance: x"), d)
    with pytest.raises(LedgerError, match="touch_number"):
        store.promote(child2.id, "numerically-supported", d)
