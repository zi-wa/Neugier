"""Counterexample-guided conjecture repair (Round-2 Step 23 / X3).

A refutation is an input, not an end. ``harness ledger repair <id>`` turns a
``refuted`` claim into a *repair request* — the counterexamples (with the
conjecture module's ``features``), the regression set they form, the known
facts, and the three repair operators of The Optimist / TxGraffiti
(arXiv 2411.09158):

* ``add-hypothesis`` — restrict to a subclass that the counterexamples violate
  (their ``features`` say which property);
* ``weaken-bound`` — keep the strongest constant/exponent that survives *all*
  data ("strongest surviving inequality");
* ``absorb-and-regenerate`` — the counterexample joins the regression set and
  a new form is proposed from scratch.

A child claim (``ledger add --repaired-from <id> --repair-op …``) reaches
``numerically-supported`` only after a **truth test** (a falsification run with
``--regression`` over the parent's regression set and no counterexample) and a
**significance test** (a ``note`` evidence whose summary starts with
``significance:`` recording that no known fact implies it; for bounds also
``touch_number >= 1``).
"""
from __future__ import annotations

import json
from pathlib import Path

from harness.ledger.ledger import LedgerError, LedgerStore, atomic_write_json

OPERATORS = {
    "add-hypothesis": (
        "Restrict the statement to a subclass. Use the counterexamples' features to name a boolean property they "
        "violate (e.g. 'connected', 'n odd', 'S is not an arithmetic progression'); the child statement must still "
        "be interesting on the original target and must exclude every counterexample."
    ),
    "weaken-bound": (
        "Keep the form, weaken the constant/exponent to the strongest value that all data (regression set + fresh "
        "search) satisfies. Record how the constant was chosen (from which instances) — this is the 'strongest "
        "surviving inequality'."
    ),
    "absorb-and-regenerate": (
        "Treat the counterexamples as new data, not as a patch target: add them to the regression set and propose a "
        "different statement (new invariant, new normalization) that explains the data. The child must survive the "
        "whole regression set."
    ),
}


def _load_report(campaign_dir: Path, rel: str) -> dict | None:
    p = Path(campaign_dir) / rel
    if not p.exists() or not p.suffix.lower() == ".json":
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def counterexamples_of(store: LedgerStore, claim_id: str, campaign_dir: Path) -> list[dict]:
    """Counterexamples recorded by falsification evidence reports of a claim."""
    claim = store.get(claim_id)
    out: list[dict] = []
    seen: set[str] = set()
    for ev in claim.evidence:
        if ev.type != "falsification" or not ev.path:
            continue
        rep = _load_report(campaign_dir, ev.path)
        if not rep:
            continue
        for r in [rep.get("counterexample_repr")] + list(rep.get("regression_failures") or []):
            if r and r not in seen:
                seen.add(r)
                out.append({
                    "repr": r,
                    "describe": rep.get("counterexample") if r == rep.get("counterexample_repr") else None,
                    "features": rep.get("features") if r == rep.get("counterexample_repr") else None,
                    "report_path": ev.path,
                    "strategy": rep.get("strategy"),
                    "seed": rep.get("seed"),
                })
    return out


def build_request(store: LedgerStore, claim_id: str, campaign_dir: Path | str) -> dict:
    """Write ``experiments/repair/<id>.json`` and the regression set; return the request."""
    campaign_dir = Path(campaign_dir)
    claim = store.get(claim_id)
    if claim.status != "refuted":
        raise LedgerError(f"{claim_id} is {claim.status!r}; only refuted claims can be repaired")
    cexs = counterexamples_of(store, claim_id, campaign_dir)
    if not cexs:
        raise LedgerError(f"{claim_id} has no falsification report with a counterexample; attach the report first")
    reg_rel = f"experiments/falsify/{claim_id}.regression.json"
    reg_path = campaign_dir / reg_rel
    existing: list[str] = []
    if reg_path.exists():
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            existing = list(data.get("instances", []) if isinstance(data, dict) else data)
        except ValueError:
            existing = []
    instances = list(dict.fromkeys(existing + [c["repr"] for c in cexs]))
    atomic_write_json(reg_path, {"claim": claim_id, "instances": instances})
    known = [{"id": c.id, "statement": c.statement} for c in store.ledger.claims.values() if c.status == "known-in-literature"]
    children = [c.id for c in store.ledger.claims.values() if c.repaired_from == claim_id]
    request = {
        "claim_id": claim_id,
        "statement": claim.statement,
        "kind": claim.kind,
        "stakes": claim.stakes,
        "counterexamples": cexs,
        "regression_path": reg_rel,
        "regression_size": len(instances),
        "known_facts": known,
        "prior_children": children,
        "operators": OPERATORS,
        "how_to_submit": (
            f"harness ledger add --kind {claim.kind} --statement '<child>' --status conjectured --repaired-from {claim_id} "
            "--repair-op <op> --campaign <slug>; then `harness falsify run <module> --regression " + reg_rel +
            " --out experiments/falsify/<child>.json`, attach it as falsification evidence, add a note evidence "
            "'significance: <why no known fact implies it>' and promote to numerically-supported"
        ),
    }
    atomic_write_json(campaign_dir / "experiments" / "repair" / f"{claim_id}.json", request)
    return request


def repair_requirements(store: LedgerStore, claim, campaign_dir: Path) -> list[str]:
    """Extra promotion requirements (to numerically-supported) for a repaired child."""
    missing: list[str] = []
    truth = False
    touch_ok = claim.kind != "bound"
    for ev in claim.evidence:
        if ev.type != "falsification" or not ev.path:
            continue
        rep = _load_report(campaign_dir, ev.path)
        if not rep:
            continue
        if rep.get("regression_set") and not rep.get("regression_failures") and rep.get("counterexample_repr") is None and not rep.get("error"):
            truth = True
            if claim.kind == "bound" and (rep.get("touch_number") or 0) >= 1:
                touch_ok = True
    if not truth:
        missing.append(
            "truth test: needs a falsification report run with --regression over the parent's regression set "
            f"(experiments/falsify/{claim.repaired_from}.regression.json) showing no counterexample and no regression failure"
        )
    if not touch_ok:
        missing.append("significance test for a bound: the report's touch_number must be >= 1 (the bound is attained somewhere)")
    if not any(ev.type == "note" and ev.summary.lower().startswith("significance:") for ev in claim.evidence):
        missing.append("significance test: add a note evidence whose summary starts with 'significance:' stating why no known-in-literature fact implies the child")
    return missing
