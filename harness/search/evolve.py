"""Agent-driven evolutionary program search with an exact, immutable scorer.

Design (AlphaEvolve/OpenEvolve-style, without an LLM API key):

* The **scorer** is a Python file exposing ``evaluate(program_path: str) -> dict`` — the OpenEvolve evaluator interface —
  returning at least ``{"score": <number or "p/q" string>, "valid": bool}`` and optionally ``"features": {name: number}``
  (used for MAP-Elites bins), ``"artifacts": str`` (stderr/notes fed back to mutators) and ``"exact": bool``.
  Its sha256 is recorded at ``init`` and re-checked at every operation (rule: verifiers are immutable during Explore);
  ``init`` also freezes it in ``campaign.json`` and refuses to re-initialize an existing run without ``new_version``.
* The **population** is a JSONL database under ``<campaign>/experiments/evolve/<name>/`` with one row per program;
  MAP-Elites bins over ``feature_keys``; optional **islands** with ring migration.
* **Mutation is done by agents**, not here: ``next()`` writes a *proposal request* (parents' code, scores, artifacts, a
  mutation prompt, the current meta-recommendations) and reserves child paths; the orchestrating skill spawns cheap
  subagents that write the children; ``score()`` then evaluates every pending child with a timeout and updates the
  elites. ``run_headless()`` can drive ``claude -p`` instead (no shell, prompt on stdin, tools restricted).
* **Novelty rejection** (ShinkaEvolve: ``code_embed_sim_threshold``/``max_novelty_attempts``): a child whose normalized
  code hash equals, or whose TF-IDF cosine similarity to an existing program exceeds ``novelty_threshold``, is rejected
  *before* spending evaluation budget; the slot is re-proposed up to ``max_novelty_attempts`` times.
* **Cascade evaluation** (OpenEvolve ``cascade_evaluation``/``cascade_thresholds``): cheap stage evaluators run first
  and must clear their thresholds before the expensive main evaluator runs.
* **Meta-recommendations** (ShinkaEvolve ``meta_rec_interval``/``meta_max_recommendations``): every ``meta_interval``
  generations a digest of what improved and what failed is written; one top-model agent turns it into ``meta.md``
  (≤ ``meta_max_recommendations`` bullets) that later proposals carry.
* **Exactness**: scores given as ``"p/q"`` strings are compared as ``fractions.Fraction``; float scores are compared
  with a configurable ``noise_floor`` (also applied to elites/best) and flagged ``needs_exact_verification``.
* ``mine()`` hands the elite population to the experimentalist (AlphaEvolve's construct → prove handoff): code, feature
  vectors, artifacts and OEIS lookups of integer sequences found in the artifacts.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from harness.verify.exact import sha256_file

# --------------------------------------------------------------------------
# config / records
# --------------------------------------------------------------------------


class CascadeStage(BaseModel):
    evaluator: str          # path relative to campaign dir
    threshold: float        # float score the stage must reach (or exceed) before the next stage runs


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
    # Round 2 (Y5)
    novelty_threshold: float = 0.95     # TF-IDF cosine over normalized code; equal hashes are always rejected
    max_novelty_attempts: int = 3
    cascade: list[CascadeStage] = []    # cheap stages before the main evaluator
    meta_interval: int = 10
    meta_max_recommendations: int = 5
    islands: int = 1
    migration_interval: int = 5
    include_artifacts: bool = True
    max_artifact_bytes: int = 4000
    version: str | None = None


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
    # Round 2
    code_hash: str = ""
    island: int = 0
    rejected: str | None = None
    attempt: int = 1
    stage_scores: list[float] = []
    migrated_from: str | None = None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


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


def _freeze_in_campaign(campaign_dir: Path, rel_paths: list[str]) -> None:
    """Record the evaluator hashes in campaign.json["frozen"] (guard_frozen hook + campaign check)."""
    cj = Path(campaign_dir) / "campaign.json"
    if not cj.exists():
        return
    try:
        data = json.loads(cj.read_text(encoding="utf-8"))
        frozen = dict(data.get("frozen") or {})
        for rel in rel_paths:
            full = Path(campaign_dir) / rel
            if full.is_file():
                frozen[rel.replace("\\", "/")] = sha256_file(full)
        data["frozen"] = frozen
        from harness.ledger.ledger import atomic_write_json

        atomic_write_json(cj, data)
    except Exception:  # noqa: BLE001 - freezing is best effort; the evaluator hash in meta.json is authoritative
        pass


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
    def run_name(self) -> str:
        return f"{self.config.name}-v{self.config.version}" if self.config.version else self.config.name

    @property
    def root(self) -> Path:
        return self.campaign_dir / "experiments" / "evolve" / self.run_name

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
                "Verifiers are immutable during Explore: write a new versioned scorer and `evolve init --new-version`."
            )
        recorded = self.meta.get("cascade_sha256") or {}
        for stage in self.config.cascade:
            cur = sha256_file(self.campaign_dir / stage.evaluator)
            if recorded.get(stage.evaluator) and recorded[stage.evaluator] != cur:
                raise RuntimeError(f"cascade evaluator {stage.evaluator} changed since init; verifiers are immutable during Explore")

    # ---- population ----
    def new_id(self) -> str:
        n = self.meta.get("counter", 0) + 1
        self.meta["counter"] = n
        return f"p{n:05d}"

    def bin_of(self, features: dict[str, float], island: int = 0) -> str:
        prefix = f"i{island}|" if self.config.islands > 1 else ""
        if not self.config.feature_keys:
            return prefix + "all"
        parts = []
        for k in self.config.feature_keys:
            lo, hi = self.config.feature_ranges.get(k, [0.0, 1.0])
            v = features.get(k, lo)
            frac = 0.0 if hi <= lo else min(max((v - lo) / (hi - lo), 0.0), 0.999999)
            parts.append(f"{k}={int(frac * self.config.feature_bins)}")
        return prefix + "|".join(parts)

    def elites(self, island: int | None = None) -> dict[str, Program]:
        best: dict[str, Program] = {}
        for p in self.programs.values():
            if not p.valid or (island is not None and p.island != island):
                continue
            cur = best.get(p.bin_key)
            if cur is None or better(p.score, cur.score, self.config.maximize, self.config.noise_floor):
                best[p.bin_key] = p
        return best

    def best(self, island: int | None = None) -> Program | None:
        b: Program | None = None
        for p in self.programs.values():
            if not p.valid or (island is not None and p.island != island):
                continue
            if b is None or better(p.score, b.score, self.config.maximize, self.config.noise_floor):
                b = p
        return b

    def ranked(self, island: int | None = None) -> list[Program]:
        valid = [p for p in self.programs.values() if p.valid and (island is None or p.island == island)]

        def key(p: Program):
            v = to_number(p.score)
            fv = float(v) if v is not None else float("-inf")
            return fv if self.config.maximize else -fv

        return sorted(valid, key=key, reverse=True)

    def select_parents(self, k: int, rng: random.Random, island: int | None = None) -> list[Program]:
        """Power-law over rank among elites (bins) plus top-ranked programs; k distinct if possible."""
        pool = list(self.elites(island).values())
        for p in self.ranked(island)[: self.config.elite_size]:
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

    # ---- novelty ----
    def code_of(self, program: Program) -> str:
        try:
            return (self.campaign_dir / program.path).read_text(encoding="utf-8")
        except OSError:
            return ""

    def novelty_check(self, child: Program) -> str | None:
        """``None`` when the child is novel, else ``"duplicate:<id>"`` / ``"similar:<id>:<score>"``."""
        from harness.text.similarity import code_hash, most_similar, normalize_code, tokenize

        src = self.code_of(child)
        if not src.strip():
            return None
        child.code_hash = code_hash(src)
        existing = [p for p in self.programs.values() if p.id != child.id and p.code_hash and not p.rejected]
        for p in existing:
            if p.code_hash == child.code_hash:
                return f"duplicate:{p.id}"
        norm = normalize_code(src)
        if len(tokenize(norm)) < 20 or not existing:
            return None
        corpus = [normalize_code(self.code_of(p)) for p in existing]
        for idx, score in most_similar(norm, corpus, k=1):
            if score >= self.config.novelty_threshold:
                return f"similar:{existing[idx].id}:{score}"
        return None


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


def _run_evaluator(store: EvolveStore, evaluator: Path, program: Program) -> tuple[dict | None, str, str]:
    """Run one evaluator file on the program: ``(result or None, stderr, error)``."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _EVAL_SNIPPET, str(evaluator), str(store.campaign_dir / program.path)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=store.config.eval_timeout,
            cwd=str(store.campaign_dir), env=env,
        )
    except subprocess.TimeoutExpired:
        return None, "", f"timeout after {store.config.eval_timeout}s"
    out = proc.stdout or ""
    marker = out.rfind("__EVOLVE_RESULT__")
    if marker < 0:
        return None, proc.stderr or "", (proc.stderr or out)[-2000:] or "evaluator produced no result"
    res = json.loads(out[marker + len("__EVOLVE_RESULT__"):].strip().splitlines()[0])
    return res, proc.stderr or "", ""


