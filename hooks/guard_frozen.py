"""PreToolUse hook: frozen files stay frozen (Round-1 Step 5 / A7, Round-2 X6, X4).

* While the active campaign is in ``explore``/``prove``/``review``, files listed in
  ``campaign.json["frozen"]`` (scorers, verifiers, statement.md — recorded by
  ``harness campaign freeze`` / ``lock-statement``) and ``proofs/*.rubric.md`` (pre-registered marking
  schemes) may not be edited by Edit/Write tools or by shell commands that name them (read-only shell
  commands are fine).
* ``HUMAN.md`` is the human's file: agents may never edit it, in any phase.
* ``harness ledger attest`` / ``harness campaign attest`` are human-only commands.

Fails open on internal errors (exit 0, nothing printed).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import active_campaign, campaign_dir_of, deny, norm_path, project_root, read_input, rel_to, utf8_stdio  # noqa: E402

FROZEN_PHASES = {"explore", "prove", "review"}
EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")
READ_ONLY = re.compile(
    r"^\s*(cat|type|Get-Content|gc|head|tail|grep|rg|findstr|Select-String|wc|sha256sum|shasum|certutil|md5sum|diff|fc|comp|less|more|ls|dir|stat|file|"
    r"git\s+(status|diff|log|show)|python3?(\.exe)?\s+[^\n]*-m\s+harness\s+(ledger\s+(show|md|summary|check|graph|assertable)|campaign\s+(check|status|budget|list|active)|review\s+(status|check|regime)|questions|proof\s+check|paper\s+check|lit|falsify\s+run)"
    r")\b",
    re.IGNORECASE,
)
ATTEST_RE = re.compile(r"\bharness\s+(ledger|campaign)\s+attest\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'|([^\s"\'|;&<>()]+)')


def _tokens(cmd: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN_RE.finditer(cmd):
        tok = next(g for g in m.groups() if g is not None).strip().rstrip(",;:")
        if tok.startswith("-"):
            eq = tok.find("=")
            tok = tok[eq + 1:] if eq > 0 else ""
        if tok:
            out.append(tok)
    return out


def _frozen_set(cdir: Path) -> tuple[set[str], str]:
    try:
        camp = json.loads((cdir / "campaign.json").read_text(encoding="utf-8"))
    except Exception:
        return set(), ""
    frozen = {str(k).replace("\\", "/").lower() for k in (camp.get("frozen") or {})}
    for k in (camp.get("rubric_hashes") or {}):
        frozen.add(f"proofs/{k}.rubric.md".lower())
    return frozen, str(camp.get("phase") or "")


def _is_protected(rel: str, frozen: set[str], phase: str) -> str | None:
    r = rel.replace("\\", "/").lower()
    if r == "human.md":
        return "HUMAN.md is the human's file; agents never edit it (answer escalations belong to the human)"
    if phase in FROZEN_PHASES:
        if r in frozen:
            return f"{rel} is frozen during {phase} (scorer/verifier/statement/rubric); re-open the phase or `harness campaign unfreeze` deliberately"
        if re.fullmatch(r"proofs/[^/]+\.rubric\.md", r):
            return f"{rel} is a pre-registered marking scheme and cannot change once proofs exist"
    return None


def main() -> int:
    utf8_stdio()
    data = read_input()
    tool = str(data.get("tool_name") or "")
    if tool not in EDIT_TOOLS + SHELL_TOOLS:
        return 0
    root = project_root(data)
    slug = active_campaign(root)
    if not slug:
        return 0
    cdir = campaign_dir_of(root, slug)
    frozen, phase = _frozen_set(cdir)
    tool_input = data.get("tool_input") or {}
    cwd = str(data.get("cwd") or root)

    if tool in SHELL_TOOLS:
        cmd = str(tool_input.get("command") or "")
        if ATTEST_RE.search(cmd):
            deny("PreToolUse", "[Neugier R4] `attest` records a HUMAN sign-off; agents may not run it. Leave the theorem marked "
                              "not-yet-human-verified and tell the user how to attest.")
            return 0
        if READ_ONLY.match(cmd):
            return 0
        for tok in _tokens(cmd):
            rel = rel_to(norm_path(tok, cwd), cdir)
            if rel is None:
                continue
            why = _is_protected(rel, frozen, phase)
            if why:
                deny("PreToolUse", f"[Neugier frozen] {why}. Command: {cmd[:120]}")
                return 0
        return 0

    target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if not target:
        return 0
    rel = rel_to(norm_path(target, cwd), cdir)
    if rel is None:
        return 0
    why = _is_protected(rel, frozen, phase)
    if why:
        deny("PreToolUse", f"[Neugier frozen] {why}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
