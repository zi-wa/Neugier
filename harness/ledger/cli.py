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
from harness.ledger.ledger import REPAIR_OPS, LedgerError, LedgerStore, load_budgets
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

    p_add = sub.add_parser("add", help="add a new claim (status idea|conjectured; known-in-literature needs an excerpt)")
    p_add.add_argument("--kind", required=True)
    p_add.add_argument("--statement", required=True)
    p_add.add_argument("--depends", default="", help="comma-separated claim ids")
    p_add.add_argument("--tags", default="", help="comma-separated tags")
    p_add.add_argument("--status", default="idea", help="idea | conjectured | known-in-literature (with --source-id/--excerpt)")
    p_add.add_argument("--notes", default="")
    p_add.add_argument("--stakes", type=int, default=None, choices=[0, 1, 2], help="0 routine, 1 standard, 2 extraordinary")
    p_add.add_argument("--source-id", default=None, help="excerpt source id (for --status known-in-literature)")
    p_add.add_argument("--excerpt", default=None)
    p_add.add_argument("--excerpt-file", default=None)
    p_add.add_argument("--locator", default=None)
    p_add.add_argument("--unverified-ok", action="store_true", help="record the excerpt even if it is not found in the cached source")
    p_add.add_argument("--repaired-from", default=None, help="id of the refuted parent this conjecture repairs")
    p_add.add_argument("--repair-op", default=None, choices=list(REPAIR_OPS))

    p_ev = sub.add_parser("evidence", help="attach evidence to a claim")
    p_ev.add_argument("id")
    p_ev.add_argument("--type", required=True, dest="type_")
    p_ev.add_argument("--path", default=None)
    p_ev.add_argument("--summary", default="")
    p_ev.add_argument("--source-id", default=None)
    p_ev.add_argument("--excerpt", default=None)
    p_ev.add_argument("--excerpt-file", default=None)
    p_ev.add_argument("--locator", default=None)
    p_ev.add_argument("--unverified-ok", action="store_true", help="record an excerpt that cannot be verified (does not count toward known-in-literature)")
    p_ev.add_argument("--role", default=None)
    p_ev.add_argument("--verdict", default=None, help="pass | fail | revise | n/a (replicator only)")
    p_ev.add_argument("--round", default=None, type=int)
    p_ev.add_argument("--agent-id", default=None, help="fresh-context id of the referee (e.g. SK-3f9a1c)")
    p_ev.add_argument("--reliability", default=None, type=float, help="lineup reliability in [0,1]")
    adm = p_ev.add_mutually_exclusive_group()
    adm.add_argument("--admissible", dest="admissible", action="store_true", default=None)
    adm.add_argument("--inadmissible", dest="admissible", action="store_false")
    p_ev.add_argument("--lineup-item", default=None)

    p_promote = sub.add_parser("promote", help="promote/demote a claim's status")
    p_promote.add_argument("id")
    p_promote.add_argument("status")
    p_promote.add_argument("--no-lint", action="store_true", help="skip the proof-artifact linter when promoting to proof-drafted")

    p_update = sub.add_parser("update", help="edit a claim's statement and/or stakes")
    p_update.add_argument("id")
    p_update.add_argument("--statement", default=None)
    p_update.add_argument("--stakes", type=int, default=None, choices=[0, 1, 2])

    p_rev = sub.add_parser("reverify", help="clear 'stale' after a fresh complete referee round")
    p_rev.add_argument("id")

    p_cred = sub.add_parser("credence", help="pre-register a credence on a claim (immutable history entry)")
    p_cred.add_argument("id")
    p_cred.add_argument("--role", required=True, help="who predicts: strategist | prover | experimentalist | …")
    p_cred.add_argument("--why", required=True, help="one-line rationale")
    p_cred.add_argument("--p-true", type=float, default=None, dest="p_true")
    p_cred.add_argument("--p-budget", type=float, default=None, dest="p_budget")
    p_cred.add_argument("--p-pass", type=float, default=None, dest="p_pass")
    p_cred.add_argument("--round", type=int, default=None)
    p_cred.add_argument("--panel", default=None, help="persona credences, e.g. skeptic=0.2,optimist=0.6,base-rate=0.3")

    p_rep = sub.add_parser("repair", help="build a counterexample-guided repair request for a refuted claim")
    p_rep.add_argument("id")

    p_cal = sub.add_parser("calibration", help="Brier scores of pre-registered credences against resolved claims")
    p_cal.add_argument("--final", action="store_true", help="treat unresolved claims as not reached within budget and append to library/calibration.jsonl")

    p_attest = sub.add_parser("attest", help="record a HUMAN sign-off on a claim (agents are denied by hook)")
    p_attest.add_argument("id")
    p_attest.add_argument("--human", required=True)
    p_attest.add_argument("--note", default="")

    p_show = sub.add_parser("show", help="print a claim, or the whole ledger, as JSON")
    p_show.add_argument("id", nargs="?", default=None)

    sub.add_parser("md", help="print the ledger as a markdown table")
    sub.add_parser("assertable", help="list claims the paper may assert as theorems")
    sub.add_parser("summary", help="print counts by status/kind")
    sub.add_parser("check", help="verify evidence file hashes are unchanged")
    sub.add_parser("graph", help="print the dependency DAG")

    return parser