def evaluate_program(store: EvolveStore, program: Program) -> Program:
    """Run the cascade (cheap stages first) and the main evaluator with timeouts; fill in the Program record."""
    store.check_evaluator()
    t0 = time.monotonic()
    program.stage_scores = []
    for i, stage in enumerate(store.config.cascade):
        res, _, err = _run_evaluator(store, store.campaign_dir / stage.evaluator, program)
        if res is None:
            program.valid = False
            program.error = f"cascade stage {i + 1} ({stage.evaluator}): {err}"
            program.seconds = time.monotonic() - t0
            return program
        try:
            s = float(to_number(res.get("score")))
        except (TypeError, ValueError):
            s = float("-inf")
        program.stage_scores.append(s)
        passed = s >= stage.threshold if store.config.maximize else s <= stage.threshold
        if not res.get("valid", True) or not passed:
            program.valid = False
            program.error = f"cascade stage {i + 1} ({stage.evaluator}) score {s} below threshold {stage.threshold}"
            program.artifacts = str(res.get("artifacts") or "")[-store.config.max_artifact_bytes:]
            program.seconds = time.monotonic() - t0
            return program
    res, stderr, err = _run_evaluator(store, store.evaluator_path(), program)
    if res is None:
        program.valid = False
        program.error = err
    else:
        program.valid = bool(res.get("valid")) and res.get("score") is not None
        program.score = res.get("score")
        if isinstance(program.score, (int, Fraction)):
            program.score = str(Fraction(program.score))
        program.exact = bool(res.get("exact", isinstance(program.score, str)))
        program.features = {k: float(v) for k, v in (res.get("features") or {}).items()}
        if store.config.include_artifacts:
            cap = store.config.max_artifact_bytes
            program.artifacts = (str(res.get("artifacts") or "")[-cap:] + (stderr[-min(1000, cap):] if stderr else ""))[-cap:]
        program.error = res.get("error")
        program.bin_key = store.bin_of(program.features, program.island)
        program.needs_exact_verification = program.valid and not program.exact
        extra = res.get("stage_scores")
        if isinstance(extra, list):
            program.stage_scores.extend(float(x) for x in extra if isinstance(x, (int, float)))
    program.seconds = time.monotonic() - t0
    return program


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------


