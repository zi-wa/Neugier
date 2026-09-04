"""Pre-registered credences and calibration (Round-2 Step 22 / X2).

Every claim at ``conjectured`` (and every attack route) carries credences recorded
*before* budget is spent: ``p_true`` (the statement is true), ``p_budget`` (it
reaches referee-passed within the campaign budget), and — before each review
round — the prover's ``p_pass``. Credences live in ``claim.history`` (op
``credence``; immutable and audited). When claims resolve, Brier scores per role
and per field are computed; ``campaign finish`` appends them to
``library/calibration.jsonl`` so later campaigns can discount an overconfident
role. Precedent: t46/claim-prediction-market (Brier 0.177 on 35 claims; predict
"before an agent executes high-cost experiments").
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

FIELDS = ("p_true", "p_budget", "p_pass")
RESOLVING = {"refuted", "referee-passed", "formalized", "known-in-literature", "dead"}


class CalibrationRow(BaseModel):
    claim_id: str
    role: str
    field: str
    p: float
    outcome: int
    brier: float
    round: int | None = None


class RoleStats(BaseModel):
    n: int = 0
    brier: float | None = None
    mean_p: float | None = None
    base_rate: float | None = None


class CalibrationReport(BaseModel):
    campaign: str
    n: int
    by_role: dict[str, RoleStats] = Field(default_factory=dict)
    by_field: dict[str, RoleStats] = Field(default_factory=dict)
    rows: list[CalibrationRow] = Field(default_factory=list)
    final: bool = False


def resolve_outcome(claim, *, final: bool = False) -> dict[str, int | None]:
    """Binary outcomes for ``p_true`` / ``p_budget`` from a claim's terminal status (None = unresolved)."""
    s = claim.status
    if s == "refuted":
        return {"p_true": 0, "p_budget": 0}
    if s in ("referee-passed", "formalized"):
        return {"p_true": 1, "p_budget": 1}
    if s == "known-in-literature":
        return {"p_true": 1, "p_budget": 0}
    if s == "dead":
        return {"p_true": None, "p_budget": 0}
    if final:
        return {"p_true": None, "p_budget": 0}
    return {"p_true": None, "p_budget": None}


def credence_entries(claim) -> list[dict]:
    return [h for h in claim.history if h.get("op") == "credence"]


def latest_credence(claim, field: str = "p_true", role: str | None = None) -> dict | None:
    for h in reversed(credence_entries(claim)):
        if h.get(field) is None:
            continue
        if role and h.get("role") != role:
            continue
        return h
    return None


def _pass_outcome(claim, round_n: int | None) -> int | None:
    if round_n is None:
        return None
    verdicts = [ev.verdict for ev in claim.evidence if ev.type == "referee" and ev.role == "judge" and ev.round == round_n]
    if not verdicts:
        return None
    return 1 if verdicts[-1] == "pass" else 0


def _stats(rows: list[CalibrationRow]) -> RoleStats:
    if not rows:
        return RoleStats()
    n = len(rows)
    return RoleStats(
        n=n,
        brier=round(sum(r.brier for r in rows) / n, 4),
        mean_p=round(sum(r.p for r in rows) / n, 4),
        base_rate=round(sum(r.outcome for r in rows) / n, 4),
    )


def compute(store, campaign: str, *, final: bool = False) -> CalibrationReport:
    rows: list[CalibrationRow] = []
    for claim in store.ledger.claims.values():
        outcomes = resolve_outcome(claim, final=final)
        seen: set[tuple[str, str, int | None]] = set()
        for h in reversed(credence_entries(claim)):  # latest credence per (role, field, round) counts
            role = str(h.get("role") or "?")
            for field in FIELDS:
                p = h.get(field)
                if p is None:
                    continue
                key = (role, field, h.get("round"))
                if key in seen:
                    continue
                seen.add(key)
                outcome = _pass_outcome(claim, h.get("round")) if field == "p_pass" else outcomes.get(field)
                if outcome is None:
                    continue
                rows.append(CalibrationRow(claim_id=claim.id, role=role, field=field, p=float(p), outcome=int(outcome),
                                           brier=round((float(p) - outcome) ** 2, 4), round=h.get("round")))
    by_role = {r: _stats([x for x in rows if x.role == r]) for r in sorted({x.role for x in rows})}
    by_field = {f: _stats([x for x in rows if x.field == f]) for f in FIELDS if any(x.field == f for x in rows)}
    return CalibrationReport(campaign=campaign, n=len(rows), by_role=by_role, by_field=by_field, rows=rows, final=final)


def write_report(campaign_dir: Path, report: CalibrationReport) -> Path:
    from harness.ledger.ledger import atomic_write_json

    out = Path(campaign_dir) / "calibration.json"
    atomic_write_json(out, json.loads(report.model_dump_json()))
    return out


def append_to_library(report: CalibrationReport) -> int:
    """One library row per (role, field) with n and Brier; returns rows written."""
    from harness.library import memory

    n = 0
    for role, stats in report.by_role.items():
        for field in FIELDS:
            rows = [r for r in report.rows if r.role == role and r.field == field]
            if not rows:
                continue
            st = _stats(rows)
            memory.add_calibration(report.campaign, role, field, st.n, st.brier or 0.0, st.mean_p or 0.0, st.base_rate or 0.0)
            n += 1
    return n
