"""Tests for harness.review.verdict — referee/judge artifact parsers."""
from __future__ import annotations

from pathlib import Path

from harness.review import verdict as V

SKEPTIC = """# Skeptic report

| Step | Status | Justification checked | Witness (if FLAWED) |
|---|---|---|---|
| 1 | VERIFIED | definition D-001 matches statement.md | |
| 2 | OPEN | | |
| 3 | FLAWED (critical) | cited theorem needs S ⊂ R | hypothesis mismatch |
| Step 4 | FLAWED-gap | compactness not shown | K not compact |

```yaml
role: skeptic
claim: T-001
round: 2
verdict: fail
critical_errors:
  - step: 3
    witness: "hypothesis mismatch"
justification_gaps:
  - step: 4
    witness: "compactness of K not shown"
interpretation_issues: []
checked:
  - "All 4 steps processed"
confidence: 0.85
```
"""

NOVELTY = """# Novelty memo — T-001 — round 1

## Classification: 1(b)   (confidence 0.7)

```yaml
role: novelty-checker
claim: T-001
round: 1
verdict: pass
class: "1 (b)"
confidence: 0.7
```
"""

JUDGE = """# Judge

```yaml
role: judge
claim: T-001
round: 2
upheld:
  - {role: skeptic, agent_id: SK-1, step: 3}
rebutted: []
moot:
verdict: REVISE_PROOF
```

VERDICT: REVISE_PROOF
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_parse_verdict_block_and_validity():
    block = V.parse_verdict_block(SKEPTIC)
    assert block["role"] == "skeptic" and block["verdict"] == "fail" and block["claim"] == "T-001"
    assert block["critical_errors"][0]["step"] == 3
    assert V.verdict_block_looks_valid(block, "skeptic")
    assert not V.verdict_block_looks_valid(block, "falsifier")
    assert not V.verdict_block_looks_valid({"role": "skeptic", "claim": "T-001"})
    assert V.parse_verdict_block("no fences here") is None
    assert V.parse_verdict_blocks("```yaml\n- just\n- a list\n```") == []


def test_novelty_class_normalization():
    block = V.parse_verdict_block(NOVELTY)
    assert block["role"] == "novelty" and block["class"] == "1b"
    assert V.normalize_class("1a") == "1a" and V.normalize_class("class 1(d)") == "1d" and V.normalize_class("2a") is None


def test_judge_verdict_and_block():
    assert V.judge_verdict(JUDGE) == "REVISE_PROOF"
    assert V.judge_verdict("VERDICT: PASS\nVERDICT: PIVOT\n") == "PIVOT"
    assert V.judge_verdict("verdict: pass") is None
    jb = V.parse_judge_block(JUDGE)
    assert jb["verdict"] == "REVISE_PROOF" and jb["upheld"][0]["step"] == 3 and jb["moot"] == []
    assert V.verdict_block_looks_valid(jb)
    assert V.verdict_block_looks_valid({"role": "judge", "claim": "T-001", "verdict": "pass"})  # lowercase PASS ok
    assert not V.verdict_block_looks_valid({"role": "judge", "claim": "T-001", "verdict": "maybe"})


def test_parse_step_table():
    rows = V.parse_step_table(SKEPTIC)
    assert rows[1].status == "VERIFIED" and rows[2].status == "OPEN"
    assert rows[3].status == "FLAWED" and rows[3].severity == "critical" and rows[3].witness == "hypothesis mismatch"
    assert rows[4].status == "FLAWED" and rows[4].severity == "gap"
    dup = V.parse_step_table("| 1 | VERIFIED | a | |\n| 1 | FLAWED | b | w |\n")
    assert dup[1].status == "FLAWED"


def test_round_helpers(tmp_path):
    camp = tmp_path / "camp"
    assert V.latest_round(camp) is None and V.novelty_class(camp) is None
    _write(camp / "reviews" / "round1" / "novelty.md", NOVELTY)
    _write(camp / "reviews" / "round2" / "skeptic.md", SKEPTIC)
    _write(camp / "reviews" / "round2" / "skeptic.SK-2.md", SKEPTIC.replace("verdict: fail", "verdict: pass"))
    assert V.latest_round(camp) == 2
    assert V.novelty_class(camp) == "1b"
    assert V.novelty_class(camp, 2) is None
    reports = V.role_reports(camp / "reviews" / "round2", "skeptic")
    assert [p.name for p in reports] == ["skeptic.SK-2.md", "skeptic.md"]
    blocks = V.blocks_for_role(camp / "reviews" / "round2", "skeptic")
    assert sorted(b["verdict"] for b in blocks) == ["fail", "pass"]
    heading_only = "# memo\n\n## Classification: 1c\n"
    _write(camp / "reviews" / "round3" / "novelty.md", heading_only)
    assert V.novelty_class(camp) == "1c"


def test_step_of_and_iter_errors():
    assert V.step_of("Step 7") == 7 and V.step_of({"step": 3}) == 3 and V.step_of(None) is None
    errs = list(V.iter_errors({"critical_errors": ["step 2: bad", {"step": 5, "witness": "w"}]}))
    assert errs[0]["step"] == 2 and errs[1]["step"] == 5
