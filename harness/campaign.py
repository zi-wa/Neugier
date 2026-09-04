"""Campaign lifecycle: create/load/save, phase transitions, and phase-exit gates.

A "campaign" (``campaigns/<slug>/``) is a portfolio of targets pursued under a
budget through the phase protocol described in CLAUDE.md:
bootstrap -> scout -> survey -> plan -> explore -> prove -> review -> write -> done.
The Stop hook is meant to call :func:`check_phase_exit` and refuse to end a
phase whose criteria are unmet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

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

OutcomeClass = Literal["autonomous-new-result", "partial", "rediscovery", "literature-find", "negative"]


class CampaignError(Exception):
    """Raised for any invalid campaign operation (unknown slug, unknown phase, missing file, ...)."""


class Campaign(BaseModel):
    """Top-level campaign record, persisted at ``campaigns/<slug>/campaign.json``."""

    slug: str
    title: str
    created: str = Field(default_factory=utc_now_iso)
    phase: str = "bootstrap"
    phase_history: list[dict] = Field(default_factory=list)
    budgets: dict = Field(default_factory=dict)
    active_targets: list[str] = Field(default_factory=list)
    outcome_class: OutcomeClass | None = None
    statement_hash: str | None = None
    notes: str = ""


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


# ------------------------------------------------------------------- lifecycle --

def create(slug: str, title: str, budgets: dict | None = None) -> Path:
    """Create ``campaigns/<slug>/`` with its subdirs and skeleton files."""
    campaign_dir = _campaign_dir(slug)
    if campaign_dir.exists():
        raise CampaignError(f"campaign {slug!r} already exists at {campaign_dir}")

    for sub in ("experiments", "proofs", "reviews", "paper", "cache"):
        (campaign_dir / sub).mkdir(parents=True, exist_ok=True)

    now = utc_now_iso()
    camp = Campaign(
        slug=slug,
        title=title,
        created=now,
        phase="bootstrap",
        phase_history=[{"phase": "bootstrap", "entered": now, "exited": None}],
        budgets=dict(budgets or {}),
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
            "`## Surprise` and `## Detour` entries. Exiting plan requires at least 3 `## Q-` entries.\n\n"
        )

    return campaign_dir


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
    """Freeze ``statement.md`` (the interpretation lock, CLAUDE.md) into ``statement_hash``."""
    camp = load(slug)
    path = _campaign_dir(slug) / "statement.md"
    if not path.exists():
        raise CampaignError(f"statement.md not found for campaign {slug!r} at {path}")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    camp.statement_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
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


# --------------------------------------------------------------- phase exit --

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

    if phase == "bootstrap":
        pass  # no exit criteria specified for bootstrap

    elif phase == "scout":
        text = _read_text(campaign_dir / "portfolio.md")
        if text is None:
            unmet.append("portfolio.md does not exist")
        elif len(text) <= 800:
            unmet.append(f"portfolio.md is only {len(text)} chars (need > 800)")

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

        if not camp.budgets:
            unmet.append("budgets is empty")

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
            round_dir = campaign_dir / "reviews" / f"round{n}"
            for fname in ("skeptic.md", "falsifier.md", "novelty.md", "judge.md"):
                if not (round_dir / fname).exists():
                    unmet.append(f"reviews/round{n}/{fname} does not exist")
            has_pass = any(c.status == "referee-passed" for c in store.ledger.claims.values())
            judge_text = _read_text(round_dir / "judge.md") or ""
            pivot = "VERDICT: PIVOT" in judge_text
            if not (has_pass or pivot):
                unmet.append(
                    f"round {n}: no claim is referee-passed, and reviews/round{n}/judge.md "
                    "does not contain the line 'VERDICT: PIVOT'"
                )

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

    elif phase == "done":
        if camp.outcome_class is None:
            unmet.append("outcome_class is not set")
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

    p_phase = sub.add_parser("phase")
    p_phase.add_argument("slug")
    p_phase.add_argument("phase", nargs="?", default=None)

    p_check = sub.add_parser("check")
    p_check.add_argument("slug")

    p_lock = sub.add_parser("lock-statement")
    p_lock.add_argument("slug")

    p_status = sub.add_parser("status")
    p_status.add_argument("slug")

    sub.add_parser("list")
    sub.add_parser("active")

    p_activate = sub.add_parser("activate")
    p_activate.add_argument("slug")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "create":
            path = create(args.slug, args.title)
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
            if unmet:
                for m in unmet:
                    print(f"- {m}")
                return 1
            print("ok: phase exit criteria met")
            return 0

        if args.cmd == "lock-statement":
            camp = lock_statement(args.slug)
            print(f"locked statement.md ({camp.statement_hash})")
            return 0

        if args.cmd == "status":
            print(status_report(args.slug))
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
