"""zbMATH Open client: search via the v1 document search API.

Wraps ``https://api.zbmath.org/v1/document/_search``.
"""
from __future__ import annotations

import sys

from harness.lit import http
from harness.lit.models import Paper

SEARCH_URL = "https://api.zbmath.org/v1/document/_search"


def _log(msg: str) -> None:
    print(f"[harness.lit.zbmath] {msg}", file=sys.stderr)


def _to_paper(d: dict) -> Paper:
    identifier = d.get("identifier") or str(d.get("id", ""))

    title_field = d.get("title") or {}
    title = title_field.get("title") if isinstance(title_field, dict) else str(title_field)
    title = title or ""

    authors = [
        a.get("name", "")
        for a in (d.get("contributors") or {}).get("authors", [])
        if a.get("name")
    ]

    year_raw = d.get("year")
    year = None
    if year_raw is not None:
        try:
            year = int(str(year_raw)[:4])
        except ValueError:
            year = None

    doi = None
    for link in d.get("links") or []:
        if link.get("type") == "doi" and link.get("identifier"):
            doi = link["identifier"]
            break

    abstract = ""
    for contrib in d.get("editorial_contributions") or []:
        if contrib.get("contribution_type") == "review" and contrib.get("text"):
            abstract = contrib["text"]
            break

    categories = [m.get("code") for m in (d.get("msc") or []) if m.get("code")]

    url = d.get("zbmath_url") or (f"https://zbmath.org/{identifier}" if identifier else None)

    return Paper(
        id=f"zbmath:{identifier}",
        source="zbmath",
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        doi=doi,
        arxiv_id=None,
        url=url,
        categories=categories,
        cited_by_count=None,
        extra={"zbmath_internal_id": d.get("id"), "keywords": d.get("keywords") or []},
    )


def search(query: str, results_per_page: int = 20) -> list[Paper]:
    """Search zbMATH Open. Never raises: returns [] and logs on failure."""
    try:
        params = {
            "search_string": query,
            "results_per_page": max(1, min(results_per_page, 100)),
        }
        data = http.get_json(SEARCH_URL, params=params, cache_ns="zbmath", ttl_hours=72)
        if not data or "result" not in data:
            return []
        return [_to_paper(d) for d in data["result"]]
    except Exception as exc:  # noqa: BLE001 - search must never raise
        _log(f"search({query!r}) failed: {exc}")
        return []
