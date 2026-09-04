"""Campaign lifecycle: create/load/save, phase transitions, budgets, frozen files,
outcome validation and phase-exit gates.

A "campaign" (``campaigns/<slug>/``) is a portfolio of targets pursued under a
budget through the phase protocol described in CLAUDE.md:
bootstrap -> scout -> survey -> plan -> explore -> prove -> review -> write -> done.
The Stop hook is meant to call :func:`check_phase_exit` and refuse to end a
phase whose criteria are unmet.

Round 2 makes three promises real here:

* **Budgets are read, not just stored.** :class:`Budgets` is typed; phase hours
  are derived from ``phase_history`` and a phase that overran its budget cannot
  exit without a ``## Budget overrun`` note in ``log.md`` naming the phase.
* **Outcome classes are derived, not declared.** :func:`validate_outcome` checks
  the class against the ledger and the novelty memo (1a/1b/1c/1d).
* **Frozen files.** :func:`freeze` records sha256 of scorer/verifier/statement
  files; the ``guard_frozen`` hook and :func:`frozen_changed` detect edits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from harness import CAMPAIGNS
from harness.ledger.ledger import LedgerError, LedgerStore, atomic_write_json, pipeline_rank
from harness.ledger.schema import utc_now_iso

PHASES: list[str] = [
    "bootstrap",
    "scout",
    "survey",
    "plan",
    "explore",
    "prove",
    "review",
    "write",
    "done",
]

OUTCOME_CLASSES = ("autonomous-new-result", "partial", "rediscovery", "literature-find", "negative")
OutcomeClass = Literal["autonomous-new-result", "partial", "rediscovery", "literature-find", "negative"]

# Files that are always treated as frozen once the statement is locked.
ALWAYS_FROZEN = ("statement.md",)


class CampaignError(Exception):
    """Raised for any invalid campaign operation (unknown slug, unknown phase, missing file, ...)."""


class Budgets(BaseModel):
    """Typed campaign budgets (``campaign.json["budgets"]``). Unknown keys are kept."""

    model_config = ConfigDict(extra="allow")

    hours_total: float | None = None
    hours_per_phase: dict[str, float] = Field(default_factory=dict)
    max_review_rounds: int = 3
    curiosity_fraction: float = 0.3
    noise_floor: float = 0.0
    max_evolve_generations: int | None = None
    # Round 2 — review regime (X1/Y1)
    decoys_per_round: int = 2
    lineup_min_recall: float = 0.8
    lineup_control: bool = True
    skeptic_passes: int = 2
    max_skeptic_respawns: int = 2
    # Round 2 — humans and calibration (X6/X2)
    human_interrupts: int = 3
    calibration_warn_brier: float = 0.25
    # Round 2 — sketch tournament (Y6)
    full_proofs: int = 2
    sketch_personas: int = 3
    elo_k: int = 32
    pucb_c: float = 1.0
    debate_top: int = 3


class Campaign(BaseModel):
    """Top-level campaign record, persisted at ``campaigns/<slug>/campaign.json``."""

    model_config = ConfigDict(validate_assignment=True)

    slug: str
    title: str
    created: str = Field(default_factory=utc_now_iso)
    phase: str = "bootstrap"
    phase_history: list[dict] = Field(default_factory=list)
    budgets: Budgets = Field(default_factory=Budgets)
    active_targets: list[str] = Field(default_factory=list)
    outcome_class: OutcomeClass | None = None
    statement_hash: str | None = None
    notes: str = ""
    frozen: dict[str, str] = Field(default_factory=dict)
    rubric_hashes: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------- paths --

def _campaign_dir(slug: str) -> Path:
    return CAMPAIGNS / slug


def _campaign_json(slug: str) -> Path:
    return _campaign_dir(slug) / "campaign.json"


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------- lifecycle --

def create(slug: str, title: str, budgets: dict | None = None, *, allow_rejected: bool = False) -> Path:
    """Create ``campaigns/<slug>/`` with its subdirs and skeleton files.

    Refuses a title that fuzzily matches ``library/rejected.jsonl`` unless
    ``allow_rejected`` (rule: consult cross-run memory before proposing topics).
    """
    campaign_dir = _campaign_dir(slug)
    if campaign_dir.exists():
        raise CampaignError(f"campaign {slug!r} already exists at {campaign_dir}")
    if not allow_rejected:
        hit = _rejected_hit(title)
        if hit is not None:
            raise CampaignError(
                f"title matches a rejected topic in library/rejected.jsonl: {hit.get('topic')!r} "
                f"(reason: {hit.get('reason')!r}, campaign {hit.get('campaign')!r}); "
                "pass --allow-rejected if the reason no longer applies"
            )

    for sub in ("experiments", "proofs", "reviews", "paper", "cache"):
        (campaign_dir / sub).mkdir(parents=True, exist_ok=True)

    now = utc_now_iso()
    camp = Campaign(
        slug=slug,
        title=title,
        created=now,
        phase="bootstrap",
        phase_history=[{"phase": "bootstrap", "entered": now, "exited": None}],
        budgets=Budgets.model_validate(dict(budgets or {})),
    )
    save(camp)

    # Empty ledger, via LedgerStore (spec: "empty ledger.json (via LedgerStore)").
    LedgerStore(campaign_dir / "ledger.json", campaign=slug).save()

    with open(campaign_dir / "log.md", "w", encoding="utf-8") as fh:
        fh.write(f"# Campaign Log: {slug}\n\n{title}\n\nCreated: {now}\n\n## Log\n\n")

    with open(campaign_dir / "ideas.md", "w", encoding="utf-8") as fh:
        fh.write(
            f"# Ideas — {slug}\n\n"
            "Record attack routes here during the plan phase. Exiting plan requires "
            "at least 5 lines beginning with `## Route` (distinct mathematical lenses), "
            "plus at least one deliberately unconventional route (CLAUDE.md, rule R3; "
            "see skills/references/creative-moves.md).\n"
        )

    with open(campaign_dir / "questions.md", "w", encoding="utf-8") as fh:
        fh.write(
            f"# Questions — {slug}\n\n"
            "The curiosity ledger (CLAUDE.md rule R6; see skills/references/curiosity.md). Every agent starts by writing the\n"
            "questions it genuinely has (`## Q-nnn: ...` with Curiosity, Expectation, Cheapest test, Status) and logs\n"
            "`## Prediction`/`## Surprise` and `## Detour` entries (`harness questions surprise|detour`).\n"
            "Exiting plan requires at least 3 `## Q-` entries; exiting explore requires at least one recorded\n"
            "prediction/observation pair.\n\n"
        )

    from harness.questions import HUMAN_FILE, HUMAN_TEMPLATE

    with open(campaign_dir / HUMAN_FILE, "w", encoding="utf-8") as fh:
        fh.write(HUMAN_TEMPLATE)

    return campaign_dir


def _rejected_hit(topic: str) -> dict | None:
    try:
        from harness.library import memory

        return memory.is_rejected(topic)
    except Exception:  # noqa: BLE001 - the library must never block campaign creation by crashing
        return None


def load(slug: str) -> Campaign:
    path = _campaign_json(slug)
    if not path.exists():
        raise CampaignError(f"no such campaign: {slug!r} ({path} not found)")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return Campaign.model_validate(data)


def save(camp: Campaign) -> None:
    atomic_write_json(_campaign_json(camp.slug), camp.model_dump(mode="json"))


def set_phase(slug: str, phase: str) -> Campaign:
    if phase not in PHASES:
        raise CampaignError(f"unknown phase {phase!r}; must be one of {PHASES}")
    camp = load(slug)
    now = utc_now_iso()
    if camp.phase_history and camp.phase_history[-1].get("exited") is None:
        camp.phase_history[-1]["exited"] = now
    camp.phase_history.append({"phase": phase, "entered": now, "exited": None})
    camp.phase = phase
    save(camp)
    return camp


def lock_statement(slug: str) -> Campaign:
    """Freeze ``statement.md`` (the interpretation lock, CLAUDE.md) into ``statement_hash``
    and into the frozen-file table."""
    camp = load(slug)
    path = _campaign_dir(slug) / "statement.md"
    if not path.exists():
        raise CampaignError(f"statement.md not found for campaign {slug!r} at {path}")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    camp.statement_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    frozen = dict(camp.frozen)
    frozen["statement.md"] = _sha256(path)
    camp.frozen = frozen
    save(camp)
    return camp


def statement_intact(slug: str) -> bool:
    """Whether ``statement.md`` still matches the locked hash (False if never locked)."""
    camp = load(slug)
    if camp.statement_hash is None:
        return False
    path = _campaign_dir(slug) / "statement.md"
    if not path.exists():
        return False
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() == camp.statement_hash


# --------------------------------------------------------------- frozen files --

def _rel(campaign_dir: Path, p: str) -> str:
    """Campaign-relative, slash-separated form of a path given relative or absolute."""
    path = Path(p)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(campaign_dir.resolve())
        except ValueError as exc:
            raise CampaignError(f"{p} is not inside the campaign directory") from exc
    return path.as_posix()


def freeze(slug: str, paths: list[str]) -> Campaign:
    """Record sha256 of each path (campaign-relative) so edits are detected."""
    camp = load(slug)
    campaign_dir = _campaign_dir(slug)
    frozen = dict(camp.frozen)
    for p in paths:
        rel = _rel(campaign_dir, p)
        full = campaign_dir / rel
        if not full.is_file():
            raise CampaignError(f"cannot freeze {rel!r}: file not found under {campaign_dir}")
        frozen[rel] = _sha256(full)
    camp.frozen = frozen
    save(camp)
    return camp


def unfreeze(slug: str, paths: list[str]) -> Campaign:
    camp = load(slug)
    campaign_dir = _campaign_dir(slug)
    frozen = dict(camp.frozen)
    for p in paths:
        rel = _rel(campaign_dir, p)
        if rel in ALWAYS_FROZEN and camp.statement_hash is not None:
            raise CampaignError(f"{rel} cannot be unfrozen while the statement is locked")
        frozen.pop(rel, None)
    camp.frozen = frozen
    save(camp)
    return camp


def frozen_changed(slug: str) -> list[str]:
    """Frozen files whose content no longer matches the recorded hash (or vanished)."""
    camp = load(slug)
    campaign_dir = _campaign_dir(slug)
    changed: list[str] = []
    for rel, digest in camp.frozen.items():
        full = campaign_dir / rel
        if not full.is_file():
            changed.append(f"{rel} (missing)")
        elif _sha256(full) != digest:
            changed.append(rel)
    return changed


# ------------------------------------------------------------------- budgets --

def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def phase_hours(camp: Campaign, now: datetime | None = None) -> dict[str, float]:
    """Hours spent per phase, summed over ``phase_history`` (open phase counted up to ``now``)."""
    now = now or datetime.now(timezone.utc)
    hours: dict[str, float] = {}
    for entry in camp.phase_history:
        start = _parse_ts(entry.get("entered"))
        if start is None:
            continue
        end = _parse_ts(entry.get("exited")) or now
        delta = max(0.0, (end - start).total_seconds() / 3600.0)
        phase = str(entry.get("phase"))
        hours[phase] = hours.get(phase, 0.0) + delta
    return hours


def budget_report(camp: Campaign, now: datetime | None = None) -> dict:
    """``{"phases": {phase: {spent, budget, over}}, "total": {spent, budget, over}}``."""
    spent = phase_hours(camp, now)
    phases: dict[str, dict] = {}
    for phase in sorted(set(spent) | set(camp.budgets.hours_per_phase)):
        budget = camp.budgets.hours_per_phase.get(phase)
        s = round(spent.get(phase, 0.0), 3)
        phases[phase] = {"spent_hours": s, "budget_hours": budget, "over": budget is not None and s > budget}
    total_spent = round(sum(spent.values()), 3)
    total_budget = camp.budgets.hours_total
    return {
        "phases": phases,
        "total": {
            "spent_hours": total_spent,
            "budget_hours": total_budget,
            "over": total_budget is not None and total_spent > total_budget,
        },
    }


def _overrun_noted(campaign_dir: Path, phase: str) -> bool:
    log = _read_text(campaign_dir / "log.md") or ""
    return re.search(rf"^##\s*Budget overrun\b[^\n]*\b{re.escape(phase)}\b", log, re.MULTILINE | re.IGNORECASE) is not None


# ------------------------------------------------------------------- outcome --

def _novelty_class(campaign_dir: Path) -> str | None:
    from harness.review.verdict import novelty_class

    return novelty_class(campaign_dir)


def validate_outcome(slug: str, outcome: str | None) -> list[str]:
    """Problems with declaring ``outcome`` for this campaign (empty list = consistent).

    Rules (CLAUDE.md R4; erdosproblems wiki placement 1a–1d):

    * ``autonomous-new-result``: a non-stale referee-passed/formalized claim **and**
      a novelty memo classifying it ``1a`` or ``1b``.
    * ``rediscovery``: a proof-drafted-or-better claim and a memo with ``1b``/``1c``.
    * ``literature-find``: a memo with ``1c``/``1d`` or a ``known-in-literature`` claim.
    * ``partial``: some claim at ``numerically-supported`` or above (pipeline).
    * ``negative``: a refuted target, or nothing at ``proof-drafted`` or above.
    * A memo saying ``1c`` forbids ``autonomous-new-result``/``partial``; ``1d`` forbids
      ``autonomous-new-result``/``rediscovery``.
    """
    problems: list[str] = []
    if outcome is None:
        return ["outcome_class is not set"]
    if outcome not in OUTCOME_CLASSES:
        return [f"unknown outcome class {outcome!r}; expected one of {OUTCOME_CLASSES}"]
    campaign_dir = _campaign_dir(slug)
    store = LedgerStore(campaign_dir / "ledger.json", campaign=slug)
    claims = list(store.ledger.claims.values())
    cls = _novelty_class(campaign_dir)

    assertable = [c for c in claims if c.status in ("referee-passed", "formalized") and not c.stale]
    drafted_rank = pipeline_rank("proof-drafted")
    numeric_rank = pipeline_rank("numerically-supported")
    drafted = [c for c in claims if (pipeline_rank(c.status) or -1) >= drafted_rank]
    numeric = [c for c in claims if (pipeline_rank(c.status) or -1) >= numeric_rank]
    refuted = [c for c in claims if c.status == "refuted"]
    known = [c for c in claims if c.status == "known-in-literature"]

    if outcome == "autonomous-new-result":
        if not assertable:
            problems.append("autonomous-new-result requires a referee-passed (or formalized), non-stale claim")
        if cls is None:
            problems.append("autonomous-new-result requires a novelty memo (reviews/roundN/novelty.md) with class 1a or 1b")
        elif cls not in ("1a", "1b"):
            problems.append(f"novelty memo classifies the result as {cls}; autonomous-new-result needs 1a or 1b")
    elif outcome == "rediscovery":
        if not drafted:
            problems.append("rediscovery requires a claim at proof-drafted or above (we proved something)")
        if cls is None:
            problems.append("rediscovery requires a novelty memo with class 1b or 1c")
        elif cls not in ("1b", "1c"):
            problems.append(f"novelty memo class is {cls}; rediscovery needs 1b or 1c")
    elif outcome == "literature-find":
        if cls not in ("1c", "1d") and not known:
            problems.append("literature-find requires a novelty memo with class 1c/1d or a known-in-literature claim")
    elif outcome == "partial":
        if not numeric:
            problems.append("partial requires a claim at numerically-supported or above")
        if cls == "1c":
            problems.append("novelty memo class 1c (already known) is inconsistent with partial; use rediscovery/literature-find")
    elif outcome == "negative":
        if not refuted and drafted:
            problems.append("negative requires a refuted target or no claim at proof-drafted or above")
    if cls == "1d" and outcome in ("autonomous-new-result", "rediscovery"):
        problems.append("novelty memo class 1d (statement misread) forbids autonomous-new-result/rediscovery")
    return problems


def set_outcome(slug: str, outcome: str) -> Campaign:
    problems = validate_outcome(slug, outcome)
    if problems:
        raise CampaignError(f"cannot set outcome {outcome!r}: " + "; ".join(problems))
    camp = load(slug)
    camp.outcome_class = outcome  # type: ignore[assignment]
    save(camp)
    return camp


def finish(slug: str, outcome: str | None = None) -> dict:
    """Close the campaign: validate the outcome, record the result and the open questions in the
    library, set phase ``done`` and release the Stop-hook gate. Returns a summary dict."""
    from harness.library import memory
    from harness.questions import load_doc

    campaign_dir = _campaign_dir(slug)
    if outcome is not None:
        set_outcome(slug, outcome)
    camp = load(slug)
    problems = validate_outcome(slug, camp.outcome_class)
    if problems:
        raise CampaignError("cannot finish: " + "; ".join(problems))
    log_text = _read_text(campaign_dir / "log.md") or ""
    if "## Outcome" not in log_text:
        raise CampaignError("cannot finish: log.md has no '## Outcome' section (what was proven, what was not, dead routes, time spent)")
    store = LedgerStore(campaign_dir / "ledger.json", campaign=slug)
    claims = [{"id": c.id, "statement": c.statement, "status": c.status, "kind": c.kind} for c in store.assertable()]
    paper = campaign_dir / "paper" / "main.pdf"
    memory.add_result(slug, camp.title, camp.outcome_class or "negative", claims=claims,
                      paper_path=str(paper) if paper.exists() else None)
    open_q = [q.model_dump() for q in load_doc(campaign_dir).open()]
    added = memory.add_open_questions(slug, open_q)
    if camp.phase != "done":
        set_phase(slug, "done")
    for marker in (".gate", ".gate_attempts"):
        try:
            (campaign_dir / marker).unlink()
        except OSError:
            pass
    return {"slug": slug, "outcome_class": camp.outcome_class, "claims": len(claims), "open_questions_recorded": added}


# ------------------------------------------------------------- portfolio --

def selected_target_statement(campaign_dir: Path) -> str | None:
    """``- Statement (informal): …`` under ``## Selected target`` in portfolio.md."""
    text = _read_text(campaign_dir / "portfolio.md")
    if not text:
        return None
    m = re.search(r"^##\s*Selected target(.*?)(?=^##\s|\Z)", text, re.DOTALL | re.MULTILINE)
    section = m.group(1) if m else text
    s = re.search(r"^-\s*Statement(?:\s*\(informal\))?:\s*(.+)$", section, re.MULTILINE)
    return s.group(1).strip() if s else None


