"""Round-2 Step 22: pre-registered credences and calibration (X2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
import harness.ledger.cli as ledger_cli
from harness.ledger import calibration as C
from harness.ledger.ledger import LedgerError, LedgerStore
from harness.ledger.schema import Evidence
from harness.library import memory
from harness.questions import calibration_warning, next_actions, parse_questions


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(ledger_cli, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_record_credence_validation_and_history(tmp_path):
    d = tmp_path / "camp"
    d.mkdir()
    store = LedgerStore(d / "ledger.json", campaign="camp")
    c = store.add(kind="conjecture", statement="C.", status="conjectured")
    with pytest.raises(LedgerError, match="at least one"):
        store.record_credence(c.id, role="strategist", why="x")
    with pytest.raises(LedgerError, match="within"):
        store.record_credence(c.id, role="strategist", why="x", p_true=1.5)
    with pytest.raises(LedgerError, match="--why"):
        store.record_credence(c.id, role="strategist", why="  ", p_true=0.5)
    with pytest.raises(LedgerError, match="--round"):
        store.record_credence(c.id, role="prover", why="x", p_pass=0.5)
    entry = store.record_credence(c.id, role="strategist", why="small cases look right", p_true=0.35, p_budget=0.2,
                                  panel={"skeptic": 0.2, "optimist": 0.6, "base-rate": 0.3})
    assert entry["op"] == "credence" and entry["spread"] == pytest.approx(0.4)
    assert store.latest_credence(c.id)["p_true"] == 0.35
    assert store.uncredenced() == []
    other = store.add(kind="bound", statement="B.", status="conjectured")
    assert store.uncredenced() == [other.id]
    assert store.summary()["credences"] == {c.id: 0.35}
    assert "0.35" in store.to_markdown()
    audit = (d / "ledger.audit.jsonl").read_text(encoding="utf-8")
    assert '"op": "credence"' in audit


def test_calibration_brier_by_role_and_field_and_library(tmp_path):
    d = tmp_path / "camp"
    d.mkdir()
    store = LedgerStore(d / "ledger.json", campaign="camp")
    ok = store.add(kind="theorem", statement="T.", status="conjectured")
    bad = store.add(kind="conjecture", statement="C.", status="conjectured")
    store.record_credence(ok.id, role="strategist", why="x", p_true=0.8, p_budget=0.6)
    store.record_credence(bad.id, role="strategist", why="x", p_true=0.7)
    store.record_credence(bad.id, role="experimentalist", why="x", p_true=0.2)
    _write(d / "experiments" / "cex.json", "{}")
    store.add_evidence(bad.id, Evidence(type="falsification", path="experiments/cex.json"), d)
    store.promote(bad.id, "refuted", d)
    _write(d / "proofs" / f"{ok.id}.md", "**Step 1.** (algebra) x.")
    store.add_evidence(ok.id, Evidence(type="proof", path=f"proofs/{ok.id}.md"), d)
    store.promote(ok.id, "proof-drafted", d)
    store.record_credence(ok.id, role="prover", why="x", p_pass=0.9, round=1)
    for role in ("skeptic", "falsifier", "novelty", "replicator", "judge"):
        store.add_evidence(ok.id, Evidence(type="referee", role=role, verdict="pass", round=1, agent_id="SK-1" if role == "skeptic" else None), d)
    store.add_evidence(ok.id, Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-2"), d)
    store.promote(ok.id, "referee-passed", d)

    rep = C.compute(store, "camp")
    briers = {(r.claim_id, r.role, r.field): r.brier for r in rep.rows}
    assert briers[(ok.id, "strategist", "p_true")] == pytest.approx((0.8 - 1) ** 2, abs=1e-4)
    assert briers[(ok.id, "strategist", "p_budget")] == pytest.approx((0.6 - 1) ** 2, abs=1e-4)
    assert briers[(bad.id, "strategist", "p_true")] == pytest.approx(0.49, abs=1e-4)
    assert briers[(bad.id, "experimentalist", "p_true")] == pytest.approx(0.04, abs=1e-4)
    assert briers[(ok.id, "prover", "p_pass")] == pytest.approx(0.01, abs=1e-4)
    assert rep.by_role["experimentalist"].brier == pytest.approx(0.04) and rep.by_field["p_pass"].n == 1
    C.write_report(d, rep)
    assert json.loads((d / "calibration.json").read_text(encoding="utf-8"))["n"] == rep.n
    # unresolved claims count only as p_budget=0 under --final
    pending = store.add(kind="conjecture", statement="P.", status="conjectured")
    store.record_credence(pending.id, role="strategist", why="x", p_true=0.5, p_budget=0.9)
    assert not any(r.claim_id == pending.id for r in C.compute(store, "camp").rows)
    final = C.compute(store, "camp", final=True)
    assert any(r.claim_id == pending.id and r.field == "p_budget" and r.outcome == 0 for r in final.rows)
    n = C.append_to_library(final)
    assert n >= 3 and memory.role_brier("strategist")["n"] == 2 and memory.role_brier("strategist", "p_budget")["n"] == 2
    assert memory.role_brier("nobody") == {"n": 0, "brier": None}


def test_cli_credence_and_calibration(tmp_path, capsys):
    d = tmp_path / "campaigns" / "demo"
    d.mkdir(parents=True)
    assert ledger_cli.main(["--campaign", "demo", "init"]) == 0
    assert ledger_cli.main(["--campaign", "demo", "add", "--kind", "conjecture", "--statement", "C.", "--status", "conjectured"]) == 0
    capsys.readouterr()
    assert ledger_cli.main(["--campaign", "demo", "credence", "C-001", "--p-true", "0.3", "--p-budget", "0.1", "--why", "guess",
                            "--role", "strategist", "--panel", "skeptic=0.1,optimist=0.5"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["spread"] == pytest.approx(0.4)
    assert ledger_cli.main(["--campaign", "demo", "credence", "C-001", "--p-true", "2", "--why", "x", "--role", "r"]) == 1
    assert ledger_cli.main(["--campaign", "demo", "calibration"]) == 0
    assert json.loads(capsys.readouterr().out)["n"] == 0
    assert (d / "calibration.json").exists()


def test_plan_gate_requires_credences_and_finish_appends_calibration():
    path = campaign.create("demo", "Demo")
    campaign.set_phase("demo", "plan")
    _write(path / "statement.md", "S.")
    campaign.lock_statement("demo")
    _write(path / "plan.md", "x" * 1600)
    _write(path / "ideas.md", "\n".join(f"## Route {i}: lens {i}" for i in range(1, 6)))
    _write(path / "questions.md", "\n".join(f"## Q-{i:03d}: why?\n- Status: open" for i in range(1, 4)))
    _write(path / "experiments" / "statement_tests.py", "def test_def(): assert True")
    _write(path / "experiments" / "results.json", json.dumps({"statement_tests": {"passed": True}}))
    c = campaign.load("demo")
    c.budgets = {"hours_total": 10}
    campaign.save(c)
    store = LedgerStore(path / "ledger.json", campaign="demo")
    g = store.add(kind="target", statement="G.", status="conjectured")
    unmet = campaign.check_phase_exit("demo")
    assert any("without p_true" in m for m in unmet) and any("routes without" in m for m in unmet)
    store.record_credence(g.id, role="strategist", why="x", p_true=0.4, p_budget=0.3)
    _write(path / "ideas.md", "\n".join(f"## Route {i}: lens {i}\n- Credence: p_true=0.2 (strategist) — why" for i in range(1, 6)))
    assert campaign.check_phase_exit("demo") == []
    report = campaign.status_report("demo")
    assert "## Calibration" in report
    with open(path / "log.md", "a", encoding="utf-8") as fh:
        fh.write("\n## Outcome\nnegative\n" + "\n## Lessons\n- [phase=explore] greedy plateau was real — evidence: questions.md — moves: M61 — tags: evolve\n")
    summary = campaign.finish("demo", outcome="negative")
    assert summary["calibration_rows"] >= 1 and (path / "calibration.json").exists()
    assert memory.all("calibration")


def test_questions_next_warns_on_poorly_calibrated_role():
    for _ in range(3):
        memory.add_calibration("old", "experimentalist", "p_true", 4, 0.4, 0.8, 0.2)
    assert calibration_warning("experimentalist") and "Brier 0.4" in calibration_warning("experimentalist")
    assert calibration_warning("strategist") is None
    doc = parse_questions("## Q-001: why?\n- Curiosity: 3/3\n- Cheapest test: x (5 min)\n- Raised by: experimentalist, 2026-09-04, explore\n- Status: open\n")
    out = next_actions(doc, None)
    assert out["warnings"] and out["next"][0]["calibration_warning"]
