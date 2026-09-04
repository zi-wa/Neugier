"""Collect proofs written in isolated git worktrees (Round-2 Step 30 / Y12).

Provers running with ``isolation: worktree`` must not touch ``ledger.json`` (parallel
writers would clobber each other). They write ``proofs/<ID>.<persona>.md`` (and
experiments) plus ``proofs/<ID>.<persona>.ledger-ops.jsonl`` — one JSON object per
intended ledger operation — and commit. ``harness prove collect --commits sha,…``
then checks those files out of each commit into the working tree and replays the
ledger operations sequentially through :class:`~harness.ledger.ledger.LedgerStore`
(so every rule still applies)::

    {"op": "add", "kind": "lemma", "statement": "...", "depends_on": [...], "tags": [...]}
    {"op": "evidence", "claim": "T-001", "type": "proof", "path": "proofs/T-001.analyst.md", "summary": "..."}
    {"op": "promote", "claim": "T-001", "status": "proof-drafted"}
    {"op": "credence", "claim": "T-001", "role": "prover", "why": "...", "p_pass": 0.7, "round": 1}
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from harness.ledger.ledger import LedgerError, LedgerStore
from harness.ledger.schema import Evidence


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def changed_paths(root: Path, commit: str, prefixes: list[str]) -> list[str]:
    out = _git(root, "diff", "--name-only", "HEAD", commit, "--", *prefixes)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def checkout_paths(root: Path, commit: str, paths: list[str]) -> None:
    if paths:
        _git(root, "checkout", commit, "--", *paths)


def replay_ledger_ops(store: LedgerStore, campaign_dir: Path, ops_path: Path) -> list[dict]:
    """Apply the recorded operations in order; stop at the first failure and report it."""
    applied: list[dict] = []
    id_map: dict[str, str] = {}
    for ln in ops_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        op = json.loads(ln)
        kind = op.get("op")
        try:
            if kind == "add":
                claim = store.add(kind=op["kind"], statement=op["statement"], depends_on=[id_map.get(d, d) for d in op.get("depends_on", [])],
                                  tags=op.get("tags", []), status=op.get("status", "idea"), notes=op.get("notes", ""))
                if op.get("temp_id"):
                    id_map[op["temp_id"]] = claim.id
                applied.append({"op": "add", "id": claim.id})
            elif kind == "evidence":
                cid = id_map.get(op["claim"], op["claim"])
                ev = Evidence(type=op["type"], path=op.get("path"), summary=op.get("summary", ""), role=op.get("role"),
                              verdict=op.get("verdict"), round=op.get("round"))
                store.add_evidence(cid, ev, campaign_dir)
                applied.append({"op": "evidence", "id": cid, "type": op["type"]})
            elif kind == "promote":
                cid = id_map.get(op["claim"], op["claim"])
                store.promote(cid, op["status"], campaign_dir)
                applied.append({"op": "promote", "id": cid, "status": op["status"]})
            elif kind == "credence":
                cid = id_map.get(op["claim"], op["claim"])
                store.record_credence(cid, role=op["role"], why=op.get("why", "worktree prover"), p_true=op.get("p_true"),
                                      p_budget=op.get("p_budget"), p_pass=op.get("p_pass"), round=op.get("round"))
                applied.append({"op": "credence", "id": cid})
            else:
                applied.append({"op": kind, "error": "unknown op"})
                break
        except (LedgerError, KeyError) as exc:
            applied.append({"op": kind, "error": str(exc)})
            break
    return applied


def collect(root: Path, slug: str, claim: str, commits: list[str]) -> dict:
    root = Path(root)
    campaign_rel = f"campaigns/{slug}"
    campaign_dir = root / campaign_rel
    prefixes = [f"{campaign_rel}/proofs", f"{campaign_rel}/experiments"]
    report: dict = {"claim": claim, "commits": {}}
    store = LedgerStore(campaign_dir / "ledger.json", campaign=slug)
    for sha in commits:
        paths = [p for p in changed_paths(root, sha, prefixes) if "ledger.json" not in p]
        checkout_paths(root, sha, paths)
        ops_applied = []
        for p in paths:
            if p.endswith(".ledger-ops.jsonl") and (root / p).exists():
                ops_applied.extend(replay_ledger_ops(store, campaign_dir, root / p))
        report["commits"][sha] = {"files": paths, "ledger_ops": ops_applied}
    return report
