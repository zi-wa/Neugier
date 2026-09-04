"""Round-1 Step 15: the harness catches every planted flaw mechanically."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "planted"
sys.path.insert(0, str(FIXTURE_DIR))


@pytest.fixture()
def planted(tmp_path):
    from make import build  # tests/fixtures/planted/make.py

    src = FIXTURE_DIR / "campaign"
    if not src.exists():
        build(src)
    dest = tmp_path / "campaigns" / "planted"
    shutil.copytree(src, dest)
    return dest


def test_fixture_is_regenerable_and_stable(tmp_path):
    from make import build

    a = build(tmp_path / "a")
    b = build(tmp_path / "b")
    pa = json.loads((a / "PLANTED.json").read_text(encoding="utf-8"))
    pb = json.loads((b / "PLANTED.json").read_text(encoding="utf-8"))
    assert pa["ids"] == pb["ids"] and set(pa["flaws"]) == {"circular_lemma", "false_lemma", "unused_hypothesis", "unverified_citation", "already_known"}


def test_proof_linter_flags_unused_hypothesis_and_unverified_cite(planted):
    from harness.ledger.ledger import LedgerStore
    from harness.proof.lint import lint_proof

    store = LedgerStore(planted / "ledger.json")
    rep = lint_proof(planted / "proofs" / "T-001.md", planted, store)
    codes = {e.code for e in rep.errors}
    assert "E_PROOF_HYPOTHESIS_UNUSED" in codes and any("S contains 0" in e.message for e in rep.errors)
    assert "E_PROOF_CITE" in codes  # F-001 is not known-in-literature / excerpt unverified
    assert isinstance(rep.warnings, list)  # rubric present, no crash
    circ = lint_proof(planted / "proofs" / "L-001.md", planted, store)
    assert circ.ok or "E_PROOF_KEYSTEP" in {e.code for e in circ.errors}  # circularity is the skeptic's job, not the linter's


def test_falsifier_finds_the_planted_counterexample(planted):
    from harness.verify import falsify
    from harness.verify import cli as fcli

    rep = falsify.run(planted / "experiments" / "falsify" / "L-002.py", strategy="exhaustive", time_limit=10)
    assert rep.counterexample_repr is not None and "3 ordered pairs" in (rep.counterexample or "")
    assert rep.features and rep.features["size"] == 3
    assert fcli.main(["run", str(planted / "experiments" / "falsify" / "L-002.py"), "--time-limit", "5"]) == 3


def test_unverified_excerpt_is_recorded_as_unverified(planted):
    from harness.ledger.ledger import LedgerError, LedgerStore
    from harness.lit.cache import verify_excerpt

    store = LedgerStore(planted / "ledger.json")
    fact = store.get(json.loads((planted / "PLANTED.json").read_text(encoding="utf-8"))["ids"]["fact"])
    ev = fact.evidence[-1]
    assert ev.verified is False and ev.source_sha256
    assert verify_excerpt(ev.excerpt, "Freiman1973", planted).method == "not-found"
    with pytest.raises(LedgerError, match="unverified excerpt"):
        store.promote(fact.id, "known-in-literature", planted)


def test_ledger_graph_and_coverage_on_planted(planted):
    from harness.ledger.graph import blueprint_statuses, render_mermaid
    from harness.ledger.ledger import LedgerStore
    from harness.proof.coverage import compute_coverage

    store = LedgerStore(planted / "ledger.json")
    st = blueprint_statuses(store)
    ids = json.loads((planted / "PLANTED.json").read_text(encoding="utf-8"))["ids"]
    assert st[ids["theorem"]] == "can_prove" and st[ids["circular"]] == "can_prove" and st[ids["false"]] == "stated"
    assert "flowchart TD" in render_mermaid(store)
    cov = compute_coverage(planted, ids["theorem"], 1, store)
    assert cov.steps_total == 6 and cov.steps_verified_by_skeptic == 2 and cov.steps_flawed == 2 and cov.steps_open == 2
    assert cov.numerics_reproduced == 1 and cov.cites_verified == 0 and cov.lemmas_total == 2


def test_lineup_and_round_checks_on_planted(planted):
    from harness.ledger.ledger import LedgerStore
    from harness.review import barrier as B
    from harness.review import lineup as L
    from harness.review.adjudication import reported_critical_errors
    from harness.review.verdict import novelty_class

    store = LedgerStore(planted / "ledger.json")
    m = B.open_round(planted, 1, "T-001", ["proofs/T-001.md"], skeptics=1)
    sealed = L.build_lineup(planted, 1, "proofs/T-001.md", 2, seed=1)
    assert sorted(v["kind"] for v in sealed["items"].values()) == ["control", "decoy", "decoy", "real"]
    errs = reported_critical_errors(planted / "reviews" / "round1")
    assert {e["step"] for e in errs if e["role"] == "skeptic"} == {3, 4}
    assert novelty_class(planted, 1) == "1c"
    problems = B.check_round(planted, 1, store)
    assert any("not scored" in p or "no hook activity" in p for p in problems)
    from harness.prove.elo import tournament

    res = tournament(planted, "T-001")
    assert res["selected"][0] == "analyst" and res["cross_pollination"]["analyst"]
    assert tournament(planted, "T-001", full_proofs=1)["selected"] == ["analyst"]


def test_campaign_outcome_for_planted_is_not_autonomous(planted, monkeypatch):
    import harness
    import harness.campaign as campaign

    monkeypatch.setattr(campaign, "CAMPAIGNS", planted.parent)
    monkeypatch.setattr(harness, "CAMPAIGNS", planted.parent)
    monkeypatch.setattr(harness, "LIBRARY", planted.parent.parent / "library")
    problems = campaign.validate_outcome("planted", "autonomous-new-result")
    assert problems and any("1c" in p or "referee-passed" in p for p in problems)
    assert campaign.validate_outcome("planted", "literature-find") == []