def _read_excerpt(args) -> str | None:
    excerpt = args.excerpt
    if getattr(args, "excerpt_file", None):
        with open(args.excerpt_file, "r", encoding="utf-8") as fh:
            excerpt = fh.read()
    return excerpt


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
            if args.kind in ("lemma", "proposition", "theorem", "conjecture", "target"):
                for hit in store.near_duplicates(args.statement):
                    print(f"[ledger] near-duplicate ({hit['where']} {hit['id']}, similarity {hit['score']}): {hit['statement'][:100]}",
                          file=sys.stderr)
            evidence = None
            excerpt = _read_excerpt(args)
            if args.source_id or excerpt:
                evidence = Evidence(
                    type="excerpt", source_id=args.source_id, excerpt=excerpt, locator=args.locator,
                    summary="excerpt recorded at claim creation",
                )
            claim = store.add(
                kind=args.kind,
                statement=args.statement,
                depends_on=_split_csv(args.depends),
                tags=_split_csv(args.tags),
                status=args.status,
                notes=args.notes,
                evidence=evidence,
                campaign_dir=campaign_dir,
                repaired_from=args.repaired_from,
                repair_op=args.repair_op,
                stakes=args.stakes,
                require_verified_excerpt=not args.unverified_ok,
            )
            _print_json(claim)
            return 0

        if args.cmd == "evidence":
            if args.round is not None:
                cap = load_budgets(campaign_dir).get("max_review_rounds")
                if isinstance(cap, int) and args.round > cap:
                    raise LedgerError(
                        f"round {args.round} exceeds budgets.max_review_rounds={cap}; the judge must PIVOT or downgrade "
                        "instead of extending rounds"
                    )
            evidence = Evidence(
                type=args.type_,
                path=args.path,
                summary=args.summary,
                source_id=args.source_id,
                excerpt=_read_excerpt(args),
                locator=args.locator,
                role=args.role,
                verdict=args.verdict,
                round=args.round,
                agent_id=args.agent_id,
                reliability=args.reliability,
                admissible=args.admissible,
                lineup_item=args.lineup_item,
            )
            claim = store.add_evidence(args.id, evidence, campaign_dir, require_verified_excerpt=not args.unverified_ok)
            _print_json(claim)
            return 0

        if args.cmd == "promote":
            if args.status == "proof-drafted" and not args.no_lint:
                from harness.proof.lint import lint_claim_proofs

                failed = [r for r in lint_claim_proofs(store, campaign_dir, args.id) if not r.ok]
                if failed:
                    for r in failed:
                        print(f"proof check FAILED for {r.path}:", file=sys.stderr)
                        for e in r.errors:
                            print(f"  [ERROR {e.code}] {e.message}", file=sys.stderr)
                    raise LedgerError(f"cannot promote {args.id} to proof-drafted: the proof artifact fails `harness proof check`")
            claim = store.promote(args.id, args.status, campaign_dir)
            _print_json(claim)
            return 0

        if args.cmd == "update":
            if args.statement is None and args.stakes is None:
                raise LedgerError("update needs --statement and/or --stakes")
            claim = store.get(args.id)
            if args.statement is not None:
                claim = store.update_statement(args.id, args.statement)
            if args.stakes is not None:
                claim = store.set_stakes(args.id, args.stakes)
            _print_json(claim)
            return 0

        if args.cmd == "reverify":
            _print_json(store.reverify(args.id))
            return 0

        if args.cmd == "credence":
            panel = None
            if args.panel:
                panel = {}
                for item in args.panel.split(","):
                    if "=" not in item:
                        raise LedgerError(f"--panel expects name=p entries, got {item!r}")
                    k, v = item.split("=", 1)
                    panel[k.strip()] = float(v)
            entry = store.record_credence(args.id, role=args.role, why=args.why, p_true=args.p_true, p_budget=args.p_budget,
                                          p_pass=args.p_pass, round=args.round, panel=panel)
            _print_json(entry)
            return 0

        if args.cmd == "repair":
            from harness.ledger.repair import build_request

            request = build_request(store, args.id, campaign_dir)
            _print_json(request)
            print(f"repair request written to experiments/repair/{args.id}.json", file=sys.stderr)
            return 0

        if args.cmd == "calibration":
            from harness.ledger.calibration import append_to_library, compute, write_report

            report = compute(store, args.campaign, final=args.final)
            write_report(campaign_dir, report)
            if args.final:
                append_to_library(report)
            _print_json(json.loads(report.model_dump_json(exclude={"rows"})))
            return 0

        if args.cmd == "attest":
            _print_json(store.attest(args.id, args.human, args.note))
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
