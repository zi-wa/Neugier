"""``python -m harness paper <build|check|repro|init|all>``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _resolve_paper_dir(args: argparse.Namespace) -> Path:
    from harness import CAMPAIGNS

    if getattr(args, "dir", None):
        return Path(args.dir)
    return CAMPAIGNS / args.campaign / "paper"


def _print_report(report) -> None:  # report: harness.paper.check.CheckReport
    status = "OK" if report.ok else "FAILED"
    print(f"check: {status}  ({len(report.errors)} error(s), {len(report.warnings)} warning(s))")
    for issue in report.errors:
        loc = f" line {issue.line}" if issue.line is not None else ""
        print(f"  [ERROR {issue.code}]{loc} {issue.message}")
        if issue.context:
            print(f"      context: {issue.context}")
    for issue in report.warnings:
        loc = f" line {issue.line}" if issue.line is not None else ""
        print(f"  [WARN  {issue.code}]{loc} {issue.message}")
        if issue.context:
            print(f"      context: {issue.context}")


def cmd_build(args: argparse.Namespace) -> int:
    from harness.paper.build import build

    paper_dir = _resolve_paper_dir(args)
    result = build(paper_dir)
    print(f"build: {'OK' if result.ok else 'FAILED'}  engine={result.engine}  seconds={result.seconds:.1f}")
    if result.pdf is not None:
        print(f"  pdf: {result.pdf}")
    if not result.ok:
        tail = "\n".join(result.log.splitlines()[-40:])
        print(tail)
    return 0 if result.ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    from harness.paper.check import check

    paper_dir = _resolve_paper_dir(args)
    report = check(paper_dir, strict=args.strict)
    _print_report(report)
    return 0 if report.ok else 1


def cmd_repro(args: argparse.Namespace) -> int:
    from harness import CAMPAIGNS
    from harness.paper.repro import write_appendix

    from harness.paper.questions_tex import write_questions_appendix

    out = write_appendix(CAMPAIGNS / args.campaign)
    print(f"wrote {out}")
    out2 = write_questions_appendix(CAMPAIGNS / args.campaign)
    print(f"wrote {out2}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from harness import CAMPAIGNS
    from harness.paper.build import render_template

    paper_dir = CAMPAIGNS / args.campaign / "paper"
    default_tools = (
        "This paper was produced with assistance from the Neugier autonomous "
        "research harness; see the reproducibility appendix for tool versions and "
        "computed quantities."
    )
    out = render_template(
        paper_dir,
        title=args.title,
        author=args.author,
        abstract=args.abstract if args.abstract is not None else "",
        body=args.body if args.body is not None else "% TODO: write the body of the paper.\n",
        tools=args.tools if args.tools is not None else default_tools,
        date=args.date,
        force=args.force,
    )
    print(f"wrote {out}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    from harness import CAMPAIGNS
    from harness.paper.build import build
    from harness.paper.check import check
    from harness.paper.repro import write_appendix

    campaign_dir = CAMPAIGNS / args.campaign
    paper_dir = campaign_dir / "paper"

    from harness.paper.questions_tex import write_questions_appendix

    write_appendix(campaign_dir)
    write_questions_appendix(campaign_dir)

    build_result = build(paper_dir)
    print(f"build: {'OK' if build_result.ok else 'FAILED'}  engine={build_result.engine}  seconds={build_result.seconds:.1f}")
    if build_result.pdf is not None:
        print(f"  pdf: {build_result.pdf}")

    report = check(paper_dir, strict=args.strict)
    _print_report(report)

    return 0 if (build_result.ok and report.ok) else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="harness paper", description="LaTeX paper build / check / repro toolchain")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="compile the paper with tectonic")
    g_build = p_build.add_mutually_exclusive_group(required=True)
    g_build.add_argument("--campaign", help="campaign slug under campaigns/")
    g_build.add_argument("--dir", help="paper directory (overrides --campaign)")
    p_build.set_defaults(func=cmd_build)

    p_check = sub.add_parser("check", help="lint the paper (labels, cites, claims, numbers, hedges)")
    g_check = p_check.add_mutually_exclusive_group(required=True)
    g_check.add_argument("--campaign", help="campaign slug under campaigns/")
    g_check.add_argument("--dir", help="paper directory (overrides --campaign)")
    p_check.add_argument("--strict", action="store_true", help="treat hedge-word findings as errors")
    p_check.set_defaults(func=cmd_check)

    p_repro = sub.add_parser("repro", help="write paper/appendix-repro.tex")
    p_repro.add_argument("--campaign", required=True, help="campaign slug under campaigns/")
    p_repro.set_defaults(func=cmd_repro)

    p_init = sub.add_parser("init", help="render the amsart template into a campaign's paper/")
    p_init.add_argument("--campaign", required=True)
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--author", required=True)
    p_init.add_argument("--abstract", default=None)
    p_init.add_argument("--body", default=None)
    p_init.add_argument("--tools", default=None)
    p_init.add_argument("--date", default=None)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_all = sub.add_parser("all", help="repro -> build -> check")
    p_all.add_argument("--campaign", required=True)
    p_all.add_argument("--strict", action="store_true")
    p_all.set_defaults(func=cmd_all)

    ns = parser.parse_args(argv)
    return int(ns.func(ns) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
