"""Local full-text cache and excerpt provenance verification (rule R5a).

Rule R5a says: *no literature claim without a fetched verbatim excerpt*. Until
Round 2 the ledger only checked that an excerpt was at least 20 characters
long. This module makes the rule real: an excerpt is **verified** when its
normalized text occurs in a cached copy of the source that was fetched by a
tool, never typed from memory.

Cache layout (searched in this order):

* ``campaigns/<slug>/cache/<safe>.txt``  -- per-campaign cache (default for
  ``harness lit fetch`` when a campaign is active)
* ``.cache/lit/fulltext/<safe>.txt``      -- project-wide cache

``<safe>`` is :func:`safe_name` of the ``source_id`` (arXiv id, ``doi:``,
``oeis:``, ``mo:``, ``url:``/``http…`` or a plain bib key). Both a bare
``<safe>.txt`` and the older ``<safe>/<safe>.txt`` layouts are accepted.

Verification is deliberately tolerant of the ways a copied excerpt differs
from the cached text: Unicode normalization (NFKC, ligatures), case, quotes and
dashes, soft hyphens, PDF end-of-line hyphenation and whitespace. If the whole
normalized excerpt is not a substring, a chunk fallback accepts the excerpt when
at least ``chunk_ratio`` of ~40-character chunks are found in order (this
survives a single mangled formula in a long excerpt). An excerpt whose source
has not been cached at all is *unverified* (``verified is None``), which the
ledger treats the same as *not found* unless the caller explicitly opts in.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import harness
from harness.verify.exact import sha256_file, sha256_text

_ARXIV_RE = re.compile(r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?)$", re.IGNORECASE)
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Characters that copy/paste and PDF extraction routinely alter.
_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
    "­": "",  # soft hyphen
    "​": "",  # zero-width space
})


@dataclass
class ExcerptCheck:
    """Result of :func:`verify_excerpt`.

    ``verified`` is ``True`` (found), ``False`` (source cached but excerpt not
    found) or ``None`` (no cached source text for this ``source_id``).
    ``method`` records how the match was made: ``exact`` | ``normalized`` |
    ``chunks`` | ``not-found`` | ``no-source`` | ``too-short``.
    """

    verified: bool | None
    source_path: str | None
    source_sha256: str | None
    excerpt_hash: str
    method: str
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ naming --

def safe_name(source_id: str) -> str:
    """Filesystem-safe cache stem for a source id.

    ``arxiv:2401.01234v2`` / ``2401.01234`` -> ``2401.01234``; ``math/0601001`` ->
    ``math_0601001``; ``doi:10.1000/x`` -> ``doi_10.1000_x``; ``oeis:A000045`` ->
    ``oeis_A000045``; ``mo:12345`` -> ``mo_12345``; URLs -> ``url_<sha16>``;
    anything else (a bib key) is sanitized as-is.
    """
    sid = source_id.strip()
    low = sid.lower()
    if low.startswith(("http://", "https://", "url:")):
        url = sid[4:] if low.startswith("url:") else sid
        return "url_" + hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]
    if low.startswith("doi:"):
        return "doi_" + _SAFE_RE.sub("_", sid[4:].strip()).strip("_")
    if low.startswith("oeis:"):
        return "oeis_" + sid[5:].strip().upper()
    if low.startswith("mo:"):
        return "mo_" + _SAFE_RE.sub("_", sid[3:].strip()).strip("_")
    if low.startswith("arxiv:"):
        sid = sid[6:].strip()
    if _ARXIV_RE.match(sid):
        from harness.lit import arxiv  # local import: keep this module cheap to import

        return arxiv.clean_id(sid).replace("/", "_")
    return _SAFE_RE.sub("_", sid).strip("_") or "source"


def kind_of(source_id: str) -> str:
    """Coarse source kind: ``arxiv`` | ``doi`` | ``oeis`` | ``mo`` | ``url`` | ``other``."""
    sid = source_id.strip()
    low = sid.lower()
    if low.startswith(("http://", "https://", "url:")):
        return "url"
    for prefix in ("doi", "oeis", "mo"):
        if low.startswith(prefix + ":"):
            return prefix
    if low.startswith("arxiv:") or _ARXIV_RE.match(sid):
        return "arxiv"
    return "other"


def fulltext_dir() -> Path:
    """Project-wide full-text cache directory (read fresh so tests can monkeypatch ``harness.CACHE``)."""
    return Path(harness.CACHE) / "lit" / "fulltext"


def active_campaign_dir() -> Path | None:
    """``campaigns/<slug>`` for the active campaign (``campaigns/ACTIVE``), if any."""
    marker = Path(harness.CAMPAIGNS) / "ACTIVE"
    try:
        slug = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not slug:
        return None
    return Path(harness.CAMPAIGNS) / slug


def cache_dirs(campaign_dir: Path | str | None = None) -> list[Path]:
    dirs: list[Path] = []
    if campaign_dir is not None:
        dirs.append(Path(campaign_dir) / "cache")
    dirs.append(fulltext_dir())
    return dirs


def _candidate_files(directory: Path, safe: str) -> list[Path]:
    return [
        directory / f"{safe}.txt",
        directory / safe / f"{safe}.txt",
        directory / safe / "fulltext.txt",
        directory / safe,
    ]


def find_cached_text(source_id: str, campaign_dir: Path | str | None = None) -> Path | None:
    """Path of the cached full text for ``source_id`` (campaign cache first), or ``None``."""
    stems = [safe_name(source_id)]
    raw = _SAFE_RE.sub("_", source_id.strip()).strip("_")
    if raw and raw not in stems:
        stems.append(raw)
    for directory in cache_dirs(campaign_dir):
        for stem in stems:
            for cand in _candidate_files(directory, stem):
                if cand.is_file():
                    return cand
    return None


# ------------------------------------------------------------ normalization --

def normalize_for_match(text: str) -> str:
    """Normalize text so that copy/paste and PDF extraction artefacts do not break matching."""
    s = unicodedata.normalize("NFKC", text)
    s = s.translate(_TRANSLATE)
    s = s.replace("≥", ">=").replace("≤", "<=").replace("≠", "!=")
    s = s.replace('"', "").replace("'", "")  # quotes are typography, not content
    s = re.sub(r"-\s*\r?\n\s*", "", s)  # end-of-line hyphenation: "com-\nbin" -> "combin"
    s = s.casefold()
    s = " ".join(s.split())
    return s


def excerpt_hash(excerpt: str) -> str:
    """First 12 hex chars of sha256(normalized excerpt) — the value ``<cite excerpt-hash>`` binds to."""
    return sha256_text(normalize_for_match(excerpt))[:12]


def _chunks(text: str, size: int) -> list[str]:
    words = text.split(" ")
    out: list[str] = []
    cur: list[str] = []
    length = 0
    for w in words:
        cur.append(w)
        length += len(w) + 1
        if length >= size:
            out.append(" ".join(cur))
            cur, length = [], 0
    if cur:
        tail = " ".join(cur)
        if out and len(tail) < size // 2:
            out[-1] = out[-1] + " " + tail
        else:
            out.append(tail)
    return out


# -------------------------------------------------------------- verification --

def verify_excerpt(
    excerpt: str,
    source_id: str,
    campaign_dir: Path | str | None = None,
    *,
    min_chars: int = 20,
    chunk_size: int = 40,
    min_chunks: int = 3,
    chunk_ratio: float = 0.8,
    source_path: Path | str | None = None,
) -> ExcerptCheck:
    """Check that ``excerpt`` occurs in the cached text of ``source_id``.

    ``source_path`` overrides the cache lookup (used by tests and by callers that
    already know the file). See the module docstring for the matching rules.
    """
    ehash = excerpt_hash(excerpt or "")
    if not excerpt or len(excerpt.strip()) < min_chars:
        return ExcerptCheck(False, None, None, ehash, "too-short", f"excerpt shorter than {min_chars} characters")

    path = Path(source_path) if source_path is not None else find_cached_text(source_id, campaign_dir)
    if path is None or not Path(path).is_file():
        return ExcerptCheck(None, None, None, ehash, "no-source", f"no cached full text for {source_id!r}")

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    sha = sha256_file(path)
    rel = str(path)

    if excerpt.strip() in text:
        return ExcerptCheck(True, rel, sha, ehash, "exact")

    nx = normalize_for_match(excerpt)
    nt = normalize_for_match(text)
    if nx and nx in nt:
        return ExcerptCheck(True, rel, sha, ehash, "normalized")

    chunks = _chunks(nx, chunk_size)
    if len(chunks) >= min_chunks:
        found = 0
        pos = 0
        for ch in chunks:
            idx = nt.find(ch, pos)
            if idx >= 0:
                found += 1
                pos = idx + len(ch)
        ratio = found / len(chunks)
        if ratio >= chunk_ratio:
            return ExcerptCheck(True, rel, sha, ehash, "chunks", f"{found}/{len(chunks)} chunks found in order")
        return ExcerptCheck(False, rel, sha, ehash, "not-found", f"only {found}/{len(chunks)} chunks found in order")
    return ExcerptCheck(False, rel, sha, ehash, "not-found", "normalized excerpt is not a substring of the cached text")


# ------------------------------------------------------------------ fetching --

def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _oeis_text(entry: dict) -> str:
    lines: list[str] = []
    number = entry.get("number")
    if number is not None:
        lines.append(f"A{int(number):06d}")
    for key in ("name", "data", "comment", "formula", "example", "reference", "link", "keyword", "author"):
        val = entry.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            lines.append(f"%{key}")
            lines.extend(str(v) for v in val)
        else:
            lines.append(f"%{key} {val}")
    return "\n".join(lines) + "\n"


def fetch_to_cache(source_id: str, out_dir: Path | str) -> Path | None:
    """Fetch the full text of ``source_id`` into ``out_dir/<safe>.txt``; ``None`` on failure.

    arXiv ids go through :func:`harness.lit.sources.fetch_fulltext` (TeX source →
    HTML → PDF); ``oeis:`` entries are dumped as ``%field`` lines; URLs/DOIs are
    downloaded and converted (HTML → text, PDF → text). MathOverflow ids are not
    fetchable here (use ``harness lit search --engine mo`` and record the URL).
    Never raises.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = safe_name(source_id)
    dest = out_dir / f"{safe}.txt"
    kind = kind_of(source_id)
    try:
        if kind == "arxiv":
            from harness.lit import sources

            ft = sources.fetch_fulltext(source_id.strip().removeprefix("arxiv:").removeprefix("arXiv:"), out_dir)
            if not ft.text:
                return None
            return _write_text(dest, ft.text)
        if kind == "oeis":
            from harness.lit import oeis

            entry = oeis.get(source_id.split(":", 1)[1])
            if not entry:
                return None
            return _write_text(dest, _oeis_text(entry))
        if kind in ("url", "doi"):
            from harness.lit import http, sources

            sid = source_id.strip()
            url = sid[4:] if sid.lower().startswith("url:") else sid
            if kind == "doi":
                url = "https://doi.org/" + sid[4:].strip()
            if url.lower().endswith(".pdf"):
                pdf = http.download(url, out_dir / f"{safe}.pdf")
                if pdf is None:
                    return None
                text = sources._pdf_to_text(Path(pdf))
            else:
                raw = http.get_text(url)
                if not raw:
                    return None
                text = sources.html_to_text(raw) if "<" in raw[:2000] else raw
            if not text.strip():
                return None
            return _write_text(dest, text)
    except Exception as exc:  # noqa: BLE001 - never raise from a fetch helper
        import sys

        print(f"[harness.lit.cache] fetch_to_cache({source_id!r}) failed: {exc}", file=sys.stderr)
        return None
    return None


def check_to_json(check: ExcerptCheck) -> str:
    return json.dumps(check.to_dict(), ensure_ascii=False, indent=2)
