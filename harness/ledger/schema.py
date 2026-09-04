"""Pydantic schema for the Neugier claim ledger.

The ledger (``campaigns/<slug>/ledger.json``) is the harness's source of
truth for what has and has not been established. Every claim carries a
stable id, a content hash, and an evidence trail; nothing may be asserted
in the paper without evidence recorded here (CLAUDE.md, rule R5).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal[
    "idea",
    "conjectured",
    "numerically-supported",
    "proof-drafted",
    "referee-passed",
    "formalized",
    "refuted",
    "known-in-literature",
    "dead",
]

Kind = Literal[
    "theorem",
    "lemma",
    "proposition",
    "conjecture",
    "fact",
    "idea",
    "definition",
    "bound",
    "construction",
    "target",
    "question",
]

EvidenceType = Literal[
    "excerpt",
    "computation",
    "proof",
    "referee",
    "falsification",
    "formalization",
    "note",
]

RefereeRole = Literal["skeptic", "falsifier", "novelty", "replicator", "judge"]
Verdict = Literal["pass", "fail", "revise"]


def utc_now_iso() -> str:
    """Current time as an ISO-8601 string in UTC. Used for every ledger timestamp."""
    return datetime.now(timezone.utc).isoformat()


class Evidence(BaseModel):
    """One piece of evidence attached to a claim.

    ``path`` is always relative to the owning campaign's directory so the
    ledger stays portable across machines. ``file_hash`` freezes the sha256
    of that file at the moment the evidence was recorded, so tampering can
    be detected later by :meth:`harness.ledger.ledger.LedgerStore.check_integrity`.
    """

    type: EvidenceType
    path: str | None = None
    summary: str = ""
    source_id: str | None = None
    excerpt: str | None = None
    locator: str | None = None
    file_hash: str | None = None
    role: RefereeRole | None = None
    verdict: Verdict | None = None
    round: int | None = None
    added: str = Field(default_factory=utc_now_iso)


class Claim(BaseModel):
    """A single node in the claim ledger's dependency DAG."""

    id: str
    kind: Kind
    statement: str
    status: Status = "idea"
    evidence: list[Evidence] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    hash: str
    stale: bool = False
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    created: str = Field(default_factory=utc_now_iso)
    updated: str = Field(default_factory=utc_now_iso)
    history: list[dict] = Field(default_factory=list)


class Ledger(BaseModel):
    """The full claim ledger for one campaign."""

    campaign: str
    claims: dict[str, Claim] = Field(default_factory=dict)
    version: int = 1
