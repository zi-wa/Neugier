"""PreToolUse hook (Bash / PowerShell): deny commands that install or change things outside the project.

Rule R2: Python packages only into .venv; no global package managers; no permanent system changes.
Fails open (exit 0, no output) on any internal error so it can never block ordinary work.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import emit, read_input  # noqa: E402

# A path separator: backslash or forward slash (one or more).
SEP = r"[\\/]+"
# Something that looks like a user's home directory prefix.
HOME = r"(?:~|\$HOME|%USERPROFILE%|\$env:USERPROFILE|[A-Za-z]:" + SEP + r"Users" + SEP + r"[^\\/\s]+)"

DENY: list[tuple[str, str]] = [
    # (regex, reason)
    (r"\buv\s+pip\s+install\b[^\n|;&]*\s--system\b", "uv pip install --system targets the global interpreter"),
    (r"\b(winget|choco|scoop|brew|apt(-get)?|yum|dnf|pacman)\s+(install|add|upgrade)\b", "system package manager install"),
    (r"\bnpm\s+(i|install|add|update)\b[^\n|;&]*\s(-g|--global)\b", "global npm install"),
    (r"\b(pnpm|yarn)\s+(add|global)\b[^\n|;&]*\s(-g|--global|global)\b", "global node package install"),
    (r"\bpipx\s+install\b", "pipx installs into the user environment"),
    (r"\bcargo\s+install\b", "cargo install writes to ~/.cargo"),
    (r"\brustup\b", "rustup modifies the user toolchain"),
    (r"\bsetx\b", "setx permanently changes environment variables"),
    (r"\breg(\.exe)?\s+(add|delete|import)\b", "registry modification"),
    (r"\b(Set|New|Remove)-ItemProperty\b[^\n]*\bHK(LM|CU)\b", "registry modification"),
    (r"\[Environment\]::SetEnvironmentVariable\b", "permanent environment variable change"),
    (HOME + SEP + r"\.claude" + SEP + r"settings\.json", "editing the global ~/.claude/settings.json (project settings only)"),
]

PIP_INSTALL = re.compile(r"(^|[\s;&|(])(python3?|py)?\s*(-m\s+)?pip3?\s+install\b", re.IGNORECASE)
ELAN = re.compile(r"(^|[\s;&|(])(elan|elan-init)(\.exe)?\b", re.IGNORECASE)


def violation(cmd: str) -> str | None:
    low = cmd.lower()
    for rx, reason in DENY:
        if re.search(rx, cmd, flags=re.IGNORECASE):
            return reason
    if PIP_INSTALL.search(cmd) and ".venv" not in low and "uv pip" not in low:
        return "bare `pip install` would install into the global interpreter"
    if ELAN.search(cmd) and "elan_home" not in low:
        return "elan without a project-local ELAN_HOME installs into ~/.elan"
    return None


def main() -> int:
    data = read_input()
    if data.get("tool_name") not in {"Bash", "PowerShell"}:
        return 0
    cmd = str((data.get("tool_input") or {}).get("command") or "")
    if not cmd:
        return 0
    reason = violation(cmd)
    if reason is None:
        return 0
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"[Neugier R2] Blocked: {reason}. Keep installs inside the project: "
                "use `uv pip install --python .venv/Scripts/python.exe <pkg>` "
                "(or `.venv/Scripts/python.exe -m pip install <pkg>`), project-local binaries under bin/, "
                "caches under .cache/, and project .claude/settings.json only."
            ),
        }
    })
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