def init(campaign_dir: Path, config: EvolveConfig, force: bool = False, new_version: str | None = None) -> EvolveStore:
    """Hash the evaluator, seed the population. Refuses to re-initialize an existing run: pass ``new_version``
    to start ``<name>-v<version>`` next to it (the old population and its evaluator hash stay intact)."""
    campaign_dir = Path(campaign_dir)
    if new_version:
        config = config.model_copy(update={"version": new_version})
    store = EvolveStore.load(campaign_dir, config)
    if store.meta_path.exists() or store.programs:
        if force:
            raise RuntimeError(
                f"run {store.run_name!r} is already initialized; --force is not allowed because it would reset the "
                "evaluator hash. Start a new versioned run with `evolve init --new-version <tag>`."
            )
        return store  # idempotent
    store.root.mkdir(parents=True, exist_ok=True)
    store.meta["evaluator_sha256"] = sha256_file(store.evaluator_path())
    store.meta["cascade_sha256"] = {st.evaluator: sha256_file(campaign_dir / st.evaluator) for st in config.cascade}
    store.meta["generation"] = 0
    store.meta["started"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    store.meta["version"] = config.version
    (store.root / "programs").mkdir(exist_ok=True)
    for i, sp in enumerate(config.seed_programs):
        pid = store.new_id()
        dest = store.root / "programs" / f"{pid}.py"
        shutil.copyfile(campaign_dir / sp, dest)
        prog = Program(id=pid, gen=0, path=str(dest.relative_to(campaign_dir)).replace("\\", "/"), parent_ids=[],
                       island=i % max(1, config.islands))
        store.novelty_check(prog)
        evaluate_program(store, prog)
        store.programs[pid] = prog
    store.save()
    _freeze_in_campaign(campaign_dir, [config.evaluator] + [st.evaluator for st in config.cascade])
    return store


def _meta_recommendations(store: EvolveStore) -> list[str]:
    path = store.root / "meta.md"
    if not path.exists():
        return []
    lines = [ln.strip().lstrip("-*0123456789. ").strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    recs = [ln for ln in lines if ln and not ln.startswith("#")]
    return recs[: store.config.meta_max_recommendations]


def _migrate(store: EvolveStore, gen: int) -> list[str]:
    """Ring migration: copy each island's best to the next island as a new program."""
    moved: list[str] = []
    n = store.config.islands
    if n <= 1 or gen % store.config.migration_interval != 0:
        return moved
    for i in range(n):
        b = store.best(i)
        if b is None:
            continue
        target = (i + 1) % n
        pid = store.new_id()
        dest = store.root / "programs" / f"{pid}.py"
        shutil.copyfile(store.campaign_dir / b.path, dest)
        clone = b.model_copy(update={
            "id": pid, "gen": gen, "path": str(dest.relative_to(store.campaign_dir)).replace("\\", "/"),
            "parent_ids": [b.id], "island": target, "migrated_from": b.id,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        clone.bin_key = store.bin_of(clone.features, target)
        store.programs[pid] = clone
        moved.append(pid)
    return moved


def next_generation(campaign_dir: Path, config: EvolveConfig, n: int | None = None, seed: int | None = None) -> dict:
    """Reserve n children (retry slots first) and write a proposal request the orchestrating agent hands to mutators."""
    campaign_dir = Path(campaign_dir)
    store = EvolveStore.load(campaign_dir, config)
    store.check_evaluator()
    n = n or config.children_per_gen
    gen = store.meta.get("generation", 0) + 1
    rng = random.Random(seed if seed is not None else gen)
    migrated = _migrate(store, gen)
    retries = list(store.meta.get("retry", []))
    proposals = []
    island_count = max(1, config.islands)
    for idx in range(n):
        retry = retries.pop(0) if retries else None
        island = int(retry["island"]) if retry else idx % island_count
        if retry:
            parents = [store.programs[pid] for pid in retry["parent_ids"] if pid in store.programs]
        else:
            parents = store.select_parents(config.parents_per_child, rng, island if island_count > 1 else None)
        cid = store.new_id()
        child_path = store.root / "programs" / f"{cid}.py"
        prog = Program(id=cid, gen=gen, path=str(child_path.relative_to(campaign_dir)).replace("\\", "/"),
                       parent_ids=[p.id for p in parents], island=island,
                       attempt=int(retry["attempt"]) if retry else 1)
        store.programs[cid] = prog  # pending (valid=False, score=None)
        entry = {
            "child_id": cid,
            "child_path": str(child_path),
            "island": island,
            "attempt": prog.attempt,
            "parents": [
                {"id": p.id, "score": p.score, "features": p.features, "artifacts": p.artifacts[-1500:],
                 "code": (campaign_dir / p.path).read_text(encoding="utf-8")}
                for p in parents
            ],
        }
        if retry:
            entry["retry_of"] = retry["child_id"]
            entry["rejected_reason"] = retry["reason"]
            entry["note"] = "the previous child was rejected as a near-duplicate; the new child MUST differ substantially"
        proposals.append(entry)
    store.meta["generation"] = gen
    store.meta["pending"] = [p["child_id"] for p in proposals]
    store.meta["retry"] = retries
    store.save()
    best = store.best()
    request = {
        "name": store.run_name,
        "generation": gen,
        "objective": "maximize" if config.maximize else "minimize",
        "known_best": config.known_best,
        "current_best": {"id": best.id, "score": best.score} if best else None,
        "evaluator_path": str(store.evaluator_path()),
        "mutation_prompt": config.mutation_prompt,
        "meta_recommendations": _meta_recommendations(store),
        "migrated": migrated,
        "proposals": proposals,
    }
    (store.root / f"proposals_gen{gen:04d}.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    return request


def write_meta_request(store: EvolveStore) -> Path:
    """Digest of the last ``meta_interval`` generations for a meta-recommendation agent (top model, R1)."""
    hist = store.meta.get("history", [])
    gen = store.meta.get("generation", 0)
    recent = [p for p in store.programs.values() if p.gen > gen - store.config.meta_interval and not p.rejected]
    improved = []
    for p in recent:
        if not p.valid:
            continue
        parents = [store.programs.get(pid) for pid in p.parent_ids]
        parents = [q for q in parents if q is not None and q.valid]
        if parents and all(better(p.score, q.score, store.config.maximize, store.config.noise_floor) for q in parents):
            improved.append({"id": p.id, "score": p.score, "parents": [q.id for q in parents],
                             "parent_scores": [q.score for q in parents], "code": store.code_of(p)[:3000]})
    errors = Counter((p.error or "").strip().splitlines()[0][:120] for p in recent if p.error)
    req = {
        "run": store.run_name,
        "generation": gen,
        "objective": "maximize" if store.config.maximize else "minimize",
        "best_per_generation": hist[-store.config.meta_interval:],
        "improved_children": improved[:10],
        "top_errors": errors.most_common(8),
        "elite_bins": {k: {"id": p.id, "score": p.score} for k, p in store.elites().items()},
        "rejected_as_duplicates": sum(1 for p in recent if p.rejected),
        "instructions": (
            f"Write experiments/evolve/{store.run_name}/meta.md with at most {store.config.meta_max_recommendations} "
            "bullet recommendations for the mutators: which kinds of changes improved the score, which failed, what to try "
            "next. Concrete and short; no motivation prose."
        ),
    }
    path = store.root / "meta_request.json"
    path.write_text(json.dumps(req, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def score_pending(campaign_dir: Path, config: EvolveConfig) -> dict:
    """Reject near-duplicates, evaluate every pending child (files that now exist), update the population."""
    campaign_dir = Path(campaign_dir)
    store = EvolveStore.load(campaign_dir, config)
    store.check_evaluator()
    prev_best = store.best()
    pending = list(store.meta.get("pending", []))
    evaluated, missing, rejected = [], [], []
    retries = list(store.meta.get("retry", []))
    for cid in pending:
        prog = store.programs.get(cid)
        if prog is None:
            continue
        if not (campaign_dir / prog.path).exists():
            missing.append(cid)
            continue
        reason = store.novelty_check(prog)
        if reason:
            prog.rejected = reason
            prog.valid = False
            prog.error = f"rejected before evaluation: {reason}"
            rejected.append({"id": cid, "reason": reason, "attempt": prog.attempt})
            if prog.attempt < config.max_novelty_attempts:
                retries.append({"child_id": cid, "parent_ids": prog.parent_ids, "island": prog.island,
                                "attempt": prog.attempt + 1, "reason": reason})
            continue
        evaluate_program(store, prog)
        evaluated.append(prog)
    store.meta["pending"] = missing
    store.meta["retry"] = retries
    store.save()
    new_best = store.best()
    improved = bool(new_best and (prev_best is None or better(new_best.score, prev_best.score, config.maximize, config.noise_floor)))
    summary = {
        "generation": store.meta.get("generation"),
        "evaluated": [{"id": p.id, "score": p.score, "valid": p.valid, "bin": p.bin_key, "error": (p.error or "")[:200],
                       "stage_scores": p.stage_scores} for p in evaluated],
        "rejected": rejected,
        "retry_slots": len(retries),
        "missing_children": missing,
        "best": {"id": new_best.id, "score": new_best.score, "exact": new_best.exact} if new_best else None,
        "improved": improved,
        "elite_bins": len(store.elites()),
        "population": len(store.programs),
        "meta_request": None,
    }
    hist = store.meta.setdefault("history", [])
    hist.append({"gen": summary["generation"], "best": summary["best"], "improved": improved,
                 "evaluated": len(evaluated), "rejected": len(rejected), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    gen = store.meta.get("generation", 0)
    if config.meta_interval > 0 and gen > 0 and gen % config.meta_interval == 0:
        summary["meta_request"] = str(write_meta_request(store))
    store.save()
    return summary


def status(campaign_dir: Path, config: EvolveConfig) -> dict:
    store = EvolveStore.load(Path(campaign_dir), config)
    best = store.best()
    return {
        "name": store.run_name,
        "generation": store.meta.get("generation", 0),
        "population": len(store.programs),
        "valid": sum(1 for p in store.programs.values() if p.valid),
        "rejected": sum(1 for p in store.programs.values() if p.rejected),
        "needs_exact_verification": sum(1 for p in store.programs.values() if p.needs_exact_verification),
        "best": best.model_dump() if best else None,
        "best_exact": bool(best and best.exact),
        "known_best": config.known_best,
        "beats_known_best": bool(best and best.exact and config.known_best is not None
                                 and better(best.score, config.known_best, config.maximize, config.noise_floor)),
        "beats_known_best_unverified": bool(best and not best.exact and config.known_best is not None
                                            and better(best.score, config.known_best, config.maximize, config.noise_floor)),
        "elites": {k: {"id": p.id, "score": p.score} for k, p in store.elites().items()},
        "islands": config.islands,
        "evaluator_sha256": store.meta.get("evaluator_sha256"),
        "meta_recommendations": _meta_recommendations(store),
        "history": store.meta.get("history", [])[-20:],
    }


# --------------------------------------------------------------------------
# checkpoints, mining
# --------------------------------------------------------------------------


def checkpoint(campaign_dir: Path, config: EvolveConfig) -> Path:
    store = EvolveStore.load(Path(campaign_dir), config)
    gen = store.meta.get("generation", 0)
    dest = store.root / "checkpoints" / f"gen{gen:04d}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("population.jsonl", "meta.json"):
        src = store.root / name
        if src.exists():
            shutil.copyfile(src, dest / name)
    return dest


def resume(campaign_dir: Path, config: EvolveConfig, from_gen: int | None = None) -> dict:
    """Restore population/meta from the latest (or a given) checkpoint; pending children whose files exist stay pending."""
    store = EvolveStore.load(Path(campaign_dir), config)
    cps = sorted((store.root / "checkpoints").glob("gen*")) if (store.root / "checkpoints").exists() else []
    if from_gen is not None:
        cps = [c for c in cps if c.name == f"gen{from_gen:04d}"]
    if not cps:
        raise RuntimeError("no checkpoint to resume from")
    src = cps[-1]
    for name in ("population.jsonl", "meta.json"):
        if (src / name).exists():
            shutil.copyfile(src / name, store.root / name)
    store = EvolveStore.load(Path(campaign_dir), config)
    pending = [cid for cid in store.meta.get("pending", []) if cid in store.programs]
    store.meta["pending"] = pending
    store.save()
    return {"restored_from": src.name, "generation": store.meta.get("generation"), "pending": pending}


_INT_SEQ_RE = re.compile(r"(?<![\d.])(-?\d+(?:\s*,\s*-?\d+){4,})(?![\d.])")


def mine(campaign_dir: Path, config: EvolveConfig, top: int = 5, oeis: bool = True) -> Path:
    """Write ``mine.md``: elite programs, feature vectors, artifacts, and OEIS lookups of integer sequences."""
    store = EvolveStore.load(Path(campaign_dir), config)
    ranked = store.ranked()[:top]
    lines = [f"# Structure mining — {store.run_name}", "",
             "Elite programs for the experimentalist to inspect for structure (symmetry, algebraic form, recurrence) and turn "
             "into a conjecture (AlphaEvolve's construct → prove handoff). Numbers below come from the evaluator, not from prose.", ""]
    seqs: dict[str, list[int]] = {}
    for p in ranked:
        lines += [f"## {p.id} — score {p.score} ({'exact' if p.exact else 'float'}) gen {p.gen} island {p.island}",
                  f"- features: {json.dumps(p.features)}", f"- bin: {p.bin_key}", f"- parents: {p.parent_ids}", ""]
        if p.artifacts:
            lines += ["```text", p.artifacts[-1200:], "```", ""]
            for m in _INT_SEQ_RE.finditer(p.artifacts):
                terms = [int(t) for t in re.split(r"\s*,\s*", m.group(1))]
                seqs[",".join(map(str, terms[:12]))] = terms[:12]
        lines += ["```python", store.code_of(p)[:4000], "```", ""]
    if seqs:
        lines += ["## Integer sequences found in artifacts", ""]
        for key, terms in seqs.items():
            lines.append(f"- `{key}`")
            if oeis:
                try:
                    from harness.lit import oeis as oeis_mod

                    hits = oeis_mod.lookup_sequence(terms)[:3]
                    for h in hits:
                        lines.append(f"  - OEIS A{int(h.get('number', 0)):06d}: {h.get('name', '')}")
                    if not hits:
                        lines.append("  - not in OEIS (candidate for a new sequence / conjecture)")
                except Exception as exc:  # noqa: BLE001 - network is optional
                    lines.append(f"  - OEIS lookup skipped ({type(exc).__name__})")
    out = store.root / "mine.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# headless driver
# --------------------------------------------------------------------------


def _claude_argv(claude_bin: str, model: str, max_turns: int, permission_mode: str) -> list[str]:
    resolved = shutil.which(claude_bin) or claude_bin
    return [resolved, "-p", "--model", model, "--max-turns", str(max_turns), "--output-format", "text",
            "--permission-mode", permission_mode, "--allowedTools", "Read,Write", "--disallowedTools", "Bash,Edit,Agent"]


def run_headless(campaign_dir: Path, config: EvolveConfig, generations: int, model: str = "sonnet",
                 claude_bin: str = "claude", max_turns: int = 12, permission_mode: str = "acceptEdits") -> list[dict]:
    """Drive the loop with `claude -p` as the mutation operator (uses the user's Claude Code login; no API key).

    The prompt is passed on stdin (never through a shell) and saved next to the child as ``<child>.prompt.md``;
    the mutator may only Read and Write.
    """
    campaign_dir = Path(campaign_dir)
    summaries = []
    for _ in range(generations):
        req = next_generation(campaign_dir, config)
        recs = "\n".join(f"- {r}" for r in req.get("meta_recommendations", []))
        for prop in req["proposals"]:
            prompt = (
                f"{config.mutation_prompt}\n\nObjective: {req['objective']} the score. Known best (literature): {config.known_best}. "
                f"Current best: {req['current_best']}.\n"
                + (f"\nRecommendations from previous generations:\n{recs}\n" if recs else "")
                + (f"\nNOTE: {prop['note']} (rejected as {prop['rejected_reason']})\n" if prop.get("note") else "")
                + "\nPARENTS:\n" + "\n\n".join(
                    f"# parent {p['id']} score={p['score']} features={p['features']}\n# artifacts: {p['artifacts'][:800]}\n{p['code']}"
                    for p in prop["parents"])
                + f"\n\nWrite the child program to exactly this path: {prop['child_path']}\nDo not modify any other file."
            )
            Path(prop["child_path"] + ".prompt.md").write_text(prompt, encoding="utf-8")
            try:
                subprocess.run(_claude_argv(claude_bin, model, max_turns, permission_mode), input=prompt,
                               cwd=str(campaign_dir), capture_output=True, encoding="utf-8", errors="replace",
                               timeout=900)
            except Exception as e:  # pragma: no cover
                sys.stderr.write(f"[evolve] mutator failed for {prop['child_id']}: {e}\n")
        summaries.append(score_pending(campaign_dir, config))
    return summaries
