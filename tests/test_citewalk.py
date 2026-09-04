"""Round-1 Step 13: `lit cite-walk` (offline, OpenAlex monkeypatched)."""
from __future__ import annotations

import json

import harness.lit.cli as lit_cli
from harness.lit import citewalk, openalex
from harness.lit.models import Paper


def _paper(pid: str, title: str, year: int = 2020, cites: int = 0) -> Paper:
    return Paper(id=pid, source="openalex", title=title, year=year, cited_by_count=cites)


def _install(monkeypatch):
    graph_fwd = {"openalex:W1": [_paper("openalex:W2", "cites W1", 2022, 5), _paper("openalex:W3", "also cites W1", 2023, 1)],
                 "openalex:W2": [_paper("openalex:W4", "cites W2", 2024)]}
    graph_back = {"openalex:W1": [_paper("openalex:W0", "referenced by W1", 2010, 100)], "openalex:W2": [_paper("openalex:W1", "seed", 2020)]}
    monkeypatch.setattr(openalex, "get_work", lambda wid: _paper("openalex:W1", "seed", 2020) if "W1" in wid or "2001.00001" in wid else None)
    monkeypatch.setattr(openalex, "cited_by", lambda wid, per_page=50: graph_fwd.get(wid, []))
    monkeypatch.setattr(openalex, "references", lambda wid: graph_back.get(wid, []))


def test_cite_walk_hops_and_directions(monkeypatch):
    _install(monkeypatch)
    one = citewalk.cite_walk("2001.00001", direction="both", hops=1)
    ids = {n["id"]: n for n in one["nodes"]}
    assert one["seed"] == "openalex:W1" and ids["openalex:W1"]["hop"] == 0
    assert ids["openalex:W2"]["hop"] == 1 and ids["openalex:W2"]["direction"] == "cited-by" and ids["openalex:W0"]["direction"] == "references"
    assert "openalex:W4" not in ids and one["counts"] == {0: 1, 1: 3}
    two = citewalk.cite_walk("openalex:W1", direction="cited-by", hops=2, max_n=10)
    ids2 = {n["id"]: n for n in two["nodes"]}
    assert ids2["openalex:W4"]["hop"] == 2 and ids2["openalex:W4"]["via"] == "openalex:W2" and "openalex:W0" not in ids2
    assert two["nodes"][1]["id"] == "openalex:W2"  # hop-1 nodes ordered by citation count
    back = citewalk.cite_walk("openalex:W1", direction="references", hops=1)
    assert [n["id"] for n in back["nodes"]] == ["openalex:W1", "openalex:W0"]


def test_cite_walk_cli(monkeypatch, capsys):
    _install(monkeypatch)
    assert lit_cli.main(["cite-walk", "openalex:W1", "--direction", "cited-by", "--hops", "1", "--max", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"][ "1" if isinstance(next(iter(out["counts"])), str) else 1] == 1
