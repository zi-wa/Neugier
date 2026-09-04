"""`python -m harness falsify <command>` -- numeric/symbolic falsification CLI.

Exit codes for `run`: 0 = no counterexample found, 3 = counterexample found,
1 = error (module failed to load, or no usable strategy was available).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from harness.verify import exact, falsify


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness falsify", description="Numeric/symbolic falsification harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run a conjecture module's falsification search")
    p_run.add_argument("path", type=Path, help="path to a conjecture .py module")
    p_run.add_argument("--strategy", default="all", choices=["exhaustive", "random", "hillclimb", "all"])
    p_run.add_argument("--time-limit", type=float, default=60.0)
    p_run.add_argument("--max-instances", type=int, default=1_000_000)
    p_run.add_argument("--seed", type=int, default=0)
    p_run.add_argument("--out", type=Path, default=None, help="write the report JSON to this path too")
    p_run.add_argument("--regression", type=Path, default=None, help="JSON list of instance reprs that must all satisfy the predicate (truth test)")
    p_run.add_argument("--no-touch", action="store_true", help="skip the touch-number (equality cases) pass")

    p_id = sub.add_parser("identity", help="random-sample check that two expressions are numerically equal")
    p_id.add_argument("lhs")
    p_id.add_argument("rhs")
    p_id.add_argument("--symbols", required=True, help="comma-separated free symbol names")
    p_id.add_argument("--n", type=int, default=200)
    p_id.add_argument("--seed", type=int, default=0)

    p_tpl = sub.add_parser("template", help="copy the commented conjecture-module skeleton")
    p_tpl.add_argument("out_path", type=Path)

    p_hash = sub.add_parser("hash", help="sha256 of a file")
    p_hash.add_argument("path", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    ns = parser.parse_args(argv)

    if ns.cmd == "run":
        try:
            report = falsify.run(
                ns.path,
                strategy=ns.strategy,
                time_limit=ns.time_limit,
                max_instances=ns.max_instances,
                seed=ns.seed,
                out_json=ns.out,
                regression_path=ns.regression,
                touch=not ns.no_touch,
            )
        except Exception as e:
            print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False), file=sys.stderr)
            return 1
        print(report.model_dump_json(indent=2))
        if report.error:
            return 1
        if report.counterexample_repr is not None or report.regression_failures:
            return 3
        return 0

    if ns.cmd == "identity":
        symbols = [s.strip() for s in ns.symbols.split(",") if s.strip()]
        result = exact.random_check_identity(ns.lhs, ns.rhs, symbols, n=ns.n, seed=ns.seed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 3

    if ns.cmd == "template":
        src = Path(__file__).parent / "template_conjecture.py"
        ns.out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, ns.out_path)
        print(f"wrote template to {ns.out_path}")
        return 0

    if ns.cmd == "hash":
        print(exact.sha256_file(ns.path))
        return 0

    parser.error(f"unknown command {ns.cmd!r}")
    return 2  # pragma: no cover - argparse.error exits before this


if __name__ == "__main__":
    raise SystemExit(main())
