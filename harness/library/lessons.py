"""Lessons and creative-move statistics across campaigns (Round-2 Step 27 / Y11).

At finish, the judge and strategist write a ``## Lessons`` block in ``log.md``::

    ## Lessons
    - [phase=review] the skeptic caught a uniformity gap the falsifier could not see — evidence: reviews/round1/skeptic.SK-1.md — moves: M32 — tags: skeptic,gap
    - [phase=explore] descending greedy scans beat ascending ones on Sidon density — evidence: experiments/evolve/sidon100/mine.md — moves: M61,M60 — tags: evolve

``campaign finish`` appends them to ``library/lessons.jsonl`` and one row per
attack route (its move ids and final status) to ``library/moves.jsonl``;
``harness library lessons --query …`` and ``harness library moves-stats`` feed
the strategist and scout (cf. the AI co-scientist's meta-review loop and
ShinkaEvolve's meta-scratchpad).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from harness.library import memory

_LESSON_RE = re.compile(r"^\s*[-*]\s*(?:\[phase\s*=\s*([a-z]+)\]\s*)?(.+?)\s*$", re.IGNORECASE)
_MOVE_RE = re.compile(r"\bM\d{1,2}\b")


def _split_meta(text: str) -> tuple[str, dict[str, str]]:
    parts = re.split(r"\s+[—–-]{1,2}\s+(?=(?:evidence|moves|tags)\s*:)", text)
    body = parts[0].strip()
    meta: dict[str, str] = {}
    for p in parts[1:]:
        k, _, v = p.partition(":")
        meta[k.strip().lower()] = v.strip()
    return body, meta


def parse_lessons(text: str) -> list[dict[str, Any]]:
    """``## Lessons`` bullets -> ``{phase, lesson, evidence_path, moves[], tags[]}``."""
    m = re.search(r"^##\s*Lessons\s*$(.*?)(?=^##\s|\Z)", text or "", re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    out: list[dict[str, Any]] = []
    for ln in m.group(1).splitlines():
        lm = _LESSON_RE.match(ln)
        if not lm or not ln.strip().startswith(("-", "*")):
            continue
        phase = (lm.group(1) or "").lower()
        body, meta = _split_meta(lm.group(2))
        if not body:
            continue
        out.append({
            "phase": phase,
            "lesson": body,
            "evidence_path": meta.get("evidence", ""),
            "moves": sorted(set(_MOVE_RE.findall(meta.get("moves", ""))), key=lambda s: int(s[1:])),
            "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
        })
    return out


def add_lessons(campaign: str, lessons: list[dict[str, Any]]) -> int:
    n = 0
    existing = {(r.get("campaign"), r.get("lesson")) for r in memory.all("lessons")}
    for l in lessons:
        key = (campaign, l.get("lesson"))
        if key in existing:
            continue
        memory._append("lessons", {"campaign": campaign, "phase": l.get("phase", ""), "lesson": l["lesson"],
                                   "evidence_path": l.get("evidence_path", ""), "tags": l.get("tags", []),
                                   "moves": l.get("moves", []), "date": memory._utc_now_iso()})
        existing.add(key)
        n += 1
    return n


def add_route_moves(campaign: str, routes) -> int:
    """One ``moves.jsonl`` row per attack route (``harness.ideas.Route``)."""
    n = 0
    existing = {(r.get("campaign"), r.get("route")) for r in memory.all("moves")}
    for r in routes:
        key = (campaign, r.index)
        if key in existing:
            continue
        memory._append("moves", {"campaign": campaign, "route": r.index, "title": r.title, "lens": r.lens,
                                 "moves": list(r.moves), "status": r.status, "claim_ids": list(r.claim_ids),
                                 "date": memory._utc_now_iso()})
        existing.add(key)
        n += 1
    return n


def lessons(query: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    if query:
        return memory.search("lessons", query, limit=limit)
    return memory.all("lessons")[-limit:]


def moves_stats() -> dict[str, dict[str, int]]:
    """Per creative move: routes tried / survived falsification / reached proof-drafted / produced a key step."""
    stats: dict[str, dict[str, int]] = {}

    def bump(move: str, key: str) -> None:
        stats.setdefault(move, {"tried": 0, "survived_falsification": 0, "proof_drafted": 0, "key_step": 0, "lessons": 0})
        stats[move][key] += 1

    for r in memory.all("moves"):
        status = str(r.get("status", "untested"))
        for mv in r.get("moves", []):
            bump(mv, "tried")
            if status in ("tested-ok", "proved", "key-step"):
                bump(mv, "survived_falsification")
            if status in ("proved", "key-step"):
                bump(mv, "proof_drafted")
            if status == "key-step":
                bump(mv, "key_step")
    for l in memory.all("lessons"):
        for mv in l.get("moves", []):
            bump(mv, "lessons")
    return dict(sorted(stats.items(), key=lambda t: int(t[0][1:])))
