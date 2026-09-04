"""Headless campaign driver (Round-1 Step 14 / C4): `claude -p` in a loop with checkpoints.

``run_campaign(slug, ...)`` repeatedly invokes ``claude -p`` with the resume
command (default ``/research --resume --slug <slug>``; use ``--command
/neugier:research`` when the plugin is installed from a marketplace), passing
the prompt on stdin (no shell) with ``--max-turns`` per iteration. It stops when
the campaign phase is ``done``, when ``blocked.md`` appears, after
``max_iterations``, or after ``stall_limit`` consecutive iterations with no phase
change and no growth of ``log.md`` (ARIS-style stall detection). Every
iteration is appended to ``campaigns/<slug>/headless.log`` (JSONL).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import harness


def _phase(campaign_dir: Path) -> str:
    try:
        return str(json.loads((campaign_dir / "campaign.json").read_text(encoding="utf-8")).get("phase", ""))
    except (OSError, ValueError):
        return ""


def _log_size(campaign_dir: Path) -> int:
    try:
        return (campaign_dir / "log.md").stat().st_size
    except OSError:
        return 0


def claude_argv(claude_bin: str, max_turns: int, permission_mode: str, model: str | None, plugin_dir: Path | None) -> list[str]:
    resolved = shutil.which(claude_bin) or shutil.which(claude_bin + ".cmd") or claude_bin
    argv = [resolved, "-p", "--max-turns", str(max_turns), "--permission-mode", permission_mode, "--output-format", "json"]
    if model:
        argv += ["--model", model]
    if plugin_dir is not None:
        argv += ["--plugin-dir", str(plugin_dir)]
    return argv


def run_campaign(
    slug: str,
    *,
    max_iterations: int = 20,
    max_turns: int = 200,
    permission_mode: str = "acceptEdits",
    command: str = "/research",
    claude_bin: str = "claude",
    model: str | None = None,
    plugin_dir: Path | None = None,
    stall_limit: int = 3,
    timeout: int = 3600,
) -> list[dict]:
    campaign_dir = Path(harness.CAMPAIGNS) / slug
    if not (campaign_dir / "campaign.json").exists():
        raise FileNotFoundError(f"no such campaign: {slug}")
    log_path = campaign_dir / "headless.log"
    prompt = f"{command} --resume --slug {slug}"
    history: list[dict] = []
    stalled = 0
    for i in range(1, max_iterations + 1):
        phase_before, size_before = _phase(campaign_dir), _log_size(campaign_dir)
        started = time.time()
        rc, out, err = -1, "", ""
        try:
            proc = subprocess.run(
                claude_argv(claude_bin, max_turns, permission_mode, model, plugin_dir), input=prompt,
                cwd=str(harness.ROOT), capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
                env=dict(os.environ, PYTHONUTF8="1"),
            )
            rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired:
            err = f"timeout after {timeout}s"
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        phase_after, size_after = _phase(campaign_dir), _log_size(campaign_dir)
        blocked = (campaign_dir / "blocked.md").exists()
        progressed = phase_after != phase_before or size_after > size_before
        stalled = 0 if progressed else stalled + 1
        entry = {
            "iteration": i, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - started, 1), "rc": rc,
            "phase_before": phase_before, "phase_after": phase_after, "log_bytes": size_after, "progressed": progressed,
            "blocked": blocked, "stderr_tail": err[-400:], "stdout_tail": out[-400:],
        }
        history.append(entry)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if phase_after == "done":
            entry["stop"] = "done"
            break
        if blocked:
            entry["stop"] = "blocked.md"
            break
        if stalled >= stall_limit:
            entry["stop"] = f"stalled {stall_limit} iterations"
            break
    return history


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness headless", description="drive a campaign with `claude -p` iterations")
    p.add_argument("slug")
    p.add_argument("--max-iterations", type=int, default=20)
    p.add_argument("--max-turns", type=int, default=200)
    p.add_argument("--permission-mode", default="acceptEdits")
    p.add_argument("--command", default="/research", help="slash command (use /neugier:research when installed as a plugin)")
    p.add_argument("--model", default=None)
    p.add_argument("--plugin-dir", default=None, help="pass --plugin-dir to claude (e.g. the repo root)")
    p.add_argument("--stall-limit", type=int, default=3)
    args = p.parse_args(argv)
    try:
        hist = run_campaign(args.slug, max_iterations=args.max_iterations, max_turns=args.max_turns,
                            permission_mode=args.permission_mode, command=args.command, model=args.model,
                            plugin_dir=Path(args.plugin_dir) if args.plugin_dir else None, stall_limit=args.stall_limit)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    last = hist[-1] if hist else {}
    print(json.dumps({"iterations": len(hist), "stop": last.get("stop", "max_iterations"), "phase": last.get("phase_after")}, indent=2))
    return 0 if last.get("stop") == "done" else 2


if __name__ == "__main__":
    raise SystemExit(main())
