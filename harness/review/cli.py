"""`python -m harness review ...` — review-round lifecycle behind the information barrier.

    harness review open --campaign s --round N --claim T-001 --artifact proofs/T-001.md [--skeptics k] [--stakes n]
    harness review close --campaign s --round N
    harness review commit-blind --campaign s --round N --file reviews/roundN/replicate/values.json
    harness review waive --campaign s --round N --role skeptic --target cache/x.txt --reason "..."
    harness review status --campaign s [--round N]
    harness review check --campaign s --round N
    harness review regime --campaign s --claim T-001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import CAMPAIGNS
from harness.ledger.ledger import LedgerError, LedgerStore, load_budgets
from harness.review import barrier
from harness.review.regime import regime_for
from harness.review.verdict import latest_round


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness review", description="review rounds: barrier manifests, blind commits, checks")
    p.add_argument("--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("open", aliases=["open-round"], help="open round N: write reviews/roundN/barrier.json")
    o.add_argument("--round", type=int, default=None, help="default: next round")
    o.add_argument("--claim", required=True)
    o.add_argument("--artifact", action="append", required=True, help="campaign-relative artifact path (repeatable)")
    o.add_argument("--skeptics", type=int, default=None, help="number of fresh-context skeptics (default: regime)")
    o.add_argument("--stakes", type=int, default=None, choices=[0, 1, 2], help="override the claim's stakes tier")
    o.add_argument("--no-lineup", action="store_true", help="do not build the decoy lineup even if the regime asks for one")
    o.add_argument("--seed", type=int, default=None, help="lineup seed (default: random)")

    lu = sub.add_parser("lineup", help="decoy lineup: build | unseal | status | verify")
    lu.add_argument("action", choices=["build", "unseal", "status", "verify"])
    lu.add_argument("--round", type=int, default=None)
    lu.add_argument("--decoys", type=int, default=None)
    lu.add_argument("--seed", type=int, default=None)
    lu.add_argument("--no-control", action="store_true")
    lu.add_argument("--item", default=None, help="verify: lineup item letter")
    lu.add_argument("--step", type=int, default=None, help="verify: the mutated step number")

    sc = sub.add_parser("score-lineup", help="score skeptic reports against the sealed lineup (exit 3 if any is inadmissible)")
    sc.add_argument("--round", type=int, default=None)
    sc.add_argument("--agent", default=None)

    c = sub.add_parser("close", aliases=["close-round"])
    c.add_argument("--round", type=int, required=True)

    b = sub.add_parser("commit-blind", help="seal the replicator's blind values and open stage B")
    b.add_argument("--round", type=int, required=True)
    b.add_argument("--file", required=True)

    w = sub.add_parser("waive", help="record a deliberate exception to a barrier denial")
    w.add_argument("--round", type=int, required=True)
    w.add_argument("--role", required=True)
    w.add_argument("--target", required=True)
    w.add_argument("--reason", required=True)

    s = sub.add_parser("status")
    s.add_argument("--round", type=int, default=None)

    k = sub.add_parser("check", aliases=["check-round"], help="phase-exit criteria for a round (exit 1 if unmet)")
    k.add_argument("--round", type=int, default=None)

    r = sub.add_parser("regime", help="print the review regime for a claim's stakes tier")
    r.add_argument("--claim", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, tok in enumerate(argv):
        if tok == "--campaign" and i + 1 < len(argv) and i != 0:
            argv = [tok, argv[i + 1]] + argv[:i] + argv[i + 2:]
            break
    args = build_parser().parse_args(argv)
    cdir: Path = CAMPAIGNS / args.campaign
    try:
        if args.cmd in ("open", "open-round"):
            round_n = args.round if args.round is not None else ((latest_round(cdir) or 0) + 1)
            m = barrier.open_round(cdir, round_n, args.claim, args.artifact, skeptics=args.skeptics,
                                   stakes=args.stakes, campaign=args.campaign)
            lineup_info = None
            if not args.no_lineup and int(m["regime"].get("decoys", 0)) > 0:
                from harness.review import lineup as L

                sealed = L.build_lineup(cdir, round_n, args.artifact[0], int(m["regime"]["decoys"]), seed=args.seed,
                                        control=bool(m["regime"].get("control", True)))
                lineup_info = {"items": sorted(sealed["items"]), "dir": f"reviews/round{round_n}/lineup/"}
                m = barrier.load_manifest(cdir, round_n)
            _print({"round": round_n, "regime": m["regime"], "roles": sorted(m["roles"]),
                    "deliverables": {k: v.get("deliverable") for k, v in m["roles"].items()},
                    "lineup": lineup_info, "manifest": str(barrier.manifest_path(cdir, round_n))})
            return 0
        if args.cmd == "lineup":
            from harness.review import lineup as L

            n = args.round if args.round is not None else latest_round(cdir)
            if n is None:
                print("no review rounds", file=sys.stderr)
                return 1
            if args.action == "build":
                m = barrier.load_manifest(cdir, n)
                k = args.decoys if args.decoys is not None else int(m["regime"].get("decoys", 2))
                sealed = L.build_lineup(cdir, n, m["artifacts"][0], k, seed=args.seed, control=not args.no_control)
                _print({"round": n, "items": sorted(sealed["items"]), "decoys": k, "dir": f"reviews/round{n}/lineup/"})
                return 0
            if args.action == "unseal":
                _print(L.unseal(cdir, n))
                return 0
            if args.action == "status":
                _print(L.status(cdir, n))
                return 0
            if args.action == "verify":
                if not args.item or args.step is None:
                    print("verify needs --item and --step", file=sys.stderr)
                    return 2
                problems = L.verify_semantic(cdir, n, args.item, args.step)
                for pr in problems:
                    print(f"- {pr}")
                return 1 if problems else 0
        if args.cmd == "score-lineup":
            from harness.review import lineup as L

            n = args.round if args.round is not None else latest_round(cdir)
            if n is None:
                print("no review rounds", file=sys.stderr)
                return 1
            scores = L.score_lineup(cdir, n, args.agent)
            _print([s.to_dict() for s in scores])
            if not scores:
                print("no skeptic reports to score", file=sys.stderr)
                return 1
            return 3 if any(not s.admissible for s in scores) else 0
        if args.cmd in ("close", "close-round"):
            barrier.close_round(cdir, args.round)
            print(f"round {args.round} closed")
            return 0
        if args.cmd == "commit-blind":
            _print(barrier.commit_blind(cdir, args.round, args.file))
            return 0
        if args.cmd == "waive":
            _print(barrier.waive(cdir, args.round, args.role, args.target, args.reason))
            return 0
        if args.cmd == "status":
            n = args.round if args.round is not None else latest_round(cdir)
            if n is None:
                print("(no review rounds)")
                return 0
            _print(barrier.round_status(cdir, n))
            return 0
        if args.cmd in ("check", "check-round"):
            n = args.round if args.round is not None else latest_round(cdir)
            if n is None:
                print("no review rounds", file=sys.stderr)
                return 1
            store = LedgerStore(cdir / "ledger.json", campaign=args.campaign)
            problems = barrier.check_round(cdir, n, store)
            if problems:
                for pr in problems:
                    print(f"- {pr}")
                return 1
            print(f"ok: round {n} passes all checks")
            return 0
        if args.cmd == "regime":
            store = LedgerStore(cdir / "ledger.json", campaign=args.campaign)
            claim = store.get(args.claim)
            reg = regime_for(claim.stakes, load_budgets(cdir))
            _print({"claim": claim.id, "stakes": claim.stakes, "regime": reg.model_dump(), "summary": reg.describe()})
            return 0
        return 2
    except (barrier.ReviewError, LedgerError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # LineupError and friends
        if type(exc).__name__ in ("LineupError", "RubricError"):
            print(str(exc), file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
