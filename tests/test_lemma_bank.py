"""Round-2 Step 23: the lemma bank / goal cache (Y7)."""
from __future__ import annotations

from pathlib import Path

import pytest

import harness
import harness.ledger.cli as ledger_cli
import harness.library.cli as library_cli
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence
from harness.library import memory


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(ledger_cli, "CAMPAIGNS", tmp_path / "campaigns")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_promotion_banks_lemma_and_find_lemma_matches(tmp_path):
    d = tmp_path / "campaigns" / "one"
    d.mkdir(parents=True)
    store = LedgerStore(d / "ledger.json", campaign="one")
    lem = store.add(kind="lemma", statement="If S is a finite set of integers with |S| >= 2 then |S+S| >= 2|S| - 1.",
                    tags=["technique:double-counting"])
    _write(d / "proofs" / f"{lem.id}.md", "**Step 1.** (algebra) x.")
    store.add_evidence(lem.id, Evidence(type="proof", path=f"proofs/{lem.id}.md"), d)
    store.promote(lem.id, "proof-drafted", d)
    rows = memory.all("lemmas")
    assert len(rows) == 1 and rows[0]["claim_id"] == lem.id and rows[0]["technique"] == ["double-counting"]
    assert rows[0]["proof_path"] == f"proofs/{lem.id}.md"
    store.promote(lem.id, "proof-drafted", d)  # deduped
    assert len(memory.all("lemmas")) == 1
    hits = memory.find_lemma("If S is a finite set of integers with |S| >= 2 then |S+S| >= 2|S| - 1.")
    assert hits and hits[0]["match"] == "hash"
    fuzzy = memory.find_lemma("For a finite set S of integers with |S| >= 2, |S+S| >= 2|S| - 1 holds.", threshold=0.5)
    assert fuzzy and fuzzy[0]["match"] in ("tfidf", "hash")
    assert memory.find_lemma("The Riemann zeta function has no zeros off the critical line.") == []


def test_ledger_near_duplicates_and_cli_warnings(tmp_path, capsys):
    d = tmp_path / "campaigns" / "two"
    d.mkdir(parents=True)
    memory.add_lemma("Every finite sum-free subset of Z has density at most 1/2.", "referee-passed", "old", "L-007", "proofs/L-007.md")
    store = LedgerStore(d / "ledger.json", campaign="two")
    store.add(kind="lemma", statement="Every graph with minimum degree at least n/2 has a Hamilton cycle.")
    hits = store.near_duplicates("Every finite sum-free subset of Z has density at most 1/2.")
    assert any(h["where"] == "library" and h["id"] == "old:L-007" for h in hits)
    hits2 = store.near_duplicates("Every graph with minimum degree at least n/2 has a Hamilton cycle.")
    assert any(h["where"] == "ledger" and h["score"] == 1.0 for h in hits2)
    assert ledger_cli.main(["--campaign", "two", "add", "--kind", "lemma", "--statement",
                            "Every finite sum-free subset of Z has density at most 1/2."]) == 0
    assert "near-duplicate" in capsys.readouterr().err
    assert library_cli.main(["find-lemma", "Every finite sum-free subset of Z has density at most 1/2."]) == 3
    assert library_cli.main(["find-lemma", "Something unrelated about elliptic curves and modular forms."]) == 0
    assert library_cli.main(["list", "lemmas"]) == 0
