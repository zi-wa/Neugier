"""Round-2 Step 18: stakes-scaled regime wired into referee-passed promotion; k-of-k skeptics."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
from harness.ledger.ledger import LedgerError, LedgerStore
from harness.ledger.schema import Evidence
from harness.review import barrier as B


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _camp(tmp_path: Path, budgets: dict | None = None) -> tuple[Path, LedgerStore]:
    d = tmp_path / "camp"
    d.mkdir()
    _write(d / "campaign.json", json.dumps({"slug": "camp", "budgets": budgets or {}}))
    store = LedgerStore(d / "ledger.json", campaign="camp")
    return d, store


def _drafted(store: LedgerStore, d: Path, stakes: int) -> str:
    thm = store.add(kind="theorem", statement=f"T{stakes}.", stakes=stakes)
    _write(d / "proofs" / f"{thm.id}.md", "**Step 1.** (algebra) x.")
    store.add_evidence(thm.id, Evidence(type="proof", path=f"proofs/{thm.id}.md"), d)
    store.promote(thm.id, "proof-drafted", d)
    return thm.id


def _others(store: LedgerStore, cid: str, d: Path, *, replicator: bool = True) -> None:
    for role in ("falsifier", "novelty", "judge"):
        store.add_evidence(cid, Evidence(type="referee", role=role, verdict="pass", round=1), d)
    if replicator:
        store.add_evidence(cid, Evidence(type="referee", role="replicator", verdict="n/a", round=1), d)


def _skeptics(store: LedgerStore, cid: str, d: Path, ids: list[str | None]) -> None:
    for a in ids:
        store.add_evidence(cid, Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id=a), d)


def test_tier0_single_skeptic_no_replicator(tmp_path):
    d, store = _camp(tmp_path)
    cid = _drafted(store, d, 0)
    _others(store, cid, d, replicator=False)
    _skeptics(store, cid, d, [None])
    assert store.promote(cid, "referee-passed", d).status == "referee-passed"


def test_tier1_needs_two_distinct_skeptics_and_replicator(tmp_path):
    d, store = _camp(tmp_path)
    cid = _drafted(store, d, 1)
    _others(store, cid, d, replicator=False)
    _skeptics(store, cid, d, [None, None])  # anonymous passes count once
    with pytest.raises(LedgerError, match="distinct agent_ids"):
        store.promote(cid, "referee-passed", d)
    _skeptics(store, cid, d, ["SK-a", "SK-b"])
    with pytest.raises(LedgerError, match="replicator"):
        store.promote(cid, "referee-passed", d)
    store.add_evidence(cid, Evidence(type="referee", role="replicator", verdict="n/a", round=1), d)
    assert store.promote(cid, "referee-passed", d).status == "referee-passed"


def test_tier2_needs_three_skeptics_and_budget_can_raise_k(tmp_path):
    d, store = _camp(tmp_path, {"skeptic_passes": 4})
    cid = _drafted(store, d, 2)
    _others(store, cid, d)
    _skeptics(store, cid, d, ["SK-1", "SK-2", "SK-3"])
    with pytest.raises(LedgerError, match="4 admissible"):
        store.promote(cid, "referee-passed", d)
    _skeptics(store, cid, d, ["SK-4"])
    assert store.promote(cid, "referee-passed", d).status == "referee-passed"


def test_manifest_present_makes_promotion_consult_check_round(tmp_path):
    d, store = _camp(tmp_path, {"max_review_rounds": 3})
    _write(d / "statement.md", "S.")
    cid = _drafted(store, d, 0)
    B.open_round(d, 1, cid, [f"proofs/{cid}.md"], skeptics=1, stakes=0)
    rdir = d / "reviews" / "round1"
    with open(rdir / "access.log", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2020-01-01T00:00:00", "role": "skeptic:SK-x", "tool": "Read", "decision": "deny",
                             "target": "plan.md", "reason": "deny:plan.md"}) + "\n")
    _others(store, cid, d, replicator=False)
    _skeptics(store, cid, d, ["SK-x"])
    with pytest.raises(LedgerError, match="barrier denial"):
        store.promote(cid, "referee-passed", d)
    B.waive(d, 1, "skeptic:SK-x", "plan.md", "human reviewed")
    assert store.promote(cid, "referee-passed", d).status == "referee-passed"


def test_campaign_attest_and_suggest_stakes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")
    path = campaign.create("demo", "Demo")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    thm = store.add(kind="target", statement="G.")
    assert campaign.main(["attest", "demo", "--claim", thm.id, "--human", "Jane"]) == 0
    assert LedgerStore(path / "ledger.json").get(thm.id).attestation["by"] == "Jane"
    assert campaign.suggest_stakes("demo")["suggested_stakes"] == 1
    _write(path / "portfolio.md", "# P\n## Rubric scores (top 12)\n| Candidate | V | T | N | P | I | L | F | Weighted |\n|---|---|---|---|---|---|---|---|---|\n| Erdős #123 | 3 | 2 | 3 | 2 | 2 | 1 | 2 | 28 |\n## Selected target\n- Statement (informal): Erdős #123 on sum-free sets\n- Known best result (excerpt, source): c = 0.29 (Smith 2020)\n")
    out = campaign.suggest_stakes("demo")
    assert out["suggested_stakes"] == 2 and any("open problem" in r for r in out["reasons"])
    _write(path / "portfolio.md", "# P\n## Rubric scores (top 12)\n| Candidate | V | T | N | P | I | L | F | Weighted |\n|---|---|---|---|---|---|---|---|---|\n| small lemma | 3 | 2 | 1 | 1 | 2 | 1 | 2 | 20 |\n## Selected target\n- Statement (informal): a routine counting lemma\n")
    assert campaign.suggest_stakes("demo")["suggested_stakes"] == 0
    assert campaign.main(["suggest-stakes", "demo"]) == 0
