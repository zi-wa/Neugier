"""`python -m harness <command>` — thin dispatcher; subcommands live in their modules."""
from __future__ import annotations

import argparse
import sys

COMMANDS = {
    # name: (module, help)
    "lit": ("harness.lit.cli", "literature search / fetch / bib tools"),
    "ledger": ("harness.ledger.cli", "claim ledger operations"),
    "falsify": ("harness.verify.cli", "numeric/symbolic falsification harness"),
    "evolve": ("harness.search.cli", "evolutionary program search"),
    "paper": ("harness.paper.cli", "build / check / repro appendix for the LaTeX paper"),
    "library": ("harness.library.cli", "cross-campaign memory (rejected topics, results, facts, questions)"),
    "campaign": ("harness.campaign", "create / inspect campaigns"),
    "questions": ("harness.questions", "curiosity engine: rank open questions, log surprises/detours, escalate to humans"),
    "review": ("harness.review.cli", "review rounds: barrier manifests, blind commits, lineups, round checks"),
    "proof": ("harness.proof.cli", "proof-artifact linter (proof-standards.md) and coverage"),
    "ideas": ("harness.ideas", "attack routes in ideas.md: list, near-duplicate detection, proximity graph"),
    "prove": ("harness.prove.cli", "sketch tournament: Elo ratings and full-proof selection"),
    "doctor": ("harness.doctor", "environment and wiring checks (venv, tectonic, hooks, links, engines)"),
    "headless": ("harness.headless", "drive a campaign with repeated `claude -p` iterations"),
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="harness", description="Neugier harness CLI")
    parser.add_argument("command", choices=sorted(COMMANDS), help="subcommand")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)
    module_name, _ = COMMANDS[ns.command]
    import importlib

    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError as e:  # pragma: no cover
        print(f"[harness] subcommand '{ns.command}' not implemented yet ({e})", file=sys.stderr)
        return 2
    return int(mod.main(ns.args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
