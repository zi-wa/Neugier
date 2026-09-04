"""Review-round manifests: the information barrier as data (Round-1 Step 4, Round-2 X1/X4).

``reviews/roundN/barrier.json`` says, per referee role, which campaign files the
role may touch; ``hooks/barrier.py`` enforces it on every tool call and writes
``reviews/roundN/access.log`` (JSONL). :func:`check_round` turns that log — plus
the blind commit of the replicator, the judge's verdict line and the novelty
memo — into phase-exit criteria, so a review round whose barrier was breached
or never exercised cannot count.

Manifest shape::

    {
      "version": 1, "campaign": "<slug>", "round": 2, "claim": "T-001",
      "status": "open" | "closed", "opened": "<iso>", "closed": null,
      "artifacts": ["proofs/T-001.md"],
      "deny_always": ["plan.md", "ideas.md", ...],
      "roles": {
        "skeptic:SK-3f9a1c": {"barrier": true, "allow": [...], "deliverable": "reviews/round2/skeptic.SK-3f9a1c.md",
                              "agent_id": "SK-3f9a1c"},
        "falsifier": {"barrier": true, "allow": [...], "deliverable": "reviews/round2/falsifier.md"},
        "novelty":   {"barrier": true, ...},
        "replicator": {"barrier": true, "stage": "A", "allow": [...], "stage_b_allow": [...],
                       "blind_sha256": null, "blind_committed": null, "deliverable": "reviews/round2/replicator.md"},
        "judge": {"barrier": false, "deliverable": "reviews/round2/judge.md"}
      },
      "waivers": [{"role": "...", "target": "...", "reason": "...", "ts": "..."}],
      "lineup": null,            # filled by harness.review.lineup (Round-2 X1)
      "regime": {...}            # harness.review.regime.Regime
    }

Patterns are campaign-relative POSIX paths; ``**`` matches any number of
segments (including none), ``*`` matches within a segment. An explicit role
``allow`` overrides ``deny_always``. ``access.log`` rows are
``{"ts","role","agent_id","session_id","tool","decision","target","reason"}``.
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

from harness.ledger.ledger import atomic_write_json, load_budgets
from harness.ledger.schema import utc_now_iso
from harness.review.regime import Regime, regime_for
from harness.review.verdict import (
    JUDGE_DECISIONS,
    blocks_for_role,
    judge_verdict,
    novelty_class,
    parse_verdict_blocks,
    role_reports,
    round_dirs,
)
from harness.verify.exact import sha256_file

MANIFEST = "barrier.json"
ACCESS_LOG = "access.log"
HOOK_ERRORS = "hook_errors.log"
ROUND_INFO = "round.json"

BARRIER_ROLES = ("skeptic", "falsifier", "novelty", "replicator")
ALL_ROLES = BARRIER_ROLES + ("judge",)

DENY_ALWAYS = [
    "plan.md", "ideas.md", "log.md", "questions.md", "survey.md", "portfolio.md", "blocked.md",
    "HUMAN.md", "ASK-HUMAN.md", "escalations.json", "campaign.json", ".gate", ".gate_attempts",
    "paper/**", "proofs/**", "reviews/**", "experiments/repair/**",
    "reviews/round*/lineup.sealed.json", "reviews/round*/lineup_score*.json",
]


class ReviewError(Exception):
    """Raised for invalid round operations (second open round, bad round number, ...)."""


# --------------------------------------------------------------- matching --

def _pattern_regex(pattern: str) -> re.Pattern[str]:
    pat = pattern.strip().replace("\\", "/").lstrip("./")
    out = []
    i = 0
    while i < len(pat):
        ch = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pat.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(rel: str, pattern: str) -> bool:
    """``rel`` (campaign-relative, POSIX) matches ``pattern`` (``**``/``*`` semantics)."""
    rel = rel.replace("\\", "/").lstrip("./")
    return _pattern_regex(pattern).match(rel) is not None


def role_allowed(manifest: dict, role_key: str, rel: str) -> tuple[bool, str]:
    """``(allowed, reason)`` for a campaign-relative path under the manifest.

    ``reason`` is ``allow:<pattern>``, ``deny:<pattern>``, ``deny:not-in-allowlist``
    or ``no-barrier`` / ``unknown-role``.
    """
    role = manifest.get("roles", {}).get(role_key)
    if role is None:
        return True, "unknown-role"
    if not role.get("barrier", True):
        return True, "no-barrier"
    allow = list(role.get("allow", []))
    if role.get("stage") == "B":
        allow += list(role.get("stage_b_allow", []))
    for pat in allow:
        if glob_match(rel, pat):
            return True, f"allow:{pat}"
    for pat in manifest.get("deny_always", []):
        if glob_match(rel, pat):
            return False, f"deny:{pat}"
    return False, "deny:not-in-allowlist"


# --------------------------------------------------------------- defaults --

def _role_defaults(round_n: int, claim: str, artifacts: list[str]) -> dict[str, dict]:
    rd = f"reviews/round{round_n}"
    common = ["statement.md", "refs.bib", "cache/**", "ledger.json", "ledger.audit.jsonl", "experiments/results.json",
              f"{rd}/{MANIFEST}", f"{rd}/{ACCESS_LOG}"]
    rubric = f"proofs/{claim}.rubric.md"
    return {
        "skeptic": {
            "barrier": True,
            "allow": common + artifacts + [rubric, f"{rd}/skeptic*.md", f"{rd}/skeptic_scratch/**", f"{rd}/lineup/**"],
            "deliverable": f"{rd}/skeptic.md",
        },
        "falsifier": {
            "barrier": True,
            "allow": common + artifacts + ["experiments/falsify/**", "experiments/evolve/**", "experiments/*.py",
                                           f"{rd}/falsifier.md", f"{rd}/falsify/**"],
            "deliverable": f"{rd}/falsifier.md",
        },
        "novelty": {
            "barrier": True,
            "allow": ["statement.md", "refs.bib", "cache/**", "ledger.json", f"{rd}/novelty.md", f"{rd}/novelty_scratch/**"]
                     + artifacts + [f"{rd}/{MANIFEST}", f"{rd}/{ACCESS_LOG}"],
            "deliverable": f"{rd}/novelty.md",
        },
        "replicator": {
            "barrier": True,
            "stage": "A",
            "allow": ["statement.md", "refs.bib", "cache/**", "ledger.json", "ledger.audit.jsonl",
                      f"{rd}/replicate/**", f"{rd}/replicator.md", f"{rd}/{MANIFEST}", f"{rd}/{ACCESS_LOG}"],
            "stage_b_allow": artifacts + ["experiments/results.json"],
            "blind_sha256": None,
            "blind_committed": None,
            "deliverable": f"{rd}/replicator.md",
        },
        "judge": {"barrier": False, "allow": [], "deliverable": f"{rd}/judge.md"},
    }


def mint_agent_id(prefix: str = "SK") -> str:
    return f"{prefix}-{secrets.token_hex(3)}"


# ------------------------------------------------------------------ files --

def round_dir(campaign_dir: Path | str, round_n: int) -> Path:
    return Path(campaign_dir) / "reviews" / f"round{round_n}"


def manifest_path(campaign_dir: Path | str, round_n: int) -> Path:
    return round_dir(campaign_dir, round_n) / MANIFEST


def load_manifest(campaign_dir: Path | str, round_n: int) -> dict:
    path = manifest_path(campaign_dir, round_n)
    if not path.exists():
        raise ReviewError(f"no barrier manifest for round {round_n} ({path})")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(campaign_dir: Path | str, round_n: int, manifest: dict) -> None:
    atomic_write_json(manifest_path(campaign_dir, round_n), manifest)


def open_barriers(campaign_dir: Path | str) -> list[tuple[int, dict]]:
    out: list[tuple[int, dict]] = []
    for n, p in round_dirs(campaign_dir):
        mp = p / MANIFEST
        if mp.exists():
            try:
                with open(mp, "r", encoding="utf-8") as fh:
                    m = json.load(fh)
            except (OSError, ValueError):
                continue
            if m.get("status") == "open":
                out.append((n, m))
    return out


def open_barrier(campaign_dir: Path | str) -> tuple[int, dict] | None:
    found = open_barriers(campaign_dir)
    return found[0] if len(found) == 1 else None


def read_access_log(rdir: Path | str) -> list[dict]:
    path = Path(rdir) / ACCESS_LOG
    rows: list[dict] = []
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append({"raw": line, "decision": "unparsable"})
    return rows


# ------------------------------------------------------------- lifecycle --

def open_round(
    campaign_dir: Path | str,
    round_n: int,
    claim: str,
    artifacts: list[str],
    *,
    skeptics: int | None = None,
    stakes: int | None = None,
    campaign: str | None = None,
    roles: dict | None = None,
) -> dict:
    """Create ``reviews/roundN/barrier.json`` (and ``round.json``); refuses a second open
    round, a round beyond ``budgets.max_review_rounds`` or a non-consecutive round number."""
    campaign_dir = Path(campaign_dir)
    if round_n < 1:
        raise ReviewError("round numbers start at 1")
    others = [n for n, _ in open_barriers(campaign_dir) if n != round_n]
    if others:
        raise ReviewError(f"round {others[0]} is still open; close it before opening round {round_n}")
    if manifest_path(campaign_dir, round_n).exists():
        raise ReviewError(f"round {round_n} already has a manifest; use a new round number")
    budgets = load_budgets(campaign_dir)
    cap = budgets.get("max_review_rounds")
    if isinstance(cap, int) and round_n > cap:
        raise ReviewError(f"round {round_n} exceeds budgets.max_review_rounds={cap}; the judge must PIVOT or downgrade")
    existing = [n for n, _ in round_dirs(campaign_dir) if (round_dir(campaign_dir, n) / MANIFEST).exists()]
    expected = (max(existing) + 1) if existing else 1
    if round_n != expected and round_n not in existing:
        raise ReviewError(f"rounds must be consecutive: next round is {expected}, got {round_n}")
    for a in artifacts:
        if not (campaign_dir / a).is_file():
            raise ReviewError(f"artifact {a!r} not found under {campaign_dir}")

    stakes_val = 1 if stakes is None else stakes
    if stakes is None:
        try:
            with open(campaign_dir / "ledger.json", "r", encoding="utf-8") as fh:
                stakes_val = int(json.load(fh).get("claims", {}).get(claim, {}).get("stakes", 1))
        except (OSError, ValueError, TypeError):
            stakes_val = 1
    regime = regime_for(stakes_val, budgets)
    k = skeptics if skeptics is not None else regime.skeptic_passes

    defaults = _role_defaults(round_n, claim, list(artifacts))
    role_map: dict[str, dict] = {}
    for i in range(max(1, k)):
        agent_id = mint_agent_id("SK")
        entry = json.loads(json.dumps(defaults["skeptic"]))
        entry["agent_id"] = agent_id
        entry["deliverable"] = f"reviews/round{round_n}/skeptic.{agent_id}.md"
        role_map[f"skeptic:{agent_id}"] = entry
    for role in ("falsifier", "novelty", "replicator", "judge"):
        role_map[role] = defaults[role]
    if roles:
        for key, override in roles.items():
            role_map.setdefault(key, {}).update(override)

    manifest = {
        "version": 1,
        "campaign": campaign or campaign_dir.name,
        "round": round_n,
        "claim": claim,
        "status": "open",
        "opened": utc_now_iso(),
        "closed": None,
        "artifacts": list(artifacts),
        "deny_always": list(DENY_ALWAYS),
        "roles": role_map,
        "waivers": [],
        "lineup": None,
        "regime": regime.model_dump(),
    }
    rdir = round_dir(campaign_dir, round_n)
    rdir.mkdir(parents=True, exist_ok=True)
    save_manifest(campaign_dir, round_n, manifest)
    atomic_write_json(rdir / ROUND_INFO, {
        "round": round_n, "claim": claim, "opened": manifest["opened"],
        "roles": sorted(role_map), "regime": regime.model_dump(),
    })
    return manifest


def close_round(campaign_dir: Path | str, round_n: int) -> dict:
    manifest = load_manifest(campaign_dir, round_n)
    manifest["status"] = "closed"
    manifest["closed"] = utc_now_iso()
    save_manifest(campaign_dir, round_n, manifest)
    return manifest


def commit_blind(campaign_dir: Path | str, round_n: int, file: str) -> dict:
    """Seal the replicator's blind values (sha256 + timestamp) and open stage B."""
    campaign_dir = Path(campaign_dir)
    manifest = load_manifest(campaign_dir, round_n)
    rep = manifest["roles"].get("replicator")
    if rep is None:
        raise ReviewError("manifest has no replicator role")
    rel = file.replace("\\", "/")
    full = campaign_dir / rel
    if not full.is_file():
        raise ReviewError(f"blind file {rel!r} not found")
    if rep.get("blind_committed"):
        raise ReviewError(f"blind values already committed at {rep['blind_committed']}")
    rep["blind_sha256"] = sha256_file(full)
    rep["blind_file"] = rel
    rep["blind_committed"] = utc_now_iso()
    rep["stage"] = "B"
    save_manifest(campaign_dir, round_n, manifest)
    return rep


