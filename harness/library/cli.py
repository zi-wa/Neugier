"""`python -m harness library ...` — cross-campaign memory CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import harness
from harness.library import memory


def _print_json(obj: object) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _split_csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness library", description="cross-campaign memory (append-only JSONL)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add-rejected", help="record a topic that was investigated and dropped")
    a.add_argument("--topic", required=True)
    a.add_argument("--reason", required=True)
    a.add_argument("--campaign")
    a.add_argument("--tags", help="comma-separated")

    r = sub.add_parser("add-result", help="record a finished campaign")
    r.add_argument("--campaign", required=True)
    r.add_argument("--title", required=True)
    r.add_argument("--outcome", required=True,
                   choices=["autonomous-new-result", "partial", "rediscovery", "literature-find", "negative"])
    r.add_argument("--claims-json", help="path to a JSON list of {id, statement, status}")
    r.add_argument("--paper", help="path to the paper PDF/TeX")

    f = sub.add_parser("add-fact", help="record an excerpt-anchored literature fact (deduped, excerpt verified against the cache)")
    f.add_argument("--statement", required=True)
    f.add_argument("--source-id", required=True)
    f.add_argument("--excerpt", required=True)
    f.add_argument("--locator")
    f.add_argument("--campaign", help="campaign slug whose cache/ holds the fetched source text")
    f.add_argument("--unverified-ok", action="store_true",
                   help="record the fact even if the excerpt is not found in a cached source (stored as unverified)")

    s = sub.add_parser("search", help="search a store")
    s.add_argument("store", choices=["rejected", "results", "facts"])
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)

    ls = sub.add_parser("list", help="dump a store")
    ls.add_argument("store", choices=["rejected", "results", "facts"])

    c = sub.add_parser("check-rejected", help="fuzzy-check whether a topic was already rejected")
    c.add_argument("topic")
    c.add_argument("--threshold", type=float, default=0.8)
    return p


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.cmd == "add-rejected":
        _print_json(memory.add_rejected(ns.topic, ns.reason, campaign=ns.campaign, tags=_split_csv(ns.tags)))
    elif ns.cmd == "add-result":
        claims = None
        if ns.claims_json:
            claims = json.loads(Path(ns.claims_json).read_text(encoding="utf-8"))
        _print_json(memory.add_result(ns.campaign, ns.title, ns.outcome, claims=claims, paper_path=ns.paper))
    elif ns.cmd == "add-fact":
        campaign_dir = (Path(harness.CAMPAIGNS) / ns.campaign) if ns.campaign else None
        try:
            rec = memory.add_fact(
                ns.statement, ns.source_id, ns.excerpt, locator=ns.locator, campaign=ns.campaign,
                campaign_dir=campaign_dir, require_verified=not ns.unverified_ok,
            )
        except memory.FactUnverified as exc:
            print(f"[harness.library] {exc}", file=sys.stderr)
            return 1
        _print_json(rec if rec is not None else {"deduped": True})
    elif ns.cmd == "search":
        _print_json(memory.search(ns.store, ns.query, limit=ns.limit))
    elif ns.cmd == "list":
        _print_json(memory.all(ns.store))
    elif ns.cmd == "check-rejected":
        hit = memory.is_rejected(ns.topic, threshold=ns.threshold)
        _print_json(hit if hit is not None else {"rejected": False})
        return 3 if hit is not None else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
