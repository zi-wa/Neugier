"""AI-involvement disclosure block (Round-2 Step 25 / Y10).

Agents4Science 2025 required public disclosure of the extent of AI involvement at
each stage of the research; Neugier generates that disclosure from the campaign
record instead of asking an agent to describe itself: per phase, which agent
types ran (from review manifests, ledger history and the campaign log), the
human's involvement (from ``HUMAN.md``: ``## <phase>`` blocks with
``involvement: none | answered-questions | edited-statement | verified-proof``,
plus attestations), and per asserted theorem a verification-level line::

    T-001: machine-refereed (2 skeptic passes, lineup reliability 0.92),
           replicated: yes, formalized: no, human-verified: no
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

MODEL_ROUTING = (
    "Rule R1: the top available model for every research-relevant agent (scouting, literature extraction, planning, "
    "experiments, proofs, all referees, judge, writing, copyediting); a cheaper model only for mechanical plumbing "
    "(downloads, bibliography formatting, batch mutation proposals in evolutionary search)."
)
LEVELS = ("none", "answered-questions", "edited-statement", "verified-proof")


class PhaseRow(BaseModel):
    phase: str
    entered: str | None = None
    exited: str | None = None
    agents: list[str] = Field(default_factory=list)
    human_involvement: str = "none"


class TheoremRow(BaseModel):
    claim: str
    skeptic_passes: int = 0
    lineup_reliability: float | None = None
    replicated: bool = False
    formalized: bool = False
    human_verified: bool = False
    line: str = ""


class Disclosure(BaseModel):
    campaign: str
    generated: str
    git_rev: str
    model_routing: str = MODEL_ROUTING
    tools: list[str] = Field(default_factory=list)
    phases: list[PhaseRow] = Field(default_factory=list)
    theorems: list[TheoremRow] = Field(default_factory=list)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _human_blocks(campaign_dir: Path) -> tuple[dict[str, str], set[str]]:
    """``({phase: level}, {claim ids listed under verified-proof})`` from HUMAN.md."""
    path = campaign_dir / "HUMAN.md"
    if not path.exists():
        return {}, set()
    text = path.read_text(encoding="utf-8", errors="replace")
    levels: dict[str, str] = {}
    verified: set[str] = set()
    for m in re.finditer(r"^##\s+([a-z]+)\s*$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL | re.IGNORECASE):
        phase = m.group(1).lower()
        body = m.group(2)
        lm = re.search(r"involvement\s*:\s*([a-z\-]+)", body, re.IGNORECASE)
        if lm and lm.group(1).lower() in LEVELS:
            levels[phase] = lm.group(1).lower()
            if levels[phase] == "verified-proof":
                verified.update(re.findall(r"\b[A-Z]-\d{3,}\b", body))
    return levels, verified


def _agents_by_phase(campaign_dir: Path, phases: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {p: set() for p in phases}
    # review rounds: manifest roles
    reviews = campaign_dir / "reviews"
    if reviews.is_dir():
        for rj in reviews.glob("round*/round.json"):
            data = _read_json(rj)
            for key in data.get("roles") or []:
                out.setdefault("review", set()).add(key.split(":", 1)[0])
    # ledger history: referee evidence roles, credence roles
    ledger = _read_json(campaign_dir / "ledger.json")
    for claim in (ledger.get("claims") or {}).values():
        for ev in claim.get("evidence") or []:
            if ev.get("type") == "referee" and ev.get("role"):
                out.setdefault("review", set()).add(str(ev["role"]))
            if ev.get("type") == "proof":
                out.setdefault("prove", set()).add("prover")
            if ev.get("type") in ("computation", "falsification"):
                out.setdefault("explore", set()).add("experimentalist" if ev.get("type") == "computation" else "falsifier")
            if ev.get("type") == "excerpt":
                out.setdefault("survey", set()).add("librarian")
        for h in claim.get("history") or []:
            if h.get("op") == "credence" and h.get("role"):
                out.setdefault("plan", set()).add(str(h["role"]))
    # campaign log: "spawned <agent>" / "agent: <name>" lines under the phase they were logged in (best effort)
    log = campaign_dir / "log.md"
    if log.exists():
        current = None
        for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
            pm = re.search(r"phase\s*(?:->|→|:)\s*([a-z]+)", ln, re.IGNORECASE)
            if pm and pm.group(1).lower() in out:
                current = pm.group(1).lower()
            am = re.search(r"\b(?:spawned|agent)\s*:?\s*`?([a-z][a-z\-]+)`?", ln, re.IGNORECASE)
            if am and current:
                out[current].add(am.group(1).lower())
    if (campaign_dir / "portfolio.md").exists():
        out.setdefault("scout", set()).add("scout")
    if (campaign_dir / "paper" / "main.tex").exists():
        out.setdefault("write", set()).update({"writer"})
    if (campaign_dir / "paper" / "qa.md").exists() or (campaign_dir / "paper" / "audit.json").exists():
        out.setdefault("write", set()).add("copyeditor")
    return out


def _theorem_rows(campaign_dir: Path, verified_by_human: set[str]) -> list[TheoremRow]:
    rows: list[TheoremRow] = []
    try:
        from harness.ledger.ledger import LedgerStore
    except Exception:
        return rows
    lp = campaign_dir / "ledger.json"
    if not lp.exists():
        return rows
    try:
        store = LedgerStore(lp)
    except Exception:  # noqa: BLE001
        return rows
    for claim in store.assertable():
        rounds = [ev.round for ev in claim.evidence if ev.type == "referee" and ev.round is not None]
        last = max(rounds) if rounds else None
        sk = [ev for ev in claim.evidence if ev.type == "referee" and ev.role == "skeptic" and ev.round == last
              and ev.verdict == "pass" and ev.admissible is not False]
        ids = {ev.agent_id for ev in sk if ev.agent_id}
        passes = len(ids) if ids else (1 if sk else 0)
        rels = [ev.reliability for ev in sk if ev.reliability is not None]
        rel = round(sum(rels) / len(rels), 2) if rels else None
        replicated = any(ev.type == "referee" and ev.role == "replicator" and ev.round == last and ev.verdict == "pass" for ev in claim.evidence)
        formalized = claim.status == "formalized"
        human = bool(claim.attestation) or claim.id in verified_by_human
        line = (f"machine-refereed ({passes} skeptic pass{'es' if passes != 1 else ''}"
                + (f", lineup reliability {rel}" if rel is not None else "") + f"), replicated: {'yes' if replicated else 'no'}, "
                f"formalized: {'yes' if formalized else 'no'}, human-verified: {'yes' if human else 'no'}")
        rows.append(TheoremRow(claim=claim.id, skeptic_passes=passes, lineup_reliability=rel, replicated=replicated,
                               formalized=formalized, human_verified=human, line=line))
    return rows


def build_disclosure(campaign_dir: Path | str) -> Disclosure:
    campaign_dir = Path(campaign_dir)
    camp = _read_json(campaign_dir / "campaign.json")
    from harness.paper.repro import _harness_version, git_revision, tectonic_version

    levels, verified = _human_blocks(campaign_dir)
    history = camp.get("phase_history") or []
    phase_names = [str(h.get("phase")) for h in history] or ["bootstrap"]
    agents = _agents_by_phase(campaign_dir, phase_names)
    phases: list[PhaseRow] = []
    seen: set[str] = set()
    for h in history:
        p = str(h.get("phase"))
        if p in seen:
            continue
        seen.add(p)
        phases.append(PhaseRow(phase=p, entered=h.get("entered"), exited=h.get("exited"),
                               agents=sorted(agents.get(p, set())), human_involvement=levels.get(p, "none")))
    # phases that left evidence but never appear in phase_history (e.g. a standalone review) are still disclosed
    order = ["bootstrap", "scout", "survey", "plan", "explore", "prove", "review", "write", "done"]
    for p in sorted((k for k, v in agents.items() if v and k not in seen), key=lambda k: order.index(k) if k in order else 99):
        seen.add(p)
        phases.append(PhaseRow(phase=p, agents=sorted(agents[p]), human_involvement=levels.get(p, "none")))
    return Disclosure(
        campaign=str(camp.get("slug") or campaign_dir.name),
        generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        git_rev=git_revision(campaign_dir),
        tools=[f"Neugier harness {_harness_version()}", f"Python {'.'.join(map(str, __import__('sys').version_info[:3]))}",
               f"tectonic {tectonic_version()}"],
        phases=phases,
        theorems=_theorem_rows(campaign_dir, verified),
    )


def write_disclosure(campaign_dir: Path | str) -> Path:
    from harness.ledger.ledger import atomic_write_json

    d = build_disclosure(campaign_dir)
    out = Path(campaign_dir) / "disclosure.json"
    atomic_write_json(out, json.loads(d.model_dump_json()))
    return out


def render_disclosure_tex(campaign_dir: Path | str, paper_dir: Path | str) -> str:
    from harness.paper.repro import _attrib, _render_table, escape_latex

    d = build_disclosure(campaign_dir)
    parts = [r"\subsection{AI involvement disclosure}\label{sec:disclosure}"]
    parts.append(
        "This section is generated from the campaign record, following the disclosure requirement of "
        + _attrib(Path(paper_dir), "agents4science2025", "Agents4Science 2025") + ". " + escape_latex(d.model_routing) + "\n"
    )
    parts.append(_render_table(["Phase", "Agents", "Human involvement"],
                               [(p.phase, ", ".join(p.agents) or "—", p.human_involvement) for p in d.phases],
                               "No phase history recorded.", small=True))
    if d.theorems:
        parts.append(r"\begin{itemize}")
        for t in d.theorems:
            parts.append(r"\item " + escape_latex(f"{t.claim}: {t.line}"))
        parts.append(r"\end{itemize}")
    else:
        parts.append("No theorem is asserted.\n")
    parts.append("Tools: " + escape_latex("; ".join(d.tools)) + ".\n")
    return "\n".join(parts) + "\n"
