"""Round-2 Step 21: the decoy lineup — mutation operators, sealing, scoring, gating."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

import harness
import harness.review.cli as review_cli
from harness.ledger.ledger import LedgerError, LedgerStore
from harness.ledger.schema import Evidence
from harness.proof.lint import parse_proof
from harness.review import barrier as B
from harness.review import lineup as L

PROOF = """---
claim: T-001
statement: "For every finite S, |S+S| >= 2|S|-1."
depends_on: [F-001]
assumes: []
uses_hypotheses: [finite, "|S|>=2"]
numerics: []
version: 1
technique: [extremal]
---

## Proof

**Setup.** Let S be a finite set of integers with |S| >= 2.

**Step 1.** (definition D-001) S+S = {a+b : a, b in S}.
**Step 2.** (hypothesis) S is finite and |S| >= 2, so for every s in S the values min S and max S exist and differ.
**Step 3.** <cite id="Ruzsa1994" claim="F-001" excerpt-hash="abcdef123456"> Cauchy-Davenport gives |S+S| >= 2|S|-1 for finite S with |S| >= 2; both hypotheses hold by assumption since S is finite. </cite>
**Step 4.** <key-original-step> Translate S so min S = 0; the new idea is the compression map. </key-original-step>
**Step 5.** (Steps 2, 4) The 2|S|-1 sums min+s and s+max are distinct except for min+max.
**Conclusion.** |S+S| >= 2|S|-1.

## Edge cases checked
- |S| = 2: S+S has exactly 3 elements.
- S an arithmetic progression: equality.

## Self-check log
- Hypothesis use: finite → Step 2; |S|>=2 → Step 2.
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _camp(tmp_path: Path, budgets: dict | None = None) -> Path:
    d = tmp_path / "campaigns" / "demo"
    d.mkdir(parents=True)
    _write(d / "campaign.json", json.dumps({"slug": "demo", "budgets": budgets or {"max_review_rounds": 3, "decoys_per_round": 2}}))
    _write(d / "statement.md", "S.")
    _write(d / "proofs" / "T-001.md", PROOF)
    LedgerStore(d / "ledger.json", campaign="demo").add(kind="theorem", statement="T.")
    return d


def _steps(text: str) -> dict[int, str]:
    return {s.n: s.text for s in parse_proof(text).steps}


def _verdict(item: str, verdict: str, errors: list[tuple[int | None, str]] = (), gaps: list[tuple[int | None, str]] = ()) -> str:
    lines = [f"```yaml", "role: skeptic", "claim: T-001", "round: 1", f"item: {item}", f"verdict: {verdict}", "critical_errors:"]
    for step, w in errors:
        lines.append(f"  - step: {step}" if step is not None else "  - step: null")
        lines.append(f'    witness: "{w}"')
    if not errors:
        lines[-1] = "critical_errors: []"
    lines.append("justification_gaps:")
    for step, w in gaps:
        lines.append(f"  - step: {step}")
        lines.append(f'    witness: "{w}"')
    if not gaps:
        lines[-1] = "justification_gaps: []"
    lines += ["checked:", "  - all steps", "```", ""]
    return "\n".join(lines)


# ------------------------------------------------------------ operators --

@pytest.mark.parametrize("op", sorted(L.DETERMINISTIC_OPS))
def test_each_operator_changes_only_its_target(op):
    mutated, mut = L.apply_op(PROOF, op, random.Random(1))
    assert mutated != PROOF and mut.op == op and mut.expected_witness_keywords
    before, after = _steps(PROOF), _steps(mutated)
    assert parse_proof(mutated).frontmatter == parse_proof(PROOF).frontmatter
    changed = [n for n in before if before[n] != after.get(n)]
    if mut.step is not None:
        assert changed == [mut.step], (op, changed)
    else:
        assert len(changed) <= 1
    if op == "make_circular":
        assert "T-001" in after[mut.step]
    if op == "clearly_ify":
        assert after[mut.step].startswith("Clearly")
    if op == "swap_quantifier":
        assert "there exists" in after[mut.step]
    if op == "drop_edge_case":
        assert mutated.count("- |S| = 2") == 0 or mutated.count("arithmetic progression") == 0