def waive(campaign_dir: Path | str, round_n: int, role: str, target: str, reason: str) -> dict:
    manifest = load_manifest(campaign_dir, round_n)
    if not reason.strip():
        raise ReviewError("a waiver needs a reason")
    entry = {"role": role, "target": target.replace("\\", "/"), "reason": reason, "ts": utc_now_iso()}
    manifest.setdefault("waivers", []).append(entry)
    save_manifest(campaign_dir, round_n, manifest)
    return entry


# ----------------------------------------------------------------- checks --

def _role_of(key: str) -> str:
    return key.split(":", 1)[0]


def _waived(manifest: dict, row: dict) -> bool:
    for w in manifest.get("waivers", []):
        if w.get("role") in (row.get("role"), _role_of(str(row.get("role", "")))) and (
            w.get("target") == row.get("target") or glob_match(str(row.get("target", "")), str(w.get("target", "")))
        ):
            return True
    return False


def check_round(campaign_dir: Path | str, round_n: int, store=None) -> list[str]:
    """Phase-exit criteria for a review round (empty = ok).

    ``store`` is an optional :class:`~harness.ledger.ledger.LedgerStore` used for
    the round-cap rule and evidence-hash integrity.
    """
    campaign_dir = Path(campaign_dir)
    rdir = round_dir(campaign_dir, round_n)
    problems: list[str] = []
    try:
        manifest = load_manifest(campaign_dir, round_n)
    except ReviewError as exc:
        return [f"round {round_n}: {exc} (open the round with `harness review open` before spawning referees)"]

    rows = read_access_log(rdir)
    denies = [r for r in rows if r.get("decision") == "deny" and not _waived(manifest, r)]
    if denies:
        head = "; ".join(f"{r.get('role')} {r.get('tool')} {r.get('target')}" for r in denies[:3])
        problems.append(f"round {round_n}: {len(denies)} barrier denial(s) without waiver (first: {head})")
    errors_path = rdir / HOOK_ERRORS
    if errors_path.exists() and errors_path.read_text(encoding="utf-8", errors="replace").strip():
        problems.append(f"round {round_n}: {HOOK_ERRORS} is not empty (barrier hook failed open); inspect and clear it")

    # every barrier role that delivered a report must show hook activity (the hook may be mis-registered)
    active = {str(r.get("role")) for r in rows if r.get("role")}
    for key, role in manifest.get("roles", {}).items():
        if not role.get("barrier", True):
            continue
        deliverable = role.get("deliverable")
        base = _role_of(key)
        delivered = bool(deliverable and (campaign_dir / deliverable).exists()) or bool(role_reports(rdir, base))
        if delivered and key not in active and base not in active and not any(a.startswith(base) for a in active):
            problems.append(
                f"round {round_n}: {key} wrote a report but no hook activity was logged in {ACCESS_LOG} "
                "(barrier hook not registered for this agent?)"
            )

    # replicator: blind commit before any artifact access; verify the sealed file is unchanged
    rep = manifest.get("roles", {}).get("replicator")
    rep_blocks = blocks_for_role(rdir, "replicator")
    if rep is not None and any(b.get("verdict") == "pass" for b in rep_blocks):
        if not rep.get("blind_committed"):
            problems.append(f"round {round_n}: replicator passed without a blind commit (`harness review commit-blind`)")
        else:
            bf = rep.get("blind_file")
            if bf and (campaign_dir / bf).is_file() and sha256_file(campaign_dir / bf) != rep.get("blind_sha256"):
                problems.append(f"round {round_n}: replicator blind file {bf} changed after the commit")
            arts = manifest.get("artifacts", [])
            for r in rows:
                if _role_of(str(r.get("role", ""))) != "replicator" or r.get("decision") != "allow":
                    continue
                if any(glob_match(str(r.get("target", "")), a) for a in arts) and str(r.get("ts", "")) < str(rep["blind_committed"]):
                    problems.append(f"round {round_n}: replicator accessed the artifact before the blind commit ({r.get('ts')})")
                    break

    # novelty memo must classify
    if role_reports(rdir, "novelty") and novelty_class(campaign_dir, round_n) is None:
        problems.append(f"round {round_n}: novelty.md has no 1a/1b/1c/1d classification in its verdict block")

    # judge must end with a valid verdict line
    judge_md = rdir / "judge.md"
    if judge_md.exists():
        text = judge_md.read_text(encoding="utf-8", errors="replace")
        decision = judge_verdict(text)
        if decision is None:
            problems.append(f"round {round_n}: judge.md has no final line 'VERDICT: <{'|'.join(JUDGE_DECISIONS)}>'")
        elif store is not None:
            cap = load_budgets(campaign_dir).get("max_review_rounds")
            has_pass = any(c.status == "referee-passed" for c in store.ledger.claims.values())
            if isinstance(cap, int) and round_n >= cap and not has_pass and decision not in ("PIVOT",):
                problems.append(f"round {round_n} is the last budgeted round without a pass: the judge must PIVOT (or downgrade)")
        for extra in _judge_consistency(rdir, manifest, text):
            problems.append(f"round {round_n}: {extra}")

    for extra in _lineup_checks(campaign_dir, round_n, manifest):
        problems.append(f"round {round_n}: {extra}")

    regime = regime_of_manifest(manifest)
    if regime.final_statement_recheck:
        try:
            from harness.review.novelty_recheck import novelty_recheck
        except ImportError:  # pragma: no cover
            novelty_recheck = None  # type: ignore[assignment]
        if novelty_recheck is not None:
            for extra in novelty_recheck(campaign_dir, round_n, manifest, required=True):
                problems.append(f"round {round_n}: {extra}")

    if store is not None:
        for p in store.check_integrity(campaign_dir):
            problems.append(f"ledger integrity: {p}")
    return problems


