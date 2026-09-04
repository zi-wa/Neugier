"""Tests for harness.proof.lint — the proof-artifact linter (proof-standards.md §1–§7)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
import harness.ledger.cli as ledger_cli
import harness.proof.cli as proof_cli
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence
from harness.proof.lint import lint_proof, parse_proof

EXCERPT = "For every finite set S of integers with at least two elements, |S+S| >= 2|S| - 1."


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _minimal_proof(*, claim="T-001", statement="For every finite S, |S+S| >= 2|S|-1.", key=True, cite_hash="",
                   extra_step="", hyps="[finite, |S|>=2]", numerics="[results.json#sumset_small_cases]", assumes="[]",
                   technique="[extremal]") -> str:
    key_line = "**Step 4.** <key-original-step> Translate S so min S = 0; the new idea is the compression map. </key-original-step>\n" if key else "**Step 4.** (Step 3) Translate S so min S = 0.\n"
    cite_line = f'**Step 3.** <cite id="Ruzsa1994" claim="F-001" excerpt-hash="{cite_hash}"> Cauchy–Davenport for the integers gives |S+S| >= 2|S|-1 for finite S with |S| >= 2; both hypotheses hold by assumption. </cite>\n' if cite_hash else "**Step 3.** (algebra) |S+S| >= 2|S|-1 follows by counting the sums min+s and s+max.\n"
    return f"""---
claim: {claim}
statement: "{statement}"
depends_on: [F-001]
assumes: {assumes}
uses_hypotheses: {hyps}
numerics: {numerics}
version: 1
technique: {technique}
---

## Proof

**Setup.** Let S be a finite set of integers with |S| >= 2.

**Step 1.** (definition D-001) S+S = {{a+b : a, b in S}}.
**Step 2.** (hypothesis) S is finite and |S| >= 2, so min S and max S exist and differ.
{cite_line}{key_line}**Step 5.** (Steps 2, 4) The 2|S|-1 sums min+s (s in S) and s+max (s in S) are distinct except for min+max.
{extra_step}**Conclusion.** |S+S| >= 2|S|-1, matching results.json#sumset_small_cases for |S| <= 12.

## Edge cases checked
- |S| = 2: S+S has exactly 3 elements.
- S an arithmetic progression: equality.

## Self-check log
- Hypothesis use: finite → Step 2; |S|>=2 → Step 2.
- Numeric spot-check: results.json#sumset_small_cases (n <= 12) — consistent.
"""


@pytest.fixture()
def camp(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(ledger_cli, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(proof_cli, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")
    path = campaign.create("demo", "Demo")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    _write(path / "cache" / "Ruzsa1994.txt", "Theorem 1. " + EXCERPT + " Proof omitted.")
    fact = store.add(kind="fact", statement="Cauchy-Davenport for Z.", status="known-in-literature",
                     evidence=Evidence(type="excerpt", source_id="Ruzsa1994", excerpt=EXCERPT), campaign_dir=path)
    thm = store.add(kind="theorem", statement="For every finite S, |S+S| >= 2|S|-1.", depends_on=[fact.id])
    _write(path / "experiments" / "results.json", json.dumps({"sumset_small_cases": {"value": True, "source": "experiments/sumset.py"}}))
    _write(path / "refs.bib", "@article{Ruzsa1994, title={Sumsets}}\n")
    return path, store, fact, thm


def test_parse_proof_kinds_and_cites():
    doc = parse_proof(_minimal_proof(cite_hash="abcdef123456"))
    assert doc.claim == "T-001" and doc.kind == "proof"
    kinds = {s.n: s.kind for s in doc.steps}
    assert kinds == {1: "definition", 2: "hypothesis", 3: "cited", 4: "key", 5: "derived"}
    assert doc.key_steps == [4] and doc.cites[0].claim == "F-001" and doc.cites[0].excerpt_hash == "abcdef123456"
    assert doc.has_conclusion and "Edge cases checked" in doc.sections


def test_valid_proof_passes(camp):
    path, store, fact, thm = camp
    h = fact.evidence[-1].excerpt_hash
    p = _write(path / "proofs" / "T-001.md", _minimal_proof(cite_hash=h))
    report = lint_proof(p, path, store)
    assert report.ok, [e.message for e in report.errors]
    assert not any(w.code == "W_TECHNIQUE_MISSING" for w in report.warnings)


def test_keystep_rules(camp):
    path, store, fact, thm = camp
    h = fact.evidence[-1].excerpt_hash
    p = _write(path / "proofs" / "T-001.md", _minimal_proof(cite_hash=h, key=False))
    codes = [e.code for e in lint_proof(p, path, store).errors]
    assert "E_PROOF_KEYSTEP" in codes
    two = _minimal_proof(cite_hash=h, extra_step="**Step 6.** <key-original-step> another new idea </key-original-step>\n")
    codes = [e.code for e in lint_proof(_write(p, two), path, store).errors]
    assert "E_PROOF_KEYSTEP" in codes
    lem = store.add(kind="lemma", statement="L.", depends_on=[fact.id])
    pl = _write(path / "proofs" / f"{lem.id}.md", _minimal_proof(claim=lem.id, statement="L.", cite_hash=h, key=False))
    assert lint_proof(pl, path, store).ok


def test_cite_must_resolve_to_verified_excerpt(camp):
    path, store, fact, thm = camp
    p = _write(path / "proofs" / "T-001.md", _minimal_proof(cite_hash="000000000000"))
    errs = lint_proof(p, path, store).errors
    assert any(e.code == "E_PROOF_CITE" and "matches no verified excerpt" in e.message for e in errs)
    bad = _minimal_proof(cite_hash=fact.evidence[-1].excerpt_hash).replace('claim="F-001"', 'claim="T-001"')
    errs = lint_proof(_write(p, bad), path, store).errors
    assert any(e.code == "E_PROOF_CITE" and "known-in-literature" in e.message for e in errs)
    nohash = _minimal_proof(cite_hash="x").replace(' excerpt-hash="x"', "")
    errs = lint_proof(_write(p, nohash), path, store).errors
    assert any(e.code == "E_PROOF_CITE" and "needs id" in e.message for e in errs)


def test_priming_hedges_numbering_numerics_hypotheses(camp):
    path, store, fact, thm = camp
    h = fact.evidence[-1].excerpt_hash
    base = _minimal_proof(cite_hash=h)
    p = path / "proofs" / "T-001.md"
    primed = base.replace("## Proof\n", "## Proof\n\nWe believe this is the right approach and after much experimentation it seems to work.\n")
    assert any(e.code == "E_PROOF_PRIMING" for e in lint_proof(_write(p, primed), path, store).errors)
    hedged = base.replace("**Step 5.** (Steps 2, 4) The", "**Step 5.** (Steps 2, 4) Clearly the")
    assert any(e.code == "E_PROOF_HEDGE" for e in lint_proof(_write(p, hedged), path, store).errors)
    gap = base.replace("**Step 5.**", "**Step 7.**")
    assert any(e.code == "E_PROOF_STEPS" and "consecutively" in e.message for e in lint_proof(_write(p, gap), path, store).errors)
    nojust = base.replace("**Step 2.** (hypothesis) S", "**Step 2.** S")
    assert any(e.code == "E_PROOF_STEPS" and "no justification" in e.message for e in lint_proof(_write(p, nojust), path, store).errors)
    untracked = base.replace("results.json#sumset_small_cases for", "results.json#unknown_key for")
    assert any(e.code == "E_PROOF_NUMERIC_UNTRACKED" for e in lint_proof(_write(p, untracked), path, store).errors)
    unused = _minimal_proof(cite_hash=h, hyps="[finite, |S|>=2, S nonempty]")
    assert any(e.code == "E_PROOF_HYPOTHESIS_UNUSED" and "S nonempty" in e.message for e in lint_proof(_write(p, unused), path, store).errors)
    nosec = base.replace("## Edge cases checked", "## Edge cases")
    assert any(e.code == "E_PROOF_SECTION_MISSING" for e in lint_proof(_write(p, nosec), path, store).errors)
    conditional = _minimal_proof(cite_hash=h, assumes="[C-009]")
    rep = lint_proof(_write(p, conditional), path, store)
    assert any(w.code == "W_PROOF_CONDITIONAL" for w in rep.warnings) and any(w.code == "W_PROOF_ASSUMES_TAG" for w in rep.warnings)
    drift = _minimal_proof(cite_hash=h, statement="Something else entirely.")
    assert any(w.code == "W_PROOF_STATEMENT_DRIFT" for w in lint_proof(_write(p, drift), path, store).warnings)
    unknown = _minimal_proof(claim="T-099", cite_hash=h)
    assert any(e.code == "E_PROOF_CLAIM_UNKNOWN" for e in lint_proof(_write(p, unknown), path, store).errors)
    nofm = base.split("---\n", 2)[2]
    assert any(e.code == "E_PROOF_HEADER" for e in lint_proof(_write(p, nofm), path, store).errors)


def test_sketch_lint():
    doc_text = """---
