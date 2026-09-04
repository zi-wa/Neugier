"""The one-line installers: they must parse, stay containment-safe, and agree with the README."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "install.sh"
PS1 = ROOT / "install.ps1"


def test_installers_exist_and_are_documented():
    assert SH.is_file() and PS1.is_file()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_ko = (ROOT / "README_ko.md").read_text(encoding="utf-8")
    for text in (readme, readme_ko):
        assert "install.sh | sh" in text
        assert "install.ps1 | iex" in text
        # the raw URL must point at this repository's default branch
        assert "raw.githubusercontent.com/zi-wa/Neugier/main/install.sh" in text


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX shell available")
def test_install_sh_is_valid_posix_shell():
    proc = subprocess.run(["sh", "-n", str(SH)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_installers_do_not_touch_anything_global():
    """Rule R2: an installer may create only the clone directory; no sudo, no PATH, no profile edits."""
    forbidden = [
        r"\bsudo\b", r"\bsetx\b", r"\bnpm\s+i(nstall)?\s+-g\b", r"pip\s+install\s+(?!-r|-e|--upgrade\s+pip)",
        r"HKEY_", r"\bReg-?Add\b", r"\$PROFILE", r"/etc/profile", r"\.bashrc", r"\.zshrc",
        r"\$env:PATH\s*=", r"Add-Content.*PATH",
    ]
    for path in (SH, PS1):
        # scan code only: both files *describe* what they refuse to do ("nothing runs with sudo")
        text = chr(10).join(line.split("#", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())
        for pattern in forbidden:
            assert not re.search(pattern, text, re.IGNORECASE), f"{path.name} matches {pattern!r}"


def test_installers_share_the_same_contract():
    sh, ps1 = SH.read_text(encoding="utf-8"), PS1.read_text(encoding="utf-8")
    for knob in ("NEUGIER_DIR", "NEUGIER_REPO", "NEUGIER_REF", "NEUGIER_NO_BOOTSTRAP"):
        assert knob in sh and knob in ps1, knob
    assert "scripts/bootstrap.sh" in sh
    assert "bootstrap.ps1" in ps1
    # both refuse to write into a directory that is not a checkout
    assert "not a git checkout" in sh and "not a git checkout" in ps1


@pytest.mark.skipif(shutil.which("git") is None or shutil.which("sh") is None, reason="needs git and sh")
def test_install_sh_clones_and_then_updates(tmp_path):
    """End-to-end against a local clone source, with the heavy bootstrap skipped."""
    target = tmp_path / "checkout"
    env = {
        "PATH": __import__("os").environ["PATH"],
        "HOME": str(tmp_path),
        "NEUGIER_DIR": str(target),
        "NEUGIER_REPO": str(ROOT),
        "NEUGIER_NO_BOOTSTRAP": "1",
    }
    first = subprocess.run(["sh", str(SH)], capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stderr
    assert (target / "harness").is_dir() and (target / ".git").exists()
    assert "cloning into" in first.stdout

    second = subprocess.run(["sh", str(SH)], capture_output=True, text=True, env=env)
    assert second.returncode == 0, second.stderr
    assert "updating existing checkout" in second.stdout

    # a non-checkout directory is refused rather than overwritten
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "keep.txt").write_text("mine", encoding="utf-8")
    env["NEUGIER_DIR"] = str(plain)
    refused = subprocess.run(["sh", str(SH)], capture_output=True, text=True, env=env)
    assert refused.returncode != 0 and "not a git checkout" in refused.stderr
    assert (plain / "keep.txt").read_text(encoding="utf-8") == "mine"
