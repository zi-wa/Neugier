"""`python -m harness proof check <file> --campaign s [--json]` — proof-artifact linter."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import CAMPAIGNS
from harness.ledger.ledger import LedgerStore
from harness.proof.lint import lint_proof


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness proof", description="proof-artifact tooling")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="lint a proof artifact against proof-standards.md (exit 1 on errors)")
    c.add_argument("file", help="campaign-relative or absolute path to proofs/<ID>.md")
    c.add_argument("--campaign", default=None, help="campaign slug (enables ledger/cite/results resolution)")
    c.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "check":
        campaign_dir = CAMPAIGNS / args.campaign if args.campaign else None
        path = Path(args.file)
        if not path.is_absolute() and campaign_dir is not None and (campaign_dir / path).exists():
            path = campaign_dir / path
        if not path.exists():
            print(f"[harness.proof] no such file: {path}", file=sys.stderr)
            return 2
        store = LedgerStore(campaign_dir / "ledger.json", campaign=args.campaign) if campaign_dir and (campaign_dir / "ledger.json").exists() else None
        report = lint_proof(path, campaign_dir, store)
        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"proof check: {'OK' if report.ok else 'FAILED'}  ({len(report.errors)} error(s), {len(report.warnings)} warning(s))  {path}")
            for e in report.errors:
                loc = f" line {e.line}" if e.line else ""
                print(f"  [ERROR {e.code}]{loc} {e.message}")
            for w in report.warnings:
                loc = f" line {w.line}" if w.line else ""
                print(f"  [WARN  {w.code}]{loc} {w.message}")
        return 0 if report.ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
