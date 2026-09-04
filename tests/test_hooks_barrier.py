"""Hook drills for barrier.py, guard_frozen.py and gate_subagent.py with synthetic payloads."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from pathlib import Path

import pytest

from harness.ledger.ledger import LedgerStore
from harness.review import barrier as HB
from harness.review import verdict as HV

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"hook_{name}", HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(HOOKS))
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def common():
    return _load("_common")


@pytest.fixture(scope="module")
def barrier():
    return _load("barrier")


@pytest.fixture(scope="module")
def guard():
    return _load("guard_frozen")


@pytest.fixture(scope="module")
def gate():
    return _load("gate_subagent")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _root(tmp_path: Path, monkeypatch, budgets: dict | None = None) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    d = root / "campaigns" / "demo"
    d.mkdir(parents=True)
    _write(root / "campaigns" / "ACTIVE", "demo")
    _write(d / "campaign.json", json.dumps({"slug": "demo", "phase": "review", "budgets": budgets or {"max_review_rounds": 3},
                                            "frozen": {"experiments/scorer.py": "abc", "statement.md": "def"}}))
    _write(d / "statement.md", "S.")
    _write(d / "plan.md", "secret plan")
    _write(d / "proofs" / "T-001.md", "**Step 1.** (algebra) x.")
    _write(d / "experiments" / "scorer.py", "def score(): return 1")
    _write(d / "HUMAN.md", "# HUMAN\n")
    LedgerStore(d / "ledger.json", campaign="demo").add(kind="theorem", statement="T.")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    return root, d


def _run(mod, monkeypatch, capsys, payload: dict) -> tuple[int, dict | None, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rc = mod.main()
    captured = capsys.readouterr()
    out = json.loads(captured.out) if captured.out.strip() else None
    return rc, out, captured.err


def _payload(tool: str, agent_type: str | None, root: Path, agent_id: str = "A1", **tool_input) -> dict:
    p = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(root), "session_id": "sess-1"}
    if agent_type:
        p["agent_type"] = agent_type
        p["agent_id"] = agent_id
    return p


def _decision(out) -> str | None:
    if not out:
        return None
    return out["hookSpecificOutput"]["permissionDecision"]


# ------------------------------------------------------------ agreement --

def test_hook_matchers_agree_with_harness(common):
    cases = [("cache/x/y.txt", "cache/**"), ("cache", "cache/**"), ("reviews/round2/skeptic.SK-1.md", "reviews/round2/skeptic*.md"),
             ("proofs/T-001.md", "proofs/**"), ("a/b/c.txt", "a/**/c.txt"), ("plan.md", "plan.md.bak"), ("x/plan.md", "plan.md")]
    for rel, pat in cases:
        assert common.glob_match(rel, pat) == HB.glob_match(rel, pat), (rel, pat)
    manifest = {"deny_always": ["plan.md", "proofs/**"], "roles": {"skeptic:SK-1": {"barrier": True, "allow": ["statement.md", "proofs/T-001.md"]},
                                                                    "judge": {"barrier": False}}}
    for key, rel in [("skeptic:SK-1", "statement.md"), ("skeptic:SK-1", "plan.md"), ("skeptic:SK-1", "proofs/T-001.md"),
                     ("skeptic:SK-1", "proofs/T-002.md"), ("judge", "plan.md"), ("prover", "plan.md")]:
        assert common.role_allowed(manifest, key, rel) == HB.role_allowed(manifest, key, rel), (key, rel)


def test_min_verdict_parser_agrees_with_harness(common):
    text = "notes\n```yaml\nrole: skeptic\nclaim: T-001\nround: 1\nverdict: pass\ncritical_errors: []\nchecked:\n  - all\n```\n"
    mini = common.verdict_block_min(text)
    full = HV.parse_verdict_block(text)
    assert mini["role"] == full["role"] and mini["claim"] == full["claim"] and mini["verdict"] == full["verdict"]
    assert common.verdict_block_looks_valid_min(mini, "skeptic") == HV.verdict_block_looks_valid(full, "skeptic")
    assert common.judge_verdict_min("x\nVERDICT: PIVOT\n") == HV.judge_verdict("x\nVERDICT: PIVOT\n") == "PIVOT"


# ---------------------------------------------------------------- barrier --

def test_barrier_noop_without_role_or_round(barrier, monkeypatch, capsys, tmp_path):
    root, d = _root(tmp_path, monkeypatch)
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", None, root, file_path=str(d / "plan.md")))
    assert rc == 0 and out is None
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "skeptic", root, file_path=str(d / "plan.md")))
    assert rc == 0 and out is None  # no open round yet


def test_barrier_decisions_and_log(barrier, monkeypatch, capsys, tmp_path):
    root, d = _root(tmp_path, monkeypatch)
    HB.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=2)
    log = d / "reviews" / "round1" / "access.log"

    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "skeptic", root, file_path=str(d / "statement.md")))
    assert rc == 0 and out is None
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "skeptic", root, file_path=str(d / "plan.md")))
    assert _decision(out) == "deny" and "[Neugier barrier]" in out["hookSpecificOutput"]["permissionDecisionReason"]
    # Windows-style backslashes and mixed case still resolve (on POSIX "\\" is an ordinary character
    # and the filesystem is case-sensitive, so PLAN.md is genuinely a different file there)
    if os.name == "nt":
        rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "skeptic", root, file_path=str(d / "PLAN.md").replace("/", "\\")))
        assert _decision(out) == "deny"
    # relative path from cwd
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "skeptic", root, file_path="campaigns/demo/ideas.md"))
    assert _decision(out) == "deny"
    # outside the campaign: reference docs allowed, transcripts denied
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "skeptic", root, file_path=str(root / "skills" / "references" / "x.md")))
    assert out is None
    home = Path(os.path.expanduser("~"))
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "skeptic", root, file_path=str(home / ".claude" / "projects" / "t.jsonl")))
    assert _decision(out) == "deny"
    # search tools
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Grep", "skeptic", root, pattern="lemma"))
    assert _decision(out) == "deny"
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Grep", "skeptic", root, pattern="lemma", path=str(d / "cache")))
    assert out is None
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Glob", "skeptic", root, pattern="*.md", path=str(d)))
    assert _decision(out) == "deny"
    # shell: allowed status, denied history/readers/diff/mutations
    for cmd, expect in [
        ("git status", None),
        ("git show HEAD:campaigns/demo/plan.md", "deny"),
        (f"cat {d / 'ideas.md'}", "deny"),
        ("cat campaigns/demo/survey.md", "deny"),
        (f"diff {d / 'reviews' / 'round1' / 'lineup' / 'A.md'} {d / 'reviews' / 'round1' / 'lineup' / 'B.md'}", "deny"),
        (".venv/Scripts/python.exe -m harness ledger promote T-001 referee-passed --campaign demo", "deny"),
        (".venv/Scripts/python.exe -m harness ledger show F-001 --campaign demo", None),
        (f".venv/Scripts/python.exe -c \"print(open(r'{d / 'statement.md'}').read())\"", None),
        (f"type {d / 'proofs' / 'T-002.md'}", "deny"),
    ]:
        rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Bash", "skeptic", root, command=cmd))
        assert _decision(out) == expect, cmd
    # writes only under the round dir
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Write", "skeptic", root, file_path=str(d / "reviews" / "round1" / "skeptic_scratch" / "n.py"), content="x"))
    assert out is None
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Write", "skeptic", root, file_path=str(d / "proofs" / "T-001.md"), content="x"))
    assert _decision(out) == "deny"
    rows = HB.read_access_log(d / "reviews" / "round1")
    assert rows and all(r["role"].startswith("skeptic:") for r in rows)
    assert any(r["decision"] == "deny" and r["target"].endswith("plan.md") for r in rows)
    # judge and prover are not barriered
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "judge", root, file_path=str(d / "plan.md")))
    assert out is None
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "prover", root, file_path=str(d / "plan.md")))
    assert out is None
    # two skeptic agents claim distinct slots
    roles = {r["role"] for r in rows}
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "skeptic", root, agent_id="A2", file_path=str(d / "statement.md")))
    rows2 = HB.read_access_log(d / "reviews" / "round1")
    assert len({r["role"] for r in rows2}) == 2 and roles < {r["role"] for r in rows2}
    assert log.exists()


def test_barrier_replicator_stages_and_ambiguous(barrier, monkeypatch, capsys, tmp_path):
    root, d = _root(tmp_path, monkeypatch, {"max_review_rounds": 3})
    HB.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=1)
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "replicator", root, file_path=str(d / "proofs" / "T-001.md")))
    assert _decision(out) == "deny"
    _write(d / "reviews" / "round1" / "replicate" / "values.json", "{}")
    HB.commit_blind(d, 1, "reviews/round1/replicate/values.json")
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "replicator", root, file_path=str(d / "proofs" / "T-001.md")))
    assert out is None
    # a second open round makes the barrier ambiguous -> deny everything
    m = HB.load_manifest(d, 1)
    _write(d / "reviews" / "round2" / "barrier.json", json.dumps(m))
    rc, out, _ = _run(barrier, monkeypatch, capsys, _payload("Read", "replicator", root, file_path=str(d / "statement.md")))
    assert _decision(out) == "deny" and "more than one" in out["hookSpecificOutput"]["permissionDecisionReason"]


# ---------------------------------------------------------- guard_frozen --

def test_guard_frozen(guard, monkeypatch, capsys, tmp_path):
    root, d = _root(tmp_path, monkeypatch)
    rc, out, _ = _run(guard, monkeypatch, capsys, _payload("Edit", None, root, file_path=str(d / "experiments" / "scorer.py"), old_string="a", new_string="b"))
    assert _decision(out) == "deny" and "frozen" in out["hookSpecificOutput"]["permissionDecisionReason"]
    rc, out, _ = _run(guard, monkeypatch, capsys, _payload("Write", None, root, file_path=str(d / "HUMAN.md"), content="x"))
    assert _decision(out) == "deny"
    rc, out, _ = _run(guard, monkeypatch, capsys, _payload("Write", None, root, file_path=str(d / "experiments" / "other.py"), content="x"))
    assert out is None
    rc, out, _ = _run(guard, monkeypatch, capsys, _payload("Bash", None, root, command=f"cat {d / 'experiments' / 'scorer.py'}"))
    assert out is None
    rc, out, _ = _run(guard, monkeypatch, capsys, _payload("Bash", None, root, command=f"sed -i 's/1/2/' {d / 'experiments' / 'scorer.py'}"))
    assert _decision(out) == "deny"
    rc, out, _ = _run(guard, monkeypatch, capsys, _payload("Bash", None, root, command=".venv/Scripts/python.exe -m harness campaign attest demo --claim T-001 --human me"))
    assert _decision(out) == "deny" and "HUMAN" in out["hookSpecificOutput"]["permissionDecisionReason"]
    # outside the frozen phases only HUMAN.md is protected
    camp = json.loads((d / "campaign.json").read_text(encoding="utf-8"))
    camp["phase"] = "plan"
    _write(d / "campaign.json", json.dumps(camp))
    rc, out, _ = _run(guard, monkeypatch, capsys, _payload("Edit", None, root, file_path=str(d / "experiments" / "scorer.py"), old_string="a", new_string="b"))
    assert out is None
    rc, out, _ = _run(guard, monkeypatch, capsys, _payload("Edit", None, root, file_path=str(d / "HUMAN.md"), old_string="a", new_string="b"))
    assert _decision(out) == "deny"


# --------------------------------------------------------- gate_subagent --

def test_gate_subagent_blocks_then_releases(gate, monkeypatch, capsys, tmp_path):
    root, d = _root(tmp_path, monkeypatch)
    HB.open_round(d, 1, "T-001", ["proofs/T-001.md"], skeptics=1)
    payload = {"hook_event_name": "SubagentStop", "agent_type": "skeptic", "agent_id": "A1", "cwd": str(root)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert gate.main() == 2
    assert "subagent gate 1/2" in capsys.readouterr().err
    rdir = d / "reviews" / "round1"
    _write(rdir / "skeptic.md", "no verdict block here")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert gate.main() == 2
    capsys.readouterr()
    _write(rdir / "skeptic.md", "report\n```yaml\nrole: skeptic\nclaim: T-001\nround: 1\nverdict: fail\ncritical_errors:\n  - step: 2\n```\n")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert gate.main() == 0
    # judge needs the VERDICT line; releases after MAX blocks
    jp = {"hook_event_name": "SubagentStop", "agent_type": "judge", "agent_id": "J1", "cwd": str(root)}
    for expected in (2, 2, 0):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(jp)))
        assert gate.main() == expected
        capsys.readouterr()
    assert "released" in (rdir / "hook_errors.log").read_text(encoding="utf-8")
    # non-review agents are never gated
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "SubagentStop", "agent_type": "prover", "cwd": str(root)})))
    assert gate.main() == 0


def test_agent_frontmatter_hooks_point_to_real_scripts():
    root = Path(__file__).resolve().parent.parent
    for name in ("skeptic", "falsifier", "novelty-checker", "replicator", "judge"):
        text = (root / "agents" / f"{name}.md").read_text(encoding="utf-8")
        fm = text.split("\n---\n", 1)[0]
        assert "hooks:" in fm, name
        assert "gate_subagent.py" in fm, name
        if name != "judge":
            assert "barrier.py" in fm and "disallowedTools:" in fm, name
        for script in ("barrier.py", "gate_subagent.py"):
            if script in fm:
                assert (root / "hooks" / script).exists()
    for reg in (root / "hooks" / "hooks.json", root / ".claude" / "settings.json"):
        data = json.loads(reg.read_text(encoding="utf-8"))
        cmds = json.dumps(data["hooks"])
        for script in ("barrier.py", "guard_frozen.py", "gate_subagent.py", "gate_stop.py", "enforce_venv.py", "inject_context.py"):
            assert script in cmds, (reg, script)
        assert "SubagentStop" in data["hooks"]
    perms = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
    assert not any(p.startswith(("Bash(cat ", "Bash(grep ", "Bash(head ", "Bash(tail ")) for p in perms)
