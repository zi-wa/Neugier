"""Round-2 Step 19: structured judge adjudication (Y3) and post-proof novelty re-check (Y4)."""
from __future__ import annotations

import json
from pathlib import Path

from harness.ledger.ledger import LedgerStore
from harness.review import barrier as B
from harness.review.adjudication import judge_consistency, reported_critical_errors
from harness.review.novelty_recheck import check_final_statement_queries, novelty_recheck, required_quantities
from harness.verify.exact import sha256_file

SKEPTIC = """```yaml
role: skeptic
claim: T-001
round: 1
agent_id: SK-1
verdict: fail
critical_errors:
  - step: 3
    witness: "hypothesis mismatch"
justification_gaps:
  - step: 5
    witness: "compactness not shown"
```
"""
FALSIFIER = """```yaml
role: falsifier
claim: T-001
round: 1
verdict: fail
critical_errors:
  - step: 7
    witness: "counterexample n=4"
```
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _judge(upheld="", rebutted="", moot="", verdict="REVISE_PROOF") -> str:
    return (f"# judge\n```yaml\nrole: judge\nclaim: T-001\nround: 1\nupheld: [{upheld}]\nrebutted: [{rebutted}]\n"
            f"moot: [{moot}]\nverdict: {verdict}\n```\n\nVERDICT: {verdict}\n")


def test_judge_consistency_rules(tmp_path):
    rdir = tmp_path / "reviews" / "round1"
    _write(rdir / "skeptic.SK-1.md", SKEPTIC)
    _write(rdir / "falsifier.md", FALSIFIER)
    errs = reported_critical_errors(rdir)
    assert {(e["role"], e["step"]) for e in errs} == {("skeptic", 3), ("falsifier", 7)}
    assert judge_consistency(rdir, {}, "no block\nVERDICT: PASS\n")[0].startswith("judge.md lacks")
    problems = judge_consistency(rdir, {}, _judge(upheld="{role: skeptic, agent_id: SK-1, step: 3}"))
    assert any("falsifier" in p and "step 7" in p for p in problems)
    problems = judge_consistency(rdir, {}, _judge(upheld="{role: skeptic, step: 3}", moot="{role: falsifier, step: 7, reason: x}"))
    assert any("marked moot" in p for p in problems)
    ok = _judge(upheld="{role: skeptic, step: 3}, {role: falsifier, step: 7}")
    assert judge_consistency(rdir, {}, ok) == []
    assert any("PASS cannot coexist" in p for p in judge_consistency(rdir, {}, _judge(upheld="{role: skeptic, step: 3}, {role: falsifier, step: 7}", verdict="PASS")))
    mismatch = ok.replace("VERDICT: REVISE_PROOF", "VERDICT: PIVOT")
    assert any("disagrees" in p for p in judge_consistency(rdir, {}, mismatch))
    # rebuttals need a long quote that occurs in response.md
    short = _judge(upheld="{role: falsifier, step: 7}", rebutted="{role: skeptic, step: 3, quote: too short}")
    assert any("at least 40" in p for p in judge_consistency(rdir, {}, short))
    quote = "The hypothesis S subset of R is satisfied because Step 2 embeds S into the reals explicitly."
    reb = _judge(upheld="{role: falsifier, step: 7}", rebutted="{role: skeptic, step: 3, quote: \"" + quote + "\"}")
    assert any("response.md does not exist" in p for p in judge_consistency(rdir, {}, reb))
    _write(rdir / "response.md", "Reply.\n\n" + quote + "\n")
    assert judge_consistency(rdir, {}, reb) == []
    _write(rdir / "response.md", "Reply with different text.\n")
    assert any("does not occur" in p for p in judge_consistency(rdir, {}, reb))
    # inadmissible skeptic verdicts are ignored
    _write(rdir / "lineup_score.SK-1.json", json.dumps({"agent_id": "SK-1", "admissible": False}))
    assert {(e["role"], e["step"]) for e in reported_critical_errors(rdir)} == {("falsifier", 7)}


def test_final_statement_recheck(tmp_path):
    d = tmp_path / "camp"
    _write(d / "campaign.json", json.dumps({"slug": "camp", "budgets": {"max_review_rounds": 3}}))
    _write(d / "statement.md", "S.")
    _write(d / "experiments" / "results.json", json.dumps({"best_bound": {"value": "29/100", "source": "x.py"}, "n_max": 5000}))
    proof = "---\nclaim: T-001\nstatement: S\nnumerics: [results.json#best_bound, results.json#n_max]\n---\n## Proof\n**Step 1.** (algebra) x.\n"
    _write(d / "proofs" / "T-001.md", proof)
    store = LedgerStore(d / "ledger.json", campaign="camp")
    store.add(kind="theorem", statement="T.", stakes=2)
    q = required_quantities(d, "proofs/T-001.md")
    assert "29/100" in q and "0.29" in q and "5000" in q
    memo_no_section = "```yaml\nrole: novelty\nclaim: T-001\nverdict: pass\nclass: 1a\n```\n"
    assert check_final_statement_queries(memo_no_section, q)[0].startswith("novelty memo has no")
    memo = ("# memo\n## Final-statement queries\n- \"sum-free\" 0.29 density bound\n- sumset 29/100 lower bound\n- Sidon 5000 plateau\n"
            "## Classification: 1a\n```yaml\nrole: novelty\nclaim: T-001\nverdict: pass\nclass: 1a\nartifact_sha256: {sha}\n```\n")
    assert check_final_statement_queries(memo.format(sha="x"), q) == []
    two = memo.replace("- Sidon 5000 plateau\n", "")
    assert any("need at least 3" in p for p in check_final_statement_queries(two.format(sha="x"), q))
    B.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=1)
    manifest = B.load_manifest(d, 1)
    assert manifest["regime"]["final_statement_recheck"] is True
    rdir = d / "reviews" / "round1"
    _write(rdir / "novelty.md", memo.format(sha="deadbeef"))
    problems = novelty_recheck(d, 1, manifest, required=True)
    assert any("does not match" in p for p in problems)
    _write(rdir / "novelty.md", memo.format(sha=sha256_file(d / "proofs" / "T-001.md")))
    assert novelty_recheck(d, 1, manifest, required=True) == []
    assert novelty_recheck(d, 1, manifest, required=False) == []
    # check_round includes the re-check for tier 2
    _write(rdir / "novelty.md", memo_no_section)
    with open(rdir / "access.log", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2020-01-01T00:00:00", "role": "novelty", "tool": "Read", "decision": "allow", "target": "statement.md"}) + "\n")
    problems = B.check_round(d, 1, store)
    assert any("final-statement re-check" in p for p in problems)
    # judge consistency is part of check_round
    _write(rdir / "skeptic.SK-1.md", SKEPTIC)
    with open(rdir / "access.log", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2020-01-01T00:00:01", "role": "skeptic:SK-1", "tool": "Read", "decision": "allow", "target": "statement.md"}) + "\n")
    _write(rdir / "judge.md", _judge(verdict="PASS"))
    problems = B.check_round(d, 1, store)
    assert any("neither upheld nor rebutted" in p for p in problems)
