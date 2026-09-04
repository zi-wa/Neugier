"""OEIS (On-Line Encyclopedia of Integer Sequences) client.

Wraps ``https://oeis.org/search``. Note that the API returns a bare JSON list
on success, JSON ``null`` when there are no matches, and (per OEIS docs) can
also wrap results as ``{"results": [...], ...}`` — this module accepts all
three shapes.
"""
from __future__ import annotations

import sys

from harness.lit import http

SEARCH_URL = "https://oeis.org/search"


def _log(msg: str) -> None:
    print(f"[harness.lit.oeis] {msg}", file=sys.stderr)


def _extract_results(data: object) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        results = data.get("results")
        return results if isinstance(results, list) else []
    return []


def _normalize_anumber(anumber: str | int) -> str:
    s = str(anumber).strip().upper().removeprefix("A")
    if s.isdigit():
        return f"A{int(s):06d}"
    return f"A{s}"


def search(query: str, start: int = 0) -> list[dict]:
    """Search OEIS. Never raises: returns [] and logs to stderr on failure."""
    try:
        params = {"q": query, "fmt": "json", "start": start}
        data = http.get_json(SEARCH_URL, params=params, cache_ns="oeis", ttl_hours=24 * 7)
        return _extract_results(data)
    except Exception as exc:  # noqa: BLE001 - search must never raise
        _log(f"search({query!r}) failed: {exc}")
        return []


def get(anumber: str | int) -> dict | None:
    """Fetch a single OEIS entry by A-number. Returns None on failure."""
    try:
        aid = _normalize_anumber(anumber)
        params = {"q": f"id:{aid}", "fmt": "json"}
        data = http.get_json(SEARCH_URL, params=params, cache_ns="oeis", ttl_hours=24 * 30)
        results = _extract_results(data)
        return results[0] if results else None
    except Exception as exc:  # noqa: BLE001
        _log(f"get({anumber!r}) failed: {exc}")
        return None


def lookup_sequence(terms: list[int]) -> list[dict]:
    """Search OEIS for sequences matching a list of leading terms."""
    query = ",".join(str(t) for t in terms)
    return search(query)


def conjectures(entry: dict) -> list[str]:
    """Lines from an entry's comment/formula fields that mention 'conjecture'."""
    lines: list[str] = []
    for field in ("comment", "formula"):
        vals = entry.get(field) or []
        if isinstance(vals, str):
            vals = [vals]
        for line in vals:
            if isinstance(line, str) and "conjectur" in line.lower():
                lines.append(line)
    return lines


def keywords(entry: dict) -> list[str]:
    """Parse an entry's comma-joined 'keyword' field into a list."""
    kw = entry.get("keyword") or ""
    if isinstance(kw, list):
        return [k.strip() for k in kw if isinstance(k, str) and k.strip()]
    return [k.strip() for k in str(kw).split(",") if k.strip()]
