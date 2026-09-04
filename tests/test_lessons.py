"""Round-2 Step 27: lessons + move statistics (Y11), structural promise checks (Y14), HUMAN.md policy hash (X6)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
import harness.library.cli as library_cli
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence
from harness.library import lessons as L
from harness.library import memory

LOG = """# log
## Outcome
negative

## Lessons
- [phase=review] the skeptic caught a uniformity gap the falsifier could not see — evidence: reviews/round1/skeptic.SK-1.md — moves: M32 — tags: skeptic,gap
- [phase=explore] descending greedy scans beat ascending ones — evidence: experiments/evolve/sidon100/mine.md — moves: M61,M60 — tags: evolve
- a bullet without phase or metadata still counts
not a bullet
"""

IDEAS = """## Route 1: Entropy — lens: information-theoretic
- Moves: M12, M21
- Cheap falsification (≤ 10 min): x
- Credence: p_true=0.3 (strategist) — why
- Status: dead: entropic inequality false

## Route 2: Polynomial — lens: algebraic
- Moves: M40
- Cheap falsification (≤ 10 min): y
- Credence: p_true=0.5 (strategist) — why
- Status: key-step T-001
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_parse_lessons_block():
    rows = L.parse_lessons(LOG)
    assert len(rows) == 3
    assert rows[0]["phase"] == "review" and rows[0]["moves"] == ["M32"] and rows[0]["tags"] == ["skeptic", "gap"]
    assert rows[0]["evidence_path"] == "reviews/round1/skeptic.SK-1.md" and "uniformity gap" in rows[0]["lesson"]
    assert rows[1]["moves"] == ["M60", "M61"]
    assert rows[2]["phase"] == "" and rows[2]["lesson"].startswith("a bullet")
    assert L.parse_lessons("## Outcome\nnothing\n") == []


def test_finish_requires_lessons_and_records_moves_stats(capsys):
    path = campaign.create("demo", "Demo")
    _write(path / "ideas.md", IDEAS)
    with open(path / "log.md", "a", encoding="utf-8") as fh:
        fh.write("\n## Outcome\nnegative\n")
    campaign.set_phase("demo", "done")
    c = campaign.load("demo")
    c.outcome_class = "negative"
    campaign.save(c)
    assert any("## Lessons" in m for m in campaign.check_phase_exit("demo"))
    with pytest.raises(campaign.CampaignError, match="Lessons"):
        campaign.finish("demo")
    with open(path / "log.md", "a", encoding="utf-8") as fh:
        fh.write(LOG.split("## Outcome\nnegative\n", 1)[1])
    assert campaign.check_phase_exit("demo") == []
    summary = campaign.finish("demo")
    assert summary["lessons_recorded"] == 3 and summary["route_moves_recorded"] == 2
    assert campaign.finish("demo")["lessons_recorded"] == 0  # deduped
    stats = L.moves_stats()
    assert stats["M40"] == {"tried": 1, "survived_falsification": 1, "proof_drafted": 1, "key_step": 1, "lessons": 0}
    assert stats["M12"]["tried"] == 1 and stats["M12"]["survived_falsification"] == 0
    assert stats["M32"]["lessons"] == 1 and stats["M61"]["lessons"] == 1
    assert L.lessons("uniformity")[0]["phase"] == "review"
    assert library_cli.main(["lessons", "--query", "greedy"]) == 0
    assert "descending" in capsys.readouterr().out
    assert library_cli.main(["moves-stats"]) == 0
    assert library_cli.main(["list", "moves"]) == 0


def test_structural_advisories_and_human_policy_state():
    path = campaign.create("demo", "Demo")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    lem = store.add(kind="lemma", statement="L.")
    _write(path / "proofs" / f"{lem.id}.md", "**Step 1.** (algebra) x.")
    store.add_evidence(lem.id, Evidence(type="proof", path=f"proofs/{lem.id}.md"), path)
    store.promote(lem.id, "proof-drafted", path)
    adv = campaign.structural_advisories("demo")
    assert any("no falsification evidence" in a for a in adv)
    _write(path / "experiments" / "results.json", json.dumps({"k1": {"value": 1}}))
    _write(path / "reviews" / "round1" / "skeptic.md", "```yaml\nrole: skeptic\nclaim: L-001\nround: 1\nverdict: pass\nchecked:\n  - \"recomputed results.json#missing_key\"\n```\n")
    adv = campaign.structural_advisories("demo")
    assert any("results.json#missing_key" in a for a in adv)
    with open(path / "log.md", "a", encoding="utf-8") as fh:
        fh.write("\nWe ran the falsifier on every lemma before submitting.\n")
    adv = campaign.structural_advisories("demo")
    assert any("ran the falsifier on every lemma" in a and lem.id in a for a in adv)
    assert campaign.human_policy_state("demo") == "ok"
    human = (path / "HUMAN.md").read_text(encoding="utf-8").replace("## Policy\n", "## Policy\nPrefer exact constructions over bounds.\n")
    _write(path / "HUMAN.md", human)
    assert campaign.human_policy_state("demo") == "MODIFIED"
    assert any("HUMAN.md policy changed" in a for a in campaign.structural_advisories("demo"))
    assert campaign.main(["ack-human", "demo"]) == 0
    assert campaign.human_policy_state("demo") == "ok"
    report = campaign.status_report("demo")
    assert "policy: ok" in report and "advisory:" in report
