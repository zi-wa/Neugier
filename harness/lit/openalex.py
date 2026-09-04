"""OpenAlex client: work search, single-record lookup, citation graph walks.

Wraps ``https://api.openalex.org/works``. Set the ``OPENALEX_MAILTO`` env var
to identify requests via OpenAlex's polite pool (optional, recommended).
"""
from __future__ import annotations

import os
import sys

from harness.lit import http
from harness.lit.models import Paper

WORKS_URL = "https://api.openalex.org/works"

SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "authorships",
        "abstract_inverted_index",
        "primary_location",
        "concepts",
        "cited_by_count",
        "referenced_works",
        "ids",
    ]
)


def _log(msg: str) -> None:
    print(f"[harness.lit.openalex] {msg}", file=sys.stderr)


def _add_mailto(params: dict) -> None:
    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto


def _clean_id(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.strip().removeprefix("openalex:")
    if s.startswith("http"):
        s = s.rstrip("/").rsplit("/", 1)[-1]
    return s


def _reconstruct_abstract(inv_index: dict | None) -> str:
    """Rebuild plaintext abstract from OpenAlex's abstract_inverted_index."""
    if not inv_index:
        return ""
    positions: dict[int, str] = {}
    max_pos = 0
    for word, pos_list in inv_index.items():
        for pos in pos_list:
            positions[pos] = word
            if pos > max_pos:
                max_pos = pos
    return " ".join(positions.get(i, "") for i in range(max_pos + 1)).strip()


def _build_filter(filters: dict | None) -> str | None:
    if not filters:
        return None
    parts = []
    for key, value in filters.items():
        if isinstance(value, (list, tuple)):
            parts.append(f"{key}:" + "|".join(str(v) for v in value))
        else:
            parts.append(f"{key}:{value}")
    return ",".join(parts)


def _to_paper(w: dict) -> Paper:
    oid = _clean_id(w.get("id", ""))
    title = w.get("title") or w.get("display_name") or ""

    authors = []
    for a in w.get("authorships") or []:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)

    year = w.get("publication_year")

    doi = w.get("doi")
    if doi:
        doi = doi.removeprefix("https://doi.org/")

    abstract = _reconstruct_abstract(w.get("abstract_inverted_index"))

    primary_loc = w.get("primary_location") or {}
    url = primary_loc.get("landing_page_url") or w.get("id")

    categories = [c.get("display_name") for c in (w.get("concepts") or []) if c.get("display_name")]

    arxiv_id = None
    if doi and "10.48550/arxiv." in doi.lower():
        arxiv_id = doi.lower().split("10.48550/arxiv.")[-1]

    return Paper(
        id=f"openalex:{oid}",
        source="openalex",
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        doi=doi,
        arxiv_id=arxiv_id,
        url=url,
        categories=categories,
        cited_by_count=w.get("cited_by_count"),
        extra={
            "referenced_works": w.get("referenced_works") or [],
            "openalex_id": w.get("id"),
        },
    )


def search_works(
    query: str, per_page: int = 25, filters: dict | None = None
) -> list[Paper]:
    """Search OpenAlex works. Never raises: returns [] and logs on failure."""
    try:
        params: dict = {
            "search": query,
            "per_page": max(1, min(per_page, 200)),
            "select": SELECT_FIELDS,
        }
        filter_str = _build_filter(filters)
        if filter_str:
            params["filter"] = filter_str
        _add_mailto(params)
        data = http.get_json(WORKS_URL, params=params, cache_ns="openalex", ttl_hours=72)
        if not data or "results" not in data:
            return []
        return [_to_paper(w) for w in data["results"]]
    except Exception as exc:  # noqa: BLE001 - search must never raise
        _log(f"search_works({query!r}) failed: {exc}")
        return []


def get_work(id_or_doi: str) -> Paper | None:
    """Fetch a single work by OpenAlex id, DOI, or full URL. None on failure."""
    try:
        ident = id_or_doi.strip().removeprefix("openalex:")
        low = ident.lower()
        if low.startswith("10.") or "doi.org" in low:
            doi = ident.split("doi.org/")[-1]
            url = f"{WORKS_URL}/doi:{doi}"
        elif ident.startswith("http"):
            url = f"{WORKS_URL}/{_clean_id(ident)}"
        else:
            url = f"{WORKS_URL}/{ident}"
        params: dict = {"select": SELECT_FIELDS}
        _add_mailto(params)
        data = http.get_json(url, params=params, cache_ns="openalex", ttl_hours=72)
        if not data or "id" not in data:
            return None
        return _to_paper(data)
    except Exception as exc:  # noqa: BLE001
        _log(f"get_work({id_or_doi!r}) failed: {exc}")
        return None


def cited_by(work_id: str, per_page: int = 50) -> list[Paper]:
    """Works that cite ``work_id``. Never raises: returns [] on failure."""
    try:
        wid = _clean_id(work_id)
        if not wid:
            return []
        params: dict = {
            "filter": f"cites:{wid}",
            "per_page": max(1, min(per_page, 200)),
            "select": SELECT_FIELDS,
        }
        _add_mailto(params)
        data = http.get_json(WORKS_URL, params=params, cache_ns="openalex", ttl_hours=24)
        if not data or "results" not in data:
            return []
        return [_to_paper(w) for w in data["results"]]
    except Exception as exc:  # noqa: BLE001
        _log(f"cited_by({work_id!r}) failed: {exc}")
        return []


def references(work_id: str) -> list[Paper]:
    """Works referenced by ``work_id`` (batch-fetched, <=50 ids per request)."""
    try:
        work = get_work(work_id)
        if work is None:
            return []
        ref_ids = [_clean_id(r) for r in (work.extra.get("referenced_works") or [])]
        ref_ids = [r for r in ref_ids if r]
        out: list[Paper] = []
        for i in range(0, len(ref_ids), 50):
            batch = ref_ids[i : i + 50]
            params: dict = {
                "filter": "openalex_id:" + "|".join(batch),
                "per_page": 50,
                "select": SELECT_FIELDS,
            }
            _add_mailto(params)
            data = http.get_json(WORKS_URL, params=params, cache_ns="openalex", ttl_hours=24 * 7)
            if data and "results" in data:
                out.extend(_to_paper(w) for w in data["results"])
        return out
    except Exception as exc:  # noqa: BLE001
        _log(f"references({work_id!r}) failed: {exc}")
        return []
