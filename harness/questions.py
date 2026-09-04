"""Curiosity engine (rule R6): the question ledger as a machine-readable object.

``campaigns/<slug>/questions.md`` is written by agents in the formats of
``skills/references/curiosity.md``; this module parses it, ranks open questions
by expected information gain, meters the detour budget, records surprises and
detours safely (editing only the lines it owns), and handles the metered human
escalations of Round 2 (``ASK-HUMAN.md`` / ``HUMAN.md``).

Block formats (a block starts at a ``## `` heading and ends at the next one)::

    ## Q-003: Why does the greedy Sidon construction plateau near density 0.29?
    - Curiosity: 3/3            (n or n/m; default scale 5)
    - Stake: 4/5                (optional, default 3)
    - Expectation: density decays like c/sqrt(N)
    - Cheapest test: run seed.py for N = 100..5000 (≤ 15 min)
    - Cost: 15 min              (optional; else parsed from the cheapest test)
    - Credence: 0.3             (optional p_true for the expectation)
    - Status: open | answered → <ref> | parked → <why> | dropped → <reason>
    - Raised by: experimentalist, 2026-09-02, explore

    ## Prediction (Q-003): greedy density for N=5000
    - Predicted: 0.014
    - Observed: 0.29
    - Surprise: 3/3
    - Follow-up: Q-007

    ## Surprise (Q-003): plateau at 0.29
    - Prediction: ...
    - Observation: ...
    - Curiosity: 3/3
    - Follow-up: ...

    ## Detour (explore, 40 min): Q-003
    - What I did: ...
    - What I learned: ...
    - Plan impact: none | re-plan requested (reason) | new target proposed (id)

Expected information gain of an open question (Round 2, X2)::

    gain = uncertainty × stake / max(cost_minutes, 5)
    uncertainty = 4·p·(1−p) if a credence p is recorded, else curiosity / scale

so that a question whose expectation is maximally uncertain, high-stakes and
cheap to test comes first.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from harness import CAMPAIGNS

QUESTION_STATUSES = ("open", "answered", "parked", "dropped")

_HEADING_RE = re.compile(r"^##\s+(.*)$")
_Q_RE = re.compile(r"^(Q-\d+)\s*[:.\-–—]\s*(.*)$")
_PRED_RE = re.compile(r"^(Prediction|Surprise)\s*(?:\((Q-\d+)\))?\s*[:.\-–—]?\s*(.*)$", re.IGNORECASE)
_DETOUR_RE = re.compile(
    r"^Detour\s*\(\s*([A-Za-z]+)\s*,\s*(\d+(?:\.\d+)?)\s*(min|mins|minutes|m|h|hr|hrs|hours)?\s*\)\s*[:.\-–—]?\s*(Q-\d+)?\s*(.*)$",
    re.IGNORECASE,
)
_FIELD_RE = re.compile(r"^\s*[-*]\s*([A-Za-z][A-Za-z /_-]*?)\s*:\s*(.*)$")
_SCORE_RE = re.compile(r"(\d+)\s*(?:/\s*(\d+))?")
_COST_RE = re.compile(r"(?:≤|<=|~|about|approx\.?)?\s*(\d+(?:\.\d+)?)\s*(min|mins|minutes|m|h|hr|hrs|hours)\b", re.IGNORECASE)
_STATUS_RE = re.compile(r"^(open|answered|parked|dropped)\b\s*(?:[→\->:]+\s*(.*))?$", re.IGNORECASE)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ models --

class Question(BaseModel):
    id: str
    title: str
    curiosity: int = 3
    curiosity_max: int = 5
    stake: int = 3
    cost_minutes: int = 30
    expectation: str = ""
    cheapest_test: str = ""
    p_true: float | None = None
    status: str = "open"
    status_ref: str = ""
    raised_by: str = ""
    phase: str = ""
    line: int = 0

    @property
    def uncertainty(self) -> float:
        if self.p_true is not None:
            p = min(max(self.p_true, 0.0), 1.0)
            return 4.0 * p * (1.0 - p)
        return self.curiosity / max(self.curiosity_max, 1)


class Observation(BaseModel):
    """A ``## Prediction`` or ``## Surprise`` block (kind tells which)."""

    kind: str  # prediction | surprise
    title: str = ""
    question_id: str | None = None
    predicted: str = ""
    observed: str = ""
    score: int | None = None  # surprise score
    score_max: int = 3
    follow_up: str = ""
    line: int = 0


