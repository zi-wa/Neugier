"""Agent-driven evolutionary program search with an exact, immutable scorer.

Design (AlphaEvolve/OpenEvolve-style, without an LLM API key):

* The **scorer** is a Python file exposing ``evaluate(program_path: str) -> dict`` — the OpenEvolve evaluator interface —
  returning at least ``{"score": <number or "p/q" string>, "valid": bool}`` and optionally ``"features": {name: number}``
  (used for MAP-Elites bins), ``"artifacts": str`` (stderr/notes fed back to mutators) and ``"exact": bool``.
  Its sha256 is recorded at ``init`` and re-checked at every ``score`` (rule: verifiers are immutable during Explore).
* The **population** is a JSONL database under ``<campaign>/experiments/evolve/<name>/`` with one row per program.
* **Mutation is done by agents**, not here: ``next()`` writes a *proposal request* (parents' code, scores, artifacts, a mutation
  prompt) and reserves child paths; the orchestrating skill spawns cheap subagents that write the children; ``score()`` then
  evaluates every pending child with a timeout and updates the elites. ``run_headless()`` can drive ``claude -p`` instead.
* **Exactness**: scores given as ``"p/q"`` strings are compared as ``fractions.Fraction``; float scores are compared with a
  configurable ``noise_floor`` and flagged ``needs_exact_verification``.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# config / records
# --------------------------------------------------------------------------


class EvolveConfig(BaseModel):
    name: str
    evaluator: str                      # path relative to campaign dir, e.g. experiments/evolve/scorer.py
    seed_programs: list[str] = []       # paths relative to campaign dir
    maximize: bool = True
    generations: int = 50
    children_per_gen: int = 6
    parents_per_child: int = 2          # 1 = mutation, 2 = crossover-style inspiration
    elite_size: int = 20
    feature_keys: list[str] = []        # MAP-Elites: names in evaluate()["features"]
    feature_bins: int = 5               # bins per feature (quantile-free: fixed ranges from feature_ranges)
    feature_ranges: dict[str, list[float]] = {}   # name -> [lo, hi]
    eval_timeout: float = 120.0
    noise_floor: float = 0.0            # float scores must beat the best by more than this
    known_best: str | float | None = None   # from the survey (excerpt-backed); "p/q" or float
    mutation_prompt: str = (
        "You are a mutation operator in an evolutionary search for a mathematical construction. "
        "Read the parent program(s) and their scores/artifacts. Write ONE child program that keeps the same interface "
        "and makes a small, purposeful change likely to improve the score (change a parameter, a construction rule, a "
        "symmetry, a search heuristic). Prefer exact arithmetic. Do not touch the evaluator. Save it to the child path."
    )


class Program(BaseModel):
    id: str
    gen: int
    path: str                     # relative to campaign dir
    parent_ids: list[str] = []
    score: str | float | None = None   # "p/q" for exact, float otherwise
    valid: bool = False
    exact: bool = False
    features: dict[str, float] = {}
    bin_key: str = ""
    artifacts: str = ""
    error: str | None = None
    seconds: float = 0.0
    created: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    needs_exact_verification: bool = False


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def to_number(s: str | float | int | None) -> Fraction | float | None:
    if s is None:
        return None
    if isinstance(s, (int, Fraction)):
        return Fraction(s)
    if isinstance(s, float):
        return s
    st = str(s).strip()
    try:
        return Fraction(st)
    except (ValueError, ZeroDivisionError):
        return float(st)


def better(a: str | float | None, b: str | float | None, maximize: bool, noise_floor: float = 0.0) -> bool:
    """Is score a better than score b? Exact if both rational; noise floor applies to floats."""
    if a is None:
        return False
    if b is None:
        return True
    x, y = to_number(a), to_number(b)
    if isinstance(x, Fraction) and isinstance(y, Fraction):
        return x > y if maximize else x < y
    fx, fy = float(x), float(y)
    return (fx - fy) > noise_floor if maximize else (fy - fx) > noise_floor


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------


@dataclass
class EvolveStore:
    campaign_dir: Path
    config: EvolveConfig
    programs: dict[str, Program] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return self.campaign_dir / "experiments" / "evolve" / self.config.name

    @property
    def db_path(self) -> Path:
        return self.root / "population.jsonl"

    @property
    def meta_path(self) -> Path:
        return self.root / "meta.json"

    # ---- persistence ----
    @classmethod
    def load(cls, campaign_dir: Path, config: EvolveConfig) -> "EvolveStore":
        st = cls(campaign_dir=Path(campaign_dir), config=config)
        if st.db_path.exists():
            for line in st.db_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    p = Program.model_validate_json(line)
                    st.programs[p.id] = p
        if st.meta_path.exists():
            st.meta = json.loads(st.meta_path.read_text(encoding="utf-8"))
        return st

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.db_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for p in self.programs.values():
                f.write(p.model_dump_json() + "\n")
        os.replace(tmp, self.db_path)
        self.meta_path.write_text(json.dumps(self.meta, indent=2, sort_keys=True), encoding="utf-8")

    # ---- evaluator integrity ----
    def evaluator_path(self) -> Path:
        return self.campaign_dir / self.config.evaluator

    def check_evaluator(self) -> None:
        h = sha256_file(self.evaluator_path())
        if self.meta.get("evaluator_sha256") and self.meta["evaluator_sha256"] != h:
            raise RuntimeError(
                f"evaluator {self.config.evaluator} changed since init (hash {self.meta['evaluator_sha256'][:12]} -> {h[:12]}). "
                "Verifiers are immutable during Explore: write a new versioned scorer and re-init."
            )

    # ---- population ----
    def new_id(self) -> str:
        n = self.meta.get("counter", 0) + 1
        self.meta["counter"] = n
        return f"p{n:05d}"

    def bin_of(self, features: dict[str, float]) -> str:
        if not self.config.feature_keys:
            return "all"
        parts = []
        for k in self.config.feature_keys:
            lo, hi = self.config.feature_ranges.get(k, [0.0, 1.0])
            v = features.get(k, lo)
            frac = 0.0 if hi <= lo else min(max((v - lo) / (hi - lo), 0.0), 0.999999)
            parts.append(f"{k}={int(frac * self.config.feature_bins)}")
        return "|".join(parts)

    def elites(self) -> dict[str, Program]:
        best: dict[str, Program] = {}
        for p in self.programs.values():
            if not p.valid:
                continue
            cur = best.get(p.bin_key)
            if cur is None or better(p.score, cur.score, self.config.maximize):
                best[p.bin_key] = p
        return best

    def best(self) -> Program | None:
        b: Program | None = None
        for p in self.programs.values():
            if p.valid and (b is None or better(p.score, b.score, self.config.maximize)):
                b = p
        return b

    def ranked(self) -> list[Program]:
        valid = [p for p in self.programs.values() if p.valid]

        def key(p: Program):
            v = to_number(p.score)
            fv = float(v) if v is not None else float("-inf")
            return fv if self.config.maximize else -fv

        return sorted(valid, key=key, reverse=True)

    def select_parents(self, k: int, rng: random.Random) -> list[Program]:
        """Power-law over rank among elites (bins) plus top-ranked programs; k distinct if possible."""
        pool = list(self.elites().values())
        for p in self.ranked()[: self.config.elite_size]:
            if p not in pool:
                pool.append(p)
        if not pool:
            return []
        pool = sorted(pool, key=lambda p: -(float(to_number(p.score)) if self.config.maximize else -float(to_number(p.score))))
        chosen: list[Program] = []
        weights = [1.0 / (i + 1) ** 1.5 for i in range(len(pool))]
        tries = 0
        while len(chosen) < k and tries < 50 * k:
            tries += 1
            c = rng.choices(pool, weights=weights, k=1)[0]
            if c not in chosen:
                chosen.append(c)
        return chosen


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------

_EVAL_SNIPPET = r"""
import importlib.util, json, sys, traceback
ev_path, prog_path = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("evaluator", ev_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
try:
    res = mod.evaluate(prog_path)
    if not isinstance(res, dict):
        res = {"score": res, "valid": True}
    res.setdefault("valid", res.get("score") is not None)
    print("__EVOLVE_RESULT__" + json.dumps(res, default=str))
except Exception:
    print("__EVOLVE_RESULT__" + json.dumps({"score": None, "valid": False, "error": traceback.format_exc()[-2000:]}))
"""


def evaluate_program(store: EvolveStore, program: Program) -> Program:
    """Run the evaluator on one program in a subprocess with a timeout; fill in the Program record."""
    store.check_evaluator()
    py = sys.executable
    t0 = time.monotonic()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            [py, "-c", _EVAL_SNIPPET, str(store.evaluator_path()), str(store.campaign_dir / program.path)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=store.config.eval_timeout,
            cwd=str(store.campaign_dir), env=env,
        )
        out = proc.stdout or ""
        marker = out.rfind("__EVOLVE_RESULT__")
        if marker < 0:
            program.valid = False
            program.error = (proc.stderr or out)[-2000:] or "evaluator produced no result"
        else:
            res = json.loads(out[marker + len("__EVOLVE_RESULT__"):].strip().splitlines()[0])
            program.valid = bool(res.get("valid")) and res.get("score") is not None
            program.score = res.get("score")
            if isinstance(program.score, (int, Fraction)):
                program.score = str(Fraction(program.score))
            program.exact = bool(res.get("exact", isinstance(program.score, str)))
            program.features = {k: float(v) for k, v in (res.get("features") or {}).items()}
            program.artifacts = str(res.get("artifacts") or "")[-4000:] + ((proc.stderr or "")[-1000:])
            program.error = res.get("error")
            program.bin_key = store.bin_of(program.features)
            program.needs_exact_verification = program.valid and not program.exact
    except subprocess.TimeoutExpired:
        program.valid = False
        program.error = f"timeout after {store.config.eval_timeout}s"
    program.seconds = time.monotonic() - t0
    return program


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------


def init(campaign_dir: Path, config: EvolveConfig, force: bool = False) -> EvolveStore:
    store = EvolveStore.load(campaign_dir, config)
    if store.programs and not force:
        return store
    if force:
        store.programs.clear()
        store.meta = {}
    store.root.mkdir(parents=True, exist_ok=True)
    store.meta["evaluator_sha256"] = sha256_file(store.evaluator_path())
    store.meta["generation"] = 0
    store.meta["started"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (store.root / "programs").mkdir(exist_ok=True)
    for sp in config.seed_programs:
        pid = store.new_id()
        dest = store.root / "programs" / f"{pid}.py"
        shutil.copyfile(campaign_dir / sp, dest)
        prog = Program(id=pid, gen=0, path=str(dest.relative_to(campaign_dir)).replace("\\", "/"), parent_ids=[])
        evaluate_program(store, prog)
        store.programs[pid] = prog
    store.save()
    return store


def next_generation(campaign_dir: Path, config: EvolveConfig, n: int | None = None, seed: int | None = None) -> dict:
    """Reserve n children and write a proposal request the orchestrating agent hands to mutator subagents."""
    store = EvolveStore.load(campaign_dir, config)
    store.check_evaluator()
    n = n or config.children_per_gen
    gen = store.meta.get("generation", 0) + 1
    rng = random.Random(seed if seed is not None else gen)
    proposals = []
    for _ in range(n):
        parents = store.select_parents(config.parents_per_child, rng)
        cid = store.new_id()
        child_path = store.root / "programs" / f"{cid}.py"
        prog = Program(id=cid, gen=gen, path=str(child_path.relative_to(campaign_dir)).replace("\\", "/"),
                       parent_ids=[p.id for p in parents])
        store.programs[cid] = prog  # pending (valid=False, score=None)
        proposals.append({
            "child_id": cid,
            "child_path": str(child_path),
            "parents": [
                {"id": p.id, "score": p.score, "features": p.features, "artifacts": p.artifacts[-1500:],
                 "code": (campaign_dir / p.path).read_text(encoding="utf-8")}
                for p in parents
            ],
        })
    store.meta["generation"] = gen
    store.meta["pending"] = [p["child_id"] for p in proposals]
    store.save()
    best = store.best()
    request = {
        "name": config.name,
        "generation": gen,
        "objective": "maximize" if config.maximize else "minimize",
        "known_best": config.known_best,
        "current_best": {"id": best.id, "score": best.score} if best else None,
        "evaluator_path": str(store.evaluator_path()),
        "mutation_prompt": config.mutation_prompt,
        "proposals": proposals,
    }
    (store.root / f"proposals_gen{gen:04d}.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    return request


def score_pending(campaign_dir: Path, config: EvolveConfig) -> dict:
    """Evaluate every pending child (files that now exist), update the population, and summarize the generation."""
    store = EvolveStore.load(campaign_dir, config)
    store.check_evaluator()
    prev_best = store.best()
    pending = list(store.meta.get("pending", []))
    evaluated, missing = [], []
    for cid in pending:
        prog = store.programs.get(cid)
        if prog is None:
            continue
        if not (campaign_dir / prog.path).exists():
            missing.append(cid)
            continue
        evaluate_program(store, prog)
        evaluated.append(prog)
    store.meta["pending"] = missing
    # keep only unfinished pending ids; drop pending records whose files never appeared if the generation is closed
    store.save()
    new_best = store.best()
    improved = bool(new_best and (prev_best is None or better(new_best.score, prev_best.score, config.maximize, config.noise_floor)))
    summary = {
        "generation": store.meta.get("generation"),
        "evaluated": [{"id": p.id, "score": p.score, "valid": p.valid, "bin": p.bin_key, "error": (p.error or "")[:200]} for p in evaluated],
        "missing_children": missing,
        "best": {"id": new_best.id, "score": new_best.score, "exact": new_best.exact} if new_best else None,
        "improved": improved,
        "elite_bins": len(store.elites()),
        "population": len(store.programs),
    }
    hist = store.meta.setdefault("history", [])
    hist.append({"gen": summary["generation"], "best": summary["best"], "improved": improved,
                 "evaluated": len(evaluated), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    store.save()
    return summary


def status(campaign_dir: Path, config: EvolveConfig) -> dict:
    store = EvolveStore.load(campaign_dir, config)
    best = store.best()
    return {
        "name": config.name,
        "generation": store.meta.get("generation", 0),
        "population": len(store.programs),
        "valid": sum(1 for p in store.programs.values() if p.valid),
        "best": best.model_dump() if best else None,
        "known_best": config.known_best,
        "beats_known_best": bool(best and config.known_best is not None and better(best.score, config.known_best, config.maximize, config.noise_floor)),
        "elites": {k: {"id": p.id, "score": p.score} for k, p in store.elites().items()},
        "evaluator_sha256": store.meta.get("evaluator_sha256"),
        "history": store.meta.get("history", [])[-20:],
    }


def run_headless(campaign_dir: Path, config: EvolveConfig, generations: int, model: str = "sonnet",
                 claude_bin: str = "claude", max_turns: int = 12) -> list[dict]:
    """Drive the loop with `claude -p` as the mutation operator (uses the user's Claude Code login; no API key)."""
    summaries = []
    for _ in range(generations):
        req = next_generation(campaign_dir, config)
        for prop in req["proposals"]:
            prompt = (
                f"{config.mutation_prompt}\n\nObjective: {req['objective']} the score. Known best (literature): {config.known_best}. "
                f"Current best: {req['current_best']}.\n\nPARENTS:\n" + "\n\n".join(
                    f"# parent {p['id']} score={p['score']} features={p['features']}\n# artifacts: {p['artifacts'][:800]}\n{p['code']}"
                    for p in prop["parents"]) +
                f"\n\nWrite the child program to exactly this path: {prop['child_path']}\nDo not modify any other file."
            )
            try:
                subprocess.run([claude_bin, "-p", prompt, "--model", model, "--max-turns", str(max_turns),
                                "--output-format", "text", "--permission-mode", "acceptEdits"],
                               cwd=str(campaign_dir), capture_output=True, encoding="utf-8", errors="replace",
                               timeout=900, shell=(os.name == "nt"))
            except Exception as e:  # pragma: no cover
                sys.stderr.write(f"[evolve] mutator failed for {prop['child_id']}: {e}\n")
        summaries.append(score_pending(campaign_dir, config))
    return summaries
