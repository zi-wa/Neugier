"""Round-2 Step 20: pre-registered marking schemes (Y2) and technique pitfalls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
from harness.ledger.ledger import LedgerStore
from harness.proof.lint import lint_proof
from harness.review import rubric as R

RUBRIC = """---
claim: T-001
technique: [extremal, double-counting]
required_hypotheses: [finite, "|S| >= 2"]
must_establish:
  - "the compression map does not increase |S+S|"
  - "equality holds only for arithmetic progressions"
hard_step: "compression preserves the sumset bound"
version: 1
---
## Marking scheme
- M1: the proof exhibits 2|S|-1 distinct sums explicitly.
- M2: the equality case is characterized.

## Pitfalls
- extremal: the extremal object exists (finite search space).
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")


def test_pitfalls_doc_tags_and_extraction():
    tags = R.technique_tags()
    assert {"induction", "compactness-limits", "probabilistic-method", "quantifier-order", "case-analysis", "extremal",
            "polynomial-method", "double-counting", "asymptotics", "density-increment", "computation-certificate"} <= set(tags)
    text = R.pitfalls_for(["induction", "nope"])
    assert text.startswith("## induction") and "Witness shape" in text and "nope" not in text


def test_parse_and_lint_rubric(tmp_path):
    p = _write(tmp_path / "T-001.rubric.md", RUBRIC)
    r = R.parse_rubric(p)
    assert r.claim == "T-001" and r.technique == ["extremal", "double-counting"] and r.required_hypotheses == ["finite", "|S| >= 2"]
    assert len(r.must_establish) == 2 and "M1" in r.marking_scheme and "extremal" in r.pitfalls
    assert R.lint_rubric(p) == []
    bad = RUBRIC.replace("technique: [extremal, double-counting]", "technique: [vibes]").replace("- M1:", "- M1: we believe the route via compression should work;")
    problems = R.lint_rubric(_write(p, bad))
    assert any("unknown technique" in x for x in problems) and any("priming" in x for x in problems)
    with pytest.raises(R.RubricError):
        R.parse_rubric(_write(p, "no frontmatter"))
    assert R.lint_rubric(_write(p, RUBRIC.replace("## Marking scheme", "## Grading")))[0].startswith("rubric needs")


def test_check_rubric_against_proof(tmp_path):
    r = R.parse_rubric(_write(tmp_path / "T-001.rubric.md", RUBRIC))
    ok = R.check_rubric_against_proof(r, {"uses_hypotheses": ["finite", "|S|>=2"], "technique": ["extremal"]})
    assert ok == []
    warns = R.check_rubric_against_proof(r, {"uses_hypotheses": ["finite"], "technique": ["fourier"]})
    assert any(w.startswith("W_RUBRIC_HYP_UNUSED") for w in warns) and any(w.startswith("W_RUBRIC_TECHNIQUE_DRIFT") for w in warns)


def test_lock_freezes_rubrics_and_plan_gate_requires_them():
    path = campaign.create("demo", "Demo")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    t = store.add(kind="target", statement="G.", status="conjectured")
    campaign.set_targets("demo", [t.id])
    campaign.set_phase("demo", "plan")
    _write(path / "statement.md", "S.")
    _write(path / "plan.md", "x" * 1600)
    _write(path / "ideas.md", "\n".join(f"## Route {i}: lens {i}" for i in range(1, 6)))
    _write(path / "questions.md", "\n".join(f"## Q-{i:03d}: why?\n- Status: open" for i in range(1, 4)))
    _write(path / "experiments" / "statement_tests.py", "def test_def(): assert True")
    _write(path / "experiments" / "results.json", json.dumps({"statement_tests": {"passed": True}}))
    campaign.lock_statement("demo")
    c = campaign.load("demo")
    c.budgets = {"hours_total": 10}
    campaign.save(c)
    unmet = campaign.check_phase_exit("demo")
    assert any("no pre-registered marking scheme" in m for m in unmet)
    _write(path / "proofs" / f"{t.id}.rubric.md", RUBRIC.replace("claim: T-001", f"claim: {t.id}"))
    unmet = campaign.check_phase_exit("demo")
    assert any("not frozen" in m for m in unmet)
    campaign.lock_statement("demo")
    assert t.id in campaign.load("demo").rubric_hashes
    assert campaign.check_phase_exit("demo") == []
    # editing a frozen rubric is detected
    _write(path / "proofs" / f"{t.id}.rubric.md", RUBRIC.replace("claim: T-001", f"claim: {t.id}") + "\n- extra\n")
    assert any("rubric.md" in x for x in campaign.frozen_changed("demo"))
    assert any("frozen files changed" in m for m in campaign.check_phase_exit("demo"))


def test_add_rubric_hash_refuses_after_proof_exists_and_cli():
    path = campaign.create("demo", "Demo")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    lem = store.add(kind="lemma", statement="L.")
    with pytest.raises(campaign.CampaignError, match="not found"):
        campaign.add_rubric_hash("demo", lem.id)
    _write(path / "proofs" / f"{lem.id}.rubric.md", RUBRIC.replace("claim: T-001", f"claim: {lem.id}"))
    assert campaign.main(["add-rubric-hash", "demo", lem.id]) == 0
    assert lem.id in campaign.load("demo").rubric_hashes
    _write(path / "proofs" / f"{lem.id}.md", "**Step 1.** (algebra) x.")
    with pytest.raises(campaign.CampaignError, match="already exists"):
        campaign.add_rubric_hash("demo", lem.id)
    assert campaign.main(["targets", "demo", "--set", lem.id]) == 0
    assert campaign.main(["targets", "demo", "--set", "Z-999"]) == 1


def test_proof_lint_reports_rubric_drift(tmp_path):
    path = campaign.create("demo", "Demo")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    thm = store.add(kind="theorem", statement="T.")
    _write(path / "proofs" / f"{thm.id}.rubric.md", RUBRIC.replace("claim: T-001", f"claim: {thm.id}"))
    proof = f"""---
claim: {thm.id}
statement: "T."
depends_on: []
assumes: []
uses_hypotheses: [finite]
numerics: []
version: 1
technique: [fourier]
---
## Proof
**Step 1.** <key-original-step> idea </key-original-step>
**Conclusion.** done.
## Edge cases checked
- none
## Self-check log
- Hypothesis use: finite → Step 1.
"""
    rep = lint_proof(_write(path / "proofs" / f"{thm.id}.md", proof), path, store)
    codes = {w.code for w in rep.warnings}
    assert "W_RUBRIC_HYP_UNUSED" in codes and "W_RUBRIC_TECHNIQUE_DRIFT" in codes