def test_applicable_ops_and_benign_edits_preserve_steps():
    assert set(L.applicable_ops(PROOF)) == set(L.DETERMINISTIC_OPS)
    rng = random.Random(3)
    t = PROOF
    for name, fn in L.BENIGN_OPS.items():
        t = fn(t, rng)
    assert _steps(t).keys() == _steps(PROOF).keys()
    assert parse_proof(t).frontmatter == parse_proof(PROOF).frontmatter
    with pytest.raises(L.LineupError):
        L.apply_op("---\nclaim: X\n---\n## Proof\n**Conclusion.** x\n", "swap_quantifier")


# ------------------------------------------------------------- lineup --

def test_build_lineup_seals_and_hides_artifact_from_skeptics(tmp_path):
    d = _camp(tmp_path)
    B.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=2)
    sealed = L.build_lineup(d, 1, "proofs/T-001.md", 2, seed=7)
    items = sealed["items"]
    kinds = sorted(v["kind"] for v in items.values())
    assert kinds == ["control", "decoy", "decoy", "real"] and sealed["real"] in items
    ldir = d / "reviews" / "round1" / "lineup"
    assert sorted(p.name for p in ldir.glob("*.md")) == sorted(f"{k}.md" for k in items)
    m = B.load_manifest(d, 1)
    assert m["lineup"]["real_commitment"] == L.commitment(sealed["salt"], sealed["real"])
    for key, role in m["roles"].items():
        if key.startswith("skeptic:"):
            assert "proofs/T-001.md" not in role["allow"] and any(p.endswith("lineup/**") for p in role["allow"])
            assert B.role_allowed(m, key, "reviews/round1/lineup.sealed.json")[0] is False
            assert B.role_allowed(m, key, "reviews/round1/lineup/A.md")[0] is True
    again = L.build_lineup(d, 1, "proofs/T-001.md", 2, seed=7)
    assert again["real"] == sealed["real"] and [v["op"] for v in again["items"].values() if v["kind"] == "decoy"] == \
        [v["op"] for v in sealed["items"].values() if v["kind"] == "decoy"]
    with pytest.raises(L.LineupError, match="applicable"):
        L.build_lineup(d, 1, "proofs/T-001.md", 20, seed=1)


def test_score_recall_control_and_gating(tmp_path):
    d = _camp(tmp_path)
    B.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=2)
    sealed = L.build_lineup(d, 1, "proofs/T-001.md", 2, seed=11, ops=["make_circular", "clearly_ify"])
    rdir = d / "reviews" / "round1"
    real = sealed["real"]
    decoys = {k: v for k, v in sealed["items"].items() if v["kind"] == "decoy"}
    control = next(k for k, v in sealed["items"].items() if v["kind"] == "control")
    # a good skeptic: finds both planted flaws, passes the control and the real item
    good = ""
    for letter, spec in decoys.items():
        if spec["op"] == "make_circular":
            good += _verdict(letter, "fail", errors=[(spec["step"], "the step is circular: it invokes theorem T-001 itself")])
        else:
            good += _verdict(letter, "fail", gaps=[(spec["step"], "'Clearly' is not a justification; the inference is unjustified")])
    good += _verdict(control, "pass") + _verdict(real, "pass")
    _write(rdir / "skeptic.SK-good.md", good)
    # a lazy skeptic: passes everything
    lazy = "".join(_verdict(k, "pass") for k in sealed["items"])
    _write(rdir / "skeptic.SK-lazy.md", lazy)
    # a paranoid skeptic: finds the flaws but also "refutes" the control
    paranoid = good.replace(_verdict(control, "pass"), _verdict(control, "fail", errors=[(2, "square could be negative")]))
    _write(rdir / "skeptic.SK-paranoid.md", paranoid)
    scores = {s.agent_id: s for s in L.score_lineup(d, 1)}
    assert scores["SK-good"].recall == 1.0 and scores["SK-good"].false_alarms == 0 and scores["SK-good"].admissible
    assert scores["SK-good"].real_verdict == "pass"
    assert scores["SK-lazy"].recall == 0.0 and not scores["SK-lazy"].admissible
    assert scores["SK-paranoid"].recall == 1.0 and scores["SK-paranoid"].false_alarms == 1
    assert scores["SK-paranoid"].reliability == pytest.approx(0.75) and not scores["SK-paranoid"].admissible
    assert (rdir / "lineup_score.SK-lazy.json").exists()
    # a wrong step number is a miss
    wrong = _verdict(next(iter(decoys)), "fail", errors=[(99, "circular")]) + "".join(_verdict(k, "pass") for k in sealed["items"] if k != next(iter(decoys)))
    _write(rdir / "skeptic.SK-wrong.md", wrong)
    s = L.score_lineup(d, 1, "SK-wrong")[0]
    assert s.detected == 0
    # gate: unscored or inadmissible skeptics are problems; unseal needs every skeptic scored
    m = B.load_manifest(d, 1)
    problems = L.lineup_checks(d, 1, m)
    assert any("inadmissible" in p for p in problems)
    with pytest.raises(L.LineupError, match="not delivered"):
        L.unseal(d, 1)
    for key, role in m["roles"].items():
        if key.startswith("skeptic:"):
            _write(d / role["deliverable"], good)
    L.score_lineup(d, 1)
    out = L.unseal(d, 1)
    assert out["real"] == real and (rdir / "lineup.unsealed.json").exists()
    assert L.status(d, 1)["items"][real] == "real"


