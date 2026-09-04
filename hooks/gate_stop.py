"""Stop hook: while a campaign phase is open (marker campaigns/<slug>/.gate), refuse to end the turn until the
phase's exit criteria are met. Exit code 2 + stderr message = "keep working". Gives up after MAX_BLOCKS
consecutive blocks (writes blocked.md) so the user is never trapped; Claude Code also caps at 8.

The gate belongs to the session that opened it (``owner=<session id>`` in the marker, written by
``harness campaign phase <slug> <phase> --gate``). Another session working in the same project is never
blocked by it and never deletes it — several Claude Code sessions share one project directory, and one
session's open phase must not trap or clobber another's. A legacy marker with no owner cannot be
attributed, so it blocks any one session at most once (LEGACY_BLOCKS) and is left in place.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    active_campaign, project_root, read_gate, read_input, run_harness, session_slug,
)

MAX_BLOCKS = 5
LEGACY_BLOCKS = 1  # unowned marker: nudge once, never escalate


def _unlink(*paths: Path) -> None:
    for p in paths:
        try:
            p.unlink()
        except Exception:
            pass


def main() -> int:
    data = read_input()
    root = project_root(data)
    slug = active_campaign(root)
    if not slug:
        return 0
    cdir = root / "campaigns" / slug
    gate = cdir / ".gate"
    if not gate.exists():
        return 0
    _, owner = read_gate(gate)
    me = str(data.get("session_id") or "")
    if owner and me and owner != me:
        return 0  # another session opened this phase; not ours to enforce or to clear
    rc, out = run_harness(root, ["campaign", "check", slug], timeout=50)
    if rc == 127:  # no venv: cannot check, never trap
        return 0
    counter = cdir / (f".gate_attempts.{session_slug(me)}" if me else ".gate_attempts")
    if rc == 0:
        _unlink(gate, counter)  # criteria met: release the gate
        return 0
    limit = MAX_BLOCKS if owner else LEGACY_BLOCKS
    try:
        n = int(counter.read_text(encoding="utf-8").strip() or 0)
    except Exception:
        n = 0
    n += 1
    counter.write_text(str(n), encoding="utf-8")
    unmet = "\n".join(ln for ln in out.splitlines() if ln.strip())
    if n > limit:
        if not owner:
            # Unowned marker: we cannot tell whether this session opened the phase, so stop blocking it
            # and leave the gate for whoever owns it.
            _unlink(counter)
            sys.stderr.write(
                f"[Neugier gate] campaign '{slug}' has an unowned phase gate; not blocking this session again. "
                f"If this session owns the phase, re-open the gate with `harness campaign phase {slug} <phase> --gate`.\n"
            )
            return 0
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        (cdir / "blocked.md").write_text(
            f"# Phase gate gave up ({stamp})\n\nUnmet exit criteria after {n - 1} attempts:\n\n{unmet}\n",
            encoding="utf-8",
        )
        _unlink(gate, counter)
        sys.stderr.write(
            f"[Neugier gate] giving up after {n - 1} blocks; see campaigns/{slug}/blocked.md. "
            "Report the blockage to the user.\n"
        )
        return 0
    phase = ""
    try:
        phase = json.loads((cdir / "campaign.json").read_text(encoding="utf-8")).get("phase", "")
    except Exception:
        pass
    sys.stderr.write(
        f"[Neugier gate {n}/{limit}] Campaign '{slug}' phase '{phase}' is still open - exit criteria unmet:\n"
        f"{unmet}\n"
        "Continue working on this phase. When done, `.venv/Scripts/python.exe -m harness campaign check "
        f"{slug}` must pass. If the phase is genuinely blocked, write campaigns/{slug}/blocked.md explaining why "
        f"and delete campaigns/{slug}/.gate.\n"
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
