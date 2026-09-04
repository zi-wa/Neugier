"""`python -m harness lit <subcommand>` — literature search / fetch / bib CLI.

Subcommands: search, get, fetch, cache-path, verify-excerpt, excerpt, resolve,
checkbib, oeis-conjectures. Always prints UTF-8 JSON (ensure_ascii=False) to
stdout; diagnostics go to stderr.

``fetch`` writes the full text into the campaign cache
(``campaigns/<slug>/cache/<safe>.txt``; ``--out`` overrides) so that excerpts
recorded in the ledger can be verified against it (rule R5a).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.lit import arxiv, bib, cache, mathoverflow, oeis, openalex, sources, zbmath
from harness.lit.models import Paper


def _print_json(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _papers_to_json(papers: list[Paper]) -> list[dict]:
    return [p.model_dump() for p in papers]


def _campaign_dir(args: argparse.Namespace) -> Path | None:
    slug = getattr(args, "campaign", None)
    if slug:
        import harness

        return Path(harness.CAMPAIGNS) / slug
    return cache.active_campaign_dir()


def _out_dir(args: argparse.Namespace) -> Path | None:
    if getattr(args, "out", None):
        return Path(args.out)
    cdir = _campaign_dir(args)
    if cdir is not None:
        return cdir / "cache"
    return None


def _cmd_search(args: argparse.Namespace) -> int:
    engine = args.engine
    query = args.query
    max_results = args.max

    if engine == "arxiv":
        out = _papers_to_json(arxiv.search(query, max_results=max_results))
    elif engine == "openalex":
        out = _papers_to_json(openalex.search_works(query, per_page=max_results))
    elif engine == "zbmath":
        out = _papers_to_json(zbmath.search(query, results_per_page=max_results))
    elif engine == "oeis":
        out = oeis.search(query)[:max_results]
    elif engine == "mo":
        out = mathoverflow.search(query, pagesize=max_results)
    else:  # pragma: no cover - argparse choices already enforce this
        print(f"[harness.lit.cli] unknown engine: {engine}", file=sys.stderr)
        return 2

    _print_json(out)
    return 0


def _cmd_get(args: argparse.Namespace) -> int:
    ident = args.id
    paper = arxiv.get(ident)
    if paper is None:
        paper = openalex.get_work(ident)
    if paper is None:
        print(f"[harness.lit.cli] not found: {ident}", file=sys.stderr)
        return 1
    _print_json(paper.model_dump())
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    out_dir = _out_dir(args)
    if out_dir is None:
        print("[harness.lit.cli] no --out and no active campaign (campaigns/ACTIVE); give --out or --campaign", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = cache.fetch_to_cache(args.source_id, out_dir)
    if txt_path is None:
        print(f"[harness.lit.cli] could not fetch full text for {args.source_id}", file=sys.stderr)
        return 1
    with open(txt_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    meta = {
        "source_id": args.source_id,
        "kind": cache.kind_of(args.source_id),
        "safe_name": cache.safe_name(args.source_id),
        "txt_path": str(txt_path),
        "char_count": len(text),
    }
    _print_json(meta)
    return 0 if text.strip() else 1


def _cmd_cache_path(args: argparse.Namespace) -> int:
    path = cache.find_cached_text(args.source_id, _campaign_dir(args))
    if path is None:
        print(f"[harness.lit.cli] not cached: {args.source_id} (run `harness lit fetch {args.source_id}`)", file=sys.stderr)
        return 1
    print(str(path))
    return 0


def _cmd_verify_excerpt(args: argparse.Namespace) -> int:
    excerpt = args.excerpt
    if args.excerpt_file:
        with open(args.excerpt_file, "r", encoding="utf-8") as fh:
            excerpt = fh.read()
    check = cache.verify_excerpt(excerpt or "", args.source_id, _campaign_dir(args))
    _print_json(check.to_dict())
    return 0 if check.verified is True else 3


def _cmd_excerpt(args: argparse.Namespace) -> int:
    path = cache.find_cached_text(args.source_id, _campaign_dir(args))
    if path is None:
        out_dir = _out_dir(args)
        if out_dir is None:
            print("[harness.lit.cli] not cached and no --out/--campaign to fetch into", file=sys.stderr)
            return 2
        path = cache.fetch_to_cache(args.source_id, out_dir)
        if path is None:
            print(f"[harness.lit.cli] could not fetch full text for {args.source_id}", file=sys.stderr)
            return 1
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    excerpts = sources.find_excerpts(text, args.keywords, window=args.window)
    _print_json({"source_id": args.source_id, "txt_path": str(path), "excerpts": excerpts})
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    entry = bib.resolve(args.query)
    if entry is None:
        print(f"[harness.lit.cli] could not resolve: {args.query}", file=sys.stderr)
        return 1
    out = entry.model_dump()
    out["bibtex"] = bib.to_bibtex(entry)
    _print_json(out)
    return 0


def _cmd_checkbib(args: argparse.Namespace) -> int:
    result = bib.check_bib(args.path)
    _print_json(result)
    return 0 if result["ok"] else 1


def _cmd_oeis_conjectures(args: argparse.Namespace) -> int:
    entry = oeis.get(args.anumber)
    if entry is None:
        print(f"[harness.lit.cli] not found: {args.anumber}", file=sys.stderr)
        return 1
    out = {
        "anumber": entry.get("number"),
        "name": entry.get("name"),
        "keywords": oeis.keywords(entry),
        "conjectures": oeis.conjectures(entry),
    }
    _print_json(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness lit", description="literature search / fetch / bib tools"
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_search = sub.add_parser("search", help="search a literature engine")
    p_search.add_argument(
        "--engine", required=True, choices=["arxiv", "openalex", "zbmath", "oeis", "mo"]
    )
    p_search.add_argument("--max", type=int, default=25)
    p_search.add_argument("query")
    p_search.set_defaults(func=_cmd_search)

    p_get = sub.add_parser("get", help="fetch a single record by id (arXiv id, DOI, OpenAlex id)")
    p_get.add_argument("id")
    p_get.set_defaults(func=_cmd_get)

    p_fetch = sub.add_parser("fetch", help="fetch full text into the campaign cache (arXiv id, doi:, oeis:, url:)")
    p_fetch.add_argument("source_id")
    p_fetch.add_argument("--out", default=None, help="cache/output directory (default: campaigns/<active>/cache)")
    p_fetch.add_argument("--campaign", default=None, help="campaign slug (default: campaigns/ACTIVE)")
    p_fetch.set_defaults(func=_cmd_fetch)

    p_cp = sub.add_parser("cache-path", help="print the cached full-text path for a source id")
    p_cp.add_argument("source_id")
    p_cp.add_argument("--campaign", default=None)
    p_cp.set_defaults(func=_cmd_cache_path)

    p_ve = sub.add_parser("verify-excerpt", help="check that an excerpt occurs in the cached source text (exit 3 if not)")
    p_ve.add_argument("source_id")
    p_ve.add_argument("--excerpt", default=None)
    p_ve.add_argument("--excerpt-file", default=None)
    p_ve.add_argument("--campaign", default=None)
    p_ve.set_defaults(func=_cmd_verify_excerpt)

    p_excerpt = sub.add_parser("excerpt", help="find keyword excerpts in a cached (or fetched) source")
    p_excerpt.add_argument("source_id")
    p_excerpt.add_argument("--out", default=None, help="cache directory to fetch into if not cached")
    p_excerpt.add_argument("--campaign", default=None)
    p_excerpt.add_argument("--window", type=int, default=600)
    p_excerpt.add_argument("keywords", nargs="+")
    p_excerpt.set_defaults(func=_cmd_excerpt)

    p_resolve = sub.add_parser("resolve", help="resolve a query (arXiv id/DOI/title) to a BibEntry")
    p_resolve.add_argument("query")
    p_resolve.set_defaults(func=_cmd_resolve)

    p_checkbib = sub.add_parser("checkbib", help="re-resolve every entry in a .bib file")
    p_checkbib.add_argument("path")
    p_checkbib.set_defaults(func=_cmd_checkbib)

    p_oeis = sub.add_parser(
        "oeis-conjectures", help="extract conjecture-mentioning lines from an OEIS entry"
    )
    p_oeis.add_argument("anumber")
    p_oeis.set_defaults(func=_cmd_oeis_conjectures)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
