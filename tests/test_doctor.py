"""Round-1 Step 12: harness doctor."""
from __future__ import annotations

import json
from pathlib import Path

import harness
from harness import doctor


def test_doctor_on_this_repo_offline(capsys):
    checks = doctor.run_all(harness.ROOT, offline=True)
    names = {c.name for c in checks}
    assert {"venv", "utf8", "python", "tectonic", "hooks:hooks/hooks.json", "hooks:.claude/settings.json", "agent-hooks",
            "link:.claude/agents", "link:.claude/skills", "claude", "git", "library", "campaigns/ACTIVE", "lean", "plugin-evals"} <= names
    by = {c.name: c for c in checks}
    assert by["hooks:hooks/hooks.json"].ok and by["hooks:.claude/settings.json"].ok and by["agent-hooks"].ok
    assert by["python"].ok and by["venv"].ok
    assert doctor.main(["--offline", "--json"]) in (0, 1)
    data = json.loads(capsys.readouterr().out)
    assert "checks" in data and any(c["name"] == "lean" for c in data["checks"])


def test_doctor_detects_broken_wiring(tmp_path):
    root = tmp_path / "proj"
    (root / "hooks").mkdir(parents=True)
    (root / ".claude").mkdir()
    (root / "agents").mkdir()
    (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/missing.py\""}]}]}}), encoding="utf-8")
    (root / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    (root / "agents" / "skeptic.md").write_text("---\nname: skeptic\nhooks:\n  PreToolUse:\n    - hooks:\n        - type: command\n          command: python \"${CLAUDE_PROJECT_DIR}/hooks/barrier.py\"\n---\nbody\n", encoding="utf-8")
    checks = {c.name: c for c in doctor.run_all(root, offline=True)}
    assert not checks["venv"].ok and "bootstrap" in checks["venv"].fix
    assert not checks["hooks:hooks/hooks.json"].ok and "missing.py" in checks["hooks:hooks/hooks.json"].detail
    assert not checks["hooks:.claude/settings.json"].ok and "invalid JSON" in checks["hooks:.claude/settings.json"].detail
    assert not checks["agent-hooks"].ok and "barrier.py missing" in checks["agent-hooks"].detail
    assert not checks["link:.claude/agents"].ok
    assert doctor.main(["--offline", "--root", str(root)]) == 1
