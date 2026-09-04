"""Tests for harness.campaign — campaign lifecycle and phase-exit gates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.campaign as campaign
from harness.review import barrier as B
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence

REFEREE_ROLES = ("skeptic", "falsifier", "novelty", "replicator", "judge")


@pytest.fixture(autouse=True)
def _isolated_campaigns(tmp_path, monkeypatch):
    """Redirect harness.campaign.CAMPAIGNS to a tmp dir so tests never touch the real repo."""
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _routes(n: int = 5) -> str:
    return "\n".join(
        f"## Route {i}: lens {i}\n- Cheap falsification (≤ 10 min): try n <= 8\n- Credence: p_true=0.3 p_budget=0.2 (strategist) — guess"
        for i in range(1, n + 1)
    )


def _questions(n: int) -> str:
    return "\n".join(f"## Q-{i:03d}: why {i}?\n- Curiosity: 2/3\n- Status: open" for i in range(1, n + 1))


def _log_activity(round_dir: Path, roles=("skeptic", "falsifier", "novelty")) -> None:
    round_dir.mkdir(parents=True, exist_ok=True)
    with open(round_dir / "access.log", "a", encoding="utf-8") as fh:
        for role in roles:
            fh.write(json.dumps({"ts": "2020-01-01T00:00:00", "role": role, "tool": "Read",
                                 "decision": "allow", "target": "statement.md"}) + "\n")


NOVELTY_OK = "memo\n```yaml\nrole: novelty\nclaim: T-001\nround: 1\nverdict: pass\nclass: 1a\n```\n"


# ------------------------------------------------------------------- create --

def test_create_makes_expected_layout():
    path = campaign.create("demo", "Demo Campaign")
    assert path.exists()
    for sub in ("experiments", "proofs", "reviews", "paper", "cache"):
        assert (path / sub).is_dir()
    assert (path / "campaign.json").exists()
    assert (path / "ledger.json").exists()
    assert (path / "log.md").exists()
    assert (path / "ideas.md").exists()

    c = campaign.load("demo")
    assert c.slug == "demo"
    assert c.title == "Demo Campaign"
    assert c.phase == "bootstrap"
    assert c.phase_history[0]["phase"] == "bootstrap"
    assert c.phase_history[0]["exited"] is None


def test_create_twice_raises():
    campaign.create("demo", "Demo Campaign")
    with pytest.raises(campaign.CampaignError):
        campaign.create("demo", "Demo Campaign Again")


def test_create_ideas_skeleton_does_not_satisfy_route_criterion():
    path = campaign.create("demo", "Demo Campaign")
    ideas = (path / "ideas.md").read_text(encoding="utf-8")
    n_routes = sum(1 for line in ideas.splitlines() if line.startswith("## Route"))
    assert n_routes == 0  # skeleton must not accidentally satisfy the plan-phase gate


# -------------------------------------------------------------------- phase --

def test_set_phase_records_history():
    campaign.create("demo", "Demo Campaign")
    c = campaign.set_phase("demo", "scout")
    assert c.phase == "scout"
    assert c.phase_history[0]["exited"] is not None
    assert c.phase_history[-1]["phase"] == "scout"
    assert c.phase_history[-1]["exited"] is None


def test_set_phase_rejects_unknown_phase():
    campaign.create("demo", "Demo Campaign")
    with pytest.raises(campaign.CampaignError):
        campaign.set_phase("demo", "not-a-real-phase")


# ---------------------------------------------------------- statement lock --

def test_lock_statement_and_intact():
    path = campaign.create("demo", "Demo Campaign")
    _write(path / "statement.md", "Prove that P holds for all n.")

    c = campaign.lock_statement("demo")
    assert c.statement_hash is not None
    assert campaign.statement_intact("demo") is True

    _write(path / "statement.md", "Prove that P holds for all n (modified!).")
    assert campaign.statement_intact("demo") is False


def test_statement_intact_false_before_lock():
    path = campaign.create("demo", "Demo Campaign")
    _write(path / "statement.md", "Statement text.")
    assert campaign.statement_intact("demo") is False


def test_lock_statement_requires_file():
    campaign.create("demo", "Demo Campaign")
    with pytest.raises(campaign.CampaignError):
        campaign.lock_statement("demo")


# -------------------------------------------------------------- phase exit --

def test_check_phase_exit_bootstrap_has_no_criteria():
    campaign.create("demo", "Demo Campaign")
    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_scout():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "scout")

    unmet = campaign.check_phase_exit("demo")
    assert any("portfolio.md" in m for m in unmet)

    _write(path / "portfolio.md", "x" * 900)
    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_survey():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "survey")

    unmet = campaign.check_phase_exit("demo")
    assert len(unmet) >= 3

    _write(path / "survey.md", "x" * 2100)
    _write(
        path / "refs.bib",
        "@article{a2020,title={A}}\n@article{b2021,title={B}}\n@article{c2022,title={C}}\n",
    )
    store = LedgerStore(path / "ledger.json", campaign="demo")
    for i in range(3):
        _write(path / "cache" / f"src{i}.txt", "Lemma. " + "x" * 25 + " (see p. 3)")
        claim = store.add(kind="fact", statement=f"Known fact number {i}.")
        store.add_evidence(
            claim.id,
            Evidence(type="excerpt", source_id=f"src{i}", excerpt="x" * 25, summary="excerpt"),
            path,
        )
        store.promote(claim.id, "known-in-literature", path)

    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_survey_bib_needs_three_entries():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "survey")
    _write(path / "survey.md", "x" * 2100)
    _write(path / "refs.bib", "@article{a2020,title={A}}\n")
    unmet = campaign.check_phase_exit("demo")
    assert any("refs.bib" in m for m in unmet)


def test_check_phase_exit_plan():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "plan")

    unmet = campaign.check_phase_exit("demo")
    assert unmet  # nothing set up yet

    _write(path / "statement.md", "The target statement.")
    campaign.lock_statement("demo")
    _write(path / "plan.md", "x" * 1600)
    _write(path / "ideas.md", _routes(5))
    _write(path / "questions.md", _questions(3))

    _write(path / "experiments" / "statement_tests.py", "def test_def(): assert True")
    _write(path / "experiments" / "results.json", json.dumps({"statement_tests": {"passed": True, "n": 1}}))
    c = campaign.load("demo")
    c.budgets = {"max_review_rounds": 3, "hours_total": 40}
    campaign.save(c)

    store = LedgerStore(path / "ledger.json", campaign="demo")
    g = store.add(kind="target", statement="Target G.", status="conjectured")
    store.record_credence(g.id, role="strategist", why="test", p_true=0.4, p_budget=0.2)

    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_plan_statement_tampered_after_lock():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "plan")
    _write(path / "statement.md", "The target statement.")
    campaign.lock_statement("demo")
    _write(path / "plan.md", "x" * 1600)
    _write(path / "ideas.md", _routes(5))
    _write(path / "questions.md", _questions(3))
    _write(path / "experiments" / "statement_tests.py", "def test_def(): assert True")
    _write(path / "experiments" / "results.json", json.dumps({"statement_tests": {"passed": True, "n": 1}}))
    c = campaign.load("demo")
    c.budgets = {"max_review_rounds": 3, "hours_total": 40}
    campaign.save(c)
    store = LedgerStore(path / "ledger.json", campaign="demo")
    g = store.add(kind="target", statement="Target G.", status="conjectured")
    store.record_credence(g.id, role="strategist", why="test", p_true=0.4, p_budget=0.2)
    assert campaign.check_phase_exit("demo") == []

    _write(path / "statement.md", "The target statement, tampered.")
    unmet = campaign.check_phase_exit("demo")
    assert any("changed since it was locked" in m for m in unmet)


def test_check_phase_exit_plan_needs_five_routes():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "plan")
    _write(path / "statement.md", "The target statement.")
    campaign.lock_statement("demo")
    _write(path / "plan.md", "x" * 1600)
    _write(path / "ideas.md", _routes(4))
    _write(path / "questions.md", _questions(3))
    _write(path / "experiments" / "statement_tests.py", "def test_def(): assert True")
    _write(path / "experiments" / "results.json", json.dumps({"statement_tests": {"passed": True, "n": 1}}))
    c = campaign.load("demo")
    c.budgets = {"max_review_rounds": 3, "hours_total": 40}
    campaign.save(c)
    store = LedgerStore(path / "ledger.json", campaign="demo")
    g = store.add(kind="target", statement="Target G.", status="conjectured")
    store.record_credence(g.id, role="strategist", why="test", p_true=0.4, p_budget=0.2)

    unmet = campaign.check_phase_exit("demo")
    assert any("Route" in m for m in unmet)


def test_check_phase_exit_explore():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "explore")

    store = LedgerStore(path / "ledger.json", campaign="demo")
    claim = store.add(kind="conjecture", statement="Conjecture.", status="conjectured")

    unmet = campaign.check_phase_exit("demo")
    assert any("untested" in m for m in unmet)

    store.add_evidence(claim.id, Evidence(type="computation", summary="checked, no path needed for this rule"), path)
    _write(path / "experiments" / "results.json", "{}")
    unmet = campaign.check_phase_exit("demo")
    assert any("prediction/observation" in m for m in unmet)  # rule R6: predict before experimenting
    _write(path / "questions.md", "## Prediction: small cases\n- Predicted: 3\n- Observed: 3\n- Surprise: 1/3\n")

    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_prove():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "prove")

    store = LedgerStore(path / "ledger.json", campaign="demo")
    claim = store.add(kind="theorem", statement="Theorem.")

    unmet = campaign.check_phase_exit("demo")
    assert unmet

    _write(path / "proofs" / "thm.tex", "proof")
    store.add_evidence(claim.id, Evidence(type="proof", path="proofs/thm.tex", summary="draft"), path)
    store.promote(claim.id, "proof-drafted", path)

    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_review_full_pass():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "review")

    unmet = campaign.check_phase_exit("demo")
    assert any("no referee evidence" in m for m in unmet)

    store = LedgerStore(path / "ledger.json", campaign="demo")
    claim = store.add(kind="theorem", statement="Theorem.")
    _write(path / "proofs" / "thm.tex", "proof")
    store.add_evidence(claim.id, Evidence(type="proof", path="proofs/thm.tex", summary="draft"), path)
    store.promote(claim.id, "proof-drafted", path)
    for role in REFEREE_ROLES:
        store.add_evidence(claim.id, Evidence(type="referee", role=role, verdict="pass", round=1, summary="ok",
                                              agent_id="SK-1" if role == "skeptic" else None), path)
    store.add_evidence(claim.id, Evidence(type="referee", role="skeptic", verdict="pass", round=1, summary="ok", agent_id="SK-2"), path)

    unmet = campaign.check_phase_exit("demo")
    assert any("round1" in m for m in unmet)  # review files missing

    round_dir = path / "reviews" / "round1"
    B.open_round(path, 1, claim.id, ["proofs/thm.tex"], skeptics=1, stakes=0)
    for fname in ("skeptic.md", "falsifier.md"):
        _write(round_dir / fname, "notes")
    _write(round_dir / "novelty.md", NOVELTY_OK)
    _write(round_dir / "judge.md", "notes\n```yaml\nrole: judge\nclaim: T-001\nround: 1\nupheld: []\nrebutted: []\nmoot: []\nverdict: PASS\n```\nVERDICT: PASS\n")
    _log_activity(round_dir)

    # files present, but no claim referee-passed yet and judge.md has no PIVOT
    unmet = campaign.check_phase_exit("demo")
    assert unmet

    store.promote(claim.id, "referee-passed", path)
    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_review_pivot_path():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "review")

    store = LedgerStore(path / "ledger.json", campaign="demo")
    claim = store.add(kind="theorem", statement="Theorem.")
    store.add_evidence(
        claim.id, Evidence(type="referee", role="skeptic", verdict="fail", round=1, summary="flawed"), path
    )

    round_dir = path / "reviews" / "round1"
    _write(path / "proofs" / "thm.tex", "proof")
    B.open_round(path, 1, claim.id, ["proofs/thm.tex"], skeptics=1, stakes=0)
    for fname in ("skeptic.md", "falsifier.md"):
        _write(round_dir / fname, "notes")
    _write(round_dir / "novelty.md", NOVELTY_OK)
    _write(round_dir / "judge.md", "Some notes.\n```yaml\nrole: judge\nclaim: T-001\nround: 1\nupheld: []\nrebutted: []\nmoot: []\nverdict: PIVOT\n```\nVERDICT: PIVOT\n")
    _log_activity(round_dir)

    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_write():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "write")

    unmet = campaign.check_phase_exit("demo")
    assert unmet

    _write(path / "paper" / "main.tex", "\\documentclass{amsart}")
    (path / "paper" / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    _write(path / "paper" / "check.json", json.dumps({"ok": False}))

    unmet = campaign.check_phase_exit("demo")
    assert any("check.json" in m for m in unmet)

    _write(path / "paper" / "check.json", json.dumps({"ok": True}))
    assert campaign.check_phase_exit("demo") == []


def test_check_phase_exit_done():
    path = campaign.create("demo", "Demo Campaign")
    campaign.set_phase("demo", "done")

    unmet = campaign.check_phase_exit("demo")
    assert unmet

    c = campaign.load("demo")
    c.outcome_class = "negative"  # consistent with an empty ledger (outcome classes are validated)
    campaign.save(c)
    with open(path / "log.md", "a", encoding="utf-8") as fh:
        fh.write("\n## Outcome\n\nNegative result.\n" + "\n## Lessons\n- [phase=explore] greedy plateau was real — evidence: questions.md — moves: M61 — tags: evolve\n")

    assert campaign.check_phase_exit("demo") == []


# ---------------------------------------------------------------- reports ---

def test_status_report_contains_phase_and_summary():
    campaign.create("demo", "Demo Campaign")
    report = campaign.status_report("demo")
    assert "demo" in report
    assert "bootstrap" in report
    assert "Ledger summary" in report


# -------------------------------------------------------------------- CLI ---

def test_main_create_phase_and_check_cli():
    assert campaign.main(["create", "demo", "--title", "Demo Campaign"]) == 0
    assert campaign.main(["check", "demo"]) == 0  # bootstrap has no exit criteria

    assert campaign.main(["phase", "demo", "scout"]) == 0
    assert campaign.main(["check", "demo"]) == 1  # portfolio.md missing


def test_main_activate_and_active_cli():
    campaign.main(["create", "demo", "--title", "Demo Campaign"])
    assert campaign.main(["activate", "demo"]) == 0
    assert campaign.main(["active"]) == 0


def test_main_list_cli():
    campaign.main(["create", "demo1", "--title", "One"])
    campaign.main(["create", "demo2", "--title", "Two"])
    assert campaign.main(["list"]) == 0
