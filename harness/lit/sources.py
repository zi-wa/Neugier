"""Full-text acquisition and analysis for arXiv papers.

:func:`fetch_fulltext` implements a fallback chain: LaTeX source (flattened,
comments stripped) -> HTML rendering (tags stripped, math alttext kept) ->
PDF text extraction via PyMuPDF. :func:`find_excerpts` and
:func:`theorem_environments` then work over the resulting plain text (most
useful on ``kind="tex"`` text, which retains ``\\section``/theorem-environment
structure).
"""
from __future__ import annotations

import gzip
import re
import sys
import tarfile
from html.parser import HTMLParser
from pathlib import Path

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz  # legacy PyMuPDF

from harness.lit import arxiv, http
from harness.lit.models import FullText

_MAIN_TEX_HINTS = ("main", "paper", "ms")


def _log(msg: str) -> None:
    print(f"[harness.lit.sources] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# TeX comment stripping / \input flattening
# --------------------------------------------------------------------------

_COMMENT_ENV_RE = re.compile(r"\\begin\{comment\}.*?\\end\{comment\}", re.DOTALL)
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")


def _strip_line_comment(line: str) -> str:
    """Strip a trailing '%...' comment from one line, respecting '\\%' escapes."""
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2  # skip the backslash and whatever it escapes
            continue
        if ch == "%":
            return line[:i]
        i += 1
    return line


def strip_comments(text: str) -> str:
    """Strip '%' line comments (respecting '\\%') and '\\begin{comment}' blocks."""
    text = _COMMENT_ENV_RE.sub("", text)
    return "\n".join(_strip_line_comment(ln) for ln in text.split("\n"))


def _find_main_tex(src_dir: Path) -> Path | None:
    """Find the main .tex file in an extracted arXiv source tree."""
    candidates: list[tuple[Path, str]] = []
    for tf in src_dir.rglob("*.tex"):
        try:
            content = tf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\\documentclass" in content:
            candidates.append((tf, content))

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    for tf, _ in candidates:
        if tf.stem.lower() in _MAIN_TEX_HINTS:
            return tf

    def _include_count(content: str) -> int:
        return len(re.findall(r"\\(?:input|include)\{", content))

    candidates.sort(key=lambda pair: _include_count(pair[1]), reverse=True)
    return candidates[0][0]


def flatten_tex(main_path: Path, base_dir: Path, _seen: set[Path] | None = None) -> str:
    """Recursively inline \\input{}/\\include{} targets, stripping comments as we go."""
    if _seen is None:
        _seen = set()
    resolved = main_path.resolve()
    if resolved in _seen:
        return ""
    _seen.add(resolved)

    try:
        text = main_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _log(f"failed to read {main_path}: {exc}")
        return ""

    text = strip_comments(text)

    def _replace(m: re.Match) -> str:
        fname = m.group(1).strip()
        tried = [fname] if fname.endswith((".tex", ".ltx")) else [fname + ".tex", fname]
        candidate = None
        for name in tried:
            for base in (main_path.parent, base_dir):
                cand = base / name
                if cand.exists():
                    candidate = cand
                    break
            if candidate is not None:
                break
        if candidate is None:
            _log(f"could not resolve \\input/\\include target: {fname!r}")
            return ""
        return flatten_tex(candidate, base_dir, _seen)

    return _INPUT_RE.sub(_replace, text)


def _extract_targz(archive_path: Path, dest_dir: Path) -> None:
    with tarfile.open(archive_path, mode="r:gz") as tf:
        tf.extractall(dest_dir, filter="data")


# --------------------------------------------------------------------------
# HTML -> text (arxiv.org/html/<id>)
# --------------------------------------------------------------------------

_HTML_BLOCK_TAGS = {
    "p", "div", "li", "br", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "tr", "table",
}


class _HTMLToText(HTMLParser):
    """Strip tags to plain text; keep <math alttext=...> / tex <annotation> content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._math_depth = 0
        self._math_has_alttext = False
        self._in_tex_annotation = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs_d = dict(attrs)
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if tag == "math":
            self._math_depth += 1
            alttext = attrs_d.get("alttext")
            if alttext:
                self._parts.append(f" {alttext} ")
                self._math_has_alttext = True
            else:
                self._math_has_alttext = False
            return
        if tag == "annotation" and self._math_depth > 0:
            enc = (attrs_d.get("encoding") or "").lower()
            if "tex" in enc and not self._math_has_alttext:
                self._in_tex_annotation = True
            return
        if tag in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # e.g. <br/>
        if tag in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag == "math":
            if self._math_depth > 0:
                self._math_depth -= 1
            self._math_has_alttext = False
            return
        if tag == "annotation":
            self._in_tex_annotation = False
            return
        if tag in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._math_depth > 0:
            if self._in_tex_annotation:
                self._parts.append(data)
            return
        self._parts.append(data)

    def raw_text(self) -> str:
        return "".join(self._parts)


def _collapse_ws(s: str) -> str:
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def html_to_text(html_text: str) -> str:
    """Convert an arXiv HTML rendering to plain text, preserving math as TeX."""
    parser = _HTMLToText()
    parser.feed(html_text)
    parser.close()
    return _collapse_ws(parser.raw_text())


def _pdf_to_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    try:
        parts = [page.get_text() for page in doc]
    finally:
        doc.close()
    return "\n".join(parts)


# --------------------------------------------------------------------------
# fetch_fulltext: the fallback chain
# --------------------------------------------------------------------------


def fetch_fulltext(arxiv_id: str, cache_dir: Path) -> FullText:
    """Fetch the fullest available text for an arXiv paper.

    Tries, in order: (a) tar.gz e-print source, flattened and de-commented;
    (b) a single gzip'd .tex e-print; (c) the arxiv.org/html rendering;
    (d) PyMuPDF text extraction from the PDF. Never raises; on total failure
    returns a ``FullText`` with an empty ``text``.
    """
    aid = arxiv.clean_id(arxiv_id)
    cache_dir = Path(cache_dir)
    safe = aid.replace("/", "_")
    paper_dir = cache_dir / safe
    paper_dir.mkdir(parents=True, exist_ok=True)

    eprint_path: Path | None
    try:
        eprint_path = arxiv.download_eprint(aid, paper_dir)
    except Exception as exc:  # noqa: BLE001
        _log(f"download_eprint({aid!r}) failed: {exc}")
        eprint_path = None

    # (a) tar.gz source
    if eprint_path is not None and eprint_path.name.endswith(".tar.gz"):
        try:
            src_dir = paper_dir / "src"
            if not src_dir.exists() or not any(src_dir.iterdir()):
                src_dir.mkdir(parents=True, exist_ok=True)
                _extract_targz(eprint_path, src_dir)
            main_tex = _find_main_tex(src_dir)
            if main_tex is not None:
                text = flatten_tex(main_tex, src_dir).strip()
                if text:
                    files = [
                        str(p.relative_to(src_dir)) for p in src_dir.rglob("*") if p.is_file()
                    ]
                    return FullText(
                        arxiv_id=aid,
                        kind="tex",
                        text=text,
                        main_file=str(main_tex.relative_to(src_dir)),
                        files=files,
                        char_count=len(text),
                    )
            else:
                _log(f"no main .tex found for {aid} under {src_dir}")
        except Exception as exc:  # noqa: BLE001
            _log(f"tar.gz processing failed for {aid}: {exc}")

    # (b) single gzip'd .tex
    if eprint_path is not None and eprint_path.name.endswith(".tex.gz"):
        try:
            with gzip.open(eprint_path, "rt", encoding="utf-8", errors="replace") as f:
                raw = f.read()
            text = strip_comments(raw).strip()
            if text:
                return FullText(
                    arxiv_id=aid,
                    kind="tex",
                    text=text,
                    main_file=eprint_path.name,
                    files=[eprint_path.name],
                    char_count=len(text),
                )
        except OSError as exc:
            _log(f"gunzip failed for {aid}: {exc}")

    # (c) HTML rendering
    html_text = arxiv.fetch_html(aid)
    if html_text:
        text = html_to_text(html_text).strip()
        if len(text) > 200:
            return FullText(
                arxiv_id=aid,
                kind="html",
                text=text,
                main_file=None,
                files=[],
                char_count=len(text),
            )

    # (d) PDF fallback via PyMuPDF
    pdf_path: Path | None
    if eprint_path is not None and eprint_path.name.endswith(".pdf"):
        pdf_path = eprint_path
    else:
        pdf_path = http.download(f"https://arxiv.org/pdf/{aid}", paper_dir / f"{safe}.pdf")

    if pdf_path is not None and pdf_path.exists():
        try:
            text = _pdf_to_text(pdf_path).strip()
        except Exception as exc:  # noqa: BLE001
            _log(f"pymupdf extraction failed for {aid}: {exc}")
            text = ""
        return FullText(
            arxiv_id=aid,
            kind="pdf",
            text=text,
            main_file=pdf_path.name,
            files=[pdf_path.name],
            char_count=len(text),
        )

    _log(f"all fulltext strategies failed for {aid}")
    return FullText(arxiv_id=aid, kind="pdf", text="", main_file=None, files=[], char_count=0)


# --------------------------------------------------------------------------
# Excerpt search / theorem-environment extraction
# --------------------------------------------------------------------------

_SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")
_ENV_BEGIN_RE = re.compile(
    r"\\begin\{(theorem|lemma|proposition|corollary|definition|conjecture)\}"
)
_LABEL_RE = re.compile(r"\\label\{([^}]*)\}")
_THEOREM_ENVS = ("theorem", "lemma", "proposition", "corollary", "definition", "conjecture")
_ENV_RE = re.compile(
    r"\\begin\{(" + "|".join(_THEOREM_ENVS) + r")\}(?:\[[^\]]*\])?(.*?)\\end\{\1\}",
    re.DOTALL,
)


def _nearest_context(text: str, offset: int) -> str | None:
    """Nearest preceding \\section{} or theorem-like environment, if any."""
    prefix = text[:offset]
    best_pos = -1
    best_desc: str | None = None

    last_section = None
    for m in _SECTION_RE.finditer(prefix):
        last_section = m
    if last_section is not None:
        best_pos = last_section.start()
        best_desc = f"section:{' '.join(last_section.group(1).split())}"

    last_env = None
    for m in _ENV_BEGIN_RE.finditer(prefix):
        last_env = m
    if last_env is not None and last_env.start() > best_pos:
        env_name = last_env.group(1)
        after = text[last_env.end() : last_env.end() + 300]
        label_m = _LABEL_RE.search(after)
        best_desc = f"{env_name}:{label_m.group(1)}" if label_m else env_name

    return best_desc


def find_excerpts(text: str, keywords: list[str], window: int = 600) -> list[dict]:
    """Find occurrences of each keyword, returning a locator + surrounding excerpt.

    ``locator`` is ``"char:<offset>"``, plus the nearest preceding
    ``\\section``/theorem-environment label when one exists in the text.
    """
    results: list[dict] = []
    if not text or not keywords:
        return results

    lower_text = text.lower()
    half = max(1, window // 2)
    for kw in keywords:
        kw_l = kw.lower().strip()
        if not kw_l:
            continue
        start = 0
        while True:
            idx = lower_text.find(kw_l, start)
            if idx == -1:
                break
            begin = max(0, idx - half)
            end = min(len(text), idx + len(kw) + half)
            excerpt = text[begin:end]
            ctx = _nearest_context(text, idx)
            locator = f"char:{idx}" + (f" near {ctx}" if ctx else "")
            results.append({"locator": locator, "excerpt": excerpt, "keyword": kw})
            start = idx + max(1, len(kw_l))
    return results


def theorem_environments(text: str) -> list[dict]:
    """Extract theorem/lemma/proposition/corollary/definition/conjecture blocks."""
    results: list[dict] = []
    for m in _ENV_RE.finditer(text):
        env = m.group(1)
        body = m.group(2).strip()
        label_m = _LABEL_RE.search(body)
        results.append(
            {
                "env": env,
                "label": label_m.group(1) if label_m else None,
                "body": body,
                "char_offset": m.start(),
            }
        )
    return results
