"""Round-1 Step 3 / Round-2 campaign rules: typed budgets, overrun notes, statement tests,
rejected-topic checks, outcome validation, frozen files."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence
from harness.library import memory

ROLES = ("skeptic", "falsifier", "novelty", "replicator", "judge")
PRED = "## Prediction: small cases\n- Predicted: 3\n- Observed: 3\n- Surprise: 1/3\n"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _plan_ready(path: Path) -> None:
    _write(path / "statement.md", "The target statement.")
    campaign.lock_statement("demo")
    _write(path / "plan.md", "x" * 1600)
    _write(path / "ideas.md", "\n".join(f"## Route {i}: lens {i}" for i in range(1, 6)))
    _write(path / "questions.md", "\n".join(f"## Q-{i:03d}: why?\n- Status: open" for i in range(1, 4)))
    _write(path / "experiments" / "statement_tests.py", "def test_def(): assert True\n")
    _write(path / "experiments" / "results.json", json.dumps({"statement_tests": {"passed": True, "n": 1}}))
    c = campaign.load("demo")
    c.budgets = {"max_review_rounds": 3, "hours_total": 40}
    campaign.save(c)
    LedgerStore(path / "ledger.json", campaign="demo").add(kind="target", statement="G.", status="conjectured")


def _referee_pass(store: LedgerStore, cid: str, path: Path, round_: int = 1) -> None:
    for role in ROLES:
        store.add_evidence(cid, Evidence(type="referee", role=role, verdict="pass", round=round_), path)


def _proof_drafted(store: LedgerStore, cid: str, path: Path) -> None:
    _write(path / "proofs" / f"{cid}.md", "**Step 1.** (algebra) x.")
    store.add_evidence(cid, Evidence(type="proof", path=f"proofs/{cid}.md"), path)
    store.promote(cid, "proof-drafted", path)


# ------------------------------------------------------------------ budgets --

def test_budgets_are_typed_and_coerced():
    campaign.create("demo", "Demo", {"hours_total": 12, "hours_per_phase": {"explore": 4}, "custom_key": 1})
    c = campaign.load("demo")
    assert isinstance(c.budgets, campaign.Budgets)
    assert c.budgets.max_review_rounds == 3 and c.budgets.skeptic_passes == 2 and c.budgets.human_interrupts == 3
    assert c.budgets.model_dump()["custom_key"] == 1
    c.budgets = {"max_review_rounds": 5}
    assert c.budgets.max_review_rounds == 5


def test_phase_hours_and_overrun_gate():
    path = campaign.create("demo", "Demo", {"hours_per_phase": {"explore": 1.0}})
    campaign.set_phase("demo", "explore")
    c = campaign.load("demo")
    start = datetime.now(timezone.utc) - timedelta(hours=3)
    c.phase_history[-1]["entered"] = start.isoformat()
    campaign.save(c)
    report = campaign.budget_report(campaign.load("demo"))
    assert report["phases"]["explore"]["over"] is True and report["phases"]["explore"]["spent_hours"] >= 2.9
    store = LedgerStore(path / "ledger.json", campaign="demo")
    _write(path / "experiments" / "results.json", "{}")
    _write(path / "questions.md", PRED)
    unmet = campaign.check_phase_exit("demo")
    assert any("Budget overrun" in m for m in unmet)
    with open(path / "log.md", "a", encoding="utf-8") as fh:
        fh.write("\n## Budget overrun (explore)\nThe evolutionary run needed one more generation.\n")
    assert campaign.check_phase_exit("demo") == []
    del store


def test_budget_cli_set_and_report(capsys):
    campaign.create("demo", "Demo")
    assert campaign.main(["budget", "demo", "--set", "hours_total=20", "--set", "hours_per_phase.prove=6"]) == 0
    c = campaign.load("demo")
    assert c.budgets.hours_total == 20 and c.budgets.hours_per_phase["prove"] == 6.0
    out = json.loads(capsys.readouterr().out)
    assert out["total"]["budget_hours"] == 20


# --------------------------------------------------------------------- plan --

def test_plan_gate_requires_statement_tests_and_hours():
    path = campaign.create("demo", "Demo")
    campaign.set_phase("demo", "plan")
    _plan_ready(path)
    assert campaign.check_phase_exit("demo") == []
    _write(path / "experiments" / "results.json", json.dumps({"statement_tests": {"passed": False}}))
    unmet = campaign.check_phase_exit("demo")
    assert any("statement tests" in m for m in unmet)
    (path / "experiments" / "statement_tests.py").unlink()
    assert any("statement_tests.py" in m for m in campaign.check_phase_exit("demo"))
    c = campaign.load("demo")
    c.budgets = {"max_review_rounds": 3}
    campaign.save(c)
    assert any("hours_total" in m for m in campaign.check_phase_exit("demo"))


# -------------------------------------------------------------- rejected --

def test_create_refuses_rejected_title_unless_allowed():
    memory.add_rejected("Sum-free subsets of abelian groups", "known result (Green-Ruzsa)")
    with pytest.raises(campaign.CampaignError, match="rejected"):
        campaign.create("demo", "Sum-free subsets of abelian groups")
    campaign.create("demo", "Sum-free subsets of abelian groups", allow_rejected=True)
    assert campaign.main(["create", "demo2", "--title", "Sum-free subsets of abelian groups"]) == 1
    assert campaign.main(["create", "demo3", "--title", "Sum-free subsets of abelian groups", "--allow-rejected"]) == 0


def test_scout_gate_checks_selected_target_against_library():
    path = campaign.create("demo", "Demo")
    campaign.set_phase("demo", "scout")
    memory.add_rejected("Erdős distinct distances in the plane", "solved by Guth-Katz")
    body = "# Portfolio\n## Harvest\n" + "x" * 900 + "\n## Selected target\n- Statement (informal): Erdős distinct distances in the plane\n"
    _write(path / "portfolio.md", body)
    unmet = campaign.check_phase_exit("demo")
    assert any("rejected topic" in m for m in unmet)
    _write(path / "portfolio.md", body + "- Rejected-override: the 2010 result leaves the constant open\n")
    assert campaign.check_phase_exit("demo") == []
    assert campaign.selected_target_statement(path) == "Erdős distinct distances in the plane"


# ------------------------------------------------------------------ outcome --

def test_outcome_validation_rules():
    path = campaign.create("demo", "Demo")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    assert campaign.validate_outcome("demo", None) == ["outcome_class is not set"]
    assert campaign.validate_outcome("demo", "negative") == []
    assert campaign.validate_outcome("demo", "autonomous-new-result")  # nothing proved
    thm = store.add(kind="theorem", statement="T.")
    _proof_drafted(store, thm.id, path)
    _referee_pass(store, thm.id, path)
    store.promote(thm.id, "referee-passed", path)
    problems = campaign.validate_outcome("demo", "autonomous-new-result")
    assert problems and "novelty memo" in problems[0]
    _write(path / "reviews" / "round1" / "novelty.md", "```yaml\nrole: novelty\nclaim: T-001\nverdict: pass\nclass: 1c\n```\n")
    assert any("1c" in p for p in campaign.validate_outcome("demo", "autonomous-new-result"))
    assert any("1c" in p for p in campaign.validate_outcome("demo", "partial"))
    assert campaign.validate_outcome("demo", "rediscovery") == []
    assert campaign.validate_outcome("demo", "literature-find") == []
    _write(path / "reviews" / "round1" / "novelty.md", "```yaml\nrole: novelty\nclaim: T-001\nverdict: pass\nclass: 1a\n```\n")
    assert campaign.validate_outcome("demo", "autonomous-new-result") == []
    assert campaign.validate_outcome("demo", "negative")  # something is proved
    _write(path / "reviews" / "round2" / "novelty.md", "```yaml\nrole: novelty\nclaim: T-001\nverdict: pass\nclass: 1d\n```\n")
    assert any("1d" in p for p in campaign.validate_outcome("demo", "rediscovery"))
    with pytest.raises(campaign.CampaignError):
        campaign.set_outcome("demo", "autonomous-new-result")
    assert campaign.main(["outcome", "demo", "literature-find"]) == 0
    assert campaign.load("demo").outcome_class == "literature-find"


def test_done_gate_revalidates_outcome():
    path = campaign.create("demo", "Demo")
    campaign.set_phase("demo", "done")
    c = campaign.load("demo")
    c.outcome_class = "autonomous-new-result"
    campaign.save(c)
    with open(path / "log.md", "a", encoding="utf-8") as fh:
        fh.write("\n## Outcome\nnothing\n")
    unmet = campaign.check_phase_exit("demo")
    assert any("autonomous-new-result requires" in m for m in unmet)


# ------------------------------------------------------------------- freeze --

def test_freeze_detects_edits_and_lock_freezes_statement():
    path = campaign.create("demo", "Demo")
    _write(path / "experiments" / "scorer.py", "def score(x): return 1\n")
    campaign.freeze("demo", ["experiments/scorer.py"])
    assert campaign.frozen_changed("demo") == []
    _write(path / "experiments" / "scorer.py", "def score(x): return 2\n")
    assert campaign.frozen_changed("demo") == ["experiments/scorer.py"]
    campaign.set_phase("demo", "explore")
    _write(path / "experiments" / "results.json", "{}")
    _write(path / "questions.md", PRED)
    assert any("frozen files changed" in m for m in campaign.check_phase_exit("demo"))
    campaign.unfreeze("demo", ["experiments/scorer.py"])
    assert campaign.check_phase_exit("demo") == []
    _write(path / "statement.md", "S.")
    campaign.lock_statement("demo")
    assert "statement.md" in campaign.load("demo").frozen
    with pytest.raises(campaign.CampaignError):
        campaign.unfreeze("demo", ["statement.md"])
    with pytest.raises(campaign.CampaignError):
        campaign.freeze("demo", ["experiments/missing.py"])
    assert campaign.main(["freeze", "demo", "experiments/scorer.py"]) == 0
    report = campaign.status_report("demo")
    assert "## Frozen files" in report and "## Budgets" in report


def test_review_gate_round_cap_and_globbed_files():
    path = campaign.create("demo", "Demo", {"max_review_rounds": 1})
    campaign.set_phase("demo", "review")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    thm = store.add(kind="theorem", statement="T.")
    _proof_drafted(store, thm.id, path)
    store.add_evidence(thm.id, Evidence(type="referee", role="skeptic", verdict="fail", round=1, agent_id="SK-1"), path)
    for f in ("skeptic.SK-1.md", "falsifier.md", "novelty.md", "judge.md"):
        _write(path / "reviews" / "round1" / f, "notes\n")
    unmet = campaign.check_phase_exit("demo")
    assert not any("skeptic.md does not exist" in m for m in unmet)
    assert any("last budgeted round" in m for m in unmet)
