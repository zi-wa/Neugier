"""Falsification-first testing of conjectures (CLAUDE.md rule R3).

A *conjecture module* is a plain ``.py`` file (no package required) that
defines:

* ``predicate(x) -> bool`` -- required. True if the conjecture holds on
  instance ``x``, False if ``x`` is a counterexample.
* ``space() -> Iterable`` -- for exhaustive search over a finite (or
  prefix-truncated) domain.
* ``sample(rng: random.Random) -> instance`` -- for random / hillclimb
  search over a domain too large or infinite to enumerate.
* ``neighbors(x) -> Iterable`` -- optional, instances "close to" ``x``, used
  by the hillclimb strategy for local search.
* ``score(x) -> float`` -- optional, lower means closer to violating the
  conjecture; used by hillclimb to pick which neighbor to move to.
* ``describe(x) -> str`` -- optional, human-readable rendering of ``x`` for
  reports (``repr(x)`` is used otherwise).

See ``harness/verify/template_conjecture.py`` for a commented skeleton and
``harness/verify/examples/`` for two worked examples.
"""
from __future__ import annotations

import importlib.util
import random
import time
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

Strategy = str  # "exhaustive" | "random" | "hillclimb" | "all"


class FalsificationReport(BaseModel):
    """Result of :func:`run` -- one falsification attempt against one module."""

    conjecture: str
    strategy: str
    tested: int
    counterexample: str | None = None
    counterexample_repr: str | None = None
    seed: int
    seconds: float
    exhausted: bool
    error: str | None = None


def _load_module(module_path: Path):
    module_path = Path(module_path)
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load conjecture module from {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_exhaustive(mod: Any, deadline: float, max_instances: int) -> tuple[int, Any | None, bool]:
    """Iterate ``mod.space()``. Returns (tested, counterexample|None, exhausted)."""
    tested = 0
    try:
        space = iter(mod.space())
    except Exception:
        return 0, None, False
    for x in space:
        if tested >= max_instances or time.monotonic() >= deadline:
            return tested, None, False
        tested += 1
        try:
            ok = mod.predicate(x)
        except Exception:
            continue
        if not ok:
            return tested, x, False
    return tested, None, True


def _run_random(mod: Any, rng: random.Random, deadline: float, max_instances: int) -> tuple[int, Any | None, bool]:
    """Draw ``mod.sample(rng)`` repeatedly for the time/instance budget."""
    tested = 0
    while tested < max_instances and time.monotonic() < deadline:
        try:
            x = mod.sample(rng)
        except Exception:
            tested += 1
            continue
        tested += 1
        try:
            ok = mod.predicate(x)
        except Exception:
            continue
        if not ok:
            return tested, x, False
    return tested, None, False


def _run_hillclimb(mod: Any, rng: random.Random, deadline: float, max_instances: int) -> tuple[int, Any | None, bool]:
    """Random restarts + local search via ``mod.neighbors`` minimizing ``mod.score``.

    Without both ``neighbors`` and ``score`` defined, this degrades to
    random restarts (equivalent to :func:`_run_random`), per spec.
    """
    has_score = hasattr(mod, "score")
    has_neighbors = hasattr(mod, "neighbors")
    if not (has_score and has_neighbors):
        return _run_random(mod, rng, deadline, max_instances)

    tested = 0
    while tested < max_instances and time.monotonic() < deadline:
        try:
            current = mod.sample(rng)
        except Exception:
            tested += 1
            continue
        tested += 1
        try:
            if not mod.predicate(current):
                return tested, current, False
            current_score = mod.score(current)
        except Exception:
            continue

        # Local search: greedily move to the first strictly-improving
        # (lower-scoring) neighbor, checking its predicate along the way.
        while tested < max_instances and time.monotonic() < deadline:
            try:
                neighbor_list = list(mod.neighbors(current))
            except Exception:
                break
            moved = False
            for nb in neighbor_list:
                if tested >= max_instances or time.monotonic() >= deadline:
                    break
                tested += 1
                try:
                    if not mod.predicate(nb):
                        return tested, nb, False
                    nb_score = mod.score(nb)
                except Exception:
                    continue
                if nb_score < current_score:
                    current, current_score = nb, nb_score
                    moved = True
                    break
            if not moved:
                break  # local optimum; restart from a fresh random sample
    return tested, None, False


def _maybe_write(report: FalsificationReport, out_json: Path | None) -> None:
    if out_json is None:
        return
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))


