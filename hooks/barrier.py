"""PreToolUse hook: the referees' information barrier, enforced (Round-1 Step 5, Round-2 X1).

Active only inside a referee subagent (``agent_type`` = skeptic | falsifier | novelty-checker |
replicator) while a review round is open (``reviews/roundN/barrier.json`` with ``status: open``).
Every decision is appended to ``reviews/roundN/access.log`` as JSONL
``{"ts","role","agent_id","session_id","tool","decision","target","reason"}``; a denial is returned to
Claude Code as ``permissionDecision: deny`` with a ``[Neugier barrier]`` reason that names the allowed
alternative. Any internal error is logged to ``reviews/roundN/hook_errors.log`` and the hook fails
open (exit 0) — ``harness review check`` then refuses the round.

Rules (see harness/review/barrier.py for the manifest):
* Read/Write/Edit: inside the campaign only paths the role's ``allow`` list matches; Write/Edit
  additionally only under ``reviews/roundN/``; outside the campaign anything except ``~/.claude``
  (transcripts) and other campaigns.
* Glob/Grep: ``path`` is required and must be outside the campaign or an allowed directory.
* Bash/PowerShell: every path-like token is checked as above; additionally, for barrier roles, reading
  forbidden markdown by name, git history commands, transcript directories, ledger/campaign mutation
  commands and pairwise diffs (lineup mode) are denied.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    active_campaign, agent_role, append_jsonl, campaign_dir_of, claude_agent_id, deny, dir_allowed,
    find_open_barrier, iso_now, log_hook_error, norm_path, project_root, read_input, rel_to, resolve_role_key,
    role_allowed, utf8_stdio,
)

BARRIER_ROLES = ("skeptic", "falsifier", "novelty", "replicator")
EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
SEARCH_TOOLS = ("Glob", "Grep")
SHELL_TOOLS = ("Bash", "PowerShell")

FORBIDDEN_MD = r"(plan|ideas|log|questions|survey|portfolio|blocked|HUMAN|ASK-HUMAN)\.md"
READERS = r"(cat|type|Get-Content|gc|grep|rg|findstr|head|tail|sed|more|less|awk|python3?(?:\.exe)?\s+-c|Select-String)"
SHELL_DENY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\b{READERS}\b[^\n|;&]*\b{FORBIDDEN_MD}\b", re.IGNORECASE), "reading the prover's planning/log files"),
    (re.compile(r"\bgit\s+(show|log|diff|grep|blame|cat-file|reflog)\b", re.IGNORECASE), "git history reveals the prover's process"),
    (re.compile(r"\.claude[\\/]projects", re.IGNORECASE), "transcript directories are off limits"),
    (re.compile(r"\bharness\s+ledger\s+(promote|add|update|attest|reverify|credence)\b", re.IGNORECASE), "referees do not mutate claims (only `ledger evidence` through the judge)"),
    (re.compile(r"\bharness\s+campaign\s+(phase|activate|freeze|unfreeze|outcome|finish|attest)\b", re.IGNORECASE), "referees do not change campaign state"),
    (re.compile(r"\bharness\s+review\s+(open|close|commit-blind|waive)\b", re.IGNORECASE), "referees do not manage the round"),
    (re.compile(r"(^|[\s;&|(])(diff|fc|comp|cmp|colordiff|delta)(\.exe)?\s", re.IGNORECASE), "pairwise diffs of lineup items are forbidden"),
    (re.compile(r"\bdifflib\b|\bfilecmp\b", re.IGNORECASE), "pairwise diffs of lineup items are forbidden"),
]

_TOKEN_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'|([^\s"\'|;&<>()]+)')
_PATHISH_RE = re.compile(r"[\\/]|\.(md|json|jsonl|py|txt|bib|tex|log|csv|yaml|yml|pdf|html)$", re.IGNORECASE)


def _tokens(cmd: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN_RE.finditer(cmd):
        tok = next(g for g in m.groups() if g is not None)
        tok = tok.strip().rstrip(",;:")
        if tok.startswith("-"):
            eq = tok.find("=")
            if eq > 0:
                tok = tok[eq + 1:]
            else:
                continue
        if tok and _PATHISH_RE.search(tok) and not tok.startswith(("http://", "https://")):
            out.append(tok)
    return out


def _outside_ok(root: Path, norm: str) -> tuple[bool, str]:
    home = norm_path(os.path.expanduser("~"))
    if norm.startswith(home + "/.claude/"):
        return False, "deny:claude-home"
    camps = norm_path(str(root / "campaigns")) + "/"
    if norm.startswith(camps):
        return False, "deny:other-campaign"
    return True, "outside-campaign"


def _check_path(root: Path, cdir: Path, manifest: dict, role_key: str, raw: str, cwd: str, *, edit: bool, round_dir: Path) -> tuple[bool, str, str]:
    norm = norm_path(raw, cwd)
    rel = rel_to(norm, cdir)
    if rel is None:
        ok, why = _outside_ok(root, norm)
        if edit and ok:
            return True, "outside-campaign", norm
        return ok, why, norm
    if edit:
        rd = rel_to(str(round_dir), cdir) or ""
        if not (rel == rd or rel.startswith(rd.rstrip("/") + "/")):
            return False, "deny:write-outside-round", rel
    ok, why = role_allowed(manifest, role_key, rel)
    return ok, why, rel


def main() -> int:
    utf8_stdio()
    data = read_input()
    tool = str(data.get("tool_name") or "")
    role = agent_role(data)
    if role not in BARRIER_ROLES:
        return 0
    root = project_root(data)
    slug = active_campaign(root)
    if not slug:
        return 0
    found = find_open_barrier(root, slug)
    if found is None:
        return 0
    cdir = campaign_dir_of(root, slug)
    agent = claude_agent_id(data)
    session = str(data.get("session_id") or "")
    tool_input = data.get("tool_input") or {}
    cwd = str(data.get("cwd") or root)
    if found == "ambiguous":
        deny("PreToolUse", "[Neugier barrier] more than one review round is open; ask the orchestrator to close the stale round (`harness review close`).")
        return 0
    round_n, manifest, round_dir = found
    log = round_dir / "access.log"
    try:
        role_key = resolve_role_key(round_dir, manifest, role, agent) or role
        decisions: list[tuple[bool, str, str]] = []

        if tool == "Read":
            target = str(tool_input.get("file_path") or "")
            decisions.append(_check_path(root, cdir, manifest, role_key, target, cwd, edit=False, round_dir=round_dir))
        elif tool in EDIT_TOOLS:
            target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
            decisions.append(_check_path(root, cdir, manifest, role_key, target, cwd, edit=True, round_dir=round_dir))
        elif tool in SEARCH_TOOLS:
            path = tool_input.get("path")
            if not path:
                decisions.append((False, "deny:search-without-path", "(no path)"))
            else:
                norm = norm_path(str(path), cwd)
                rel = rel_to(norm, cdir)
                if rel is None:
                    ok, why = _outside_ok(root, norm)
                    decisions.append((ok, why, norm))
                elif dir_allowed(manifest, role_key, rel):
                    decisions.append((True, "allow:dir", rel or "."))
                else:
                    decisions.append((False, "deny:search-dir-not-allowed", rel or "."))
        elif tool in SHELL_TOOLS:
            cmd = str(tool_input.get("command") or "")
            for rx, why in SHELL_DENY:
                if rx.search(cmd):
                    decisions.append((False, f"deny:shell:{why}", cmd[:160]))
                    break
            else:
                for tok in _tokens(cmd):
                    decisions.append(_check_path(root, cdir, manifest, role_key, tok, cwd, edit=False, round_dir=round_dir))
                if not decisions:
                    decisions.append((True, "allow:no-paths", cmd[:160]))
        else:
            return 0

        denied = [d for d in decisions if not d[0]]
        for ok, why, target in (denied or decisions[:1]):
            append_jsonl(log, {
                "ts": iso_now(), "role": role_key, "agent_id": agent, "session_id": session, "tool": tool,
                "decision": "deny" if not ok else "allow", "target": target, "reason": why,
            })
        if denied:
            _, why, target = denied[0]
            allowed = manifest.get("roles", {}).get(role_key, {}).get("allow", [])
            hint = ", ".join(allowed[:6]) + (" …" if len(allowed) > 6 else "")
            deny(
                "PreToolUse",
                f"[Neugier barrier] {tool} on {target!r} is not permitted for {role_key} ({why}). "
                f"You see only statement.md and the artifact(s) under review; your allowlist: {hint}. "
                "Glob/Grep need an explicit path inside your allowlist; write only under your own reviews/round"
                f"{round_n}/ files.",
            )
        return 0
    except Exception as exc:  # fail open, but leave a trace the gate will refuse
        log_hook_error(round_dir, exc, f"barrier.py {tool}")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