def test_ledger_requires_lineup_score_for_skeptic_evidence(tmp_path):
    d = _camp(tmp_path)
    store = LedgerStore(d / "ledger.json", campaign="demo")
    B.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=1)
    L.build_lineup(d, 1, "proofs/T-001.md", 1, seed=5)
    with pytest.raises(LedgerError, match="agent-id"):
        store.add_evidence("T-001", Evidence(type="referee", role="skeptic", verdict="pass", round=1), d)
    with pytest.raises(LedgerError, match="reliability"):
        store.add_evidence("T-001", Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-1"), d)
    with pytest.raises(LedgerError, match="contradicts"):
        store.add_evidence("T-001", Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-1", reliability=0.5, admissible=True), d)
    claim = store.add_evidence("T-001", Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-1", reliability=0.5), d)
    assert claim.evidence[-1].admissible is False
    _write(d / "reviews" / "round1" / "lineup_score.SK-2.json", json.dumps({"agent_id": "SK-2", "reliability": 1.0, "admissible": True}))
    with pytest.raises(LedgerError, match="does not match"):
        store.add_evidence("T-001", Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-2", reliability=0.9), d)
    ok = store.add_evidence("T-001", Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-2", reliability=1.0), d)
    assert ok.evidence[-1].admissible is True


def test_cli_open_builds_lineup_and_scores(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(review_cli, "CAMPAIGNS", tmp_path / "campaigns")
    d = _camp(tmp_path)
    assert review_cli.main(["--campaign", "demo", "open", "--claim", "T-001", "--artifact", "proofs/T-001.md", "--seed", "3"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["lineup"] and len(out["lineup"]["items"]) == 4
    assert review_cli.main(["--campaign", "demo", "lineup", "status"]) == 0
    assert review_cli.main(["--campaign", "demo", "score-lineup"]) == 1  # no reports yet
    sealed = L.load_sealed(d, 1)
    lazy = "".join(_verdict(k, "pass") for k in sealed["items"])
    _write(d / "reviews" / "round1" / "skeptic.SK-z.md", lazy)
    assert review_cli.main(["--campaign", "demo", "score-lineup"]) == 3
    assert review_cli.main(["--campaign", "demo", "lineup", "unseal"]) == 1  # skeptic slots not delivered
    # verify_semantic: a change outside the target step is reported
    ldir = d / "reviews" / "round1" / "lineup"
    _write(ldir / ".work" / "A.orig.md", (ldir / "A.md").read_text(encoding="utf-8"))
    text = (ldir / "A.md").read_text(encoding="utf-8").replace("**Conclusion.**", "**Conclusion.** (edited)")
    _write(ldir / "A.md", text)
    assert review_cli.main(["--campaign", "demo", "lineup", "verify", "--item", "A", "--step", "5"]) == 1
