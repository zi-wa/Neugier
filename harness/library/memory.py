"""Cross-campaign memory: append-only JSONL stores under ``harness.LIBRARY``.

Three stores, one file each (created lazily under ``harness.LIBRARY``):

* ``rejected.jsonl`` -- topics a past campaign investigated and dropped,
  with the reason, so future campaigns don't re-litigate them from scratch.
* ``results.jsonl`` -- one row per finished campaign: title, outcome class,
  and the claims it produced.
* ``facts.jsonl`` -- excerpt-anchored facts pulled from the literature,
  deduped by a hash of the normalized statement so the same fact recorded
  twice (possibly by different campaigns) doesn't bloat the store. Since
  Round 2 every fact carries excerpt provenance (``verified``,
  ``source_sha256``, ``excerpt_hash``) computed against the cached source text.

Every write is a single ``json.dumps(..., ensure_ascii=False)`` line,
appended under a UTF-8 file handle -- never rewritten, so the history of
what has been tried is always intact.

``harness.LIBRARY`` is read fresh (via ``harness.LIBRARY``, not a
module-level copy) on every call so tests can monkeypatch it to a temp
directory.
"""
from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import harness
from harness.verify.exact import sha256_text

_STORE_FILES = {
    "rejected": "rejected.jsonl",
    "results": "results.jsonl",
    "facts": "facts.jsonl",
}


class FactUnverified(Exception):
    """Raised by :func:`add_fact` when verification is required and the excerpt is not found."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(s: str) -> str:
    """Lowercase, whitespace-collapsed form used for hashing/fuzzy matching."""
    return " ".join(s.split()).strip().lower()


def _store_path(store: str) -> Path:
    try:
        filename = _STORE_FILES[store]
    except KeyError:
        raise ValueError(f"unknown store {store!r}; expected one of {sorted(_STORE_FILES)}") from None
    harness.LIBRARY.mkdir(parents=True, exist_ok=True)
    return harness.LIBRARY / filename


def _append(store: str, record: dict[str, Any]) -> None:
    path = _store_path(store)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def all(store: str) -> list[dict[str, Any]]:
    """Every record in ``store``, in file (append) order."""
    path = _store_path(store)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def add_rejected(
    topic: str,
    reason: str,
    campaign: str | None = None,
    tags: list[str] | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Append a rejected-topic record. Always appends (no dedupe)."""
    record = {
        "topic": topic,
        "reason": reason,
        "campaign": campaign,
        "date": date or _utc_now_iso(),
        "tags": list(tags) if tags else [],
    }
    _append("rejected", record)
    return record


def add_result(
    campaign: str,
    title: str,
    outcome_class: str,
    claims: list[dict[str, Any]] | None = None,
    date: str | None = None,
    paper_path: str | None = None,
) -> dict[str, Any]:
    """Append a finished-campaign record. Always appends (no dedupe)."""
    record = {
        "campaign": campaign,
        "title": title,
        "outcome_class": outcome_class,
        "claims": claims or [],
        "date": date or _utc_now_iso(),
        "paper_path": paper_path,
    }
    _append("results", record)
    return record


def add_fact(
    statement: str,
    source_id: str,
    excerpt: str,
    locator: str | None = None,
    campaign: str | None = None,
    date: str | None = None,
    *,
    campaign_dir: Path | str | None = None,
    require_verified: bool = False,
) -> dict[str, Any] | None:
    """Append a literature fact, deduped by sha256 of the normalized statement.

    The excerpt is verified against the cached source text
    (:func:`harness.lit.cache.verify_excerpt`, searching ``campaign_dir/cache``
    then the project cache); the record stores ``verified`` (True/False/None),
    ``source_sha256`` and ``excerpt_hash``. With ``require_verified`` an excerpt
    that is not verified raises :class:`FactUnverified` and nothing is written.

    Returns the new record, or ``None`` if a fact with the same normalized
    statement is already recorded (nothing is written in that case).
    """
    from harness.lit.cache import verify_excerpt  # local import keeps the library cheap to import

    fact_hash = sha256_text(_normalize(statement))
    for existing in all("facts"):
        if existing.get("hash") == fact_hash:
            return None
    check = verify_excerpt(excerpt, source_id, campaign_dir)
    if require_verified and check.verified is not True:
        raise FactUnverified(
            f"excerpt for {source_id!r} is not verified ({check.method}: {check.detail}); fetch the source into "
            "the cache (`harness lit fetch <source-id>`) or pass --unverified-ok"
        )
    record = {
        "statement": statement,
        "source_id": source_id,
        "excerpt": excerpt,
        "locator": locator,
        "hash": fact_hash,
        "campaign": campaign,
        "date": date or _utc_now_iso(),
        "verified": check.verified,
        "source_sha256": check.source_sha256,
        "excerpt_hash": check.excerpt_hash,
    }
    _append("facts", record)
    return record


def _tokenize(text: str) -> list[str]:
    buf = "".join(c if c.isalnum() else " " for c in text.lower())
    return [t for t in buf.split() if t]


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for v in value.values():
            out.extend(_flatten_strings(v))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(_flatten_strings(v))
        return out
    return []


def search(store: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Case-insensitive token match over every string field of every record.

    Ranked by number of distinct query tokens matched (descending), ties
    broken by original (append) order.
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for idx, record in enumerate(all(store)):
        text = " ".join(_flatten_strings(record))
        record_tokens = set(_tokenize(text))
        matched = query_tokens & record_tokens
        if matched:
            scored.append((len(matched), idx, record))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [record for _, _, record in scored[:limit]]


def is_rejected(topic: str, threshold: float = 0.8) -> dict[str, Any] | None:
    """The best-matching rejected record for ``topic``, if any, above ``threshold``.

    Similarity is ``difflib.SequenceMatcher.ratio()`` on normalized
    (lowercased, whitespace-collapsed) topic strings.
    """
    norm_topic = _normalize(topic)
    best_ratio = 0.0
    best_record: dict[str, Any] | None = None
    for record in all("rejected"):
        norm_candidate = _normalize(str(record.get("topic", "")))
        ratio = difflib.SequenceMatcher(None, norm_topic, norm_candidate).ratio()
        if ratio >= threshold and ratio > best_ratio:
            best_ratio = ratio
            best_record = record
    return best_record