class Detour(BaseModel):
    phase: str
    minutes: float
    question_id: str | None = None
    what: str = ""
    learned: str = ""
    impact: str = ""
    line: int = 0


class QuestionsDoc(BaseModel):
    questions: list[Question] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    detours: list[Detour] = Field(default_factory=list)

    def open(self) -> list[Question]:
        return [q for q in self.questions if q.status == "open"]

    def get(self, qid: str) -> Question | None:
        for q in self.questions:
            if q.id == qid:
                return q
        return None


class Escalation(BaseModel):
    id: str
    question_id: str | None = None
    question: str
    stake: int = 3
    would_change: str = ""
    cheapest_human_action: str = ""
    best_guess: str = ""
    p_true: float | None = None
    raised_by: str = ""
    phase: str = ""
    created: str = Field(default_factory=_utc)
    answered: str | None = None
    answer: str = ""


# ----------------------------------------------------------------- parsing --

def _score(value: str, default_max: int) -> tuple[int, int]:
    m = _SCORE_RE.search(value or "")
    if not m:
        return 0, default_max
    n = int(m.group(1))
    mx = int(m.group(2)) if m.group(2) else default_max
    return n, mx


def _minutes(value: str) -> float | None:
    m = _COST_RE.search(value or "")
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2).lower()
    return n * 60.0 if unit.startswith("h") else n