def _judge_consistency(rdir: Path, manifest: dict, judge_text: str) -> list[str]:
    """Hook for Round-2 Y3 (structured adjudication); extended in Step 19."""
    try:
        from harness.review.adjudication import judge_consistency
    except ImportError:
        return []
    return judge_consistency(rdir, manifest, judge_text)


def _lineup_checks(campaign_dir: Path, round_n: int, manifest: dict) -> list[str]:
    """Hook for Round-2 X1 (decoy lineup); extended in Step 21."""
    try:
        from harness.review.lineup import lineup_checks
    except ImportError:
        return []
    return lineup_checks(campaign_dir, round_n, manifest)


def round_status(campaign_dir: Path | str, round_n: int) -> dict:
    campaign_dir = Path(campaign_dir)
    manifest = load_manifest(campaign_dir, round_n)
    rdir = round_dir(campaign_dir, round_n)
    rows = read_access_log(rdir)
    reports = {}
    for key, role in manifest.get("roles", {}).items():
        base = _role_of(key)
        files = [p.name for p in role_reports(rdir, base)]
        blocks = blocks_for_role(rdir, base)
        reports[key] = {"reports": files, "verdicts": [b.get("verdict") for b in blocks]}
    return {
        "round": round_n,
        "claim": manifest.get("claim"),
        "status": manifest.get("status"),
        "regime": manifest.get("regime"),
        "access_rows": len(rows),
        "denies": sum(1 for r in rows if r.get("decision") == "deny"),
        "roles": reports,
        "replicator_stage": manifest.get("roles", {}).get("replicator", {}).get("stage"),
        "judge": judge_verdict((rdir / "judge.md").read_text(encoding="utf-8", errors="replace")) if (rdir / "judge.md").exists() else None,
        "problems": check_round(campaign_dir, round_n),
    }


def regime_of_manifest(manifest: dict) -> Regime:
    return Regime.model_validate(manifest.get("regime") or {})


__all__ = [
    "ReviewError", "DENY_ALWAYS", "BARRIER_ROLES", "ALL_ROLES", "glob_match", "role_allowed", "open_round",
    "close_round", "commit_blind", "waive", "check_round", "round_status", "open_barrier", "open_barriers",
    "read_access_log", "load_manifest", "save_manifest", "manifest_path", "round_dir", "mint_agent_id",
    "parse_verdict_blocks", "regime_of_manifest",
]
