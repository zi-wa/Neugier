"""Tests for harness.questions — the curiosity engine (rule R6)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
import harness.questions as Q
from harness.library import memory
from harness.paper.questions_tex import render_questions_tex, write_questions_appendix

DOC = """# Questions — demo

## Q-001: Why does the greedy Sidon construction plateau near density 0.29 for N ≤ 2000?
- Curiosity: 3/3
- Stake: 4/5
- Expectation: density decays like c/sqrt(N); a plateau would be surprising.
- Cheapest test: run seed.py for N = 100..5000, fit exponent (≤ 15 min).
- Status: open
- Raised by: experimentalist, 2026-09-02, explore

## Q-002: Is the extremal configuration always symmetric?
- Curiosity: 2/3
- Stake: 5/5
- Expectation: yes for n ≤ 12
- Cheapest test: enumerate n ≤ 8 (~2 h)
- Credence: 0.5
- Status: open
- Raised by: prover, 2026-09-03, prove

## Q-003: Does source A's constant match source B's?
- Curiosity: 1/3
- Expectation: they agree
- Cheapest test: reread both excerpts (5 min)
- Status: answered → F-004
- Raised by: librarian, 2026-09-02, survey

## Prediction (Q-001): greedy density at N = 5000
- Predicted: 0.014
- Observed: 0.29
- Surprise: 3/3

## Surprise: two sources disagree on the constant
- Prediction: constants agree
- Observation: 1.96 vs 1.94
- Curiosity: 2/3
- Follow-up: Q-003

