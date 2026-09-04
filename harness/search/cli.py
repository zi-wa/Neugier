"""`python -m harness evolve ...` — agent-driven evolutionary search CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import harness
from harness.search import evolve


def _load(args: argparse.Namespace) -> tuple[Path, evolve.EvolveConfig]:
    cdir = Path(args.dir) if getattr(args, "dir", None) else harness.CAMPAIGNS / args.campaign
    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = cdir / cfg_path
    cfg = evolve.EvolveConfig.model_validate_json(cfg_path.read_text(encoding="utf-8"))
    return cdir, cfg


def _out(obj: object) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness evolve", description="evolutionary program search with an exact, immutable scorer")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        g = sp.add_mutually_exclusive_group(required=True)
        g.add_argument("--campaign", help="campaign slug")
        g.add_argument("--dir", help="campaign directory (alternative to --campaign)")
        sp.add_argument("--config", required=True, help="config JSON (relative to the campaign dir or absolute)")

    s = sub.add_parser("init", help="hash the evaluator and seed the population"); common(s)
    s.add_argument("--force", action="store_true", help="discard an existing population")
    s = sub.add_parser("next", help="reserve children and write a proposal request for mutator agents"); common(s)
    s.add_argument("--n", type=int); s.add_argument("--seed", type=int)
    s = sub.add_parser("score", help="evaluate pending children and update elites"); common(s)
    s = sub.add_parser("status", help="best score, elites, history"); common(s)
    s = sub.add_parser("run", help="headless loop using `claude -p` as the mutation operator"); common(s)
    s.add_argument("--generations", type=int, default=5); s.add_argument("--model", default="sonnet")
    s = sub.add_parser("template", help="write an example config + evaluator + seed into DIR")
    s.add_argument("dir")
    return p


TEMPLATE_EVALUATOR = '''"""Example exact evaluator (OpenEvolve interface): maximize the size of a Sidon set inside {0..N-1}.

evaluate(program_path) imports the candidate program, calls its `construct(N)` which must return a list of ints,
verifies the Sidon property EXACTLY, and returns {"score": "<size>", "valid": bool, "exact": True, "features": {...}}.
"""
import importlib.util

N = 100

def evaluate(program_path):
    spec = importlib.util.spec_from_file_location("cand", program_path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    S = sorted(set(int(x) for x in mod.construct(N)))
    if any(x < 0 or x >= N for x in S):
        return {"score": None, "valid": False, "artifacts": "element out of range"}
    sums = set()
    for i, a in enumerate(S):
        for b in S[i:]:
            if a + b in sums:
                return {"score": None, "valid": False, "artifacts": f"not Sidon: repeated sum {a+b}"}
            sums.add(a + b)
    return {"score": str(len(S)), "valid": True, "exact": True,
            "features": {"density": len(S) / N, "maxgap": max((b - a for a, b in zip(S, S[1:])), default=0) / N},
            "artifacts": f"size={len(S)} min={S[0] if S else None} max={S[-1] if S else None}"}
'''

TEMPLATE_SEED = '''"""Seed program: greedy Sidon set. Mutators edit this file's logic (keep `construct(N)`)."""

def construct(N):
    S, sums = [], set()
    for x in range(N):
        new = {x + s for s in S} | {2 * x}
        if new & sums:
            continue
        S.append(x); sums |= new
    return S
'''


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.cmd == "template":
        d = Path(ns.dir); d.mkdir(parents=True, exist_ok=True)
        (d / "scorer.py").write_text(TEMPLATE_EVALUATOR, encoding="utf-8")
        (d / "seed.py").write_text(TEMPLATE_SEED, encoding="utf-8")
        cfg = evolve.EvolveConfig(name="sidon100", evaluator="experiments/evolve/scorer.py", seed_programs=["experiments/evolve/seed.py"],
                                  feature_keys=["density", "maxgap"], feature_ranges={"density": [0, 0.3], "maxgap": [0, 0.5]},
                                  generations=20, children_per_gen=6, known_best=None)
        (d / "sidon100.json").write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        _out({"written": [str(d / "scorer.py"), str(d / "seed.py"), str(d / "sidon100.json")],
              "note": "paths inside the config are relative to the campaign dir; place DIR at <campaign>/experiments/evolve"})
        return 0
    cdir, cfg = _load(ns)
    try:
        if ns.cmd == "init":
            st = evolve.init(cdir, cfg, force=ns.force)
            _out(evolve.status(cdir, cfg) | {"seeded": len(st.programs)})
        elif ns.cmd == "next":
            req = evolve.next_generation(cdir, cfg, n=ns.n, seed=ns.seed)
            _out(req)
        elif ns.cmd == "score":
            _out(evolve.score_pending(cdir, cfg))
        elif ns.cmd == "status":
            _out(evolve.status(cdir, cfg))
        elif ns.cmd == "run":
            _out(evolve.run_headless(cdir, cfg, ns.generations, model=ns.model))
    except RuntimeError as e:
        sys.stderr.write(f"[evolve] {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
