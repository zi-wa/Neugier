"""arXiv client: search, single-record lookup, e-print download, HTML fetch.

Uses the public Atom-based API at ``https://export.arxiv.org/api/query`` for
metadata, and the ``arxiv.org`` mirrors for full-text sources.
"""
from __future__ import annotations

import re
import sys
import tarfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness.lit import http
from harness.lit.models import Paper

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
NS = {"atom": ATOM_NS, "arxiv": ARXIV_NS}

_ID_RE = re.compile(r"arxiv\.org/abs/(?P<id>[^v]+?)(v(?P<version>\d+))?$", re.IGNORECASE)
_FIELD_PREFIXES = ("all:", "ti:", "au:", "abs:", "cat:", "co:", "jr:", "id:")


def _log(msg: str) -> None:
    print(f"[harness.lit.arxiv] {msg}", file=sys.stderr)


def _clean_id(arxiv_id: str) -> str:
    """Normalize a raw id/URL/prefixed-id into the bare arXiv identifier (no version)."""
    aid = arxiv_id.strip()
    aid = aid.removeprefix("arxiv:").removeprefix("arXiv:")
    m = _ID_RE.search(aid)
    if m:
        return m.group("id")
    return re.sub(r"v\d+$", "", aid)


def clean_id(arxiv_id: str) -> str:
    """Public wrapper: normalize a raw id/URL/prefixed-id to a bare arXiv id."""
    return _clean_id(arxiv_id)


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return " ".join(el.text.split())


def _build_search_query(query: str, categories: list[str] | None) -> str:
    q = query.strip()
    has_field = any(tok in q for tok in _FIELD_PREFIXES)
    base = q if has_field else f"all:{q}"
    if categories:
        cat_q = " OR ".join(f"cat:{c}" for c in categories)
        base = f"({base}) AND ({cat_q})"
    return base


def _parse_entry(entry: ET.Element) -> Paper:
    id_el = entry.find("atom:id", NS)
    raw_id = (id_el.text or "").strip() if id_el is not None else ""
    m = _ID_RE.search(raw_id)
    if m:
        arxiv_id = m.group("id")
        version = m.group("version")
    else:
        arxiv_id = raw_id.rsplit("/", 1)[-1]
        version = None

    title = _text(entry.find("atom:title", NS))
    summary = _text(entry.find("atom:summary", NS))
    authors = [
        name
        for a in entry.findall("atom:author", NS)
        if (name := _text(a.find("atom:name", NS)))
    ]
    published = _text(entry.find("atom:published", NS))
    updated = _text(entry.find("atom:updated", NS))
    year = int(published[:4]) if published[:4].isdigit() else None

    categories = [c.get("term") for c in entry.findall("atom:category", NS) if c.get("term")]
    primary_el = entry.find("arxiv:primary_category", NS)
    primary = primary_el.get("term") if primary_el is not None else None

    doi_el = entry.find("arxiv:doi", NS)
    doi = _text(doi_el) or None

    comment = _text(entry.find("arxiv:comment", NS)) or None
    journal_ref = _text(entry.find("arxiv:journal_ref", NS)) or None

    return Paper(
        id=f"arxiv:{arxiv_id}",
        source="arxiv",
        title=title,
        authors=authors,
        year=year,
        abstract=summary,
        doi=doi,
        arxiv_id=arxiv_id,
        url=f"https://arxiv.org/abs/{arxiv_id}",
        categories=categories,
        cited_by_count=None,
        extra={
            "version": version,
            "published": published,
            "updated": updated,
            "primary_category": primary,
            "comment": comment,
            "journal_ref": journal_ref,
        },
    )


def parse_atom(xml_text: str) -> list[Paper]:
    """Parse an arXiv Atom feed (as returned by the query API) into Papers."""
    root = ET.fromstring(xml_text)
    return [_parse_entry(e) for e in root.findall("atom:entry", NS)]


def search(
    query: str,
    max_results: int = 25,
    sort: str = "relevance",
    categories: list[str] | None = None,
) -> list[Paper]:
    """Search arXiv. Never raises: returns [] and logs to stderr on failure."""
    sort_by = "submittedDate" if sort == "submittedDate" else "relevance"
    params = {
        "search_query": _build_search_query(query, categories),
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }
    try:
        text = http.get_text(ARXIV_API, params=params, cache_ns="arxiv", ttl_hours=24)
        if text is None:
            return []
        return parse_atom(text)
    except Exception as exc:  # noqa: BLE001 - search must never raise
        _log(f"search({query!r}) failed: {exc}")
        return []


def get(arxiv_id: str) -> Paper | None:
    """Fetch a single arXiv record by id. Returns None on failure (never raises)."""
    aid = _clean_id(arxiv_id)
    params = {"id_list": aid, "max_results": 1}
    try:
        text = http.get_text(ARXIV_API, params=params, cache_ns="arxiv", ttl_hours=24 * 7)
        if text is None:
            return None
        papers = parse_atom(text)
        return papers[0] if papers else None
    except Exception as exc:  # noqa: BLE001
        _log(f"get({arxiv_id!r}) failed: {exc}")
        return None


def fetch_html(arxiv_id: str) -> str | None:
    """Fetch the HTML rendering of a paper from arxiv.org/html/<id>, if it exists."""
    aid = _clean_id(arxiv_id)
    url = f"https://arxiv.org/html/{aid}"
    return http.get_text(url, cache_ns="arxiv", ttl_hours=24 * 7)


def download_eprint(arxiv_id: str, dest_dir: Path | str) -> Path:
    """Download the e-print source for ``arxiv_id`` into ``dest_dir``.

    The e-print may be a gzip'd tarball, a gzip'd single .tex file, or (for
    older/PDF-only submissions) a raw PDF. This detects the actual content by
    magic bytes and saves it with the matching extension (.tar.gz, .tex.gz,
    or .pdf; unrecognized content falls back to .bin).

    Unlike the ``search``-style functions, this raises on failure (callers
    such as ``sources.fetch_fulltext`` catch it as part of a fallback chain).
    """
    aid = _clean_id(arxiv_id)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = aid.replace("/", "_")
    raw_path = dest_dir / f"{safe}.download"
    url = f"https://arxiv.org/e-print/{aid}"

    result = http.download(url, raw_path)
    if result is None:
        raise RuntimeError(f"failed to download e-print for {aid!r} from {url}")

    with open(result, "rb") as f:
        head = f.read(4)

    if head.startswith(b"%PDF"):
        ext = ".pdf"
    elif head[:2] == b"\x1f\x8b":
        ext = ".tar.gz" if tarfile.is_tarfile(result) else ".tex.gz"
    else:
        ext = ".bin"

    final_path = dest_dir / f"{safe}{ext}"
    if final_path != result:
        if final_path.exists():
            final_path.unlink()
        result.replace(final_path)
    return final_path


def recent(category: str, days: int = 7, max_results: int = 100) -> list[Paper]:
    """Recent submissions in ``category`` within the last ``days`` days."""
    papers = search(f"cat:{category}", max_results=max_results, sort="submittedDate")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for p in papers:
        published = p.extra.get("published") or ""
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt >= cutoff:
            out.append(p)
    return out