## Detour (explore, 40 min): Q-001
- What I did: refit the exponent on N ≤ 5000
- What I learned: plateau is real
- Plan impact: re-plan requested (density exponent wrong)
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(Q, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")


def test_parse_questions_fields():
    doc = Q.parse_questions(DOC)
    assert [q.id for q in doc.questions] == ["Q-001", "Q-002", "Q-003"]
    q1, q2, q3 = doc.questions
    assert q1.curiosity == 3 and q1.curiosity_max == 3 and q1.stake == 4 and q1.cost_minutes == 15
    assert q1.phase == "explore" and q1.status == "open"
    assert q2.cost_minutes == 120 and q2.p_true == 0.5 and "prover" in q2.raised_by
    assert q3.status == "answered" and q3.status_ref == "F-004" and q3.stake == 3
    assert len(doc.observations) == 2
    pred, surp = doc.observations
    assert pred.kind == "prediction" and pred.question_id == "Q-001" and pred.score == 3 and pred.observed == "0.29"
    assert surp.kind == "surprise" and surp.follow_up == "Q-003" and surp.score == 2
    assert doc.detours[0].minutes == 40 and doc.detours[0].phase == "explore" and doc.detours[0].question_id == "Q-001"


def test_info_gain_ranking_uses_credence_entropy():
    doc = Q.parse_questions(DOC)
    ranked = Q.rank_open(doc)
    assert [q.id for _, q in ranked] == ["Q-001", "Q-002"]
    gains = {q.id: g for g, q in ranked}
    assert gains["Q-001"] == pytest.approx(1.0 * 4 / 15)
    assert gains["Q-002"] == pytest.approx(1.0 * 5 / 120)  # 4·0.5·0.5 = 1 uncertainty
    q2 = doc.get("Q-002")
    q2.p_true = 0.95
    assert Q.info_gain(q2) < gains["Q-002"]
    nxt = Q.next_actions(doc, budget_left=30)
    assert nxt["next"][0]["id"] == "Q-001" and nxt["next"][0]["affordable"] is True
    assert nxt["next"][1]["affordable"] is False


def test_set_status_and_append_blocks():
    text = Q.set_status(DOC, "Q-002", "parked", "waiting for the extremal enumeration")
    doc = Q.parse_questions(text)
    assert doc.get("Q-002").status == "parked" and "extremal enumeration" in doc.get("Q-002").status_ref
    with pytest.raises(KeyError):
        Q.set_status(DOC, "Q-999", "answered")
    no_status = "## Q-010: new?\n- Curiosity: 2/3\n"
    assert "- Status: dropped → dup" in Q.set_status(no_status, "Q-010", "dropped", "dup")
    text2 = Q.append_block(text, Q.surprise_block(question_id="Q-002", title="sym", prediction="yes", observation="no", score=3))
    doc2 = Q.parse_questions(text2)
    assert doc2.observations[-1].question_id == "Q-002" and doc2.observations[-1].score == 3
    assert Q.hot_surprises_without_followup(doc2)
    text3 = Q.append_block(text2, Q.detour_block(phase="prove", minutes=90, question_id="Q-002", what="w", learned="l", impact="none"))
    assert Q.detour_minutes(Q.parse_questions(text3), "prove") == 90


def test_budget_and_advisories(tmp_path):
    path = campaign.create("demo", "Demo", {"hours_per_phase": {"explore": 2}, "curiosity_fraction": 0.3})
    campaign.set_phase("demo", "explore")
    _write(path / "questions.md", DOC)
    b = Q.budget_status(path)
    assert b["detour_budget_minutes"] == pytest.approx(36.0) and b["detour_minutes_used"] == 40 and b["over"] is True
    adv = Q.advisories(path)
    assert any("without follow-up" in a for a in adv) and any("detour budget exceeded" in a for a in adv)
    assert "Q-001" in Q.top_open_line(path)


def test_gates_explore_prediction_and_prover_questions(tmp_path):
    path = campaign.create("demo", "Demo")
    campaign.set_phase("demo", "explore")
    _write(path / "experiments" / "results.json", "{}")
    unmet = campaign.check_phase_exit("demo")
    assert any("prediction/observation" in m for m in unmet)
    _write(path / "questions.md", DOC)
    assert campaign.check_phase_exit("demo") == []
    campaign.set_phase("demo", "prove")
    unmet = campaign.check_phase_exit("demo")
    assert any("raised by the prover" in m and "Q-002" in m for m in unmet)


def test_cli_roundtrip(tmp_path, capsys):
    path = campaign.create("demo", "Demo", {"human_interrupts": 1})
    _write(path / "questions.md", DOC)
    assert Q.main(["--campaign", "demo", "next"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["next"][0]["id"] == "Q-001"
    assert Q.main(["--campaign", "demo", "surprise", "--question", "Q-002", "--prediction", "sym", "--observation", "asym", "--score", "3", "--follow-up", "Q-004"]) == 0
    assert Q.main(["--campaign", "demo", "detour", "--phase", "explore", "--minutes", "10", "--what", "w", "--learned", "l"]) == 0
    assert Q.main(["--campaign", "demo", "answer", "Q-002", "--ref", "results.json#sym"]) == 0
    doc = Q.load_doc(path)
    assert doc.get("Q-002").status == "answered" and len(doc.observations) == 3 and len(doc.detours) == 2
    assert Q.main(["--campaign", "demo", "answer", "Q-404"]) == 1
    assert Q.main(["--campaign", "demo", "next", "--brief"]) == 0
    assert "Q-001" in capsys.readouterr().out
    assert Q.main(["--campaign", "demo", "budget"]) == 0
    assert Q.main(["--campaign", "demo", "export"]) == 0


def test_human_escalation_budget_and_answers(tmp_path, capsys):
    path = campaign.create("demo", "Demo", {"human_interrupts": 1})
    assert (path / "HUMAN.md").exists()
    _write(path / "questions.md", DOC)
    rc = Q.main(["--campaign", "demo", "for-human", "--q", "Q-002", "--stake", "5", "--would-change", "route choice",
                 "--cheapest", "sketch the n=6 case", "--best-guess", "symmetric", "--p", "0.6", "--raised-by", "prover"])
    assert rc == 0
    ask = (path / "ASK-HUMAN.md").read_text(encoding="utf-8")
    assert "H-001" in ask and "extremal configuration" in ask and "route choice" in ask
    assert Q.main(["--campaign", "demo", "for-human", "--question", "second?"]) == 3  # budget exhausted
    human = (path / "HUMAN.md").read_text(encoding="utf-8")
    human += "\n### H-001\nYes: by a reflection argument; see Lemma 2 of the 1998 paper.\n"
    _write(path / "HUMAN.md", human)
    newly = Q.sync_human_answers(path, "demo")
    assert len(newly) == 1 and "reflection" in newly[0].answer
    doc = Q.load_doc(path)
    assert doc.get("Q-002").status == "answered" and "HUMAN.md#H-001" in doc.get("Q-002").status_ref
    assert Q.sync_human_answers(path, "demo") == []
    summary = Q.human_summary(path, {"human_interrupts": 1})
    assert summary["used"] == 1 and summary["open"] == []
    report = campaign.status_report("demo")
    assert "## Human" in report and "## Questions" in report


def test_library_open_questions_and_finish(tmp_path):
    path = campaign.create("demo", "Demo")
    _write(path / "questions.md", DOC)
    with open(path / "log.md", "a", encoding="utf-8") as fh:
        fh.write("\n## Outcome\nnegative\n")
    summary = campaign.finish("demo", outcome="negative")
    assert summary["open_questions_recorded"] == 2 and campaign.load("demo").phase == "done"
    assert campaign.finish("demo") ["open_questions_recorded"] == 0  # deduped
    rows = memory.open_questions("Sidon")
    assert rows and rows[0]["id"] == "Q-001"
    assert len(memory.all("results")) == 2


def test_questions_appendix(tmp_path):
    path = campaign.create("demo", "Demo")
    _write(path / "questions.md", DOC)
    tex = render_questions_tex(Q.load_doc(path))
    assert r"\subsection{Open questions and surprises}" in tex and "Q-001" in tex and "0.29" in tex
    out = write_questions_appendix(path)
    assert out.name == "appendix-questions.tex" and out.exists()