kind: sketch
claim: T-001
persona: analyst
route: 3
key_idea: compression
lemmas:
  - label: S1
    statement: "compression does not increase |S+S|"
    needs: [D-001]
    cheapest_falsification: "brute force |S| <= 8"
---
S1 <- D-001. We believe it works.
"""
    p = Path.cwd()  # placeholder to satisfy the signature
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        f = _write(Path(td) / "T-001.sketch.analyst.md", doc_text)
        rep = lint_proof(f)
        assert rep.ok and rep.doc.kind == "sketch" and any(w.code == "W_SKETCH_PRIMING" for w in rep.warnings)
        rep2 = lint_proof(_write(f, doc_text.replace("    cheapest_falsification: \"brute force |S| <= 8\"\n", "")))
        assert not rep2.ok
    del p


def test_cli_and_promotion_gate(camp, capsys):
    path, store, fact, thm = camp
    h = fact.evidence[-1].excerpt_hash
    _write(path / "proofs" / "T-001.md", _minimal_proof(cite_hash=h, key=False))
    store.add_evidence(thm.id, Evidence(type="proof", path="proofs/T-001.md"), path)
    assert proof_cli.main(["check", "proofs/T-001.md", "--campaign", "demo"]) == 1
    assert "E_PROOF_KEYSTEP" in capsys.readouterr().out
    # ledger CLI refuses to promote to proof-drafted while the linter fails
    assert ledger_cli.main(["--campaign", "demo", "promote", "T-001", "proof-drafted"]) == 1
    assert "E_PROOF_KEYSTEP" in capsys.readouterr().err
    _write(path / "proofs" / "T-001.md", _minimal_proof(cite_hash=h))
    store2 = LedgerStore(path / "ledger.json", campaign="demo")
    store2.add_evidence(thm.id, Evidence(type="proof", path="proofs/T-001.md"), path)
    assert proof_cli.main(["check", "proofs/T-001.md", "--campaign", "demo", "--json"]) == 0
    assert ledger_cli.main(["--campaign", "demo", "promote", "T-001", "proof-drafted"]) == 0
    # prove gate lints the artifact too
    campaign.set_phase("demo", "prove")
    assert campaign.check_phase_exit("demo") == []
    _write(path / "proofs" / "T-001.md", _minimal_proof(cite_hash=h, key=False))
    unmet = campaign.check_phase_exit("demo")
    assert any("E_PROOF_KEYSTEP" in m for m in unmet)
