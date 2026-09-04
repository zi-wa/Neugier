"""In-house eval runner (Round-2 Step 29 / Y13) — `claude plugin eval` stand-in until early access lands.

Reads ``evals/<case>/case.yaml`` (the official layout plus a ``neugier:`` block
with deterministic graders), scaffolds the planted fixture into a throwaway
workspace, runs ``claude -p`` there (prompt on stdin, no shell) in two arms —
**with** the plugin (``--plugin-dir <repo>``, the project's hooks and skills)
and **without** (a bare workspace: no ``.claude/``, no ``CLAUDE.md``) — and scores
the produced files. Results go to ``evals/results/<timestamp>/aggregate.json``;
the README may quote numbers only from such files.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

import harness

EVALS_DIR = Path(harness.ROOT) / "evals"
LIB = EVALS_DIR / "_lib"
sys.path.insert(0, str(LIB))


def load_cases(pattern: str | None = None) -> list[dict]:
    cases = []
    for cy in sorted(EVALS_DIR.glob("*/case.yaml")):
        data = yaml.safe_load(cy.read_text(encoding="utf-8")) or {}
        data["_dir"] = cy.parent
        data.setdefault("name", cy.parent.name)
        if pattern and not fnmatch.fnmatch(data["name"], pattern):
            continue
        prompt_ref = data.get("prompt", "prompt.md")
        prompt_path = cy.parent / prompt_ref if not str(prompt_ref).strip().startswith(("You ", "The ")) else None
        data["_prompt"] = prompt_path.read_text(encoding="utf-8") if prompt_path and prompt_path.exists() else str(prompt_ref)
        cases.append(data)
    return cases


def grade(workspace: Path, spec: dict) -> tuple[float, str]:
    import graders  # evals/_lib/graders.py

    t = spec.get("type")
    if t == "file_exists":
        return graders.file_exists(workspace, spec["path"])
    if t == "file_regex":
        return graders.file_regex(workspace, spec["path"], spec["regex"])
    if t == "json_not_null":
        return graders.json_path_not_null(workspace, spec["path"], spec["key"])
    if t == "access_log_deny":
        return graders.access_log_has_deny(workspace, spec["path"], spec["target"])
    return 0.0, f"unknown grader type {t!r}"


def _workspace(case: dict, arm: str, run: int, base: Path) -> Path:
    ws = base / case["name"] / arm / f"run{run}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    from scaffold import scaffold  # evals/_lib/scaffold.py

    scaffold(case["name"], ws)
    if arm == "with":
        # project-mode wiring: hooks + skills + agents visible from the workspace
        (ws / ".claude").mkdir(exist_ok=True)
        shutil.copyfile(harness.ROOT / ".claude" / "settings.json", ws / ".claude" / "settings.json")
        for d in ("agents", "skills"):
            shutil.copytree(harness.ROOT / d, ws / ".claude" / d)
        shutil.copytree(harness.ROOT / "hooks", ws / "hooks")
        shutil.copyfile(harness.ROOT / "CLAUDE.md", ws / "CLAUDE.md")
    return ws


def _claude_argv(claude_bin: str, max_turns: int, model: str | None, plugin_dir: Path | None, allowed: list[str]) -> list[str]:
    resolved = shutil.which(claude_bin) or shutil.which(claude_bin + ".cmd") or claude_bin
    argv = [resolved, "-p", "--max-turns", str(max_turns), "--permission-mode", "acceptEdits", "--output-format", "json"]
    if allowed:
        argv += ["--allowedTools", ",".join(allowed)]
    if model:
        argv += ["--model", model]
    if plugin_dir is not None:
        argv += ["--plugin-dir", str(plugin_dir)]
    return argv


def run_cases(cases: list[dict], *, runs: int | None = None, arms: tuple[str, ...] = ("with", "without"),
              max_turns: int | None = None, model: str | None = None, claude_bin: str = "claude",
              base: Path | None = None, results_dir: Path | None = None, dry_run: bool = False) -> dict:
    base = base or Path(harness.CACHE) / "evals"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results_dir = results_dir or (EVALS_DIR / "results" / stamp)
    results_dir.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    out_cases = []
    for case in cases:
        n_runs = runs or int(case.get("runs", 3))
        turns = max_turns or int(case.get("max_turns", 30))
        meta = case.get("neugier") or {}
        specs = meta.get("graders") or []
        case_arms = [a for a in arms if not (a == "without" and meta.get("requires_plugin"))]
        arm_results: dict[str, list[dict]] = {}
        for arm in case_arms:
            arm_results[arm] = []
            for i in range(n_runs):
                ws = _workspace(case, arm, i, base)
                prompt = case["_prompt"].replace(".venv/Scripts/python.exe", py)
                rc, err = -1, ""
                if not dry_run:
                    try:
                        proc = subprocess.run(
                            _claude_argv(claude_bin, turns, model, harness.ROOT if arm == "with" else None, case.get("allowed_tools") or []),
                            input=prompt, cwd=str(ws), capture_output=True, encoding="utf-8", errors="replace",
                            timeout=int(case.get("timeout_seconds", 900)), env=dict(os.environ, PYTHONUTF8="1", CLAUDE_PROJECT_DIR=str(ws)),
                        )
                        rc, err = proc.returncode, (proc.stderr or "")[-400:]
                    except Exception as exc:  # noqa: BLE001
                        err = f"{type(exc).__name__}: {exc}"
                scores = []
                for spec in specs:
                    if spec.get("with_only") and arm != "with":
                        continue
                    s, detail = grade(ws, spec)
                    scores.append({"grader": spec.get("type"), "score": s, "detail": detail})
                case_score = round(sum(s["score"] for s in scores) / len(scores), 4) if scores else None
                arm_results[arm].append({"run": i, "rc": rc, "stderr_tail": err, "graders": scores, "score": case_score, "workspace": str(ws)})
        means = {arm: round(sum(r["score"] or 0 for r in rs) / len(rs), 4) if rs else None for arm, rs in arm_results.items()}
        delta = (means["with"] - means["without"]) if means.get("with") is not None and means.get("without") is not None else None
        out_cases.append({"name": case["name"], "runs": n_runs, "arms": arm_results, "mean": means,
                          "delta_with_minus_without": round(delta, 4) if delta is not None else None})
    aggregate = {"schemaVersion": "neugier-evals-1", "timestamp": stamp, "dry_run": dry_run, "cases": out_cases}
    (results_dir / "aggregate.json").write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")
    aggregate["results_dir"] = str(results_dir)
    return aggregate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness evals", description="run the plugin eval cases with `claude -p` (with/without arms)")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--case", default=None)
    r = sub.add_parser("run")
    r.add_argument("--case", default=None, help="glob on case names (default: all)")
    r.add_argument("--all", action="store_true")
    r.add_argument("--runs", type=int, default=None)
    r.add_argument("--max-turns", type=int, default=None)
    r.add_argument("--model", default=None)
    r.add_argument("--without", action="store_true", help="only the without-plugin arm")
    r.add_argument("--with-only", action="store_true", help="only the with-plugin arm")
    r.add_argument("--dry-run", action="store_true", help="scaffold + grade without calling claude (expect zeros)")
    args = p.parse_args(argv)
    cases = load_cases(args.case)
    if args.cmd == "list":
        for c in cases:
            print(f"{c['name']:<40} runs={c.get('runs', 3)} graders={len((c.get('neugier') or {}).get('graders') or [])}  {c.get('description', '')}")
        return 0
    if not cases:
        print("no cases match", file=sys.stderr)
        return 1
    arms = ("with", "without")
    if args.without:
        arms = ("without",)
    elif args.with_only:
        arms = ("with",)
    agg = run_cases(cases, runs=args.runs, arms=arms, max_turns=args.max_turns, model=args.model, dry_run=args.dry_run)
    for c in agg["cases"]:
        print(f"{c['name']:<40} with={c['mean'].get('with')} without={c['mean'].get('without')} delta={c['delta_with_minus_without']}")
    print(f"results: {agg['results_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
