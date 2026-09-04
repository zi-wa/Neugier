"""Sketch-first prove with an Elo tournament (Round-2 Step 26 / Y6).

Before anyone writes a full proof, each persona prover writes a **sketch**
(``proofs/<ID>.sketch.<persona>.md``: lemma DAG, key idea, per-lemma cheapest
falsification). The falsifier attacks every sketch lemma cheaply; judge-class
raters compare sketches pairwise on plausibility / clarity / novelty and write
one ``match-<a>-<b>-<axis>-<tier>.json`` each. This module aggregates matches
into Elo ratings (init 1200, K = 32) and a P-UCB style selection score, vetoes
sketches with a falsified lemma, and selects which sketches receive the
full-proof budget (``budgets.full_proofs``).

Precedent: DeepMind's formal proof search (arXiv 2605.22763) rates sketches on
"plausibility, clarity, and novelty", aggregates into Elo and samples with
P-UCB; the AI co-scientist (arXiv 2502.18864) starts hypotheses at Elo 1200
and reserves multi-turn debates for top-ranked pairs (single-turn below) — the
``tier`` field (``pairwise`` | ``debate``) records which kind of match a file is.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from pydantic import BaseModel, Field

AXES = ("plausibility", "clarity", "novelty")
TIERS = ("pairwise", "debate")


class Match(BaseModel):
    a: str
    b: str
    winner: str  # a | b | draw (or the persona name)
    axis: str = "plausibility"
    tier: str = "pairwise"
    rationale: str = ""
    steal_from_loser: str = ""
    rater: str = ""
    file: str = ""

    def outcome(self) -> tuple[float, float]:
        """Scores for (a, b): 1/0, 0/1 or 0.5/0.5."""
        w = self.winner.strip().lower()
        if w in ("a", self.a.lower()):
            return 1.0, 0.0
        if w in ("b", self.b.lower()):
            return 0.0, 1.0
        return 0.5, 0.5


class Rating(BaseModel):
    elo: float = 1200.0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    visits: int = 0


def tournament_dir(campaign_dir: Path | str, claim_id: str) -> Path:
    return Path(campaign_dir) / "reviews" / f"tournament-{claim_id}"


def load_matches(directory: Path | str) -> list[Match]:
    """All ``match-*.json`` files (sorted by name) merged with ``matches.jsonl``; deduped; rewritten to the jsonl."""
    directory = Path(directory)
    seen: set[str] = set()
    out: list[Match] = []

    def _add(data: dict, file: str) -> None:
        try:
            m = Match.model_validate({**data, "file": file})
        except Exception:
            return
        key = hashlib.sha256(json.dumps(m.model_dump(exclude={"file"}), sort_keys=True).encode("utf-8")).hexdigest()
        if key in seen:
            return
        seen.add(key)
        out.append(m)

    jsonl = directory / "matches.jsonl"
    if jsonl.exists():
        for ln in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            if ln.strip():
                try:
                    _add(json.loads(ln), "matches.jsonl")
                except ValueError:
                    continue
    for p in sorted(directory.glob("match-*.json"), key=lambda p: p.name):
        try:
            _add(json.loads(p.read_text(encoding="utf-8")), p.name)
        except ValueError:
            continue
    if out:
        directory.mkdir(parents=True, exist_ok=True)
        with open(jsonl, "w", encoding="utf-8") as fh:
            for m in out:
                fh.write(json.dumps(m.model_dump(exclude={"file"}), ensure_ascii=False) + "\n")
    return out


def rate(matches: list[Match], init: float = 1200.0, k: float = 32.0) -> dict[str, Rating]:
    """Sequential Elo in file order (deterministic)."""
    ratings: dict[str, Rating] = {}
    for m in matches:
        ra = ratings.setdefault(m.a, Rating(elo=init))
        rb = ratings.setdefault(m.b, Rating(elo=init))
        ea = 1.0 / (1.0 + 10 ** ((rb.elo - ra.elo) / 400.0))
        eb = 1.0 - ea
        sa, sb = m.outcome()
        ra.elo += k * (sa - ea)
        rb.elo += k * (sb - eb)
        ra.visits += 1
        rb.visits += 1
        if sa == 1.0:
            ra.wins += 1
            rb.losses += 1
        elif sb == 1.0:
            rb.wins += 1
            ra.losses += 1
        else:
            ra.draws += 1
            rb.draws += 1
    for r in ratings.values():
        r.elo = round(r.elo, 2)
    return ratings


def aggregate_from_odds(lam: float, init: float = 1200.0) -> float:
    """``Elo = 1200 + 400·log10(λ)`` for a mean odds ratio λ (arXiv 2605.22763 §A.1)."""
    return init + 400.0 * math.log10(max(lam, 1e-9))


def pucb_scores(ratings: dict[str, Rating], c: float = 1.0, init: float = 1200.0) -> dict[str, float]:
    """``(elo − init)/400 + c·sqrt(Σ visits)/(visits + 1)`` — strength plus an exploration bonus for rarely rated sketches."""
    total = sum(r.visits for r in ratings.values())
    return {name: round((r.elo - init) / 400.0 + c * math.sqrt(total) / (r.visits + 1), 4) for name, r in ratings.items()}


def select(scores: dict[str, float], falsified: set[str], n: int) -> list[dict]:
    rows = []
    for name, score in sorted(scores.items(), key=lambda t: (-t[1], t[0])):
        rows.append({"persona": name, "score": score, "falsified": name in falsified, "selected": False, "reason": ""})
    picked = 0
    for r in rows:
        if r["falsified"]:
            r["reason"] = "a sketch lemma was falsified"
            continue
        if picked < n:
            r["selected"] = True
            picked += 1
        else:
            r["reason"] = "budget"
    return rows


# ------------------------------------------------------------ campaign glue --

_SKETCH_RE = re.compile(r"^(?P<claim>[A-Z]-\d{3,})\.sketch\.(?P<persona>[A-Za-z0-9_\-]+)\.md$")


def sketches(campaign_dir: Path | str, claim_id: str) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in sorted((Path(campaign_dir) / "proofs").glob(f"{claim_id}.sketch.*.md")):
        m = _SKETCH_RE.match(p.name)
        if m:
            out[m.group("persona")] = p
    return out


def falsified_personas(tdir: Path) -> dict[str, list[str]]:
    """``{persona: [lemma labels with a counterexample]}`` from ``falsify/<persona>-<label>.json`` reports."""
    out: dict[str, list[str]] = {}
    fdir = tdir / "falsify"
    if not fdir.is_dir():
        return out
    for p in sorted(fdir.glob("*.json")):
        try:
            rep = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if rep.get("counterexample_repr") is None and not rep.get("regression_failures"):
            continue
        stem = p.stem
        persona, _, label = stem.partition("-")
        out.setdefault(persona, []).append(label or stem)
    return out


def tournament(campaign_dir: Path | str, claim_id: str, *, k: float = 32.0, c: float = 1.0, full_proofs: int | None = None) -> dict:
    """Rate all matches for a claim, veto falsified sketches, select the full-proof budget; write tournament.json."""
    from harness.ledger.ledger import atomic_write_json, load_budgets

    campaign_dir = Path(campaign_dir)
    tdir = tournament_dir(campaign_dir, claim_id)
    matches = load_matches(tdir)
    ratings = rate(matches, k=k)
    for persona in sketches(campaign_dir, claim_id):
        ratings.setdefault(persona, Rating())
    if full_proofs is None:
        full_proofs = int(load_budgets(campaign_dir).get("full_proofs", 2))
    fals = falsified_personas(tdir)
    scores = pucb_scores(ratings, c)
    rows = select(scores, set(fals), full_proofs)
    cross: dict[str, list[str]] = {}
    for m in matches:
        sa, sb = m.outcome()
        loser = m.b if sa == 1.0 else (m.a if sb == 1.0 else None)
        winner = m.a if sa == 1.0 else (m.b if sb == 1.0 else None)
        if winner and m.steal_from_loser.strip():
            cross.setdefault(winner, []).append(f"from {loser} ({m.axis}): {m.steal_from_loser.strip()}")
    result = {
        "claim": claim_id,
        "params": {"k": k, "c": c, "full_proofs": full_proofs, "init": 1200},
        "matches": len(matches),
        "axes": {ax: sum(1 for m in matches if m.axis == ax) for ax in AXES},
        "tiers": {t: sum(1 for m in matches if m.tier == t) for t in TIERS},
        "sketches": {
            r["persona"]: {
                **ratings.get(r["persona"], Rating()).model_dump(),
                "score": r["score"], "falsified_lemmas": fals.get(r["persona"], []),
                "selected": r["selected"], "reason": r["reason"],
            }
            for r in rows
        },
        "selected": [r["persona"] for r in rows if r["selected"]],
        "cross_pollination": cross,
    }
    tdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(tdir / "tournament.json", result)
    return result
