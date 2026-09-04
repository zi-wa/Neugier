"""Round-2 Step 24: verification coverage of a proof artifact (X5a)."""
from __future__ import annotations

import json
from pathlib import Path

import harness
import harness.proof.cli as proof_cli
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence
from harness.proof.coverage import compute_coverage, write_coverage

EXC = "For every finite set S of integers with at least two elements, |S+S| >= 2|S| - 1."


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _proof(cite_hash: str) -> str:
    return f"""---
claim: T-001
statement: "T."
depends_on: [F-001, L-001]
assumes: []
uses_hypotheses: [finite]
numerics: [results.json#small_cases, results.json#constant]
version: 1
technique: [extremal]
---
## Proof
**Step 1.** (definition D-001) setup.
**Step 2.** (algebra) rearrange.
**Step 3.** <cite id="R" claim="F-001" excerpt-hash="{cite_hash}"> cited bound </cite>
**Step 4.** (computation: results.json#small_cases) checked.
**Step 5.** <key-original-step> the idea </key-original-step>
**Step 6.** (Steps 4, 5) combine.
**Step 7.** hand-wavy synthesis without a tag.
**Conclusion.** done.
## Edge cases checked
- none
## Self-check log
- Hypothesis use: finite → Step 1.
"""


SKEPTIC = """| Step | Status | Justification checked | Witness |
|---|---|---|---|
| 1 | VERIFIED | def | |
| 2 | VERIFIED | algebra | |
| 3 | VERIFIED | excerpt read | |
| 4 | OPEN | | |
| 5 | FLAWED (critical) | breaks at n=3 | witness |
| 6 | OPEN | | |
```yaml
role: skeptic
claim: T-001
round: 1
verdict: fail
critical_errors:
  - step: 5
    witness: "breaks at n=3"
```
"""
REPLICATOR = """```yaml
role: replicator
claim: T-001
round: 1
verdict: pass
reproduced: [results.json#small_cases]
checked:
  - "constant results.json#constant matches to 12 digits"
```
"""


def test_coverage_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(proof_cli, "CAMPAIGNS", tmp_path / "campaigns")
    d = tmp_path / "campaigns" / "demo"
    (d / "cache").mkdir(parents=True)
    store = LedgerStore(d / "ledger.json", campaign="demo")
    _write(d / "cache" / "R.txt", "Theorem. " + EXC)
    fact = store.add(kind="fact", statement="F.", status="known-in-literature",
                     evidence=Evidence(type="excerpt", source_id="R", excerpt=EXC), campaign_dir=d)
    lem = store.add(kind="lemma", statement="L.")
    thm = store.add(kind="theorem", statement="T.", depends_on=[fact.id, lem.id])
    h = fact.evidence[-1].excerpt_hash
    _write(d / "proofs" / "T-001.md", _proof(h))
    store.add_evidence(thm.id, Evidence(type="proof", path="proofs/T-001.md"), d)
    _write(d / "experiments" / "results.json", json.dumps({"small_cases": {"value": True}, "constant": {"value": "1/2"}}))
    cov = compute_coverage(d, thm.id, store=store)
    assert cov.round is None and cov.steps_total == 7 and cov.steps_verified_by_skeptic == 0 and cov.warnings
    _write(d / "reviews" / "round1" / "skeptic.SK-1.md", SKEPTIC)
    _write(d / "reviews" / "round1" / "replicator.md", REPLICATOR)
    cov = compute_coverage(d, thm.id, store=store)
    assert cov.round == 1 and cov.skeptic_reports == 1
    assert cov.steps_verified_by_skeptic == 3 and cov.steps_open == 2 and cov.steps_flawed == 1 and cov.steps_unreviewed == 1
    assert cov.by_type["cited"].total == 1 and cov.by_type["cited"].verified == 1
    assert cov.by_type["synthesis"].total == 1 and cov.synthesis_steps == 1 and cov.by_type["key"].verified == 0
    assert cov.cites_total == 1 and cov.cites_verified == 1
    assert cov.numerics_total == 2 and cov.numerics_reproduced == 2
    assert cov.lemmas_total == 1 and cov.lemmas_falsified == 0
    assert cov.overall_pct == 42.9 and "cites 1/1" in cov.summary_line()
    _write(d / "experiments" / "lem.json", "{}")
    store.add_evidence(lem.id, Evidence(type="falsification", path="experiments/lem.json"), d)
    assert compute_coverage(d, thm.id, store=store).lemmas_falsified == 1
    # wrong excerpt hash is not verified
    _write(d / "proofs" / "T-001.md", _proof("000000000000"))
    assert compute_coverage(d, thm.id, store=store).cites_verified == 0
    out = write_coverage(d, cov)
    assert out.name == "coverage-T-001.json" and json.loads(out.read_text(encoding="utf-8"))["summary"]
    assert proof_cli.main(["coverage", "T-001", "--campaign", "demo", "--min-verified", "0.9"]) == 3
    assert proof_cli.main(["coverage", "T-001", "--campaign", "demo", "--json"]) == 0
