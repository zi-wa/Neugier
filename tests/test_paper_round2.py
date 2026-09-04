"""Round-2 Step 24 / Round-1 Step 8: paper rules — knownresult, conditional, fully_proved, attestation, keystep."""
from __future__ import annotations

from pathlib import Path

from harness.paper.check import check

BIB = "@article{foo2020, title={Foo}, author={Foo, A.}, journal={J}, year={2020}}\n"


def _paper(tmp_path: Path, tex: str) -> Path:
    d = tmp_path / "paper"
    d.mkdir(parents=True, exist_ok=True)
    (d / "main.tex").write_text(tex, encoding="utf-8")
    (d / "refs.bib").write_text(BIB, encoding="utf-8")
    return d


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


THM = r"""
\begin{theorem}\claim{T-1}
Main result.
\end{theorem}
\begin{proof}
Proof. \keystep{the idea}
\end{proof}
"""


def test_knownresult_rules(tmp_path):
    d = _paper(tmp_path, "\\begin{knownresult}\nNo citation here.\n\\end{knownresult}\n")
    assert "E_KNOWNRESULT_NO_CITE" in _codes(check(d, ledger_status={}, results={}).errors)
    d = _paper(tmp_path, "\\begin{knownresult}\\claim{F-1}\nSee \\cite{foo2020}.\n\\end{knownresult}\n")
    assert "E_CLAIM_STATUS" in _codes(check(d, ledger_status={"F-1": "referee-passed"}, results={}).errors)
    assert check(d, ledger_status={"F-1": "known-in-literature"}, results={}).ok


def test_not_fully_proved_requires_conditional(tmp_path):
    d = _paper(tmp_path, THM)
    rep = check(d, ledger_status={"T-1": "referee-passed"}, results={}, fully_proved=set())
    assert "E_CLAIM_NOT_FULLY_PROVED" in _codes(rep.errors)
    cond = THM.replace("theorem}", "conditional}")
    d = _paper(tmp_path, cond)
    rep = check(d, ledger_status={"T-1": "referee-passed"}, results={}, fully_proved=set())
    assert rep.ok and "W_CONDITIONAL_UNNEEDED" not in _codes(rep.warnings)
    rep = check(d, ledger_status={"T-1": "referee-passed"}, results={}, fully_proved={"T-1"})
    assert rep.ok and "W_CONDITIONAL_UNNEEDED" in _codes(rep.warnings)
    d = _paper(tmp_path, THM)
    assert check(d, ledger_status={"T-1": "referee-passed"}, results={}).ok  # status-only meta assumes fully proved


def test_keystep_missing_is_error_and_attestation(tmp_path):
    d = _paper(tmp_path, THM.replace(" \\keystep{the idea}", ""))
    rep = check(d, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_KEYSTEP_MISSING" in _codes(rep.errors)
    d = _paper(tmp_path, THM)
    meta = {"T-1": {"status": "referee-passed", "stakes": 2, "attested": False, "fully_proved": True}}
    rep = check(d, ledger_status={"T-1": "referee-passed"}, results={}, ledger_meta=meta, strict=True)
    assert "E_HUMAN_ATTEST" in _codes(rep.errors)
    rep = check(d, ledger_status={"T-1": "referee-passed"}, results={}, ledger_meta=meta, strict=False)
    assert "E_HUMAN_ATTEST" not in _codes(rep.errors)
    marked = THM.replace("Main result.", "Main result.\\unverified{}")
    rep = check(_paper(tmp_path, marked), ledger_status={"T-1": "referee-passed"}, results={}, ledger_meta=meta, strict=True)
    assert "E_HUMAN_ATTEST" not in _codes(rep.errors)
    meta["T-1"]["attested"] = True
    rep = check(d, ledger_status={"T-1": "referee-passed"}, results={}, ledger_meta=meta, strict=True)
    assert "E_HUMAN_ATTEST" not in _codes(rep.errors)


def test_meta_loaded_from_ledger(tmp_path):
    from harness.ledger.ledger import LedgerStore
    from harness.ledger.schema import Evidence

    camp = tmp_path / "camp"
    camp.mkdir()
    store = LedgerStore(camp / "ledger.json", campaign="camp")
    lem = store.add(kind="lemma", statement="L.")
    thm = store.add(kind="theorem", statement="T.", depends_on=[lem.id])
    for cid in (lem.id, thm.id):
        (camp / "proofs").mkdir(exist_ok=True)
        (camp / "proofs" / f"{cid}.md").write_text("**Step 1.** (algebra) x.", encoding="utf-8")
        store.add_evidence(cid, Evidence(type="proof", path=f"proofs/{cid}.md"), camp)
        store.promote(cid, "proof-drafted", camp)
    for cid in (thm.id,):
        for role in ("skeptic", "falsifier", "novelty", "replicator", "judge"):
            store.add_evidence(cid, Evidence(type="referee", role=role, verdict="pass", round=1, agent_id="SK-1" if role == "skeptic" else None), camp)
        store.add_evidence(cid, Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-2"), camp)
    # the theorem cannot even be referee-passed while its lemma is only proof-drafted; use the assumes tag
    store.get(thm.id).tags.append(f"assumes:{lem.id}")
    store.save()
    store.promote(thm.id, "referee-passed", camp)
    paper = camp / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(THM.replace("T-1", thm.id), encoding="utf-8")
    (paper / "refs.bib").write_text(BIB, encoding="utf-8")
    rep = check(paper, results={})
    assert "E_CLAIM_NOT_FULLY_PROVED" in _codes(rep.errors)
    (paper / "main.tex").write_text(THM.replace("T-1", thm.id).replace("theorem}", "conditional}"), encoding="utf-8")
    assert check(paper, results={}).ok