def run(
    module_path: Path,
    strategy: Strategy = "all",
    time_limit: float = 60.0,
    max_instances: int = 1_000_000,
    seed: int = 0,
    out_json: Path | None = None,
) -> FalsificationReport:
    """Falsify the conjecture defined in ``module_path``.

    Stops at the first counterexample found. Exceptions raised by a single
    instance's ``predicate`` (or ``sample``/``neighbors``/``score``) are
    caught, counted toward the time/instance budget, and skipped -- they do
    not abort the run. ``strategy="all"`` runs exhaustive (if ``space`` is
    defined), then random (if ``sample`` is defined), then hillclimb (if
    ``sample`` and ``neighbors`` are defined), sharing one overall
    ``time_limit`` wall-clock budget, stopping early on the first
    counterexample.
    """
    module_path = Path(module_path)
    conjecture_name = module_path.stem
    start = time.monotonic()
    deadline = start + time_limit
    rng = random.Random(seed)

    tested_total = 0
    counterexample_x: Any = None
    exhausted = False
    error_msg: str | None = None

    try:
        mod = _load_module(module_path)
    except Exception as e:
        seconds = time.monotonic() - start
        report = FalsificationReport(
            conjecture=conjecture_name,
            strategy=strategy,
            tested=0,
            seed=seed,
            seconds=seconds,
            exhausted=False,
            error=f"module load failed: {type(e).__name__}: {e}",
        )
        _maybe_write(report, out_json)
        return report

    if not hasattr(mod, "predicate"):
        error_msg = "conjecture module has no predicate(x) function"
    else:
        has_space = hasattr(mod, "space")
        has_sample = hasattr(mod, "sample")
        has_neighbors = hasattr(mod, "neighbors")

        if strategy == "all":
            strategies_to_run = []
            if has_space:
                strategies_to_run.append("exhaustive")
            if has_sample:
                strategies_to_run.append("random")
            if has_sample and has_neighbors:
                strategies_to_run.append("hillclimb")
            if not strategies_to_run:
                error_msg = "conjecture module defines neither space() nor sample(); nothing to run"
        elif strategy in ("exhaustive", "random", "hillclimb"):
            strategies_to_run = [strategy]
        else:
            error_msg = f"unknown strategy {strategy!r}"
            strategies_to_run = []

        try:
            for strat in strategies_to_run:
                if counterexample_x is not None:
                    break
                if time.monotonic() >= deadline:
                    break
                remaining = max_instances - tested_total
                if remaining <= 0:
                    break

                if strat == "exhaustive":
                    if not has_space:
                        error_msg = "strategy 'exhaustive' requires space()"
                        continue
                    n, cx, exh = _run_exhaustive(mod, deadline, remaining)
                elif strat == "random":
                    if not has_sample:
                        error_msg = "strategy 'random' requires sample(rng)"
                        continue
                    n, cx, exh = _run_random(mod, rng, deadline, remaining)
                else:  # hillclimb
                    if not has_sample:
                        error_msg = "strategy 'hillclimb' requires sample(rng)"
                        continue
                    n, cx, exh = _run_hillclimb(mod, rng, deadline, remaining)

                tested_total += n
                if cx is not None:
                    counterexample_x = cx
                    error_msg = None
                exhausted = exhausted or exh
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"

    counterexample_str: str | None = None
    counterexample_repr: str | None = None
    if counterexample_x is not None:
        try:
            counterexample_str = (
                mod.describe(counterexample_x) if hasattr(mod, "describe") else repr(counterexample_x)
            )
        except Exception:
            counterexample_str = repr(counterexample_x)
        counterexample_repr = repr(counterexample_x)

    seconds = time.monotonic() - start
    report = FalsificationReport(
        conjecture=conjecture_name,
        strategy=strategy,
        tested=tested_total,
        counterexample=counterexample_str,
        counterexample_repr=counterexample_repr,
        seed=seed,
        seconds=seconds,
        exhausted=bool(exhausted and counterexample_x is None),
        error=error_msg,
    )
    _maybe_write(report, out_json)
    return report


# --------------------------------------------------------------------------
# SAT / SMT helpers
# --------------------------------------------------------------------------


def sat_check(cnf_clauses: list[list[int]], time_limit: float = 30.0) -> dict[str, Any]:
    """Check satisfiability of a CNF (DIMACS-style clause list) with pysat.

    Returns ``{"sat": True|False|None, "model": list[int]|None}``; ``sat`` is
    ``None`` if the solver was interrupted by ``time_limit`` before
    deciding.
    """
    import threading

    from pysat.solvers import Solver

    with Solver(name="g3", bootstrap_with=cnf_clauses) as solver:
        timer = threading.Timer(time_limit, solver.interrupt)
        timer.start()
        try:
            result = solver.solve_limited(expect_interrupt=True)
        finally:
            timer.cancel()
        model = solver.get_model() if result else None
        return {"sat": result, "model": model}


def z3_check(build: Callable[[Any], None], time_limit_ms: int = 30_000) -> dict[str, Any]:
    """Run a z3 solver built by ``build(solver)``, with a millisecond timeout.

    Returns ``{"result": "sat"|"unsat"|"unknown", "model": dict[str, str]|None}``.
    """
    import z3

    solver = z3.Solver()
    solver.set("timeout", int(time_limit_ms))
    build(solver)
    outcome = solver.check()
    if outcome == z3.sat:
        model = solver.model()
        return {
            "result": "sat",
            "model": {str(d): str(model[d]) for d in model.decls()},
        }
    if outcome == z3.unsat:
        return {"result": "unsat", "model": None}
    return {"result": "unknown", "model": None}
