from __future__ import annotations

import json

import pytest

import harness
from harness.library import cli, memory


@pytest.fixture(autouse=True)
def _tmp_library(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")
    yield tmp_path / "library"


def test_add_and_list_rejected(_tmp_library):
    memory.add_rejected("Zarankiewicz z(11,21;3,3)", "solved by OpenEvolve 2026", campaign="c1", tags=["extremal"])
    rows = memory.all("rejected")
    assert len(rows) == 1 and rows[0]["topic"].startswith("Zarankiewicz")
    raw = (_tmp_library / "rejected.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(raw) == 1 and json.loads(raw[0])["tags"] == ["extremal"]


def test_fact_dedupe():
    r1 = memory.add_fact("R(5,5) <= 46", "arxiv:2409.00001", "we prove R(5,5) is at most 46 using flag algebras")
    r2 = memory.add_fact("  r(5,5)  <= 46 ", "arxiv:other", "some other excerpt that is long enough")
    assert r1 is not None and r2 is None
    assert len(memory.all("facts")) == 1


def test_search_ranks_by_matched_tokens():
    memory.add_rejected("kissing number dimension 11", "beaten by humans", tags=["packing"])
    memory.add_rejected("Ramsey R(3,10) lower bound", "already in literature", tags=["ramsey"])
    hits = memory.search("rejected", "kissing dimension")
    assert hits and hits[0]["topic"].startswith("kissing")


def test_is_rejected_fuzzy():
    memory.add_rejected("Sidon set constant improvement", "known")
    assert memory.is_rejected("Sidon-set constant improvements") is not None
    assert memory.is_rejected("Hadamard matrix of order 668") is None


def test_results_store_and_cli(capsys, tmp_path):
    claims = tmp_path / "claims.json"
    claims.write_text(json.dumps([{"id": "T-001", "statement": "x", "status": "referee-passed"}]), encoding="utf-8")
    rc = cli.main(["add-result", "--campaign", "c1", "--title", "T", "--outcome", "partial", "--claims-json", str(claims)])
    assert rc == 0
    assert cli.main(["list", "results"]) == 0
    rows = memory.all("results")
    assert rows[0]["claims"][0]["id"] == "T-001" and rows[0]["outcome_class"] == "partial"


def test_cli_check_rejected_exit_code(capsys):
    cli.main(["add-rejected", "--topic", "unit distance graph chromatic number", "--reason", "too hard"])
    capsys.readouterr()
    assert cli.main(["check-rejected", "unit-distance graph chromatic number"]) == 3
    assert cli.main(["check-rejected", "superpermutations n=7"]) == 0