def suggest_stakes(slug: str) -> dict:
    """Suggest a stakes tier (0/1/2) for the selected target from ``portfolio.md`` (Round-2 X4).

    Heuristics, all visible in the returned ``reasons``: tier 2 when the selected target block mentions
    a prize, a listed open problem (erdosproblems / formal-conjectures / Open Problem Garden ids) or a
    tracked best-known value, or when the rubric's N (novelty/impact) score is 3; tier 0 when the
    target is a lemma-sized routine statement (N ≤ 1); otherwise tier 1. Never writes anything.
    """
    campaign_dir = _campaign_dir(slug)
    text = _read_text(campaign_dir / "portfolio.md") or ""
    m = re.search(r"^##\s*Selected target(.*?)(?=^##\s|\Z)", text, re.DOTALL | re.MULTILINE)
    block = m.group(1) if m else text
    reasons: list[str] = []
    score = 1
    low = block.lower()
    if re.search(r"\bprize\b|\$\s?\d+", low):
        reasons.append("prize mentioned")
        score = 2
    if re.search(r"erd[oő]s\s*#?\d+|erdosproblems|formal-conjectures|open problem garden|\bopg\b", low):
        reasons.append("listed open problem")
        score = 2
    if re.search(r"known best result[^\n]*:\s*\S", block, re.IGNORECASE) and re.search(r"\d", re.search(r"known best result[^\n]*", block, re.IGNORECASE).group(0)):
        reasons.append("tracked best-known value")
        score = 2
    n_score = None
    tbl = re.search(r"^##\s*Rubric scores(.*?)(?=^##\s|\Z)", text, re.DOTALL | re.MULTILINE)
    if tbl:
        for row in tbl.group(1).splitlines():
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) >= 8 and cells[0] and cells[0].lower() not in ("candidate", "---") and not set(cells[0]) <= {"-"}:
                try:
                    n_score = int(cells[3])
                except ValueError:
                    continue
                break
    if n_score is not None:
        reasons.append(f"rubric N score {n_score}")
        if n_score >= 3:
            score = 2
        elif n_score <= 1 and score < 2:
            score = 0
    if not reasons:
        reasons.append("no signal in portfolio.md; default tier 1")
    return {"suggested_stakes": score, "reasons": reasons, "apply_with": f"harness ledger update <ID> --stakes {score} --campaign {slug}"}


