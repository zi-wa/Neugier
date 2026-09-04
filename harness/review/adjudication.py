"""Structured judge adjudication (Round-2 Step 19 / Y3).

``reviews/roundN/judge.md`` must carry a yaml block::

    role: judge
    claim: T-001
    round: 2
    upheld:   [{role: skeptic, agent_id: SK-1, step: 3}]
    rebutted: [{role: skeptic, agent_id: SK-1, step: 5, quote: "…≥ 40 chars from response.md…"}]
    moot:     [{role: falsifier, step: 2, reason: "…"}]      # gaps / interpretation issues only
    verdict: PASS | REVISE_PROOF | REVISE_PLAN | REWRITE | PIVOT

:func:`judge_consistency` turns the referee reports and this block into problems:
every critical error reported by an admissible referee must be upheld or
rebutted (never merely "moot"), a ``PASS`` cannot coexist with an upheld
critical error, a rebuttal must quote the prover's ``response.md`` (≥ 40
characters), and the yaml ``verdict`` must equal the final ``VERDICT:`` line.
Typed defect classes follow Huang & Yang (arXiv 2507.15855): critical error vs
justification gap.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from harness.review.verdict import (
    blocks_for_role,
    ensure_list,
    iter_errors,
    judge_verdict,
    parse_judge_block,
    step_of,
)

REFEREE_ROLES_WITH_ERRORS = ("skeptic", "falsifier", "replicator", "novelty")
MIN_QUOTE = 40


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def inadmissible_agents(rdir: Path) -> set[str]:
    """Agent ids whose lineup score marked them inadmissible (Round-2 X1)."""
    out: set[str] = set()
    for p in Path(rdir).glob("lineup_score*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("admissible") is False and data.get("agent_id"):
            out.add(str(data["agent_id"]))
    return out


def reported_critical_errors(rdir: Path) -> list[dict]:
    """``{role, agent_id, step, witness}`` for every critical error in admissible referee blocks."""
    rdir = Path(rdir)
    bad = inadmissible_agents(rdir)
    out: list[dict] = []
    for role in REFEREE_ROLES_WITH_ERRORS:
        for block in blocks_for_role(rdir, role):
            agent = block.get("agent_id")
            if agent and str(agent) in bad:
                continue
            for err in iter_errors(block, "critical_errors"):
                out.append({"role": role, "agent_id": agent, "step": step_of(err), "witness": str(err.get("witness", ""))})
    return out


def _entries(block: dict, key: str) -> list[dict]:
    out = []
    for e in ensure_list(block.get(key)):
        if isinstance(e, dict):
            out.append(e)
        else:
            m = re.match(r"^\s*([a-z-]+)\s*(?:\(([^)]*)\))?\s*(?:step\s*)?(\d+)?", str(e), re.IGNORECASE)
            out.append({"role": m.group(1).lower() if m else None, "agent_id": m.group(2) if m else None,
                        "step": int(m.group(3)) if m and m.group(3) else None})
    return out


def _matches(entry: dict, err: dict) -> bool:
    role = str(entry.get("role") or "").lower()
    role = "novelty" if role == "novelty-checker" else role
    if role and role != err["role"]:
        return False
    if entry.get("agent_id") and err.get("agent_id") and str(entry["agent_id"]) != str(err["agent_id"]):
        return False
    return step_of(entry.get("step")) == err["step"]


def judge_consistency(rdir: Path | str, manifest: dict | None, judge_text: str) -> list[str]:
    rdir = Path(rdir)
    problems: list[str] = []
    block = parse_judge_block(judge_text)
    if block is None:
        return ["judge.md lacks the structured adjudication block (yaml with role: judge, upheld, rebutted, moot, verdict)"]
    decision = judge_verdict(judge_text)
    if decision and block.get("verdict") and str(block["verdict"]).upper() != decision:
        problems.append(f"judge block verdict {block['verdict']!r} disagrees with the final line VERDICT: {decision}")
    upheld = _entries(block, "upheld")
    rebutted = _entries(block, "rebutted")
    moot = _entries(block, "moot")
    if (decision == "PASS" or str(block.get("verdict", "")).upper() == "PASS") and upheld:
        problems.append("VERDICT: PASS cannot coexist with upheld critical errors")
    for err in reported_critical_errors(rdir):
        if any(_matches(e, err) for e in upheld) or any(_matches(e, err) for e in rebutted):
            continue
        if any(_matches(e, err) for e in moot):
            problems.append(f"critical error by {err['role']} at step {err['step']} is marked moot; critical errors must be upheld or rebutted")
        else:
            problems.append(f"critical error by {err['role']}{' ' + str(err['agent_id']) if err.get('agent_id') else ''} at step {err['step']} is neither upheld nor rebutted in judge.md")
    response = rdir / "response.md"
    resp_text = _norm(response.read_text(encoding="utf-8", errors="replace")) if response.exists() else None
    for e in rebutted:
        quote = str(e.get("quote") or "")
        if len(quote.strip()) < MIN_QUOTE:
            problems.append(f"rebuttal of step {step_of(e.get('step'))} needs a quote of at least {MIN_QUOTE} characters from the prover's response")
            continue
        if resp_text is not None and _norm(quote) not in resp_text:
            problems.append(f"rebuttal quote for step {step_of(e.get('step'))} does not occur in response.md")
        elif resp_text is None:
            problems.append(f"rebuttal of step {step_of(e.get('step'))} quotes a response but reviews/{rdir.name}/response.md does not exist")
    return problems
