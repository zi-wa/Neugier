"""Tests for harness.text.similarity and harness.ideas (routes parser + dedup)."""
from __future__ import annotations

from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
import harness.ideas as ideas
from harness.text import similarity as S

IDEAS = """# Ideas — demo

## Route 1: Entropy reformulation — lens: information-theoretic
- Moves: M12 (change the ambient object), M21 (entropy)
- Idea: replace |A+A| by H(X+X') for X uniform on A; prove the entropic inequality.
- Why it might work: entropy versions are often cleaner.
- Cheap falsification (≤ 30 min): compute H(X+X') for random A, |A| ≤ 12.
- Cost estimate: 2 h explore / 6 h prove
- Kill criterion: entropic inequality false for some |A| ≤ 12.
- Credence: p_true=0.35 p_budget=0.2 (strategist) — the entropic form is known to be weaker in some cases
- Status: untested

## Route 2: Entropic reformulation via Shannon entropy — lens: information-theoretic
- Moves: M12, M21
- Idea: replace |A+A| by the entropy H(X+X') of X uniform on A and prove the entropic inequality.
- Cheap falsification (≤ 30 min): compute H(X+X') for random A with |A| ≤ 12.
- Status: dead: entropic inequality false for |A| = 7

## Route 3: Polynomial method — lens: algebraic
- Moves: M40, M43
- Idea: encode A as the zero set of a low-degree polynomial over F_p.
- Cheap falsification (≤ 1 h): check the degree bound for p ≤ 13.
- Status: proved L-002

## Route 4: Fourier analysis — lens: analytic
- Moves: M30
- Idea: bound the additive energy through the large spectrum.
- Status: key-step T-001
"""


def test_tokenize_keeps_math_symbols():
    toks = S.tokenize("|S+S| ≥ 2|S| − 1 for every finite S")
    assert "≥" in toks and "|" in toks and "finite" in toks and "for" not in toks


def test_code_hash_ignores_comments_docstrings_whitespace():
    a = "def f(x):\n    '''doc'''\n    return x+1  # comment\n"
    b = "def f(x):\n    return x + 1\n"
    assert S.code_hash(a) == S.code_hash(b)
    assert S.code_hash("def f(x): return x+2") != S.code_hash(b)
    assert S.normalize_code("not python (") == "not python ("


def test_near_duplicates_threshold_and_fallback():
    items = [
        "replace |A+A| by the entropy H(X+X') of X uniform on A and prove the entropic inequality",
        "replace |A+A| by H(X+X') for X uniform on A; prove the entropic inequality",
        "encode A as the zero set of a low-degree polynomial over F_p",
        "bound the additive energy through the large spectrum",
    ]
    pairs = S.near_duplicates(items, 0.6)
    assert pairs and pairs[0][:2] == (0, 1)
    assert not [p for p in pairs if 2 in p[:2] or 3 in p[:2]]
    assert S.near_duplicates(items[:2], 0.5)  # difflib fallback for n < 3
    assert S.near_duplicates(items[:1]) == []
    top = S.most_similar("entropy of X+X'", items, k=2)
    assert top[0][0] in (0, 1)
    g = S.proximity_graph(items, 0.5)
    assert g["nodes"] == 4 and [0, 1] in g["clusters"]


def test_parse_routes_and_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(ideas, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")
    routes = ideas.parse_routes(IDEAS)
    assert [r.index for r in routes] == [1, 2, 3, 4]
    r1, r2, r3, r4 = routes
    assert r1.lens == "information-theoretic" and r1.moves == ["M12", "M21"] and r1.status == "untested"
    assert r1.credence and r1.credence.p_true == 0.35 and r1.credence.p_budget == 0.2 and r1.credence.role == "strategist"
    assert "weaker" in r1.credence.why and "random A" in r1.falsification and r1.kill.startswith("entropic")
    assert r2.status == "dead" and "|A| = 7" in r2.status_note
    assert r3.status == "proved" and r3.claim_ids == ["L-002"]
    assert r4.status == "key-step" and r4.claim_ids == ["T-001"] and r4.falsification == ""
    pairs = ideas.dedup(routes, 0.6)
    assert pairs and {pairs[0]["a"], pairs[0]["b"]} == {1, 2}
    path = campaign.create("demo", "Demo")
    (path / "ideas.md").write_text(IDEAS, encoding="utf-8")
    adv = ideas.advisories(path, 0.6)
    assert any("near-duplicates" in a for a in adv) and any("share a lens" in a for a in adv) and any("[4]" in a for a in adv)
    assert ideas.main(["--campaign", "demo", "dedup", "--threshold", "0.6"]) == 3
    assert ideas.main(["--campaign", "demo", "list"]) == 0
    assert ideas.main(["--campaign", "demo", "graph"]) == 0
