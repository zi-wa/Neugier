"""Tests for harness.paper: template rendering, check.py lint rules, repro.py,
and (skipped unless tectonic is available) an actual tectonic build."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.paper.build import BuildResult, build, find_tectonic, render_template
from harness.paper.check import check
from harness.paper.repro import escape_latex, write_appendix

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "harness" / "paper" / "templates" / "example"

MINIMAL_BIB = """
@article{foo2020,
  author = {A. Author},
  title = {A Title},
  journal = {J. Math},
  year = {2020},
  eprint = {2001.00001},
  archivePrefix = {arXiv}
}
"""


def _write_paper(tmp_path: Path, main_tex: str, bib: str | None = MINIMAL_BIB) -> Path:
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "main.tex").write_text(main_tex, encoding="utf-8")
    if bib is not None:
        (paper_dir / "refs.bib").write_text(bib, encoding="utf-8")
    return paper_dir


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


# --------------------------------------------------------------------------
# render_template
# --------------------------------------------------------------------------


def test_render_template_fills_placeholders(tmp_path: Path) -> None:
    paper_dir = tmp_path / "paper"
    out = render_template(
        paper_dir,
        title="My Title",
        author="A. Uthor",
        abstract="An abstract.",
        body="\\section{Intro}\nBody text.",
        tools="Tools disclosure text.",
        date="2026-09-02",
    )
    text = out.read_text(encoding="utf-8")
    assert "{{" not in text
    assert "My Title" in text
    assert "A. Uthor" in text
    assert "An abstract." in text
    assert "Body text." in text
    assert "Tools disclosure text." in text
    assert "2026-09-02" in text
    assert "amsart" in text
    assert "\\newcommand{\\claim}" in text
    assert "\\newcommand{\\keystep}" in text


def test_render_template_does_not_overwrite_without_force(tmp_path: Path) -> None:
    paper_dir = tmp_path / "paper"
    render_template(paper_dir, "T1", "A1", "Ab1", "Body1", "Tools1")
    out = render_template(paper_dir, "T2", "A2", "Ab2", "Body2", "Tools2")
    text = out.read_text(encoding="utf-8")
    assert "T1" in text
    assert "T2" not in text

    out2 = render_template(paper_dir, "T3", "A3", "Ab3", "Body3", "Tools3", force=True)
    text2 = out2.read_text(encoding="utf-8")
    assert "T3" in text2


# --------------------------------------------------------------------------
# check.py: labels / refs
# --------------------------------------------------------------------------


def test_undef_ref_flagged() -> None:
    from harness.paper.check import _check_refs_labels

    errors: list = []
    warnings: list = []
    _check_refs_labels("See Theorem~\\ref{thm:missing}.", errors, warnings)
    assert "E_UNDEF_REF" in _codes(errors)


def test_ref_and_label_match_clean() -> None:
    from harness.paper.check import _check_refs_labels

    errors: list = []
    warnings: list = []
    text = "\\begin{theorem}\\label{thm:ok}Statement.\\end{theorem} See~\\ref{thm:ok}."
    _check_refs_labels(text, errors, warnings)
    assert errors == []
    assert "W_UNUSED_LABEL" not in _codes(warnings)


def test_unused_label_is_warning() -> None:
    from harness.paper.check import _check_refs_labels

    errors: list = []
    warnings: list = []
    _check_refs_labels("\\label{thm:unused} Statement.", errors, warnings)
    assert errors == []
    assert "W_UNUSED_LABEL" in _codes(warnings)


# --------------------------------------------------------------------------
# check.py: citations
# --------------------------------------------------------------------------


def test_undef_cite_flagged(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
A result following \cite{nosuchkey}.
\end{theorem}
"""
    paper_dir = _write_paper(tmp_path, tex, bib=MINIMAL_BIB)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_UNDEF_CITE" in _codes(report.errors)


def test_cite_resolves_and_uncited_bib_is_warning(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
A result following \cite{foo2020}.
\end{theorem}
\begin{proof}
Trivial.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex, bib=MINIMAL_BIB)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_UNDEF_CITE" not in _codes(report.errors)
    # foo2020 IS cited here, so it should not be flagged as uncited.
    assert "W_UNCITED_BIB" not in _codes(report.warnings)


def test_uncited_bib_entry_is_warning(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Statement with no citations.
\end{theorem}
\begin{proof}
Trivial.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex, bib=MINIMAL_BIB)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "W_UNCITED_BIB" in _codes(report.warnings)


# --------------------------------------------------------------------------
# check.py: theorem-needs-proof-or-cite
# --------------------------------------------------------------------------


