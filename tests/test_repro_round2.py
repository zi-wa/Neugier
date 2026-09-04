"""Round-1 Step 8 + Round-2 Step 25: reproducibility appendix, provenance, audit, disclosure."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
import harness.paper.cli as paper_cli
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence
from harness.paper import audit as A
from harness.paper import disclosure as D
from harness.paper import repro as R
from harness.paper.check import check

TEX = r"""\documentclass{amsart}
\begin{document}
\section{Introduction}
Short intro sentence that should not be sampled here.
\section{Main results}
The greedy construction attains density at least one third for every admissible order.
We verify the bound for all orders up to twelve by exhaustive computation in the appendix.
The equality case occurs exactly when the set is an arithmetic progression of common difference one.
\begin{theorem}\claim{T-001}
Main theorem statement with enough words to be a sentence.
\end{theorem}
\begin{proof}
The proof proceeds in three numbered steps following the compression argument. \keystep{compression}
\end{proof}
\section{Discussion}
Discussion sentences are not part of the audit sample by default.
\end{document}
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
    monkeypatch.setattr(R, "_pip_list", lambda: [("numpy", "2.0")])
    monkeypatch.setattr(R, "tectonic_version", lambda: "0.17.0")
    monkeypatch.setattr(R, "git_revision", lambda d: "abc1234 (dirty)")