# --------------------------------------------------------------- phase exit --

def _statement_tests_passed(campaign_dir: Path) -> tuple[bool, str]:
    results = _read_text(campaign_dir / "experiments" / "results.json")
    if results is None:
        return False, "experiments/results.json does not exist"
    try:
        data = json.loads(results)
    except json.JSONDecodeError as exc:
        return False, f"experiments/results.json is not valid JSON: {exc}"
    entry = data.get("statement_tests") if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        return False, "experiments/results.json has no 'statement_tests' entry"
    if entry.get("passed") is not True:
        return False, "experiments/results.json['statement_tests'].passed is not true"
    return True, ""


def check_phase_exit(slug: str) -> list[str]:
    """Return the list of UNMET criteria for leaving the campaign's *current* phase.

    Empty list = the phase's exit criteria are satisfied.
    """
    camp = load(slug)
    campaign_dir = _campaign_dir(slug)
    phase = camp.phase
    unmet: list[str] = []

    def _ledger() -> LedgerStore:
        return LedgerStore(campaign_dir / "ledger.json", campaign=slug)

    # -- every phase: budget accounting and frozen files
    report = budget_report(camp)
    info = report["phases"].get(phase)
    if info and info["over"] and not _overrun_noted(campaign_dir, phase):
        unmet.append(
            f"phase '{phase}' spent {info['spent_hours']} h of its {info['budget_hours']} h budget; add a "
            f"'## Budget overrun ({phase})' note to log.md explaining why before exiting"
        )
    if report["total"]["over"] and not _overrun_noted(campaign_dir, "total"):
        unmet.append(
            f"campaign spent {report['total']['spent_hours']} h of hours_total={report['total']['budget_hours']}; "
            "add a '## Budget overrun (total)' note to log.md"
        )
    changed = frozen_changed(slug)
    if changed:
        unmet.append(f"frozen files changed since they were frozen: {changed} (re-open the phase or unfreeze deliberately)")

    if phase == "bootstrap":
        pass  # no exit criteria specified for bootstrap

    elif phase == "scout":
        text = _read_text(campaign_dir / "portfolio.md")
        if text is None:
            unmet.append("portfolio.md does not exist")
        elif len(text) <= 800:
            unmet.append(f"portfolio.md is only {len(text)} chars (need > 800)")
        else:
            stmt = selected_target_statement(campaign_dir)
            if stmt and "Rejected-override:" not in text:
                hit = _rejected_hit(stmt)
                if hit is not None:
                    unmet.append(
                        f"selected target matches a rejected topic in library/rejected.jsonl ({hit.get('topic')!r}, "
                        f"reason {hit.get('reason')!r}); add a 'Rejected-override: <why the reason no longer applies>' line"
                    )

    elif phase == "survey":
        text = _read_text(campaign_dir / "survey.md")
        if text is None:
            unmet.append("survey.md does not exist")
        elif len(text) <= 2000:
            unmet.append(f"survey.md is only {len(text)} chars (need > 2000)")

        bib = _read_text(campaign_dir / "refs.bib")
        if bib is None:
            unmet.append("refs.bib does not exist")
        else:
            n_entries = len(re.findall(r"@\w+\s*\{", bib))
            if n_entries < 3:
                unmet.append(f"refs.bib has only {n_entries} '@...{{' entries (need >= 3)")

        store = _ledger()
        n_known = sum(1 for c in store.ledger.claims.values() if c.status == "known-in-literature")
        if n_known < 3:
            unmet.append(f"ledger has only {n_known} known-in-literature claims (need >= 3)")

    elif phase == "plan":
        if not (campaign_dir / "statement.md").exists():
            unmet.append("statement.md does not exist")
        if camp.statement_hash is None:
            unmet.append("statement_hash is not set (run lock-statement)")
        elif not statement_intact(slug):
            unmet.append("statement.md has changed since it was locked")

        text = _read_text(campaign_dir / "plan.md")
        if text is None:
            unmet.append("plan.md does not exist")
        elif len(text) <= 1500:
            unmet.append(f"plan.md is only {len(text)} chars (need > 1500)")

        ideas = _read_text(campaign_dir / "ideas.md") or ""
        n_routes = sum(1 for line in ideas.splitlines() if line.startswith("## Route"))
        if n_routes < 5:
            unmet.append(f"ideas.md has only {n_routes} '## Route' lines (need >= 5)")

        questions = _read_text(campaign_dir / "questions.md") or ""
        n_questions = sum(1 for line in questions.splitlines() if line.startswith("## Q-"))
        if n_questions < 3:
            unmet.append(f"questions.md has only {n_questions} '## Q-' entries (need >= 3; rule R6 curiosity ledger)")

        store = _ledger()
        conjectured_rank = pipeline_rank("conjectured")
        has_target = any(
            c.kind in ("target", "conjecture")
            and pipeline_rank(c.status) is not None
            and pipeline_rank(c.status) >= conjectured_rank
            for c in store.ledger.claims.values()
        )
        if not has_target:
            unmet.append("ledger has no target/conjecture claim with status >= conjectured")

        if camp.budgets.hours_total is None:
            unmet.append("budgets.hours_total is not set (the strategist must set budgets)")

        if not (campaign_dir / "experiments" / "statement_tests.py").exists():
            unmet.append("experiments/statement_tests.py does not exist (definition unit tests of the interpretation lock)")
        ok, why = _statement_tests_passed(campaign_dir)
        if not ok:
            unmet.append(f"statement tests not recorded as passed: {why}")

    elif phase == "explore":
        store = _ledger()
        untested = [
            c.id
            for c in store.ledger.claims.values()
            if c.kind in ("conjecture", "target", "bound", "construction")
            and c.status == "conjectured"
            and not any(ev.type in ("computation", "falsification") for ev in c.evidence)
        ]
        if untested:
            unmet.append(f"untested conjectured claims (need computation/falsification evidence): {untested}")
        if not (campaign_dir / "experiments" / "results.json").exists():
            unmet.append("experiments/results.json does not exist")
        from harness.questions import load_doc, recorded_predictions

        if not recorded_predictions(load_doc(campaign_dir)):
            unmet.append(
                "questions.md has no recorded prediction/observation pair (rule R6: write the prediction before each "
                "experiment and compare after; `harness questions surprise --prediction … --observation … --score n`)"
            )

    elif phase == "prove":
        store = _ledger()
        proof_rank = pipeline_rank("proof-drafted")
        ok = False
        for c in store.ledger.claims.values():
            rank = pipeline_rank(c.status)
            if rank is None or rank < proof_rank:
                continue
            if any(ev.type == "proof" and ev.path and (campaign_dir / ev.path).exists() for ev in c.evidence):
                ok = True
                break
        if not ok:
            unmet.append("no claim with status >= proof-drafted has a proof evidence file that still exists")
        from harness.proof.lint import lint_claim_proofs

        for c in store.ledger.claims.values():
            rank = pipeline_rank(c.status)
            if rank is None or rank < proof_rank:
                continue
            for report in lint_claim_proofs(store, campaign_dir, c.id):
                if not report.ok:
                    codes = sorted({e.code for e in report.errors})
                    unmet.append(f"proof artifact {report.path} fails `harness proof check`: {', '.join(codes)}")
        from harness.questions import load_doc, unanswered_by

        open_prover = [q.id for q in unanswered_by(load_doc(campaign_dir), "prover")]
        if open_prover:
            unmet.append(
                f"open questions raised by the prover must be answered or parked before leaving prove: {open_prover} "
                "(`harness questions answer|park <id> --ref …`)"
            )

    elif phase == "review":
        store = _ledger()
        rounds = {
            ev.round
            for c in store.ledger.claims.values()
            for ev in c.evidence
            if ev.type == "referee" and ev.round is not None
        }
        if not rounds:
            unmet.append("no referee evidence recorded (no review round found)")
        else:
            n = max(rounds)
            if n > camp.budgets.max_review_rounds:
                unmet.append(f"round {n} exceeds budgets.max_review_rounds={camp.budgets.max_review_rounds}")
            round_dir = campaign_dir / "reviews" / f"round{n}"
            for fname in ("skeptic", "falsifier", "novelty", "judge"):
                if not list(round_dir.glob(f"{fname}*.md")):
                    unmet.append(f"reviews/round{n}/{fname}.md does not exist")
            has_pass = any(c.status == "referee-passed" for c in store.ledger.claims.values())
            judge_text = _read_text(round_dir / "judge.md") or ""
            pivot = "VERDICT: PIVOT" in judge_text
            if not (has_pass or pivot):
                unmet.append(
                    f"round {n}: no claim is referee-passed, and reviews/round{n}/judge.md "
                    "does not contain the line 'VERDICT: PIVOT'"
                )
            if n == camp.budgets.max_review_rounds and not has_pass and not pivot:
                unmet.append(f"round {n} is the last budgeted round: the judge must PIVOT or downgrade")
            try:
                from harness.review.barrier import check_round  # Round-1 Step 4
            except ImportError:
                check_round = None  # type: ignore[assignment]
            if check_round is not None:
                unmet.extend(check_round(campaign_dir, n, store))

    elif phase == "write":
        if not (campaign_dir / "paper" / "main.tex").exists():
            unmet.append("paper/main.tex does not exist")
        if not (campaign_dir / "paper" / "main.pdf").exists():
            unmet.append("paper/main.pdf does not exist")
        check_json_path = campaign_dir / "paper" / "check.json"
        text = _read_text(check_json_path)
        if text is None:
            unmet.append("paper/check.json does not exist")
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                unmet.append(f"paper/check.json is not valid JSON: {exc}")
            else:
                if data.get("ok") is not True:
                    unmet.append("paper/check.json does not report \"ok\": true")
        store = _ledger()
        if store.assertable() and _novelty_class(campaign_dir) is None:
            unmet.append("assertable claims exist but no novelty memo (reviews/roundN/novelty.md) classifies them")

    elif phase == "done":
        if camp.outcome_class is None:
            unmet.append("outcome_class is not set")
        else:
            unmet.extend(validate_outcome(slug, camp.outcome_class))
        log_text = _read_text(campaign_dir / "log.md") or ""
        if "## Outcome" not in log_text:
            unmet.append("log.md does not contain a '## Outcome' section")

    else:  # pragma: no cover - PHASES/set_phase already guard this
        unmet.append(f"unknown phase: {phase!r}")

    return unmet