def test_theorem_with_proof_passes(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Statement.
\end{theorem}
\begin{proof}
Proof text.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_THEOREM_NO_PROOF" not in _codes(report.errors)


def test_theorem_without_proof_or_cite_fails(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Statement with nothing backing it.
\end{theorem}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_THEOREM_NO_PROOF" in _codes(report.errors)


def test_theorem_with_cite_instead_of_proof_passes(tmp_path: Path) -> None:
    # results quoted from the literature live in a knownresult environment (the \cite loophole is closed)
    tex = r"""
\begin{knownresult}
This is a known result, see \cite{foo2020}.
\end{knownresult}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={}, results={})
    assert "E_THEOREM_NO_PROOF" not in _codes(report.errors)
    assert "E_CLAIM_UNBOUND" not in _codes(report.errors)
    tex2 = r"""
\begin{theorem}
This is a known result, see \cite{foo2020}.
\end{theorem}
"""
    report2 = check(_write_paper(tmp_path, tex2), ledger_status={}, results={})
    assert "E_CLAIM_UNBOUND" in _codes(report2.errors)


def test_conjecture_exempt_from_proof_requirement(tmp_path: Path) -> None:
    tex = r"""
\begin{conjecture}\claim{C-1}
An open statement.
\end{conjecture}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"C-1": "idea"}, results={})
    assert "E_THEOREM_NO_PROOF" not in _codes(report.errors)
    assert "E_CLAIM_STATUS" not in _codes(report.errors)
    assert "E_CLAIM_UNBOUND" not in _codes(report.errors)


# --------------------------------------------------------------------------
# check.py: claim binding
# --------------------------------------------------------------------------


def test_claim_unbound_when_no_claim_or_cite(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}
Statement.
\end{theorem}
\begin{proof}
Proof text.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={}, results={})
    assert "E_CLAIM_UNBOUND" in _codes(report.errors)


def test_claim_unknown_when_id_missing_from_ledger(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-GHOST}
Statement.
\end{theorem}
\begin{proof}
Proof text.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={}, results={})
    assert "E_CLAIM_UNKNOWN" in _codes(report.errors)


def test_claim_status_rejected_when_not_referee_passed(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Statement.
\end{theorem}
\begin{proof}
Proof text.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "conjectured"}, results={})
    assert "E_CLAIM_STATUS" in _codes(report.errors)


