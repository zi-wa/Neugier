"""Round-2 Step 29: eval cases parse, reference real files, scaffold, and the in-house runner grades outputs."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

import harness
from harness import evals

EVALS = Path(harness.ROOT) / "evals"


def test_cases_parse_and_reference_existing_files():
    cases = evals.load_cases()
    names = {c["name"] for c in cases}
    assert {"review-planted-circular", "falsify-finds-counterexample", "paper-check-rejects-unbound-theorem", "barrier-denies-plan-read"} <= names
    for c in cases:
        d = c["_dir"]
        assert (d / "prompt.md").exists() and (d / "graders").is_dir() and list((d / "graders").glob("*.md"))
        assert c["_prompt"].strip() and int(c.get("runs", 3)) >= 1 and int(c.get("max_turns", 30)) > 0
        assert (c.get("neugier") or {}).get("graders"), c["name"]
        scaffold = (c.get("context") or {}).get("scaffold_script", "")
        assert "evals/_lib/scaffold.py" in scaffold and c["name"] in scaffold
        for g in (d / "graders").glob("*.md"):
            fm = yaml.safe_load(g.read_text(encoding="utf-8").split("---", 2)[1])
            assert fm.get("type") in ("regex", "tool_used", "file_exists", "llm")
    assert (EVALS / "README.md").exists()


def test_scaffold_into_tmp(tmp_path):
    import sys

    sys.path.insert(0, str(EVALS / "_lib"))
    from scaffold import scaffold

    dest = scaffold("paper-check-rejects-unbound-theorem", tmp_path)
    assert (dest / "ledger.json").exists() and (dest / "paper" / "main.tex").exists()
    assert (tmp_path / "campaigns" / "ACTIVE").read_text(encoding="utf-8") == "eval-paper-check-rejects-unbound-theorem"


def test_runner_grades_fake_claude_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CACHE", tmp_path / "cache")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        ws = Path(kwargs["cwd"])
        camp = next(ws.glob("campaigns/eval-*"))
        if "--plugin-dir" in argv:  # the with-plugin arm "succeeds"
            (camp / "paper").mkdir(exist_ok=True)
            (camp / "paper" / "check.json").write_text(json.dumps({"ok": False, "errors": [{"code": "E_CLAIM_UNBOUND"}]}), encoding="utf-8")

        class R:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    cases = evals.load_cases("paper-check-*")
    agg = evals.run_cases(cases, runs=1, base=tmp_path / "ws", results_dir=tmp_path / "results")
    c = agg["cases"][0]
    assert c["mean"]["with"] == 1.0 and c["mean"]["without"] == 0.0 and c["delta_with_minus_without"] == 1.0
    assert (tmp_path / "results" / "aggregate.json").exists()
    argv, kwargs = calls[0]
    assert "-p" in argv and "shell" not in kwargs and kwargs["input"].startswith("The campaign directory")
    assert (tmp_path / "ws" / "paper-check-rejects-unbound-theorem" / "with" / "run0" / "hooks" / "barrier.py").exists()
    assert not (tmp_path / "ws" / "paper-check-rejects-unbound-theorem" / "without" / "run0" / ".claude").exists()
    dry = evals.run_cases(evals.load_cases("falsify-*"), runs=1, base=tmp_path / "ws2", results_dir=tmp_path / "r2", dry_run=True)
    assert dry["cases"][0]["mean"]["with"] == 0.0
    barrier = evals.load_cases("barrier-*")[0]
    agg2 = evals.run_cases([barrier], runs=1, base=tmp_path / "ws3", results_dir=tmp_path / "r3", dry_run=True)
    assert list(agg2["cases"][0]["arms"]) == ["with"]  # requires_plugin: no without arm
