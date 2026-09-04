"""Round-2 Step 30: collecting worktree proofs and replaying ledger ops (temp git repo)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.ledger.ledger import LedgerStore
from harness.prove.collect import collect, replay_ledger_ops

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, encoding="utf-8", check=True).stdout


def test_collect_checks_out_files_and_replays_ops(tmp_path):
    root = tmp_path / "repo"
    (root / "campaigns" / "demo" / "proofs").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    store = LedgerStore(root / "campaigns" / "demo" / "ledger.json", campaign="demo")
    thm = store.add(kind="theorem", statement="T.")
    (root / "campaigns" / "demo" / "proofs" / ".keep").write_text("", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    # a "worktree" branch adds a proof + ledger ops without touching ledger.json
    _git(root, "checkout", "-qb", "prover-analyst")
    proof = root / "campaigns" / "demo" / "proofs" / f"{thm.id}.analyst.md"
    proof.write_text("**Step 1.** (algebra) x.\n", encoding="utf-8")
    ops = [
        {"op": "add", "kind": "lemma", "statement": "Helper.", "temp_id": "L-new"},
        {"op": "evidence", "claim": thm.id, "type": "proof", "path": f"proofs/{thm.id}.analyst.md", "summary": "analyst proof"},
        {"op": "credence", "claim": thm.id, "role": "prover", "why": "sketch survived", "p_pass": 0.7, "round": 1},
        {"op": "promote", "claim": thm.id, "status": "proof-drafted"},
    ]
    (root / "campaigns" / "demo" / "proofs" / f"{thm.id}.analyst.ledger-ops.jsonl").write_text("\n".join(json.dumps(o) for o in ops) + "\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "analyst proof")
    sha = _git(root, "rev-parse", "HEAD").strip()
    _git(root, "checkout", "-q", "-")
    assert not proof.exists()
    report = collect(root, "demo", thm.id, [sha])
    files = report["commits"][sha]["files"]
    assert any(f.endswith(f"{thm.id}.analyst.md") for f in files) and proof.exists()
    applied = report["commits"][sha]["ledger_ops"]
    assert [a["op"] for a in applied] == ["add", "evidence", "credence", "promote"] and not any(a.get("error") for a in applied)
    store2 = LedgerStore(root / "campaigns" / "demo" / "ledger.json")
    assert store2.get(thm.id).status == "proof-drafted" and any(c.kind == "lemma" for c in store2.ledger.claims.values())
    # a failing op stops the replay and is reported
    bad = root / "bad.jsonl"
    bad.write_text(json.dumps({"op": "promote", "claim": thm.id, "status": "referee-passed"}) + "\n", encoding="utf-8")
    out = replay_ledger_ops(store2, root / "campaigns" / "demo", bad)
    assert out[-1].get("error")