def _campaign_with_theorem() -> tuple[Path, LedgerStore]:
    path = campaign.create("demo", "Demo")
    store = LedgerStore(path / "ledger.json", campaign="demo")
    thm = store.add(kind="theorem", statement="Main theorem.")
    _write(path / "proofs" / "T-001.md", "---\nclaim: T-001\nnumerics: [results.json#small]\n---\n## Proof\n**Step 1.** (computation: results.json#small) x.\n**Conclusion.** y.\n")
    store.add_evidence(thm.id, Evidence(type="proof", path="proofs/T-001.md"), path)
    _write(path / "experiments" / "check.py", "print(1)")
    store.add_evidence(thm.id, Evidence(type="computation", path="experiments/check.py", summary="small cases"), path)
    store.promote(thm.id, "proof-drafted", path)
    for role in ("skeptic", "falsifier", "novelty", "replicator", "judge"):
        store.add_evidence(thm.id, Evidence(type="referee", role=role, verdict="pass", round=1,
                                            agent_id="SK-1" if role == "skeptic" else None,
                                            reliability=0.9 if role == "skeptic" else None), path)
    store.add_evidence(thm.id, Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-2", reliability=1.0), path)
    store.promote(thm.id, "referee-passed", path)
    _write(path / "reviews" / "round1" / "novelty.md", "```yaml\nrole: novelty\nclaim: T-001\nverdict: pass\nclass: 1a\n```\n")
    _write(path / "reviews" / "round1" / "skeptic.SK-1.md", "| Step | Status | J | W |\n|---|---|---|---|\n| 1 | VERIFIED | ok | |\n```yaml\nrole: skeptic\nclaim: T-001\nverdict: pass\n```\n")
    _write(path / "experiments" / "results.json", json.dumps({"small": {"value": 12, "source": "experiments/check.py", "args": ["--n", "12"], "seed": 7}}))
    campaign.freeze("demo", ["experiments/check.py"])
    return path, store


def test_appendix_sections_and_commands():
    path, store = _campaign_with_theorem()
    out = R.write_appendix(path)
    tex = out.read_text(encoding="utf-8")
    for sec in ("Environment", "Installed packages", "Frozen files and scorers", "Ledger evidence", "Provenance",
                "Computed quantities", "How to reproduce", "AI involvement disclosure"):
        assert f"\\subsection{{{sec}}}" in tex, sec
    assert "abc1234 (dirty)" in tex and "tectonic 0.17.0" in tex and "Neugier harness" in tex
    assert "experiments/check.py" in tex.replace("\\_", "_") and "7" in tex  # frozen file + seed column
    assert "python experiments/check.py --n 12" in tex.replace("\\_", "_")
    assert "T-001" in tex and "fully_proved" in tex.replace("\\_", "_") and "1a" in tex
    assert "(Mitchener et al., 2025)" in tex and "Agents4Science 2025" in tex  # plain-text attributions without bib keys
    assert "\\label{sec:provenance}" in tex and "\\label{sec:disclosure}" in tex
    assert "No sampled accuracy audit" in tex
    assert (path / "disclosure.json").exists()


def test_disclosure_phases_theorem_lines_and_human_md():
    path, store = _campaign_with_theorem()
    campaign.set_phase("demo", "review")
    _write(path / "HUMAN.md", "# HUMAN\n## Policy\n## review\ninvolvement: verified-proof\nT-001 checked by hand\n## Answers\n")
    d = D.build_disclosure(path)
    phases = {p.phase: p for p in d.phases}
    assert "bootstrap" in phases and phases["review"].human_involvement == "verified-proof"
    assert "skeptic" in phases["review"].agents and "prover" in [a for p in d.phases for a in p.agents]
    t = d.theorems[0]
    assert t.claim == "T-001" and t.skeptic_passes == 2 and t.lineup_reliability == 0.95 and t.replicated and t.human_verified
    assert "2 skeptic passes" in t.line and "human-verified: yes" in t.line
    tex = D.render_disclosure_tex(path, path / "paper")
    assert "verified-proof" in tex and "T-001" in tex


def test_audit_sample_check_and_strict_rules(capsys):
    path, store = _campaign_with_theorem()
    _write(path / "paper" / "main.tex", TEX)
    _write(path / "paper" / "refs.bib", "")
    sents = A.extract_sentences(path / "paper")
    texts = [s["text"] for s in sents]
    assert any("greedy construction" in t for t in texts) and not any("Short intro" in t for t in texts)
    assert not any("Discussion sentences" in t for t in texts)
    picked = A.sample(sents, 2, "demo")
    again = A.sample(sents, 2, "demo")
    assert [p["sha12"] for p in picked] == [p["sha12"] for p in again] and len(picked) == 2
    assert paper_cli.main(["audit", "sample", "--campaign", "demo", "--n", "3"]) == 0
    audit = json.loads((path / "paper" / "audit.json").read_text(encoding="utf-8"))
    assert audit["n"] == 3 and audit["seed"] == "demo"
    assert paper_cli.main(["audit", "check", "--campaign", "demo"]) == 1  # unlabeled
    rep = check(path / "paper", ledger_status={"T-001": "referee-passed"}, results={"small": 12})
    assert "W_AUDIT_INCOMPLETE" in {i.code for i in rep.warnings}
    audit["sentences"][0]["label"] = "refuted"
    audit["sentences"][1]["label"] = "supported"
    audit["sentences"][1]["evidence"] = "results.json#small"
    audit["sentences"][2]["label"] = "supported"
    _write(path / "paper" / "audit.json", json.dumps(audit))
    assert paper_cli.main(["audit", "check", "--campaign", "demo"]) == 3
    rep = check(path / "paper", ledger_status={"T-001": "referee-passed"}, results={"small": 12}, strict=True)
    codes = {i.code for i in rep.errors}
    assert "E_AUDIT_REFUTED" in codes
    assert any(w.code == "W_AUDIT_INCOMPLETE" and "without an evidence pointer" in w.message for w in rep.warnings)
    rep = check(path / "paper", ledger_status={"T-001": "referee-passed"}, results={"small": 12}, strict=False)
    assert "W_AUDIT_REFUTED" in {i.code for i in rep.warnings} and "E_AUDIT_REFUTED" not in {i.code for i in rep.errors}
    _write(path / "paper" / "main.tex", TEX.replace("attains density at least one third", "attains density at least one half"))
    rep = check(path / "paper", ledger_status={"T-001": "referee-passed"}, results={"small": 12})
    assert any(w.code == "W_AUDIT_STALE" for w in rep.warnings)
    tex = R.write_appendix(path).read_text(encoding="utf-8")
    assert "Audited accuracy: 2/3" in tex
