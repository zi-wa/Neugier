"""Pydantic schema for the Neugier claim ledger.

The ledger (``campaigns/<slug>/ledger.json``) is the harness's source of
truth for what has and has not been established. Every claim carries a
stable id, a content hash, and an evidence trail; nothing may be asserted
in the paper without evidence recorded here (CLAUDE.md, rule R5).

Round-2 additions: excerpt provenance (``verified``, ``source_sha256``,
``excerpt_hash``), referee identity and lineup reliability (``agent_id``,
``reliability``, ``admissible``, ``lineup_item``), claim stakes and human
attestation, and conjecture-repair provenance (``repaired_from``, ``repair_op``).
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
# "n/a" is accepted only for the replicator (nothing to replicate); see LedgerStore.add_evidence.
Verdict = Literal["pass", "fail", "revise", "n/a"]
# 0 = routine lemma, 1 = standard target, 2 = would resolve a listed open problem / beat a tracked best-known value.
Stakes = Literal[0, 1, 2]
RepairOp = Literal["add-hypothesis", "weaken-bound", "absorb-and-regenerate"]


def utc_now_iso() -> str:
    """Current time as an ISO-8601 string in UTC. Used for every ledger timestamp."""
    return datetime.now(timezone.utc).isoformat()


class Evidence(BaseModel):
    """One piece of evidence attached to a claim.

    ``path`` is always relative to the owning campaign's directory so the
    ledger stays portable across machines. ``file_hash`` freezes the sha256
    of that file at the moment the evidence was recorded, so tampering can
    be detected later by :meth:`harness.ledger.ledger.LedgerStore.check_integrity`.

    Excerpt provenance (type ``excerpt``): ``verified`` is ``True`` when the
    excerpt was found in the cached source text at ``source_path`` (whose
    sha256 is ``source_sha256``), ``False`` when the source was cached but the
    excerpt was not found, ``None`` when no source text was available.
    ``excerpt_hash`` is the 12-hex prefix that ``<cite excerpt-hash="…">`` binds to.

    Referee provenance (type ``referee``): ``agent_id`` identifies the fresh
    context that produced the verdict; ``reliability`` / ``admissible`` come
    from the decoy-lineup score; ``lineup_item`` is the item letter reviewed.
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
    # excerpt provenance
    source_path: str | None = None
    source_sha256: str | None = None
    verified: bool | None = None
    excerpt_hash: str | None = None
    # referee provenance
    agent_id: str | None = None
    reliability: float | None = None
    admissible: bool | None = None
    lineup_item: str | None = None


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
    # Round 2
    stakes: Stakes = 1
    attestation: dict | None = None
    repaired_from: str | None = None
    repair_op: RepairOp | None = None


class Ledger(BaseModel):
    """The full claim ledger for one campaign."""

    campaign: str
    claims: dict[str, Claim] = Field(default_factory=dict)
    version: int = 1
