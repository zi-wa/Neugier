"""Offline unit tests for harness.lit, plus a few polite live smoke tests.

Run offline tests only:
    .venv/Scripts/python.exe -m pytest tests/test_lit.py -q -m "not live"
Run live tests (hits real APIs; kept few and polite):
    .venv/Scripts/python.exe -m pytest tests/test_lit.py -q -m live
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.lit import arxiv, bib, oeis, sources
from harness.lit.models import Paper

# --------------------------------------------------------------------------
# Atom parsing
# --------------------------------------------------------------------------

ATOM_FIXTURE = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query: search_query=all:sum-product</title>
  <opensearch:totalResults>2</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2607.29042v1</id>
    <updated>2026-07-31T05:43:56Z</updated>
    <published>2026-07-31T05:43:56Z</published>
    <title>  The Entropic
      Sum-Product Phenomenon</title>
    <summary>  We prove an entropic analog of the sum-product phenomenon.
    </summary>
    <author><name>Rupert Li</name></author>
    <arxiv:comment>40 pages</arxiv:comment>
    <category term="cs.IT" scheme="http://arxiv.org/schemas/atom"/>
    <category term="math.CO" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:primary_category term="cs.IT" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1201.0001v2</id>
    <updated>2012-01-02T00:00:00Z</updated>
    <published>2012-01-01T00:00:00Z</published>
    <title>A Classical Result on Sums and Products</title>
    <summary>An older classical result.</summary>
    <author><name>Jean Bourgain</name></author>
    <author><name>Someone Else</name></author>
    <arxiv:doi>10.1234/example.doi</arxiv:doi>
    <arxiv:journal_ref>J. Fake Math. 1 (2012) 1-10</arxiv:journal_ref>
    <category term="math.CO" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:primary_category term="math.CO" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""


def test_parse_atom_basic_fields():
    papers = arxiv.parse_atom(ATOM_FIXTURE)
    assert len(papers) == 2

    p0 = papers[0]
    assert isinstance(p0, Paper)
    assert p0.id == "arxiv:2607.29042"
    assert p0.arxiv_id == "2607.29042"
    # whitespace/newlines inside <title> must be collapsed
    assert p0.title == "The Entropic Sum-Product Phenomenon"
    assert p0.authors == ["Rupert Li"]
    assert p0.year == 2026
    assert "cs.IT" in p0.categories and "math.CO" in p0.categories
    assert p0.extra["primary_category"] == "cs.IT"
    assert p0.extra["version"] == "1"
    assert p0.doi is None
    assert p0.url == "https://arxiv.org/abs/2607.29042"


def test_parse_atom_doi_and_multi_author():
    papers = arxiv.parse_atom(ATOM_FIXTURE)
    p1 = papers[1]
    assert p1.arxiv_id == "1201.0001"
    assert p1.authors == ["Jean Bourgain", "Someone Else"]
    assert p1.doi == "10.1234/example.doi"
    assert p1.extra["journal_ref"] == "J. Fake Math. 1 (2012) 1-10"
    assert p1.year == 2012


def test_clean_id_normalizes_various_forms():
    assert arxiv.clean_id("2607.29042") == "2607.29042"
    assert arxiv.clean_id("arXiv:2607.29042v2") == "2607.29042"
    assert arxiv.clean_id("http://arxiv.org/abs/2607.29042v1") == "2607.29042"


# --------------------------------------------------------------------------
# TeX comment stripping / flattening
# --------------------------------------------------------------------------


def test_strip_comments_respects_escaped_percent():
    text = "abc % this is a comment\nfoo \\% bar % another comment\nbaz"
    out = sources.strip_comments(text)
    lines = out.split("\n")
    assert lines[0] == "abc "
    assert lines[1] == "foo \\% bar "
    assert lines[2] == "baz"


def test_strip_comments_removes_comment_environment():
    text = (
        "before\n"
        "\\begin{comment}\n"
        "this is hidden and should not appear\n"
        "\\end{comment}\n"
        "after"
    )
    out = sources.strip_comments(text)
    assert "hidden" not in out
    assert "before" in out
    assert "after" in out


def test_flatten_tex_inlines_input_recursively(tmp_path: Path):
    main_tex = tmp_path / "main.tex"
    sub_tex = tmp_path / "sub.tex"
    subsub_tex = tmp_path / "subsub.tex"

    with open(main_tex, "w", encoding="utf-8") as f:
        f.write("\\documentclass{article}\n\\begin{document}\n\\input{sub}\n\\end{document}\n")
    with open(sub_tex, "w", encoding="utf-8") as f:
        f.write("intro text\n\\include{subsub}\nmore text % trailing comment\n")
    with open(subsub_tex, "w", encoding="utf-8") as f:
        f.write("deeply nested content\n")

    flattened = sources.flatten_tex(main_tex, tmp_path)

    assert "\\input{sub}" not in flattened
    assert "\\include{subsub}" not in flattened
    assert "intro text" in flattened
    assert "deeply nested content" in flattened
    assert "more text" in flattened
    assert "trailing comment" not in flattened


def test_flatten_tex_avoids_infinite_recursion_on_cycle(tmp_path: Path):
    a_tex = tmp_path / "a.tex"
    b_tex = tmp_path / "b.tex"
    with open(a_tex, "w", encoding="utf-8") as f:
        f.write("A start\n\\input{b}\nA end\n")
    with open(b_tex, "w", encoding="utf-8") as f:
        f.write("B start\n\\input{a}\nB end\n")

    # Must terminate rather than recurse forever.
    flattened = sources.flatten_tex(a_tex, tmp_path)
    assert "A start" in flattened
    assert "B start" in flattened


# --------------------------------------------------------------------------
# theorem_environments / find_excerpts
# --------------------------------------------------------------------------


def test_theorem_environments_extracts_env_label_body():
    text = (
        "\\section{Introduction}\n"
        "Some intro text.\n"
        "\\begin{theorem}\\label{thm:main}\n"
        "For all $x$, $x = x$.\n"
        "\\end{theorem}\n"
        "\\begin{lemma}\n"
        "A lemma with no label.\n"
        "\\end{lemma}\n"
    )
    envs = sources.theorem_environments(text)
    assert len(envs) == 2

    thm = envs[0]
    assert thm["env"] == "theorem"
    assert thm["label"] == "thm:main"
    assert "x = x" in thm["body"]
    assert thm["char_offset"] == text.index("\\begin{theorem}")

    lem = envs[1]
    assert lem["env"] == "lemma"
    assert lem["label"] is None
    assert "no label" in lem["body"]


def test_find_excerpts_locator_and_section_context():
    text = (
        "filler " * 20
        + "\\section{Main Results}\n"
        + "padding " * 10
        + "our key lemma establishes the bound directly.\n"
    )
    idx = text.find("key lemma")
    excerpts = sources.find_excerpts(text, ["key lemma"], window=40)
    assert len(excerpts) == 1
    exc = excerpts[0]
    assert exc["locator"].startswith(f"char:{idx}")
    assert "section:Main Results" in exc["locator"]
    assert "key lemma" in exc["excerpt"]


def test_find_excerpts_no_match_returns_empty():
    assert sources.find_excerpts("nothing interesting here", ["quasiperiodic"], window=100) == []


# --------------------------------------------------------------------------
# bib key generation
# --------------------------------------------------------------------------


def test_make_key_is_ascii_and_uses_lastname_year():
    paper = Paper(
        id="arxiv:1201.0001",
        source="arxiv",
        title="Around the Sum-Product Phenomenon",
        authors=["Jean Bourgain"],
        year=2013,
    )
    key = bib._make_key(paper)
    assert key.startswith("Bourgain2013")
    assert key.isascii()
    assert len(key) > len("Bourgain2013")


def test_make_key_strips_non_ascii_accents():
    paper = Paper(
        id="arxiv:0000.00001",
        source="arxiv",
        title="A Result on Loewner Chains",
        authors=["Karl Loewner"],
        year=1923,
    )
    # Simulate an accented surname as would come from a real record.
    paper.authors = ["Karl L\u00f6wner"]  # "Karl Löwner"
    key = bib._make_key(paper)
    assert key.isascii()
    assert key.startswith("Lowner1923")


def test_make_key_handles_missing_year_and_authors():
    paper = Paper(id="arxiv:x", source="arxiv", title="Untitled Work", authors=[], year=None)
    key = bib._make_key(paper)
    assert key.isascii()
    assert "Unknown" in key
    assert "nd" in key


# --------------------------------------------------------------------------
# OEIS JSON shape handling
# --------------------------------------------------------------------------


def test_oeis_extract_results_handles_bare_list():
    data = [{"number": 108, "keyword": "core,nonn"}]
    assert oeis._extract_results(data) == data


def test_oeis_extract_results_handles_results_wrapper():
    data = {"count": 1, "results": [{"number": 108}]}
    assert oeis._extract_results(data) == [{"number": 108}]


def test_oeis_extract_results_handles_null():
    assert oeis._extract_results(None) == []


def test_oeis_extract_results_handles_dict_without_results():
    assert oeis._extract_results({"count": 0}) == []


def test_oeis_conjectures_finds_matching_lines():
    entry = {
        "comment": [
            "This is unrelated.",
            "It is conjectured that a(n) grows like n^2.",
        ],
        "formula": ["a(n) = n^2 (conjectural)."],
    }
    lines = oeis.conjectures(entry)
    assert len(lines) == 2
    assert any("conjectured" in ln for ln in lines)
    assert any("conjectural" in ln for ln in lines)


def test_oeis_keywords_splits_comma_string():
    entry = {"keyword": "core,nonn,easy,eigen,nice,changed"}
    kws = oeis.keywords(entry)
    assert kws == ["core", "nonn", "easy", "eigen", "nice", "changed"]


def test_oeis_normalize_anumber():
    assert oeis._normalize_anumber("108") == "A000108"
    assert oeis._normalize_anumber("A000108") == "A000108"
    assert oeis._normalize_anumber("a108") == "A000108"


# --------------------------------------------------------------------------
# Live tests (real network calls) -- kept few and polite.
# --------------------------------------------------------------------------


@pytest.mark.live
def test_arxiv_search_live():
    from harness.lit import arxiv as arxiv_mod

    papers = arxiv_mod.search("sum-product", max_results=5)
    assert len(papers) >= 1
    assert all(p.id.startswith("arxiv:") for p in papers)


@pytest.mark.live
def test_fetch_fulltext_live(tmp_path: Path):
    from harness.lit import sources as sources_mod

    ft = sources_mod.fetch_fulltext("2607.29042", tmp_path)
    assert ft.kind in ("tex", "html")
    assert ft.char_count > 5000


@pytest.mark.live
def test_openalex_search_live():
    from harness.lit import openalex as openalex_mod

    papers = openalex_mod.search_works("sum-product phenomenon", per_page=5)
    assert len(papers) >= 1


@pytest.mark.live
def test_oeis_get_live():
    from harness.lit import oeis as oeis_mod

    entry = oeis_mod.get("A000108")
    assert entry is not None
    assert "core" in oeis_mod.keywords(entry)


@pytest.mark.live
def test_bib_resolve_live():
    from harness.lit import bib as bib_mod

    entry = bib_mod.resolve("2607.29042")
    assert entry is not None
    assert entry.resolved is True
