"""MathOverflow client via the public Stack Exchange API.

Wraps ``https://api.stackexchange.com/2.3/search/advanced`` with
``site=mathoverflow``.
"""
from __future__ import annotations

import html
import sys
from html.parser import HTMLParser

from harness.lit import http

SEARCH_URL = "https://api.stackexchange.com/2.3/search/advanced"
_VALID_SORTS = {"activity", "creation", "votes", "relevance"}
_BLOCK_TAGS = {"p", "br", "li", "blockquote", "div", "pre"}


def _log(msg: str) -> None:
    print(f"[harness.lit.mathoverflow] {msg}", file=sys.stderr)


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text stripper: drops tags, keeps block-level line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [ln.strip() for ln in raw.splitlines()]
        return "\n".join(ln for ln in lines if ln).strip()


def strip_html(html_body: str) -> str:
    """Strip HTML tags to plain text, collapsing whitespace."""
    if not html_body:
        return ""
    parser = _TextExtractor()
    parser.feed(html_body)
    parser.close()
    return parser.text()


def _to_dict(item: dict) -> dict:
    return {
        "title": html.unescape(item.get("title", "")),
        "link": item.get("link"),
        "score": item.get("score"),
        "tags": item.get("tags") or [],
        "body": strip_html(item.get("body", "")),
        "question_id": item.get("question_id"),
        "creation_date": item.get("creation_date"),
    }


def search(
    query: str,
    tagged: str | None = None,
    pagesize: int = 20,
    sort: str = "votes",
) -> list[dict]:
    """Search MathOverflow questions. Never raises: [] and log on failure."""
    try:
        params: dict = {
            "q": query,
            "site": "mathoverflow",
            "filter": "withbody",
            "pagesize": max(1, min(pagesize, 100)),
            "sort": sort if sort in _VALID_SORTS else "votes",
            "order": "desc",
        }
        if tagged:
            params["tagged"] = tagged
        data = http.get_json(SEARCH_URL, params=params, cache_ns="mathoverflow", ttl_hours=24)
        if not data or "items" not in data:
            return []
        return [_to_dict(item) for item in data["items"]]
    except Exception as exc:  # noqa: BLE001 - search must never raise
        _log(f"search({query!r}) failed: {exc}")
        return []
