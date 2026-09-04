"""Generate the *Questions and surprises* appendix (``paper/appendix-questions.tex``).

Curiosity is a first-class output of a Neugier campaign (rule R6): the paper
prints what the campaign still does not know, what surprised it and why, and
which detours it took. ``main.tex`` includes the file when it exists.
"""
from __future__ import annotations

from pathlib import Path

from harness.paper.repro import _render_table, escape_latex
from harness.questions import QuestionsDoc, load_doc


def render_questions_tex(doc: QuestionsDoc) -> str:
    parts: list[str] = [r"\subsection{Open questions and surprises}"]
    open_q = [q for q in doc.questions if q.status == "open"]
    parked = [q for q in doc.questions if q.status == "parked"]
    answered = [q for q in doc.questions if q.status == "answered"]
    parts.append(
        f"The campaign recorded {len(doc.questions)} question(s): {len(open_q)} open, {len(answered)} answered, "
        f"{len(parked)} parked; {len(doc.observations)} prediction/observation pair(s); {len(doc.detours)} detour(s). "
        "Open questions are listed so that the reader knows what the authors do not know.\n"
    )
    parts.append(r"\subsubsection*{Open questions}")
    parts.append(_render_table(
        ["Id", "Question", "Curiosity", "Stake", "Cheapest test"],
        [(q.id, q.title, f"{q.curiosity}/{q.curiosity_max}", str(q.stake), q.cheapest_test) for q in open_q + parked],
        "No open questions remain.",
    ))
    parts.append(r"\subsubsection*{Predictions and surprises}")
    parts.append(_render_table(
        ["Kind", "Question", "Predicted", "Observed", "Surprise", "Follow-up"],
        [(o.kind, o.question_id or o.title, o.predicted, o.observed,
          f"{o.score}/{o.score_max}" if o.score is not None else "", o.follow_up) for o in doc.observations],
        "No predictions were recorded.",
    ))
    parts.append(r"\subsubsection*{Detours}")
    parts.append(_render_table(
        ["Phase", "Minutes", "Question", "What was learned", "Plan impact"],
        [(d.phase, f"{d.minutes:.0f}", d.question_id or "", d.learned, d.impact) for d in doc.detours],
        "No detours were taken.",
    ))
    return "\n".join(parts) + "\n"


def write_questions_appendix(campaign_dir: Path) -> Path:
    campaign_dir = Path(campaign_dir)
    paper_dir = campaign_dir / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    out = paper_dir / "appendix-questions.tex"
    out.write_text(render_questions_tex(load_doc(campaign_dir)), encoding="utf-8")
    return out


__all__ = ["render_questions_tex", "write_questions_appendix", "escape_latex"]
