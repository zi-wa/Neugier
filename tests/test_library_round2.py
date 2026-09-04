"""Round-2 library rules: add-fact verifies excerpts against the campaign cache."""
from __future__ import annotations

from pathlib import Path

import pytest

import harness
from harness.library import cli as library_cli
from harness.library import memory


@pytest.fixture(autouse=True)
def _tmp_library(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "LIBRARY", tmp_path / "library")
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(harness, "CACHE", tmp_path / "dotcache")
    yield


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


EXC = "the number of monochromatic triangles is at least n(n-1)(n-5)/24"


def test_add_fact_records_provenance(tmp_path):
    camp = tmp_path / "campaigns" / "demo"
    _write(camp / "cache" / "goodman1959.txt", "Goodman proved that " + EXC + " for every 2-colouring.")
    rec = memory.add_fact("Goodman's bound.", "goodman1959", EXC, campaign="demo", campaign_dir=camp, require_verified=True)
    assert rec["verified"] is True and rec["source_sha256"] and len(rec["excerpt_hash"]) == 12
    with pytest.raises(memory.FactUnverified):
        memory.add_fact("Another fact.", "ghost", EXC, campaign_dir=camp, require_verified=True)
    loose = memory.add_fact("Another fact.", "ghost", EXC, campaign_dir=camp)
    assert loose["verified"] is None


def test_cli_add_fact_requires_verification_unless_opted_out(tmp_path, capsys):
    camp = tmp_path / "campaigns" / "demo"
    _write(camp / "cache" / "goodman1959.txt", "text " + EXC + " text")
    ok = library_cli.main(["add-fact", "--statement", "Goodman.", "--source-id", "goodman1959", "--excerpt", EXC, "--campaign", "demo"])
    assert ok == 0
    bad = library_cli.main(["add-fact", "--statement", "Ghost.", "--source-id", "ghost", "--excerpt", EXC, "--campaign", "demo"])
    assert bad == 1
    assert "not verified" in capsys.readouterr().err
    assert library_cli.main([
        "add-fact", "--statement", "Ghost.", "--source-id", "ghost", "--excerpt", EXC, "--campaign", "demo", "--unverified-ok",
    ]) == 0
    facts = memory.all("facts")
    assert [f["verified"] for f in facts] == [True, None]
