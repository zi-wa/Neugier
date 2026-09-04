"""Tests for harness.review.barrier / regime / cli — the information barrier as data."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.review.cli as review_cli
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence
from harness.review import barrier as B
from harness.review.regime import regime_for


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _camp(tmp_path: Path, budgets: dict | None = None) -> Path:
    d = tmp_path / "campaigns" / "demo"
    d.mkdir(parents=True)
    _write(d / "campaign.json", json.dumps({"slug": "demo", "budgets": budgets or {"max_review_rounds": 2}}))
    _write(d / "statement.md", "S.")
    _write(d / "proofs" / "T-001.md", "**Step 1.** (algebra) x.")
    LedgerStore(d / "ledger.json", campaign="demo").add(kind="theorem", statement="T.")
    return d


def _log(rdir: Path, rows: list[dict]) -> None:
    with open(rdir / "access.log", "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# ------------------------------------------------------------- matching --

def test_glob_match_semantics():
    assert B.glob_match("cache/x/y.txt", "cache/**")
    assert B.glob_match("cache", "cache/**") is False
    assert B.glob_match("reviews/round2/skeptic.SK-1.md", "reviews/round2/skeptic*.md")
    assert B.glob_match("proofs/T-001.md", "proofs/**")
    assert B.glob_match("reviews/round3/lineup.sealed.json", "reviews/round*/lineup.sealed.json")
    assert not B.glob_match("plan.md", "plan.md.bak")
    assert B.glob_match("a\\b\\c.txt", "a/**/c.txt")


def test_regime_tiers():
    r0, r1, r2 = regime_for(0, {}), regime_for(1, {"skeptic_passes": 2, "decoys_per_round": 1}), regime_for(2, {})
    assert r0.skeptic_passes == 1 and r0.decoys == 0 and not r0.replicator_required
    assert r1.skeptic_passes == 2 and r1.decoys == 1 and r1.control and r1.replicator_required and r1.novelty_hops == 1
    assert r2.skeptic_passes == 3 and r2.decoys == 2 and r2.novelty_hops == 2 and r2.final_statement_recheck and r2.human_attest
    assert "tier 2" in r2.describe()


# --------------------------------------------------------------- rounds --

def test_open_round_defaults_and_role_access(tmp_path):
    d = _camp(tmp_path)
    m = B.open_round(d, 1, "T-001", ["proofs/T-001.md"])
    assert m["status"] == "open" and m["regime"]["stakes"] == 1
    sk = [k for k in m["roles"] if k.startswith("skeptic:")]
    assert len(sk) == 2 and all(m["roles"][k]["agent_id"].startswith("SK-") for k in sk)
    assert (d / "reviews" / "round1" / "round.json").exists()
    ok, why = B.role_allowed(m, sk[0], "statement.md")
    assert ok and why.startswith("allow:")
    ok, why = B.role_allowed(m, sk[0], "proofs/T-001.md")
    assert ok
    ok, why = B.role_allowed(m, sk[0], "plan.md")
    assert not ok and why == "deny:plan.md"
    ok, why = B.role_allowed(m, sk[0], "proofs/T-002.md")
    assert not ok and why == "deny:proofs/**"
    ok, why = B.role_allowed(m, sk[0], "reviews/round1/lineup.sealed.json")
    assert not ok
    ok, why = B.role_allowed(m, "judge", "ideas.md")
    assert ok and why == "no-barrier"
    ok, why = B.role_allowed(m, "prover", "ideas.md")
    assert ok and why == "unknown-role"
    # replicator: artifact only after the blind commit (stage B)
    ok, _ = B.role_allowed(m, "replicator", "proofs/T-001.md")
    assert not ok
    _write(d / "reviews" / "round1" / "replicate" / "values.json", '{"c": 1}')
    rep = B.commit_blind(d, 1, "reviews/round1/replicate/values.json")
    assert rep["stage"] == "B" and rep["blind_sha256"]
    m = B.load_manifest(d, 1)
    ok, why = B.role_allowed(m, "replicator", "proofs/T-001.md")
    assert ok
    with pytest.raises(B.ReviewError):
        B.commit_blind(d, 1, "reviews/round1/replicate/values.json")


def test_open_round_refuses_second_open_cap_and_gaps(tmp_path):
    d = _camp(tmp_path, {"max_review_rounds": 5})
    B.open_round(d, 1, "T-001", ["proofs/T-001.md"])
    with pytest.raises(B.ReviewError, match="still open"):
        B.open_round(d, 2, "T-001", ["proofs/T-001.md"])
    B.close_round(d, 1)
    with pytest.raises(B.ReviewError, match="consecutive"):
        B.open_round(d, 3, "T-001", ["proofs/T-001.md"])
    B.open_round(d, 2, "T-001", ["proofs/T-001.md"], skeptics=1, stakes=0)
    B.close_round(d, 2)
    _write(d / "campaign.json", json.dumps({"slug": "demo", "budgets": {"max_review_rounds": 2}}))
    with pytest.raises(B.ReviewError, match="max_review_rounds"):
        B.open_round(d, 3, "T-001", ["proofs/T-001.md"])
    _write(d / "campaign.json", json.dumps({"slug": "demo", "budgets": {"max_review_rounds": 5}}))
    with pytest.raises(B.ReviewError, match="not found"):
        B.open_round(d, 3, "T-001", ["proofs/missing.md"])
    assert B.open_barrier(d) is None


def test_check_round_flags_denials_missing_activity_and_replicator_order(tmp_path):
    d = _camp(tmp_path)
    store = LedgerStore(d / "ledger.json", campaign="demo")
    assert B.check_round(d, 1, store)[0].startswith("round 1: no barrier manifest")
    m = B.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=1)
    sk = next(k for k in m["roles"] if k.startswith("skeptic:"))
    rdir = d / "reviews" / "round1"
    _write(rdir / f"skeptic.{sk.split(':')[1]}.md", "```yaml\nrole: skeptic\nclaim: T-001\nround: 1\nverdict: pass\n```\n")
    problems = B.check_round(d, 1, store)
    assert any("no hook activity" in p for p in problems)
    _log(rdir, [{"ts": "2026-09-04T10:00:00", "role": sk, "tool": "Read", "decision": "allow", "target": "statement.md"},
                {"ts": "2026-09-04T10:00:01", "role": sk, "tool": "Read", "decision": "deny", "target": "plan.md", "reason": "deny:plan.md"}])
    problems = B.check_round(d, 1, store)
    assert any("denial" in p for p in problems) and not any("no hook activity" in p for p in problems)
    B.waive(d, 1, sk, "plan.md", "the skeptic needed the notation table; reviewed by the human")
    assert not any("denial" in p for p in B.check_round(d, 1, store))
    _write(rdir / "hook_errors.log", "Traceback ...")
    assert any("hook_errors" in p for p in B.check_round(d, 1, store))
    (rdir / "hook_errors.log").unlink()
    # replicator pass without blind commit
    _write(rdir / "replicator.md", "```yaml\nrole: replicator\nclaim: T-001\nround: 1\nverdict: pass\n```\n")
    _log(rdir, [{"ts": "2020-01-01T00:00:02", "role": "replicator", "tool": "Read", "decision": "allow", "target": "proofs/T-001.md"}])
    assert any("blind commit" in p for p in B.check_round(d, 1, store))
    _write(rdir / "replicate" / "values.json", "{}")
    B.commit_blind(d, 1, "reviews/round1/replicate/values.json")
    assert any("before the blind commit" in p for p in B.check_round(d, 1, store))
    # novelty memo without a class; judge without a verdict line
    _write(rdir / "novelty.md", "# memo\n```yaml\nrole: novelty\nclaim: T-001\nverdict: pass\n```\n")
    _write(rdir / "judge.md", "# judge\nno decision yet\n")
    _log(rdir, [{"ts": "2026-09-04T10:00:03", "role": "novelty", "tool": "Read", "decision": "allow", "target": "statement.md"}])
    problems = B.check_round(d, 1, store)
    assert any("classification" in p for p in problems) and any("VERDICT" in p for p in problems)


def test_check_round_last_round_requires_pivot(tmp_path):
    d = _camp(tmp_path, {"max_review_rounds": 1})
    store = LedgerStore(d / "ledger.json", campaign="demo")
    B.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=1)
    rdir = d / "reviews" / "round1"
    _write(rdir / "judge.md", "flaws...\n\nVERDICT: REVISE_PROOF\n")
    assert any("must PIVOT" in p for p in B.check_round(d, 1, store))
    _write(rdir / "judge.md", "flaws...\n\nVERDICT: PIVOT\n")
    assert not any("must PIVOT" in p for p in B.check_round(d, 1, store))


def test_cli_lifecycle(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(review_cli, "CAMPAIGNS", tmp_path / "campaigns")
    d = _camp(tmp_path)
    assert review_cli.main(["--campaign", "demo", "open", "--claim", "T-001", "--artifact", "proofs/T-001.md", "--skeptics", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["round"] == 1 and any(k.startswith("skeptic:") for k in out["roles"])
    assert review_cli.main(["--campaign", "demo", "open", "--claim", "T-001", "--artifact", "proofs/T-001.md"]) == 1  # still open
    assert review_cli.main(["--campaign", "demo", "status"]) == 0
    assert review_cli.main(["--campaign", "demo", "check"]) == 0  # manifest only: nothing to flag yet
    _write(d / "reviews" / "round1" / "replicate" / "values.json", "{}")
    assert review_cli.main(["--campaign", "demo", "commit-blind", "--round", "1", "--file", "reviews/round1/replicate/values.json"]) == 0
    assert review_cli.main(["--campaign", "demo", "waive", "--round", "1", "--role", "novelty", "--target", "survey.md", "--reason", "ok"]) == 0
    assert review_cli.main(["--campaign", "demo", "regime", "--claim", "T-001"]) == 0
    assert review_cli.main(["--campaign", "demo", "close", "--round", "1"]) == 0
    assert B.load_manifest(d, 1)["status"] == "closed"


def test_campaign_review_gate_uses_check_round(tmp_path, monkeypatch):
    import harness.campaign as campaign

    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")
    path = campaign.create("demo", "Demo")
    campaign.set_phase("demo", "review")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    thm = store.add(kind="theorem", statement="T.")
    _write(path / "proofs" / "T-001.md", "**Step 1.** (algebra) x.")
    store.add_evidence(thm.id, Evidence(type="proof", path="proofs/T-001.md"), path)
    store.promote(thm.id, "proof-drafted", path)
    for role in ("skeptic", "falsifier", "novelty", "replicator", "judge"):
        store.add_evidence(thm.id, Evidence(type="referee", role=role, verdict="pass", round=1,
                                            agent_id="SK-1" if role == "skeptic" else None), path)
    store.add_evidence(thm.id, Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-2"), path)
    for f in ("skeptic.md", "falsifier.md", "novelty.md", "judge.md"):
        _write(path / "reviews" / "round1" / f, "notes\nVERDICT: PASS\n")
    store.promote(thm.id, "referee-passed", path)
    unmet = campaign.check_phase_exit("demo")
    assert any("no barrier manifest" in m for m in unmet)
