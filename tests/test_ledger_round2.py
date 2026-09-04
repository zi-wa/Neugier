"""Round-2 ledger rules: status bypass closed, verified excerpts, replicator round,
reverify, review-round cap, repair provenance, stakes and attestation."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import harness.ledger.cli as ledger_cli
from harness.ledger.ledger import REFEREE_ROUND_ROLES, LedgerError, LedgerStore
from harness.ledger.schema import Evidence


def _mk(tmp_path: Path) -> Path:
    d = tmp_path / "camp"
    (d / "cache").mkdir(parents=True)
    return d


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _store(d: Path) -> LedgerStore:
    return LedgerStore(d / "ledger.json", campaign="camp")


def _proof_drafted(store: LedgerStore, cid: str, d: Path):
    _write(d / "proofs" / f"{cid}.md", "**Step 1.** (algebra) x.")
    store.add_evidence(cid, Evidence(type="proof", path=f"proofs/{cid}.md", summary="draft"), d)
    return store.promote(cid, "proof-drafted", d)


def _round(store: LedgerStore, cid: str, d: Path, round_: int = 1, replicator: str = "pass", **overrides) -> None:
    for role in REFEREE_ROUND_ROLES:
        verdict = replicator if role == "replicator" else "pass"
        verdict = overrides.get(role, verdict)
        store.add_evidence(cid, Evidence(type="referee", role=role, verdict=verdict, round=round_, summary="r"), d)


EXCERPT = "For every finite set S of integers with at least two elements, |S+S| >= 2|S| - 1."


# ------------------------------------------------------------------- add --

def test_add_rejects_status_beyond_conjectured(tmp_path):
    store = _store(_mk(tmp_path))
    for status in ("numerically-supported", "proof-drafted", "referee-passed", "formalized", "refuted", "dead"):
        with pytest.raises(LedgerError):
            store.add(kind="conjecture", statement=f"Bypass to {status}.", status=status)
    assert store.add(kind="conjecture", statement="Fine.", status="conjectured").status == "conjectured"


def test_add_known_in_literature_requires_excerpt_in_same_call(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    with pytest.raises(LedgerError):
        store.add(kind="fact", statement="Known thing.", status="known-in-literature")
    _write(d / "cache" / "ruzsa1994.txt", "Section 2. " + EXCERPT + " This is the Cauchy-Davenport bound.")
    claim = store.add(
        kind="fact", statement="Cauchy-Davenport for integers.", status="known-in-literature",
        evidence=Evidence(type="excerpt", source_id="ruzsa1994", excerpt=EXCERPT, locator="§2"),
        campaign_dir=d,
    )
    assert claim.status == "known-in-literature"
    ev = claim.evidence[-1]
    assert ev.verified is True and ev.source_sha256 and len(ev.excerpt_hash) == 12
    assert [h["op"] for h in claim.history] == ["add", "add_evidence", "promote"]


def test_unverified_excerpt_recorded_only_with_opt_in_and_never_counts(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="Something from memory.")
    ev = Evidence(type="excerpt", source_id="nobody2020", excerpt=EXCERPT)
    with pytest.raises(LedgerError):
        store.add_evidence(claim.id, ev, d)  # no cached source -> rejected by default
    updated = store.add_evidence(claim.id, Evidence(type="excerpt", source_id="nobody2020", excerpt=EXCERPT), d,
                                 require_verified_excerpt=False)
    assert updated.evidence[-1].verified is None
    with pytest.raises(LedgerError, match="unverified excerpt"):
        store.promote(claim.id, "known-in-literature", d)


def test_excerpt_not_in_cached_source_is_rejected(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    _write(d / "cache" / "smith2020.txt", "A completely different paper about graphs and their colourings.")
    claim = store.add(kind="fact", statement="Misattributed.")
    with pytest.raises(LedgerError, match="not-found"):
        store.add_evidence(claim.id, Evidence(type="excerpt", source_id="smith2020", excerpt=EXCERPT), d)
    updated = store.add_evidence(claim.id, Evidence(type="excerpt", source_id="smith2020", excerpt=EXCERPT), d,
                                 require_verified_excerpt=False)
    assert updated.evidence[-1].verified is False


def test_caller_supplied_verified_flag_is_ignored(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="Sneaky.")
    ev = Evidence(type="excerpt", source_id="ghost", excerpt=EXCERPT, verified=True)
    with pytest.raises(LedgerError):
        store.add_evidence(claim.id, ev, d)


# ---------------------------------------------------------------- referees --

def test_referee_round_requires_replicator(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="T.")
    _proof_drafted(store, claim.id, d)
    for role in ("skeptic", "falsifier", "novelty", "judge"):
        store.add_evidence(claim.id, Evidence(type="referee", role=role, verdict="pass", round=1), d)
    with pytest.raises(LedgerError, match="replicator"):
        store.promote(claim.id, "referee-passed", d)
    store.add_evidence(claim.id, Evidence(type="referee", role="replicator", verdict="n/a", round=1), d)
    assert store.promote(claim.id, "referee-passed", d).status == "referee-passed"


def test_na_verdict_only_for_replicator(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="T.")
    with pytest.raises(LedgerError, match="n/a"):
        store.add_evidence(claim.id, Evidence(type="referee", role="skeptic", verdict="n/a", round=1), d)


def test_skeptic_dissent_breaks_unanimity(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="T.")
    _proof_drafted(store, claim.id, d)
    _round(store, claim.id, d)
    store.add_evidence(claim.id, Evidence(type="referee", role="skeptic", verdict="fail", round=1, agent_id="SK-2"), d)
    with pytest.raises(LedgerError, match="unanimity"):
        store.promote(claim.id, "referee-passed", d)


def test_inadmissible_skeptic_verdict_does_not_count(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="T.")
    _proof_drafted(store, claim.id, d)
    for role in ("falsifier", "novelty", "replicator", "judge"):
        store.add_evidence(claim.id, Evidence(type="referee", role=role, verdict="pass", round=1), d)
    store.add_evidence(
        claim.id,
        Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-1", reliability=0.3, admissible=False),
        d,
    )
    with pytest.raises(LedgerError, match="skeptic pass"):
        store.promote(claim.id, "referee-passed", d)
    with pytest.raises(LedgerError, match="reliability"):
        store.add_evidence(claim.id, Evidence(type="referee", role="skeptic", verdict="pass", round=1, reliability=1.5), d)


# ---------------------------------------------------------------- reverify --

def test_reverify_requires_fresh_complete_round(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    lemma = store.add(kind="lemma", statement="L.")
    thm = store.add(kind="theorem", statement="T.", depends_on=[lemma.id])
    _proof_drafted(store, lemma.id, d)
    _round(store, lemma.id, d)
    store.promote(lemma.id, "referee-passed", d)
    _proof_drafted(store, thm.id, d)
    _round(store, thm.id, d)
    store.promote(thm.id, "referee-passed", d)

    store.update_statement(lemma.id, "L (sharpened).")
    thm = store.get(thm.id)
    assert thm.stale and thm.status == "proof-drafted"
    with pytest.raises(LedgerError, match="no complete referee round"):
        store.reverify(thm.id)
    with pytest.raises(LedgerError, match="stale"):
        store.promote(thm.id, "referee-passed", d)

    time.sleep(0.01)
    _round(store, thm.id, d, round_=2)
    assert store.reverify(thm.id).stale is False
    with pytest.raises(LedgerError):
        store.reverify(thm.id)  # not stale any more


# ------------------------------------------------------------------ repair --

def test_repaired_from_requires_refuted_parent_and_op(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    parent = store.add(kind="conjecture", statement="All n are prime.", status="conjectured")
    with pytest.raises(LedgerError, match="refuted"):
        store.add(kind="conjecture", statement="All odd n are prime.", repaired_from=parent.id, repair_op="add-hypothesis")
    _write(d / "experiments" / "cex.json", json.dumps({"counterexample": 4}))
    store.add_evidence(parent.id, Evidence(type="falsification", path="experiments/cex.json", summary="n=4"), d)
    store.promote(parent.id, "refuted", d)
    with pytest.raises(LedgerError, match="repair_op"):
        store.add(kind="conjecture", statement="All odd n are prime.", repaired_from=parent.id)
    child = store.add(kind="conjecture", statement="All odd n < 9 are prime.", repaired_from=parent.id, repair_op="add-hypothesis")
    assert child.repaired_from == parent.id and child.repair_op == "add-hypothesis"
    assert f"repaired:{parent.id}" in child.tags
    with pytest.raises(LedgerError, match="requires repaired_from"):
        store.add(kind="conjecture", statement="x", repair_op="weaken-bound")


# ---------------------------------------------------------- stakes / attest --

def test_stakes_and_attestation(tmp_path):
    d = _mk(tmp_path)
    store = _store(d)
    claim = store.add(kind="target", statement="Open problem.", stakes=2)
    assert claim.stakes == 2
    assert store.set_stakes(claim.id, 0).stakes == 0
    with pytest.raises(LedgerError):
        store.set_stakes(claim.id, 5)
    att = store.attest(claim.id, "Jane Doe", note="checked by hand")
    assert att.attestation["by"] == "Jane Doe"
    assert store.summary()["stale"] == 0
    assert "| stakes |" in store.to_markdown()


# --------------------------------------------------------------------- CLI --

def test_cli_round_cap_and_new_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_cli, "CAMPAIGNS", tmp_path)
    d = tmp_path / "demo"
    d.mkdir()
    _write(d / "campaign.json", json.dumps({"slug": "demo", "budgets": {"max_review_rounds": 1}}))
    assert ledger_cli.main(["--campaign", "demo", "init"]) == 0
    assert ledger_cli.main(["--campaign", "demo", "add", "--kind", "theorem", "--statement", "T.", "--stakes", "2"]) == 0
    assert ledger_cli.main(["--campaign", "demo", "add", "--kind", "lemma", "--statement", "L.", "--status", "proof-drafted"]) == 1
    assert ledger_cli.main([
        "--campaign", "demo", "evidence", "T-001", "--type", "referee", "--role", "skeptic", "--verdict", "pass",
        "--round", "2", "--agent-id", "SK-1",
    ]) == 1  # exceeds max_review_rounds
    assert ledger_cli.main([
        "--campaign", "demo", "evidence", "T-001", "--type", "referee", "--role", "skeptic", "--verdict", "pass",
        "--round", "1", "--agent-id", "SK-1", "--reliability", "0.9", "--admissible", "--lineup-item", "B",
    ]) == 0
    store = LedgerStore(d / "ledger.json")
    ev = store.get("T-001").evidence[-1]
    assert ev.agent_id == "SK-1" and ev.reliability == 0.9 and ev.admissible is True and ev.lineup_item == "B"
    assert ledger_cli.main(["--campaign", "demo", "update", "T-001", "--stakes", "1"]) == 0
    assert LedgerStore(d / "ledger.json").get("T-001").stakes == 1
    assert ledger_cli.main(["--campaign", "demo", "reverify", "T-001"]) == 1  # not stale
    assert ledger_cli.main(["--campaign", "demo", "attest", "T-001", "--human", "Jane"]) == 0
    # known-in-literature in one call, with a cached source
    _write(d / "cache" / "src1.txt", "blah " + EXCERPT + " blah")
    assert ledger_cli.main([
        "--campaign", "demo", "add", "--kind", "fact", "--statement", "CD bound.", "--status", "known-in-literature",
        "--source-id", "src1", "--excerpt", EXCERPT,
    ]) == 0
    assert LedgerStore(d / "ledger.json").get("F-001").status == "known-in-literature"
    # unverified excerpt via evidence needs --unverified-ok
    assert ledger_cli.main([
        "--campaign", "demo", "evidence", "T-001", "--type", "excerpt", "--source-id", "nowhere", "--excerpt", EXCERPT,
    ]) == 1
    assert ledger_cli.main([
        "--campaign", "demo", "evidence", "T-001", "--type", "excerpt", "--source-id", "nowhere", "--excerpt", EXCERPT,
        "--unverified-ok",
    ]) == 0