def _fields(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    last: str | None = None
    for ln in lines:
        m = _FIELD_RE.match(ln)
        if m:
            last = m.group(1).strip().lower().replace("_", " ")
            out[last] = m.group(2).strip()
        elif last and ln.strip() and not ln.startswith("#"):
            out[last] = (out[last] + " " + ln.strip()).strip()
    return out


def _blocks(text: str) -> list[tuple[int, str, list[str]]]:
    """``(line_no, heading, body_lines)`` for every ``## `` block."""
    blocks: list[tuple[int, str, list[str]]] = []
    cur: tuple[int, str, list[str]] | None = None
    for i, ln in enumerate(text.splitlines(), 1):
        m = _HEADING_RE.match(ln)
        if m:
            if cur:
                blocks.append(cur)
            cur = (i, m.group(1).strip(), [])
        elif cur:
            cur[2].append(ln)
    if cur:
        blocks.append(cur)
    return blocks


def parse_questions(text: str) -> QuestionsDoc:
    doc = QuestionsDoc()
    for line_no, heading, body in _blocks(text or ""):
        f = _fields(body)
        mq = _Q_RE.match(heading)
        if mq:
            cur, cur_max = _score(f.get("curiosity", ""), 5)
            stake, _ = _score(f.get("stake", ""), 5)
            cost = _minutes(f.get("cost", "")) or _minutes(f.get("cheapest test", "")) or 30.0
            p = None
            for key in ("credence", "p true", "p_true", "p"):
                if key in f:
                    try:
                        p = float(f[key].split()[0])
                    except ValueError:
                        p = None
                    break
            status, ref = "open", ""
            ms = _STATUS_RE.match(f.get("status", "open"))
            if ms:
                status = ms.group(1).lower()
                ref = (ms.group(2) or "").strip()
            raised = f.get("raised by", "")
            phase = ""
            parts = [p_.strip() for p_ in raised.split(",")]
            if len(parts) >= 3:
                phase = parts[-1]
            doc.questions.append(Question(
                id=mq.group(1), title=mq.group(2).strip(), curiosity=cur or 3, curiosity_max=cur_max,
                stake=stake or 3, cost_minutes=int(round(cost)), expectation=f.get("expectation", ""),
                cheapest_test=f.get("cheapest test", ""), p_true=p, status=status, status_ref=ref,
                raised_by=raised, phase=phase, line=line_no,
            ))
            continue
        mp = _PRED_RE.match(heading)
        if mp:
            kind = mp.group(1).lower()
            score_txt = f.get("surprise", "") or f.get("score", "") or f.get("curiosity", "")
            score, score_max = _score(score_txt, 3)
            qid = mp.group(2)
            fu = f.get("follow-up", "") or f.get("follow up", "") or f.get("followup", "")
            if qid is None:
                mq2 = re.search(r"(Q-\d+)", mp.group(3) or "")
                qid = mq2.group(1) if mq2 else None
            doc.observations.append(Observation(
                kind=kind, title=(mp.group(3) or "").strip(), question_id=qid,
                predicted=f.get("predicted", "") or f.get("prediction", ""),
                observed=f.get("observed", "") or f.get("observation", ""),
                score=score if score_txt else None, score_max=score_max, follow_up=fu, line=line_no,
            ))
            continue
        md = _DETOUR_RE.match(heading)
        if md:
            n = float(md.group(2))
            unit = (md.group(3) or "min").lower()
            minutes = n * 60.0 if unit.startswith("h") else n
            doc.detours.append(Detour(
                phase=md.group(1).lower(), minutes=minutes, question_id=md.group(4),
                what=f.get("what i did", ""), learned=f.get("what i learned", ""),
                impact=f.get("plan impact", ""), line=line_no,
            ))
    return doc


# ----------------------------------------------------------------- ranking --

def info_gain(q: Question) -> float:
    return q.uncertainty * q.stake / max(q.cost_minutes, 5)


def rank_open(doc: QuestionsDoc) -> list[tuple[float, Question]]:
    ranked = [(info_gain(q), q) for q in doc.open()]
    ranked.sort(key=lambda t: (-t[0], t[1].id))
    return ranked


def detour_minutes(doc: QuestionsDoc, phase: str | None = None) -> float:
    return sum(d.minutes for d in doc.detours if phase is None or d.phase == phase)


def detour_budget_minutes(budgets: dict, phase: str) -> float | None:
    """``curiosity_fraction × hours_per_phase[phase] × 60`` or ``None`` when the phase has no budget."""
    frac = float(budgets.get("curiosity_fraction", 0.3) or 0.0)
    per = budgets.get("hours_per_phase") or {}
    hours = per.get(phase)
    if hours is None:
        return None
    return float(hours) * 60.0 * frac


def _role_of(raised_by: str) -> str:
    return (raised_by or "").split(",")[0].strip().lower()


def calibration_warning(role: str, warn_brier: float = 0.25, min_n: int = 10) -> str | None:
    """Warn when the role's pooled Brier score across campaigns is poor (Round-2 X2)."""
    if not role:
        return None
    try:
        from harness.library import memory

        stats = memory.role_brier(role)
    except Exception:
        return None
    if stats["n"] >= min_n and stats["brier"] is not None and stats["brier"] > warn_brier:
        return f"{role}'s pre-registered credences have Brier {stats['brier']} over {stats['n']} resolved claims (> {warn_brier}); discount its expectation"
    return None


def next_actions(doc: QuestionsDoc, budget_left: float | None, top: int = 3, warn_brier: float = 0.25) -> dict:
    ranked = rank_open(doc)
    items = []
    warnings: list[str] = []
    for gain, q in ranked[:top]:
        w = calibration_warning(_role_of(q.raised_by), warn_brier)
        if w and w not in warnings:
            warnings.append(w)
        items.append({
            "id": q.id, "title": q.title, "gain": round(gain, 4), "expectation": q.expectation,
            "cheapest_test": q.cheapest_test, "cost_minutes": q.cost_minutes, "stake": q.stake,
            "p_true": q.p_true, "curiosity": f"{q.curiosity}/{q.curiosity_max}", "raised_by": q.raised_by,
            "affordable": budget_left is None or q.cost_minutes <= budget_left,
            "calibration_warning": w,
        })
    return {"open": len(doc.open()), "detour_budget_left_minutes": budget_left, "next": items, "warnings": warnings}


def hot_surprises_without_followup(doc: QuestionsDoc) -> list[Observation]:
    return [o for o in doc.observations if o.score is not None and o.score >= o.score_max and not o.follow_up.strip()]


def unanswered_by(doc: QuestionsDoc, role: str) -> list[Question]:
    return [q for q in doc.open() if role.lower() in q.raised_by.lower()]


def recorded_predictions(doc: QuestionsDoc) -> list[Observation]:
    return [o for o in doc.observations if o.observed.strip()]


# ---------------------------------------------------------------- editing --

def set_status(text: str, qid: str, status: str, ref: str = "") -> str:
    """Rewrite (or add) the ``- Status:`` line of question ``qid``; other text untouched."""
    if status not in QUESTION_STATUSES:
        raise ValueError(f"status must be one of {QUESTION_STATUSES}")
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        m = _HEADING_RE.match(ln)
        if m and _Q_RE.match(m.group(1).strip()) and _Q_RE.match(m.group(1).strip()).group(1) == qid:
            start = i
            break
    if start is None:
        raise KeyError(f"question {qid} not found")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _HEADING_RE.match(lines[j]):
            end = j
            break
    new_line = f"- Status: {status}" + (f" → {ref}" if ref else "")
    for j in range(start + 1, end):
        m = _FIELD_RE.match(lines[j])
        if m and m.group(1).strip().lower() == "status":
            lines[j] = new_line
            break
    else:
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, new_line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def append_block(text: str, block: str) -> str:
    base = text if text.endswith("\n") or not text else text + "\n"
    if base and not base.endswith("\n\n"):
        base += "\n"
    return base + block.rstrip("\n") + "\n"


def surprise_block(*, question_id: str | None, title: str, prediction: str, observation: str,
                   score: int, follow_up: str = "", kind: str = "Surprise") -> str:
    head = f"## {kind}" + (f" ({question_id})" if question_id else "") + (f": {title}" if title else "")
    key_p, key_o = ("Predicted", "Observed") if kind.lower() == "prediction" else ("Prediction", "Observation")
    lines = [head, f"- {key_p}: {prediction}", f"- {key_o}: {observation}", f"- Surprise: {score}/3"]
    if follow_up:
        lines.append(f"- Follow-up: {follow_up}")
    return "\n".join(lines) + "\n"


def detour_block(*, phase: str, minutes: float, question_id: str | None, what: str, learned: str, impact: str) -> str:
    head = f"## Detour ({phase}, {int(round(minutes))} min)" + (f": {question_id}" if question_id else "")
    return "\n".join([head, f"- What I did: {what}", f"- What I learned: {learned}", f"- Plan impact: {impact or 'none'}"]) + "\n"


# ------------------------------------------------------------ escalations --

ESCALATIONS_FILE = "escalations.json"
ASK_HUMAN_FILE = "ASK-HUMAN.md"
HUMAN_FILE = "HUMAN.md"

HUMAN_TEMPLATE = """# HUMAN.md — the human's file

This file belongs to the human running the campaign. **Agents never edit it**
(the frozen-file guard denies writes). Agents read it at the start of every
phase. Cf. karpathy/autoresearch (`program.md` is owned by the human; the loop
never stops to ask) and the DeepMind co-mathematician (escalations carry a
concrete question and never block other work).

## Policy

<!-- Standing instructions for this campaign: preferences, constraints, what to prioritize, what to avoid. -->

## Answers

<!-- Answer escalations from ASK-HUMAN.md here, one block per id:
### H-001
your answer …
-->
"""


def load_escalations(campaign_dir: Path) -> list[Escalation]:
    path = Path(campaign_dir) / ESCALATIONS_FILE
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return [Escalation.model_validate(e) for e in data.get("escalations", [])]


def save_escalations(campaign_dir: Path, items: list[Escalation]) -> None:
    from harness.ledger.ledger import atomic_write_json

    atomic_write_json(Path(campaign_dir) / ESCALATIONS_FILE, {"escalations": [e.model_dump() for e in items]})


def render_ask_human(items: list[Escalation], slug: str) -> str:
    lines = [f"# ASK-HUMAN — {slug}", "",
             "Concrete questions where the campaign's expected gain from a human answer is highest.",
             "Answer in `HUMAN.md` under `## Answers` as `### H-nnn` blocks; the campaign keeps working meanwhile.", ""]
    if not items:
        lines.append("(no escalations)")
    for e in items:
        state = f"answered {e.answered}" if e.answered else "open"
        lines += [
            f"## {e.id} ({state}) — stake {e.stake}/5" + (f" — {e.question_id}" if e.question_id else ""),
            f"- Question: {e.question}",
            f"- What the answer would change: {e.would_change or '(unspecified)'}",
            f"- Cheapest thing you could do: {e.cheapest_human_action or '(unspecified)'}",
            f"- Our best guess: {e.best_guess or '(none)'}" + (f" (p={e.p_true})" if e.p_true is not None else ""),
            f"- Raised by: {e.raised_by or '?'}, {e.phase or '?'}, {e.created[:10]}",
        ]
        if e.answered:
            lines.append(f"- Answer: {e.answer}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def escalate(campaign_dir: Path, slug: str, budgets: dict, **fields) -> Escalation:
    """Add an escalation (exit 3 at the CLI when the human-interrupt budget is exhausted)."""
    items = load_escalations(campaign_dir)
    limit = int(budgets.get("human_interrupts", 3))
    if len(items) >= limit:
        raise BudgetExhausted(f"human-interrupt budget exhausted ({len(items)}/{limit}); answer or drop existing escalations first")
    esc = Escalation(id=f"H-{len(items) + 1:03d}", **fields)
    items.append(esc)
    save_escalations(campaign_dir, items)
    (Path(campaign_dir) / ASK_HUMAN_FILE).write_text(render_ask_human(items, slug), encoding="utf-8")
    return esc


class BudgetExhausted(Exception):
    pass


def parse_human_answers(text: str) -> dict[str, str]:
    """``### H-001`` blocks under ``## Answers`` in HUMAN.md -> {id: answer}."""
    m = re.search(r"^##\s+Answers\s*$(.*)", text or "", re.MULTILINE | re.DOTALL)
    section = m.group(1) if m else ""
    section = re.sub(r"<!--.*?-->", "", section, flags=re.DOTALL)
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for ln in section.splitlines():
        h = re.match(r"^###\s+(H-\d+)\b", ln)
        if h:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = h.group(1), []
        elif ln.startswith("## "):
            break
        elif cur is not None:
            buf.append(ln)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return {k: v for k, v in out.items() if v}


def sync_human_answers(campaign_dir: Path, slug: str) -> list[Escalation]:
    """Pull answers from HUMAN.md into escalations.json, mark linked questions answered."""
    campaign_dir = Path(campaign_dir)
    human = campaign_dir / HUMAN_FILE
    if not human.exists():
        return []
    answers = parse_human_answers(human.read_text(encoding="utf-8"))
    items = load_escalations(campaign_dir)
    newly: list[Escalation] = []
    for e in items:
        if e.id in answers and not e.answered:
            e.answered = _utc()
            e.answer = answers[e.id]
            newly.append(e)
    if newly:
        save_escalations(campaign_dir, items)
        (campaign_dir / ASK_HUMAN_FILE).write_text(render_ask_human(items, slug), encoding="utf-8")
        qpath = campaign_dir / "questions.md"
        if qpath.exists():
            text = qpath.read_text(encoding="utf-8")
            for e in newly:
                if e.question_id:
                    try:
                        text = set_status(text, e.question_id, "answered", f"HUMAN.md#{e.id}")
                    except KeyError:
                        pass
            qpath.write_text(text, encoding="utf-8")
    return newly


def human_summary(campaign_dir: Path, budgets: dict) -> dict:
    items = load_escalations(campaign_dir)
    human = Path(campaign_dir) / HUMAN_FILE
    mtime = None
    if human.exists():
        mtime = datetime.fromtimestamp(human.stat().st_mtime, tz=timezone.utc).isoformat(timespec="minutes")
    return {
        "used": len(items),
        "limit": int(budgets.get("human_interrupts", 3)),
        "open": [e.id for e in items if not e.answered],
        "human_md_updated": mtime,
    }


# --------------------------------------------------------------- campaign --

def _campaign_dir(slug: str) -> Path:
    return Path(CAMPAIGNS) / slug


def _budgets(campaign_dir: Path) -> dict:
    try:
        with open(campaign_dir / "campaign.json", "r", encoding="utf-8") as fh:
            data = json.load(fh)
        b = data.get("budgets") or {}
        return b if isinstance(b, dict) else {}
    except (OSError, ValueError):
        return {}


def _phase(campaign_dir: Path) -> str:
    try:
        with open(campaign_dir / "campaign.json", "r", encoding="utf-8") as fh:
            return str(json.load(fh).get("phase", ""))
    except (OSError, ValueError):
        return ""


def load_doc(campaign_dir: Path) -> QuestionsDoc:
    path = Path(campaign_dir) / "questions.md"
    if not path.exists():
        return QuestionsDoc()
    return parse_questions(path.read_text(encoding="utf-8"))


def budget_status(campaign_dir: Path) -> dict:
    doc = load_doc(campaign_dir)
    phase = _phase(campaign_dir)
    budgets = _budgets(campaign_dir)
    used = detour_minutes(doc, phase)
    limit = detour_budget_minutes(budgets, phase)
    return {
        "phase": phase, "detour_minutes_used": used, "detour_budget_minutes": limit,
        "left": (limit - used) if limit is not None else None,
        "over": limit is not None and used > limit,
        "curiosity_fraction": budgets.get("curiosity_fraction", 0.3),
    }


def advisories(campaign_dir: Path) -> list[str]:
    """Non-blocking recommendations printed by ``campaign check`` (rule R6)."""
    doc = load_doc(campaign_dir)
    out: list[str] = []
    for o in hot_surprises_without_followup(doc):
        out.append(
            f"surprise {o.score}/{o.score_max} without follow-up (line {o.line}: {o.title or o.question_id or '?'}); "
            "consider re-planning (strategist) or a detour, and record `decision: …` in log.md"
        )
    b = budget_status(campaign_dir)
    if b["over"]:
        out.append(f"detour budget exceeded in phase {b['phase']}: {b['detour_minutes_used']:.0f}/{b['detour_budget_minutes']:.0f} min")
    return out


def top_open_line(campaign_dir: Path) -> str:
    """One-line reminder for context injection after compaction."""
    doc = load_doc(campaign_dir)
    ranked = rank_open(doc)
    if not ranked:
        return "open questions: 0"
    gain, q = ranked[0]
    return f"open questions: {len(ranked)}; top: {q.id} {q.title} (gain {gain:.3f}, cheapest test: {q.cheapest_test or '?'})"


# -------------------------------------------------------------------- CLI --

def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness questions", description="curiosity engine over questions.md (rule R6)")
    p.add_argument("--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="all questions, surprises and detours as JSON")
    n = sub.add_parser("next", help="open questions ranked by expected information gain")
    n.add_argument("--top", type=int, default=3)
    n.add_argument("--brief", action="store_true", help="one line (used by the context hook)")
    s = sub.add_parser("surprise", help="append a prediction/observation pair")
    s.add_argument("--question", default=None)
    s.add_argument("--title", default="")
    s.add_argument("--prediction", required=True)
    s.add_argument("--observation", required=True)
    s.add_argument("--score", type=int, required=True, choices=[1, 2, 3])
    s.add_argument("--follow-up", default="")
    s.add_argument("--as-prediction", action="store_true", help="record as `## Prediction` (matched prediction) instead of `## Surprise`")
    d = sub.add_parser("detour", help="log a detour against the curiosity budget")
    d.add_argument("--phase", required=True)
    d.add_argument("--minutes", type=float, required=True)
    d.add_argument("--question", default=None)
    d.add_argument("--what", required=True)
    d.add_argument("--learned", required=True)
    d.add_argument("--impact", default="none")
    for name in ("answer", "park", "drop"):
        a = sub.add_parser(name, help=f"mark a question {name}ed")
        a.add_argument("id")
        a.add_argument("--ref", default="", help="evidence path / claim id / reason")
    sub.add_parser("budget", help="detour minutes used vs curiosity budget for the current phase")
    e = sub.add_parser("export", help="open questions as JSON rows (for library/questions.jsonl)")
    e.add_argument("--json", action="store_true")
    fh = sub.add_parser("for-human", help="escalate a concrete question to the human (metered by budgets.human_interrupts)")
    fh.add_argument("--q", default=None, help="question id")
    fh.add_argument("--question", default=None, help="question text (default: the question's title)")
    fh.add_argument("--stake", type=int, default=3, choices=[1, 2, 3, 4, 5])
    fh.add_argument("--would-change", default="")
    fh.add_argument("--cheapest", default="")
    fh.add_argument("--best-guess", default="")
    fh.add_argument("--p", type=float, default=None)
    fh.add_argument("--raised-by", default="")
    sub.add_parser("human-answers", help="pull answers from HUMAN.md into the question ledger")
    sub.add_parser("advisories", help="non-blocking curiosity advisories")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, tok in enumerate(argv):
        if tok == "--campaign" and i + 1 < len(argv) and i != 0:
            argv = [tok, argv[i + 1]] + argv[:i] + argv[i + 2:]
            break
    args = build_parser().parse_args(argv)
    cdir = _campaign_dir(args.campaign)
    qpath = cdir / "questions.md"
    doc = load_doc(cdir)
    budgets = _budgets(cdir)

    if args.cmd == "list":
        _print(doc.model_dump())
        return 0
    if args.cmd == "next":
        b = budget_status(cdir)
        if args.brief:
            print(top_open_line(cdir))
            return 0
        _print(next_actions(doc, b["left"], top=args.top, warn_brier=float(budgets.get("calibration_warn_brier", 0.25))))
        return 0
    if args.cmd == "surprise":
        block = surprise_block(question_id=args.question, title=args.title, prediction=args.prediction,
                               observation=args.observation, score=args.score, follow_up=args.follow_up,
                               kind="Prediction" if args.as_prediction else "Surprise")
        text = qpath.read_text(encoding="utf-8") if qpath.exists() else ""
        qpath.write_text(append_block(text, block), encoding="utf-8")
        print(block, end="")
        return 0
    if args.cmd == "detour":
        block = detour_block(phase=args.phase, minutes=args.minutes, question_id=args.question,
                             what=args.what, learned=args.learned, impact=args.impact)
        text = qpath.read_text(encoding="utf-8") if qpath.exists() else ""
        qpath.write_text(append_block(text, block), encoding="utf-8")
        print(block, end="")
        b = budget_status(cdir)
        if b["over"]:
            print(f"[questions] detour budget exceeded: {b['detour_minutes_used']:.0f}/{b['detour_budget_minutes']:.0f} min", file=sys.stderr)
        return 0
    if args.cmd in ("answer", "park", "drop"):
        status = {"answer": "answered", "park": "parked", "drop": "dropped"}[args.cmd]
        try:
            text = set_status(qpath.read_text(encoding="utf-8"), args.id, status, args.ref)
        except (KeyError, OSError) as exc:
            print(f"[questions] {exc}", file=sys.stderr)
            return 1
        qpath.write_text(text, encoding="utf-8")
        print(f"{args.id}: {status}" + (f" → {args.ref}" if args.ref else ""))
        return 0
    if args.cmd == "budget":
        _print(budget_status(cdir))
        return 0
    if args.cmd == "export":
        rows = [q.model_dump() for q in doc.open()]
        _print(rows)
        return 0
    if args.cmd == "for-human":
        q = doc.get(args.q) if args.q else None
        question = args.question or (q.title if q else None)
        if not question:
            print("[questions] give --question or a known --q id", file=sys.stderr)
            return 1
        try:
            esc = escalate(
                cdir, args.campaign, budgets, question_id=args.q, question=question, stake=args.stake,
                would_change=args.would_change, cheapest_human_action=args.cheapest, best_guess=args.best_guess,
                p_true=args.p, raised_by=args.raised_by, phase=_phase(cdir),
            )
        except BudgetExhausted as exc:
            print(f"[questions] {exc}", file=sys.stderr)
            return 3
        _print(esc.model_dump())
        return 0
    if args.cmd == "human-answers":
        newly = sync_human_answers(cdir, args.campaign)
        _print([e.model_dump() for e in newly])
        return 0
    if args.cmd == "advisories":
        for a in advisories(cdir):
            print(f"advisory: {a}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
