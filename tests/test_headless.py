"""Round-1 Step 14: headless campaign driver (subprocess monkeypatched)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import harness
import harness.campaign as campaign
from harness import headless


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")


class _R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_headless_stops_on_done_and_logs(monkeypatch):
    path = campaign.create("demo", "Demo")
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        n = len(calls)
        with open(path / "log.md", "a", encoding="utf-8") as fh:
            fh.write(f"iteration {n}\n")
        if n == 2:
            campaign.set_phase("demo", "done")
        return _R(0, '{"result": "ok"}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    hist = headless.run_campaign("demo", max_iterations=5, max_turns=7, command="/research", claude_bin="claude-x")
    assert len(hist) == 2 and hist[-1]["stop"] == "done" and hist[-1]["phase_after"] == "done"
    argv, kwargs = calls[0]["argv"], calls[0]["kwargs"]
    assert argv[0] == "claude-x" and argv[1] == "-p" and "--max-turns" in argv and "7" in argv and "shell" not in kwargs
    assert kwargs["input"] == "/research --resume --slug demo"
    lines = (path / "headless.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["progressed"] is True


def test_headless_stall_and_blocked(monkeypatch):
    path = campaign.create("demo", "Demo")
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _R(0, ""))
    hist = headless.run_campaign("demo", max_iterations=10, stall_limit=2)
    assert len(hist) == 2 and hist[-1]["stop"].startswith("stalled")
    (path / "blocked.md").write_text("stuck", encoding="utf-8")
    hist = headless.run_campaign("demo", max_iterations=10)
    assert len(hist) == 1 and hist[-1]["stop"] == "blocked.md"
    with pytest.raises(FileNotFoundError):
        headless.run_campaign("nope")
    assert headless.main(["nope"]) == 1
    (path / "blocked.md").unlink()
    assert headless.main(["demo", "--max-iterations", "1", "--command", "/neugier:research", "--plugin-dir", str(harness.ROOT)]) == 2
