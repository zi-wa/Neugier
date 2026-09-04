"""Verification coverage of a proof artifact (Round-2 Step 24 / X5a).

"Refereed" becomes a number: how many proof steps the skeptic's state machine
marked VERIFIED, how many steps rest on computation or verified citations,
which cited excerpts are verified in the ledger, which numerics the blinded
replicator reproduced, and which lemmas the falsifier attacked. The breakdown
by step type mirrors the Kosmos audit (arXiv 2511.02824: 79.4% of statements
accurate overall; 85.5% data-analysis, 82.1% literature, 57.9% synthesis — the
synthesis steps are where proofs are weakest, so they are reported separately).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from harness.proof.lint import parse_proof
from harness.review.verdict import blocks_for_role, ensure_list, latest_round, parse_step_table, role_reports

STEP_TYPES = ("definition", "hypothesis", "algebra", "computation", "derived", "cited", "key", "synthesis")
_RESULTS_KEY_RE = re.compile(r"results\.json#([A-Za-z0-9_.\-]+)")


class TypeCoverage(BaseModel):
    total: int = 0
    verified: int = 0

    @property
    def pct(self) -> float | None:
        return round(100.0 * self.verified / self.total, 1) if self.total else None


class Coverage(BaseModel):
    claim: str
    round: int | None
    steps_total: int = 0
    steps_verified_by_skeptic: int = 0
    steps_open: int = 0
    steps_flawed: int = 0
    steps_unreviewed: int = 0
    by_type: dict[str, TypeCoverage] = Field(default_factory=dict)
    steps_by_computation: int = 0
    steps_by_citation: int = 0
    synthesis_steps: int = 0
    cites_total: int = 0
    cites_verified: int = 0
    numerics_total: int = 0
    numerics_reproduced: int = 0
    lemmas_total: int = 0
    lemmas_falsified: int = 0
    skeptic_reports: int = 0
    warnings: list[str] = Field(default_factory=list)

    @property
    def overall_pct(self) -> float | None:
        return round(100.0 * self.steps_verified_by_skeptic / self.steps_total, 1) if self.steps_total else None

    def by_type_pct(self) -> dict[str, float | None]:
        return {k: v.pct for k, v in self.by_type.items()}

    def summary_line(self) -> str:
        parts = [f"overall {self.overall_pct if self.overall_pct is not None else 'n/a'}%"]
        for k in ("computation", "cited", "derived", "synthesis"):
            tc = self.by_type.get(k)
            if tc and tc.total:
                parts.append(f"{k} {tc.pct}%")
        parts.append(f"cites {self.cites_verified}/{self.cites_total}")
        parts.append(f"numerics reproduced {self.numerics_reproduced}/{self.numerics_total}")
        parts.append(f"lemmas falsified {self.lemmas_falsified}/{self.lemmas_total}")
        return "; ".join(parts)

    def to_dict(self) -> dict:
        d = json.loads(self.model_dump_json())
        d["overall_pct"] = self.overall_pct
        d["by_type_pct"] = self.by_type_pct()
        d["summary"] = self.summary_line()
        return d


def _reproduced_keys(rdir: Path) -> set[str]:
    keys: set[str] = set()
    for block in blocks_for_role(rdir, "replicator"):
        for item in ensure_list(block.get("reproduced")):
            s = str(item)
            keys.add(s.split("#", 1)[1] if "#" in s else s)
        for item in ensure_list(block.get("checked")):
            keys.update(_RESULTS_KEY_RE.findall(str(item)))
    return keys


def compute_coverage(campaign_dir: Path | str, claim_id: str, round_n: int | None = None, store=None) -> Coverage:
    campaign_dir = Path(campaign_dir)
    if store is None:
        from harness.ledger.ledger import LedgerStore

        store = LedgerStore(campaign_dir / "ledger.json")
    claim = store.get(claim_id)
    proof_rel = next((ev.path for ev in reversed(claim.evidence) if ev.type == "proof" and ev.path and ev.path.endswith(".md")), None)
    if proof_rel is None:
        cand = campaign_dir / "proofs" / f"{claim_id}.md"
        proof_rel = f"proofs/{claim_id}.md" if cand.exists() else None
    if round_n is None:
        round_n = latest_round(campaign_dir)
    cov = Coverage(claim=claim_id, round=round_n)
    if proof_rel is None:
        cov.warnings.append("no proof artifact (.md) found for the claim")
        return cov
    doc = parse_proof((campaign_dir / proof_rel).read_text(encoding="utf-8", errors="replace"))

    # skeptic step tables (merged; FLAWED wins over OPEN wins over VERIFIED)
    rows: dict[int, str] = {}
    rank = {"VERIFIED": 0, "OPEN": 1, "FLAWED": 2}
    if round_n is not None:
        rdir = campaign_dir / "reviews" / f"round{round_n}"
        reports = role_reports(rdir, "skeptic")
        cov.skeptic_reports = len(reports)
        for p in reports:
            table = parse_step_table(p.read_text(encoding="utf-8", errors="replace"))
            if not table:
                cov.warnings.append(f"W_STEP_TABLE_UNPARSED: {p.name} has no parsable step table")
            for n, row in table.items():
                if n not in rows or rank[row.status] > rank[rows[n]]:
                    rows[n] = row.status
    else:
        rdir = None
        cov.warnings.append("no review round yet; skeptic coverage is zero")

    cov.steps_total = len(doc.steps)
    for s in doc.steps:
        kind = s.kind if s.kind in STEP_TYPES else "synthesis"
        tc = cov.by_type.setdefault(kind, TypeCoverage())
        tc.total += 1
        st = rows.get(s.n)
        if st == "VERIFIED":
            cov.steps_verified_by_skeptic += 1
            tc.verified += 1
        elif st == "OPEN":
            cov.steps_open += 1
        elif st == "FLAWED":
            cov.steps_flawed += 1
        else:
            cov.steps_unreviewed += 1
        if kind == "computation":
            cov.steps_by_computation += 1
        elif kind == "cited":
            cov.steps_by_citation += 1
        elif kind == "synthesis":
            cov.synthesis_steps += 1

    # citations: verified excerpt with matching hash on the cited fact
    cov.cites_total = len(doc.cites)
    for c in doc.cites:
        fact = store.ledger.claims.get(c.claim or "")
        if fact is None or not c.excerpt_hash:
            continue
        hashes = {ev.excerpt_hash for ev in fact.evidence if ev.type == "excerpt" and ev.verified is True and ev.excerpt_hash}
        if any(h.startswith(c.excerpt_hash) or c.excerpt_hash.startswith(h) for h in hashes):
            cov.cites_verified += 1

    # numerics reproduced by the replicator
    keys = [str(n).split("#", 1)[1] if "#" in str(n) else str(n) for n in (doc.frontmatter.get("numerics") or [])]
    cov.numerics_total = len(keys)
    if rdir is not None:
        repro = _reproduced_keys(rdir)
        cov.numerics_reproduced = sum(1 for k in keys if k in repro)

    # lemmas attacked by the falsifier
    for dep in claim.depends_on:
        d = store.ledger.claims.get(dep)
        if d is None or d.kind not in ("lemma", "proposition"):
            continue
        cov.lemmas_total += 1
        if any(ev.type == "falsification" and ev.path and (campaign_dir / ev.path).exists() for ev in d.evidence):
            cov.lemmas_falsified += 1
    return cov


def write_coverage(campaign_dir: Path | str, cov: Coverage) -> Path | None:
    from harness.ledger.ledger import atomic_write_json

    campaign_dir = Path(campaign_dir)
    if cov.round is None:
        out = campaign_dir / "reviews" / f"coverage-{cov.claim}.json"
    else:
        out = campaign_dir / "reviews" / f"round{cov.round}" / f"coverage-{cov.claim}.json"
    atomic_write_json(out, cov.to_dict())
    return out
