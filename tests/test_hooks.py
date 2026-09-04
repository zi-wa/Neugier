"""Tests for the Neugier hook scripts (imported as modules; no live hook invocation)."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(HOOKS))
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def enforce():
    return _load("enforce_venv")


@pytest.mark.parametrize(
    "cmd",
    [
        "pip install requests",
        "pip3 install numpy",
        "python -m pip install sympy",
        "py -m pip install sympy",
        "npm install -g typescript",
        "npm i --global eslint",
        "winget install Git.Git",
        "choco install python",
        "scoop install lean",
        "cargo install ripgrep",
        "rustup default stable",
        "setx PATH \"%PATH%;C:\\\\foo\"",
        "reg add HKCU\\\\Software\\\\Foo /v Bar /d 1",
        "uv pip install --system sympy",
        "elan default leanprover/lean4:stable",
        "code ~/.claude/settings.json",
        "python edit.py C:\\\\Users\\\\admin\\\\.claude\\\\settings.json",
    ],
)
def test_denied_commands(enforce, cmd):
    assert enforce.violation(cmd) is not None, cmd


@pytest.mark.parametrize(
    "cmd",
    [
        "uv pip install --python .venv/Scripts/python.exe sympy",
        "uv pip install sympy",
        ".venv/Scripts/python.exe -m pip install sympy",
        ".venv\\Scripts\\python.exe -m pip install -r requirements.txt",
        "git status",
        "ls -la",
        ".venv/Scripts/python.exe -m harness ledger summary --campaign x",
        "ELAN_HOME=.lean/elan elan default stable",
        "cat .claude/settings.json",
        "npm install",
        "npx tsc",
        "echo pip-installed already",
    ],
)
def test_allowed_commands(enforce, cmd):
    assert enforce.violation(cmd) is None, cmd


def test_main_emits_deny_json(enforce, monkeypatch, capsys):
    payload = {"tool_name": "Bash", "tool_input": {"command": "pip install requests"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert enforce.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "R2" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_main_silent_on_allowed(enforce, monkeypatch, capsys):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git diff"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert enforce.main() == 0
    assert capsys.readouterr().out == ""


def test_main_ignores_other_tools(enforce, monkeypatch, capsys):
    payload = {"tool_name": "Write", "tool_input": {"command": "pip install x"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert enforce.main() == 0
    assert capsys.readouterr().out == ""


def test_inject_context_no_campaign(tmp_path, monkeypatch, capsys):
    inject = _load("inject_context")
    (tmp_path / "campaigns").mkdir()
    payload = {"hook_event_name": "SessionStart", "cwd": str(tmp_path)}
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert inject.main() == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "standing instructions" in ctx and "No active campaign" in ctx


def test_inject_context_prompt_brief_without_campaign_is_silent(tmp_path, monkeypatch, capsys):
    inject = _load("inject_context")
    (tmp_path / "campaigns").mkdir()
    payload = {"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path)}
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert inject.main() == 0
    assert capsys.readouterr().out == ""


def test_gate_stop_without_gate_marker_allows(tmp_path, monkeypatch):
    gate = _load("gate_stop")
    (tmp_path / "campaigns" / "demo").mkdir(parents=True)
    (tmp_path / "campaigns" / "ACTIVE").write_text("demo", encoding="utf-8")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path)})))
    assert gate.main() == 0


def test_gate_stop_blocks_when_criteria_unmet(tmp_path, monkeypatch, capsys):
    gate = _load("gate_stop")
    cdir = tmp_path / "campaigns" / "demo"
    cdir.mkdir(parents=True)
    (tmp_path / "campaigns" / "ACTIVE").write_text("demo", encoding="utf-8")
    (cdir / ".gate").write_text("scout", encoding="utf-8")
    (cdir / "campaign.json").write_text(json.dumps({"phase": "scout"}), encoding="utf-8")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    # simulate the harness check reporting one unmet criterion
    monkeypatch.setattr(gate, "run_harness", lambda root, args, timeout=30: (1, "- portfolio.md missing"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path)})))
    assert gate.main() == 2
    err = capsys.readouterr().err
    assert "portfolio.md missing" in err and "gate 1/" in err
    assert (cdir / ".gate_attempts").read_text(encoding="utf-8") == "1"


def test_gate_stop_releases_when_criteria_met(tmp_path, monkeypatch):
    gate = _load("gate_stop")
    cdir = tmp_path / "campaigns" / "demo"
    cdir.mkdir(parents=True)
    (tmp_path / "campaigns" / "ACTIVE").write_text("demo", encoding="utf-8")
    (cdir / ".gate").write_text("scout", encoding="utf-8")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(gate, "run_harness", lambda root, args, timeout=30: (0, ""))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path)})))
    assert gate.main() == 0
    assert not (cdir / ".gate").exists()


def test_gate_stop_gives_up_after_max_blocks(tmp_path, monkeypatch):
    gate = _load("gate_stop")
    cdir = tmp_path / "campaigns" / "demo"
    cdir.mkdir(parents=True)
    (tmp_path / "campaigns" / "ACTIVE").write_text("demo", encoding="utf-8")
    (cdir / ".gate").write_text("scout", encoding="utf-8")
    (cdir / ".gate_attempts").write_text(str(gate.MAX_BLOCKS), encoding="utf-8")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(gate, "run_harness", lambda root, args, timeout=30: (1, "- still missing"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path)})))
    assert gate.main() == 0
    assert (cdir / "blocked.md").exists() and not (cdir / ".gate").exists()