def test_claim_status_accepted_when_referee_passed_or_formalized(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Statement one.
\end{theorem}
\begin{proof}
Proof.
\end{proof}

\begin{lemma}\claim{L-1}
Statement two.
\end{lemma}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(
        paper_dir,
        ledger_status={"T-1": "referee-passed", "L-1": "formalized"},
        results={},
    )
    assert "E_CLAIM_STATUS" not in _codes(report.errors)
    assert "E_CLAIM_UNKNOWN" not in _codes(report.errors)
    assert "E_CLAIM_UNBOUND" not in _codes(report.errors)


# --------------------------------------------------------------------------
# check.py: keystep
# --------------------------------------------------------------------------


def test_keystep_missing_warns_when_referee_passed_claim_bound(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Statement.
\end{theorem}
\begin{proof}
Proof with no key step marked.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_KEYSTEP_MISSING" in _codes(report.errors)


def test_keystep_present_silences_warning(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Statement.
\end{theorem}
\begin{proof}
\keystep{The genuinely new argument.}
Rest of the proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_KEYSTEP_MISSING" not in _codes(report.errors)


# --------------------------------------------------------------------------
# check.py: numbers
# --------------------------------------------------------------------------


def test_number_matches_results_json_passes(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
The constant is $3.14159$.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(
        paper_dir,
        ledger_status={"T-1": "referee-passed"},
        results={"pi_approx": 3.14159},
    )
    assert "E_NUMBER_UNTRACKED" not in _codes(report.errors)


def test_number_untracked_fails(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
The constant is $2.718281828$.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_NUMBER_UNTRACKED" in _codes(report.errors)


def test_number_skips_years_and_small_integers(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
In 2024 we found exactly 42 examples out of 512 attempts.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_NUMBER_UNTRACKED" not in _codes(report.errors)


def test_number_skips_inside_numref_label_cite_url(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}\label{thm:99999}
See \numref{widget-count-123456} and \url{https://example.com/99999.888}.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_NUMBER_UNTRACKED" not in _codes(report.errors)


def test_scientific_notation_always_tracked(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
The value is $6.02e23$.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report_fail = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_NUMBER_UNTRACKED" in _codes(report_fail.errors)

    report_pass = check(
        paper_dir,
        ledger_status={"T-1": "referee-passed"},
        results={"avogadro": 6.02e23},
    )
    assert "E_NUMBER_UNTRACKED" not in _codes(report_pass.errors)


def test_times10_scientific_notation_tracked(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
The value is $6.022 \times 10^{23}$.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report_pass = check(
        paper_dir,
        ledger_status={"T-1": "referee-passed"},
        results={"avogadro": 6.022e23},
    )
    assert "E_NUMBER_UNTRACKED" not in _codes(report_pass.errors)


# --------------------------------------------------------------------------
# check.py: hedge words
# --------------------------------------------------------------------------


def test_hedge_without_cite_or_ref_is_warning(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
It is well known that widgets commute.
\end{theorem}
\begin{proof}
Proof. \keystep{the new step}
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "W_HEDGE" in _codes(report.warnings)
    assert report.ok  # warning only, not fatal


def test_hedge_with_cite_is_not_flagged(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
It is well known that widgets commute \cite{foo2020}.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "W_HEDGE" not in _codes(report.warnings)


def test_hedge_strict_mode_is_error(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Clearly, widgets commute.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={}, strict=True)
    assert "E_HEDGE" in _codes(report.errors)
    assert not report.ok


# --------------------------------------------------------------------------
# check.py: TODO / placeholders
# --------------------------------------------------------------------------


def test_todo_marker_is_warning(tmp_path: Path) -> None:
    tex = "Some text. % TODO: fill this in\nMore text with ?? unresolved."
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={}, results={})
    assert "W_TODO" in _codes(report.warnings)


def test_placeholder_remaining_is_error(tmp_path: Path) -> None:
    tex = "The title is {{TITLE}} and it is unresolved."
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={}, results={})
    assert "E_PLACEHOLDER" in _codes(report.errors)
    assert not report.ok


def test_no_placeholder_when_resolved(tmp_path: Path) -> None:
    tex = "The title is My Paper and it is resolved."
    paper_dir = _write_paper(tmp_path, tex)
    report = check(paper_dir, ledger_status={}, results={})
    assert "E_PLACEHOLDER" not in _codes(report.errors)


# --------------------------------------------------------------------------
# check.py: flatten_tex (\input / \IfFileExists) and check.json output
# --------------------------------------------------------------------------


def test_flatten_tex_resolves_input() -> None:
    from harness.paper.check import flatten_tex

    def _mk(tmp_path: Path) -> Path:
        paper_dir = tmp_path / "paper"
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "sub.tex").write_text("\\label{lbl:sub}\nSub content.", encoding="utf-8")
        (paper_dir / "main.tex").write_text("Intro.\n\\input{sub}\nOutro.", encoding="utf-8")
        return paper_dir

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        paper_dir = _mk(Path(td))
        flat = flatten_tex(paper_dir / "main.tex", paper_dir)
        assert "Sub content." in flat
        assert "\\label{lbl:sub}" in flat


def test_check_resolves_labels_across_input(tmp_path: Path) -> None:
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "sub.tex").write_text(
        "\\begin{theorem}\\claim{T-1}\\label{thm:sub}\nSub statement.\n\\end{theorem}\n"
        "\\begin{proof}\nSub proof.\n\\end{proof}\n",
        encoding="utf-8",
    )
    (paper_dir / "main.tex").write_text(
        "Intro.\n\\input{sub}\nSee~\\ref{thm:sub}.",
        encoding="utf-8",
    )
    report = check(paper_dir, ledger_status={"T-1": "referee-passed"}, results={})
    assert "E_UNDEF_REF" not in _codes(report.errors)
    assert "E_THEOREM_NO_PROOF" not in _codes(report.errors)


def test_check_iffileexists_true_branch(tmp_path: Path) -> None:
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "appendix-repro.tex").write_text("Appendix content 424242.", encoding="utf-8")
    (paper_dir / "main.tex").write_text(
        "Body.\n\\IfFileExists{appendix-repro.tex}{\\input{appendix-repro}}{Fallback text.}",
        encoding="utf-8",
    )
    from harness.paper.check import flatten_tex

    flat = flatten_tex(paper_dir / "main.tex", paper_dir)
    assert "Appendix content" in flat
    assert "Fallback text." not in flat


def test_check_iffileexists_false_branch(tmp_path: Path) -> None:
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "main.tex").write_text(
        "Body.\n\\IfFileExists{appendix-repro.tex}{\\input{appendix-repro}}{Fallback text.}",
        encoding="utf-8",
    )
    from harness.paper.check import flatten_tex

    flat = flatten_tex(paper_dir / "main.tex", paper_dir)
    assert "Fallback text." in flat


def test_check_writes_check_json(tmp_path: Path) -> None:
    tex = "Plain text, no theorems."
    paper_dir = _write_paper(tmp_path, tex, bib=None)
    report = check(paper_dir, ledger_status={}, results={})
    check_json_path = paper_dir / "check.json"
    assert check_json_path.exists()
    data = json.loads(check_json_path.read_text(encoding="utf-8"))
    assert data["ok"] == report.ok
    assert "checked_at" in data and data["checked_at"]


def test_check_results_missing_is_warning(tmp_path: Path) -> None:
    tex = "Plain text, no theorems, no numbers here."
    paper_dir = _write_paper(tmp_path, tex, bib=None)
    # No results.json anywhere under paper_dir.parent, and results not passed.
    report = check(paper_dir, ledger_status={})
    assert "W_RESULTS_MISSING" in _codes(report.warnings)


def test_check_ledger_defaults_to_empty_when_missing(tmp_path: Path) -> None:
    tex = r"""
\begin{theorem}\claim{T-1}
Statement.
\end{theorem}
\begin{proof}
Proof.
\end{proof}
"""
    paper_dir = _write_paper(tmp_path, tex)
    # No ledger_status passed, and no ledger.json next to paper_dir -> treated as empty.
    report = check(paper_dir, results={})
    assert "E_CLAIM_UNKNOWN" in _codes(report.errors)


# --------------------------------------------------------------------------
# repro.py: escape_latex
# --------------------------------------------------------------------------


def test_escape_latex_all_specials() -> None:
    raw = r"a_b % c & d # e $ f { g } h ~ i ^ j \ k"
    escaped = escape_latex(raw)
    assert r"\_" in escaped
    assert r"\%" in escaped
    assert r"\&" in escaped
    assert r"\#" in escaped
    assert r"\$" in escaped
    assert r"\{" in escaped
    assert r"\}" in escaped
    assert r"\textasciitilde{}" in escaped
    assert r"\textasciicircum{}" in escaped
    assert r"\textbackslash{}" in escaped


def test_escape_latex_handles_none_and_numbers() -> None:
    assert escape_latex(None) == ""
    assert escape_latex(42) == "42"
    assert escape_latex(3.14) == "3.14"


# --------------------------------------------------------------------------
# repro.py: write_appendix
# --------------------------------------------------------------------------


def _write_synthetic_campaign(tmp_path: Path) -> Path:
    campaign_dir = tmp_path / "campaign"
    experiments_dir = campaign_dir / "experiments"
    experiments_dir.mkdir(parents=True, exist_ok=True)

    script_path = experiments_dir / "compute_bound.py"
    script_path.write_text("print(1)\n", encoding="utf-8")

    ledger = {
        "claims": {
            "T-001": {
                "id": "T-001",
                "kind": "theorem",
                "status": "referee-passed",
                "stale": False,
                "evidence": [
                    {
                        "type": "computation",
                        "path": "experiments/compute_bound.py",
                        "sha256": "abcdef0123456789",
                        "summary": "Computed the bound_1 value numerically.",
                    }
                ],
            }
        }
    }
    (campaign_dir / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")

    results = {
        "bound_1": 3.14159,
        "note": {"value": 42, "source": "compute_bound.py"},
    }
    (experiments_dir / "results.json").write_text(json.dumps(results), encoding="utf-8")

    return campaign_dir


def test_write_appendix_creates_file_with_expected_sections(tmp_path: Path) -> None:
    campaign_dir = _write_synthetic_campaign(tmp_path)
    out_path = write_appendix(campaign_dir)

    assert out_path == campaign_dir / "paper" / "appendix-repro.tex"
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")

    assert "Environment" in text
    assert "Installed packages" in text
    assert "Ledger evidence" in text
    assert "T-001" in text
    assert "computation" in text
    assert "abcdef012345" in text  # first 12 chars of the sha256
    assert "Computed the bound" in text
    assert "Computed quantities" in text
    assert "3.14159" in text
    assert "How to reproduce" in text
    assert "python " in text
    # underscore in the path must be escaped for LaTeX
    assert "compute\\_bound.py" in text


def test_write_appendix_tolerates_missing_ledger_and_results(tmp_path: Path) -> None:
    campaign_dir = tmp_path / "empty_campaign"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    out_path = write_appendix(campaign_dir)
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "No computation, falsification, or formalization evidence" in text
    assert "No entries found" in text


# --------------------------------------------------------------------------
# build.py: find_tectonic + an actual compile (skipped if tectonic missing)
# --------------------------------------------------------------------------


def test_find_tectonic_returns_path_or_none() -> None:
    result = find_tectonic()
    assert result is None or isinstance(result, Path)


@pytest.mark.timeout(600)
def test_build_example_produces_pdf(tmp_path: Path) -> None:
    if find_tectonic() is None:
        pytest.skip("tectonic not available in harness.BIN or PATH")

    import shutil

    paper_dir = tmp_path / "paper"
    shutil.copytree(EXAMPLE_DIR, paper_dir)

    result: BuildResult = build(paper_dir, timeout=600)
    assert result.ok, result.log[-4000:]
    assert result.pdf is not None
    assert result.pdf.exists()
    assert result.pdf.stat().st_size > 10 * 1024
