"""`python -m harness prove elo --campaign s --claim T-001 [--k 32] [--c 1.0] [--full-proofs N]`"""
from __future__ import annotations

import argparse
import json
import sys

from harness import CAMPAIGNS
from harness.prove.elo import tournament


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness prove", description="sketch tournament: Elo ratings and full-proof selection")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("elo", help="rate reviews/tournament-<ID>/match-*.json and select sketches for full proofs")
    e.add_argument("--campaign", required=True)
    e.add_argument("--claim", required=True)
    e.add_argument("--k", type=float, default=32.0)
    e.add_argument("--c", type=float, default=1.0)
    e.add_argument("--full-proofs", type=int, default=None, dest="full_proofs")
    e.add_argument("--json", action="store_true")
    c = sub.add_parser("collect", help="check proof files out of worktree commits and replay their ledger-ops")
    c.add_argument("--campaign", required=True)
    c.add_argument("--claim", required=True)
    c.add_argument("--commits", required=True, help="comma-separated commit shas")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "elo":
        result = tournament(CAMPAIGNS / args.campaign, args.claim, k=args.k, c=args.c, full_proofs=args.full_proofs)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"tournament {args.claim}: {result['matches']} match(es); selected {result['selected'] or 'none'}")
            for persona, row in sorted(result["sketches"].items(), key=lambda t: -t[1]["score"]):
                flag = "SELECTED" if row["selected"] else (row["reason"] or "")
                print(f"  {persona:<16} elo {row['elo']:>7}  W/L/D {row['wins']}/{row['losses']}/{row['draws']}  score {row['score']:>7}  {flag}")
            for persona, notes in result["cross_pollination"].items():
                for n in notes:
                    print(f"  {persona} <- {n}")
        if not result["selected"]:
            print("no sketch selectable (all falsified or no sketches)", file=sys.stderr)
            return 3
        return 0
    if args.cmd == "collect":
        import harness
        from harness.prove.collect import collect

        try:
            report = collect(harness.ROOT, args.campaign, args.claim, [c.strip() for c in args.commits.split(",") if c.strip()])
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if any(o.get("error") for c in report["commits"].values() for o in c["ledger_ops"]) else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
