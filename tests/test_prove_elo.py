"""Round-2 Step 26: sketch-first Elo tournament (Y6)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.prove.cli as prove_cli
from harness.prove import elo as E


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _match(a, b, winner, axis="plausibility", tier="pairwise", steal="", rater="J1") -> dict:
    return {"a": a, "b": b, "winner": winner, "axis": axis, "tier": tier, "rationale": "r", "steal_from_loser": steal, "rater": rater}


def test_elo_updates_are_symmetric_and_draws_halve():
    ms = [E.Match(**_match("x", "y", "a"))]
    r = E.rate(ms)
    assert r["x"].elo == 1216.0 and r["y"].elo == 1184.0 and r["x"].wins == 1 and r["y"].losses == 1
    d = E.rate([E.Match(**_match("x", "y", "draw"))])
    assert d["x"].elo == 1200.0 and d["y"].elo == 1200.0 and d["x"].draws == 1
    named = E.rate([E.Match(**_match("x", "y", "y"))])
    assert named["y"].elo > named["x"].elo
    assert round(E.aggregate_from_odds(10.0)) == 1600


def test_pucb_prefers_unvisited_and_select_respects_budget_and_veto():
    ratings = {"a": E.Rating(elo=1250, visits=4), "b": E.Rating(elo=1250, visits=0), "c": E.Rating(elo=1100, visits=4)}
    scores = E.pucb_scores(ratings, c=1.0)
    assert scores["b"] > scores["a"] > scores["c"]
    rows = E.select(scores, falsified={"b"}, n=1)
    by = {r["persona"]: r for r in rows}
    assert by["b"]["selected"] is False and "falsified" in by["b"]["reason"]
    assert by["a"]["selected"] is True and by["c"]["selected"] is False and by["c"]["reason"] == "budget"


def test_tournament_end_to_end_and_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(prove_cli, "CAMPAIGNS", tmp_path / "campaigns")
    d = tmp_path / "campaigns" / "demo"
    _write(d / "campaign.json", json.dumps({"slug": "demo", "budgets": {"full_proofs": 1}}))
    for persona in ("analyst", "combinatorialist", "algebraist"):
        _write(d / "proofs" / f"T-001.sketch.{persona}.md", f"---\nkind: sketch\nclaim: T-001\npersona: {persona}\n---\n")
    tdir = d / "reviews" / "tournament-T-001"
    _write(tdir / "match-analyst-combinatorialist-plausibility-pairwise.json", json.dumps(_match("analyst", "combinatorialist", "a", steal="the compression lemma")))
    _write(tdir / "match-analyst-algebraist-clarity-pairwise.json", json.dumps(_match("analyst", "algebraist", "b")))
    _write(tdir / "match-combinatorialist-algebraist-novelty-debate.json", json.dumps(_match("combinatorialist", "algebraist", "draw", axis="novelty", tier="debate")))
    _write(tdir / "falsify" / "algebraist-S2.json", json.dumps({"conjecture": "S2", "counterexample_repr": "3"}))
    _write(tdir / "falsify" / "analyst-S1.json", json.dumps({"conjecture": "S1", "counterexample_repr": None}))
    res = E.tournament(d, "T-001")
    assert res["matches"] == 3 and res["tiers"] == {"pairwise": 2, "debate": 1}
    assert res["sketches"]["algebraist"]["falsified_lemmas"] == ["S2"] and not res["sketches"]["algebraist"]["selected"]
    assert res["selected"] == ["analyst"] or res["selected"] == ["combinatorialist"]
    assert res["cross_pollination"]["analyst"] == ["from combinatorialist (plausibility): the compression lemma"]
    assert (tdir / "tournament.json").exists() and (tdir / "matches.jsonl").exists()
    again = E.tournament(d, "T-001")
    assert again["matches"] == 3  # jsonl + files deduped
    assert prove_cli.main(["elo", "--campaign", "demo", "--claim", "T-001"]) == 0
    out = capsys.readouterr().out
    assert "SELECTED" in out and "<- from combinatorialist" in out
    for p in tdir.glob("match-*.json"):
        p.unlink()
    (tdir / "matches.jsonl").unlink()
    _write(tdir / "falsify" / "analyst-S1.json", json.dumps({"conjecture": "S1", "counterexample_repr": "9"}))
    _write(tdir / "falsify" / "combinatorialist-S1.json", json.dumps({"conjecture": "S1", "regression_failures": ["1"]}))
    assert prove_cli.main(["elo", "--campaign", "demo", "--claim", "T-001", "--json"]) == 3
