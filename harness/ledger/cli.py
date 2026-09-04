"""`python -m harness ledger ...` — claim ledger CLI.

Operates on ``campaigns/<slug>/ledger.json``. Every subcommand takes
``--campaign SLUG``. On a :class:`~harness.ledger.ledger.LedgerError` the
message is printed to stderr and the process exits with status 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import CAMPAIGNS
from harness.ledger.ledger import LedgerError, LedgerStore
from harness.ledger.schema import Claim, Evidence


def _campaign_dir(slug: str) -> Path:
    return CAMPAIGNS / slug


def _ledger_path(slug: str) -> Path:
    return _campaign_dir(slug) / "ledger.json"


def _print_json(obj) -> None:
    if isinstance(obj, Claim):
        obj = obj.model_dump(mode="json")
    elif isinstance(obj, list):
        obj = [x.model_dump(mode="json") if isinstance(x, Claim) else x for x in obj]
    print(json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False))


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness ledger")
    parser.add_argument("--campaign", required=True, help="campaign slug")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create an empty ledger for the campaign")

    p_add = sub.add_parser("add", help="add a new claim")
    p_add.add_argument("--kind", required=True)
    p_add.add_argument("--statement", required=True)
    p_add.add_argument("--depends", default="", help="comma-separated claim ids")
    p_add.add_argument("--tags", default="", help="comma-separated tags")
    p_add.add_argument("--status", default="idea")
    p_add.add_argument("--notes", default="")

    p_ev = sub.add_parser("evidence", help="attach evidence to a claim")
    p_ev.add_argument("id")
    p_ev.add_argument("--type", required=True, dest="type_")
    p_ev.add_argument("--path", default=None)
    p_ev.add_argument("--summary", default="")
    p_ev.add_argument("--source-id", default=None)
    p_ev.add_argument("--excerpt", default=None)
    p_ev.add_argument("--excerpt-file", default=None)
    p_ev.add_argument("--locator", default=None)
    p_ev.add_argument("--role", default=None)
    p_ev.add_argument("--verdict", default=None)
    p_ev.add_argument("--round", default=None, type=int)

    p_promote = sub.add_parser("promote", help="promote/demote a claim's status")
    p_promote.add_argument("id")
    p_promote.add_argument("status")

    p_update = sub.add_parser("update", help="edit a claim's statement")
    p_update.add_argument("id")
    p_update.add_argument("--statement", required=True)

    p_show = sub.add_parser("show", help="print a claim, or the whole ledger, as JSON")
    p_show.add_argument("id", nargs="?", default=None)

    sub.add_parser("md", help="print the ledger as a markdown table")
    sub.add_parser("assertable", help="list claims the paper may assert as theorems")
    sub.add_parser("summary", help="print counts by status/kind")
    sub.add_parser("check", help="verify evidence file hashes are unchanged")
    sub.add_parser("graph", help="print the dependency DAG")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # allow `--campaign SLUG` anywhere (e.g. after the subcommand): move it to the front
    for i, tok in enumerate(argv):
        if tok == "--campaign" and i + 1 < len(argv) and i != 0:
            argv = [tok, argv[i + 1]] + argv[:i] + argv[i + 2:]
            break
        if tok.startswith("--campaign=") and i != 0:
            argv = [tok] + argv[:i] + argv[i + 1:]
            break
    args = build_parser().parse_args(argv)
    campaign_dir = _campaign_dir(args.campaign)
    ledger_path = _ledger_path(args.campaign)

    try:
        if args.cmd == "init":
            campaign_dir.mkdir(parents=True, exist_ok=True)
            store = LedgerStore(ledger_path, campaign=args.campaign)
            store.save()
            print(f"initialized ledger at {ledger_path}")
            return 0

        store = LedgerStore(ledger_path, campaign=args.campaign)

        if args.cmd == "add":
            claim = store.add(
                kind=args.kind,
                statement=args.statement,
                depends_on=_split_csv(args.depends),
                tags=_split_csv(args.tags),
                status=args.status,
                notes=args.notes,
            )
            _print_json(claim)
            return 0

        if args.cmd == "evidence":
            excerpt = args.excerpt
            if args.excerpt_file:
                with open(args.excerpt_file, "r", encoding="utf-8") as fh:
                    excerpt = fh.read()
            evidence = Evidence(
                type=args.type_,
                path=args.path,
                summary=args.summary,
                source_id=args.source_id,
                excerpt=excerpt,
                locator=args.locator,
                role=args.role,
                verdict=args.verdict,
                round=args.round,
            )
            claim = store.add_evidence(args.id, evidence, campaign_dir)
            _print_json(claim)
            return 0

        if args.cmd == "promote":
            claim = store.promote(args.id, args.status, campaign_dir)
            _print_json(claim)
            return 0

        if args.cmd == "update":
            claim = store.update_statement(args.id, args.statement)
            _print_json(claim)
            return 0

        if args.cmd == "show":
            if args.id:
                _print_json(store.get(args.id))
            else:
                _print_json(store.ledger.model_dump(mode="json"))
            return 0

        if args.cmd == "md":
            print(store.to_markdown())
            return 0

        if args.cmd == "assertable":
            _print_json(store.assertable())
            return 0

        if args.cmd == "summary":
            _print_json(store.summary())
            return 0

        if args.cmd == "check":
            problems = store.check_integrity(campaign_dir)
            if problems:
                for p in problems:
                    print(p, file=sys.stderr)
                return 1
            print("ok: all evidence file hashes match")
            return 0

        if args.cmd == "graph":
            dag = store.dag()
            for cid in store.topological_order():
                node = dag[cid]
                print(f"{cid} [{node['kind']}/{node['status']}] depends_on={node['depends_on']}")
            return 0

        return 2
    except LedgerError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