# ------------------------------------------------------------------- reports --

def status_report(slug: str) -> str:
    camp = load(slug)
    unmet = check_phase_exit(slug)
    store = LedgerStore(_campaign_dir(slug) / "ledger.json", campaign=slug)

    lock_state = "not set"
    if camp.statement_hash is not None:
        lock_state = "intact" if statement_intact(slug) else "MODIFIED since lock"

    lines = [
        f"# Campaign status: {camp.slug}",
        "",
        f"- Title: {camp.title}",
        f"- Phase: {camp.phase}",
        f"- Statement lock: {lock_state}",
        f"- Active targets: {', '.join(camp.active_targets) if camp.active_targets else '(none)'}",
        f"- Outcome class: {camp.outcome_class or '(not set)'}",
        "",
        "## Phase exit criteria",
        "",
    ]
    if unmet:
        lines.append(f"{len(unmet)} unmet criterion/criteria to leave phase '{camp.phase}':")
        lines.extend(f"- [ ] {m}" for m in unmet)
    else:
        lines.append(f"All exit criteria for phase '{camp.phase}' are met.")

    report = budget_report(camp)
    lines += ["", "## Budgets", ""]
    tot = report["total"]
    lines.append(
        f"- total: {tot['spent_hours']} h spent / {tot['budget_hours'] if tot['budget_hours'] is not None else 'unset'} h"
        + (" **OVER**" if tot["over"] else "")
    )
    for phase, info in report["phases"].items():
        b = info["budget_hours"]
        lines.append(f"- {phase}: {info['spent_hours']} h / {b if b is not None else 'unset'} h" + (" **OVER**" if info["over"] else ""))
    lines.append(f"- max_review_rounds: {camp.budgets.max_review_rounds}; curiosity_fraction: {camp.budgets.curiosity_fraction}")

    changed = set(frozen_changed(slug))
    if camp.frozen:
        lines += ["", "## Frozen files", ""]
        for rel in sorted(camp.frozen):
            flag = "MODIFIED" if rel in changed or f"{rel} (missing)" in changed else "ok"
            lines.append(f"- {rel}: {flag}")

    from harness.questions import advisories, budget_status, human_summary, load_doc, rank_open

    cdir = _campaign_dir(slug)
    doc = load_doc(cdir)
    by_status: dict[str, int] = {}
    for q in doc.questions:
        by_status[q.status] = by_status.get(q.status, 0) + 1
    qb = budget_status(cdir)
    lines += ["", "## Questions (rule R6)", ""]
    lines.append(f"- questions: {', '.join(f'{k} {v}' for k, v in sorted(by_status.items())) or 'none'}; "
                 f"observations: {len(doc.observations)}; detours: {len(doc.detours)}")
    if qb["detour_budget_minutes"] is not None:
        lines.append(f"- detour budget ({qb['phase']}): {qb['detour_minutes_used']:.0f}/{qb['detour_budget_minutes']:.0f} min"
                     + (" **OVER**" if qb["over"] else ""))
    for gain, q in rank_open(doc)[:3]:
        lines.append(f"- next: {q.id} {q.title} (gain {gain:.3f}; test: {q.cheapest_test or '?'})")
    for a in advisories(cdir):
        lines.append(f"- advisory: {a}")
    hs = human_summary(cdir, camp.budgets.model_dump())
    lines += ["", "## Human", "",
              f"- escalations: {hs['used']}/{hs['limit']} used; open: {', '.join(hs['open']) or 'none'}; "
              f"HUMAN.md updated: {hs['human_md_updated'] or 'never'}"]

    lines += [
        "",
        "## Ledger summary",
        "",
        "```json",
        json.dumps(store.summary(), sort_keys=True, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------------ CLI --

def _active_path() -> Path:
    return CAMPAIGNS / "ACTIVE"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="harness campaign")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("slug")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--hours-total", type=float, default=None)
    p_create.add_argument("--allow-rejected", action="store_true", help="create even if the title matches a rejected topic")

    p_phase = sub.add_parser("phase")
    p_phase.add_argument("slug")
    p_phase.add_argument("phase", nargs="?", default=None)

    p_check = sub.add_parser("check")
    p_check.add_argument("slug")

    p_lock = sub.add_parser("lock-statement")
    p_lock.add_argument("slug")

    p_status = sub.add_parser("status")
    p_status.add_argument("slug")

    p_budget = sub.add_parser("budget", help="print the budget report (hours per phase vs budgets)")
    p_budget.add_argument("slug")
    p_budget.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                          help="set a budget field, e.g. --set hours_total=40 --set hours_per_phase.explore=8")

    p_outcome = sub.add_parser("outcome", help="set the outcome class (validated against the ledger and novelty memo)")
    p_outcome.add_argument("slug")
    p_outcome.add_argument("outcome", choices=list(OUTCOME_CLASSES))

    p_finish = sub.add_parser("finish", help="validate the outcome, record result + open questions in the library, set phase done")
    p_finish.add_argument("slug")
    p_finish.add_argument("--outcome", choices=list(OUTCOME_CLASSES), default=None)

    p_attest = sub.add_parser("attest", help="record a HUMAN sign-off on a claim (agents are denied by hook)")
    p_attest.add_argument("slug")
    p_attest.add_argument("--claim", required=True)
    p_attest.add_argument("--human", required=True)
    p_attest.add_argument("--note", default="")

    p_stakes = sub.add_parser("suggest-stakes", help="suggest a stakes tier for the selected target from portfolio.md (never writes)")
    p_stakes.add_argument("slug")

    p_freeze = sub.add_parser("freeze", help="record hashes of files that must not change during explore/prove/review")
    p_freeze.add_argument("slug")
    p_freeze.add_argument("paths", nargs="+")

    p_unfreeze = sub.add_parser("unfreeze")
    p_unfreeze.add_argument("slug")
    p_unfreeze.add_argument("paths", nargs="+")

    sub.add_parser("list")
    sub.add_parser("active")

    p_activate = sub.add_parser("activate")
    p_activate.add_argument("slug")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "create":
            budgets = {"hours_total": args.hours_total} if args.hours_total is not None else None
            path = create(args.slug, args.title, budgets, allow_rejected=args.allow_rejected)
            print(f"created campaign at {path}")
            return 0

        if args.cmd == "phase":
            if args.phase is None:
                print(load(args.slug).phase)
            else:
                camp = set_phase(args.slug, args.phase)
                print(f"{args.slug}: phase -> {camp.phase}")
            return 0

        if args.cmd == "check":
            unmet = check_phase_exit(args.slug)
            from harness.ideas import advisories as route_advisories
            from harness.questions import advisories

            for a in advisories(_campaign_dir(args.slug)) + route_advisories(_campaign_dir(args.slug)):
                print(f"advisory: {a}", file=sys.stderr)
            if unmet:
                for m in unmet:
                    print(f"- {m}")
                return 1
            print("ok: phase exit criteria met")
            return 0

        if args.cmd == "finish":
            summary = finish(args.slug, args.outcome)
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0

        if args.cmd == "lock-statement":
            camp = lock_statement(args.slug)
            print(f"locked statement.md ({camp.statement_hash})")
            return 0

        if args.cmd == "status":
            print(status_report(args.slug))
            return 0

        if args.cmd == "budget":
            camp = load(args.slug)
            if args.set:
                data = camp.budgets.model_dump()
                for item in args.set:
                    if "=" not in item:
                        raise CampaignError(f"--set expects KEY=VALUE, got {item!r}")
                    key, raw = item.split("=", 1)
                    try:
                        value = json.loads(raw)
                    except json.JSONDecodeError:
                        value = raw
                    if key.startswith("hours_per_phase."):
                        data.setdefault("hours_per_phase", {})[key.split(".", 1)[1]] = float(value)
                    else:
                        data[key] = value
                camp.budgets = Budgets.model_validate(data)
                save(camp)
            print(json.dumps({"budgets": camp.budgets.model_dump(), **budget_report(camp)}, indent=2, sort_keys=True))
            return 0

        if args.cmd == "outcome":
            camp = set_outcome(args.slug, args.outcome)
            print(f"{args.slug}: outcome_class -> {camp.outcome_class}")
            return 0

        if args.cmd == "attest":
            store = LedgerStore(_campaign_dir(args.slug) / "ledger.json", campaign=args.slug)
            claim = store.attest(args.claim, args.human, args.note)
            print(json.dumps({"claim": claim.id, "attestation": claim.attestation}, indent=2, sort_keys=True))
            return 0

        if args.cmd == "suggest-stakes":
            print(json.dumps(suggest_stakes(args.slug), indent=2, sort_keys=True, ensure_ascii=False))
            return 0

        if args.cmd == "freeze":
            camp = freeze(args.slug, args.paths)
            print(json.dumps(camp.frozen, indent=2, sort_keys=True))
            return 0

        if args.cmd == "unfreeze":
            camp = unfreeze(args.slug, args.paths)
            print(json.dumps(camp.frozen, indent=2, sort_keys=True))
            return 0

        if args.cmd == "list":
            if CAMPAIGNS.exists():
                for p in sorted(CAMPAIGNS.iterdir()):
                    if (p / "campaign.json").exists():
                        print(p.name)
            return 0

        if args.cmd == "active":
            active_path = _active_path()
            if not active_path.exists():
                print("(no active campaign)", file=sys.stderr)
                return 1
            with open(active_path, "r", encoding="utf-8") as fh:
                print(fh.read().strip())
            return 0

        if args.cmd == "activate":
            CAMPAIGNS.mkdir(parents=True, exist_ok=True)
            with open(_active_path(), "w", encoding="utf-8") as fh:
                fh.write(args.slug)
            print(f"active campaign -> {args.slug}")
            return 0

        return 2
    except (CampaignError, LedgerError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
