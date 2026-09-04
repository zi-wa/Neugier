"""Round-1 Step 7/10 + Round-2 Y5: evolve hardening and upgrades."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness.search import cli, evolve


@pytest.fixture()
def campaign(tmp_path: Path) -> tuple[Path, evolve.EvolveConfig]:
    cdir = tmp_path / "camp"
    d = cdir / "experiments" / "evolve"
    d.mkdir(parents=True)
    assert cli.main(["template", str(d)]) == 0
    cfg = evolve.EvolveConfig.model_validate_json((d / "sidon100.json").read_text(encoding="utf-8"))
    (cdir / "campaign.json").write_text(json.dumps({"slug": "camp", "phase": "explore", "budgets": {}, "frozen": {}}), encoding="utf-8")
    return cdir, cfg


CHILD_REVERSED = (
    "def construct(N):\n"
    "    S, sums = [], set()\n"
    "    for x in range(N - 1, -1, -1):\n"
    "        new = {x + s for s in S} | {2 * x}\n"
    "        if new & sums: continue\n"
    "        S.append(x); sums |= new\n"
    "    return S\n"
)


def test_init_refuses_reinit_and_freezes_evaluator(campaign):
    cdir, cfg = campaign
    st = evolve.init(cdir, cfg)
    assert len(st.programs) == 1
    frozen = json.loads((cdir / "campaign.json").read_text(encoding="utf-8"))["frozen"]
    assert "experiments/evolve/scorer.py" in frozen
    again = evolve.init(cdir, cfg)  # idempotent
    assert len(again.programs) == 1
    with pytest.raises(RuntimeError, match="new-version"):
        evolve.init(cdir, cfg, force=True)
    v2 = evolve.init(cdir, cfg, new_version="2")
    assert v2.run_name == "sidon100-v2" and v2.root.name == "sidon100-v2" and len(v2.programs) == 1
    assert evolve.status(cdir, cfg)["name"] == "sidon100"


def test_noise_floor_applies_to_best_and_elites(tmp_path):
    cdir = tmp_path / "camp"
    (cdir / "experiments" / "evolve").mkdir(parents=True)
    (cdir / "experiments" / "evolve" / "scorer.py").write_text(
        "import importlib.util\n"
        "def evaluate(p):\n"
        "    spec = importlib.util.spec_from_file_location('c', p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "    return {'score': float(m.VALUE), 'valid': True, 'exact': False}\n", encoding="utf-8")
    (cdir / "experiments" / "evolve" / "seed.py").write_text("VALUE = 1.0\n", encoding="utf-8")
    cfg = evolve.EvolveConfig(name="noise", evaluator="experiments/evolve/scorer.py", seed_programs=["experiments/evolve/seed.py"],
                              noise_floor=0.05, known_best=1.02)
    evolve.init(cdir, cfg)
    req = evolve.next_generation(cdir, cfg, n=1, seed=0)
    Path(req["proposals"][0]["child_path"]).write_text("VALUE = 1.01\n", encoding="utf-8")
    summary = evolve.score_pending(cdir, cfg)
    assert summary["improved"] is False
    st = evolve.status(cdir, cfg)
    assert st["best"]["id"] == "p00001" and st["needs_exact_verification"] == 2
    assert st["beats_known_best"] is False and st["beats_known_best_unverified"] is False


def test_duplicate_child_rejected_without_evaluation_and_retry_capped(campaign):
    cdir, cfg = campaign
    cfg = cfg.model_copy(update={"max_novelty_attempts": 2})
    evolve.init(cdir, cfg)
    seed_code = (cdir / "experiments" / "evolve" / "seed.py").read_text(encoding="utf-8")
    req = evolve.next_generation(cdir, cfg, n=2, seed=0)
    dup, fresh = req["proposals"]
    Path(dup["child_path"]).write_text(seed_code + "\n# only a comment differs\n", encoding="utf-8")
    Path(fresh["child_path"]).write_text(CHILD_REVERSED, encoding="utf-8")
    summary = evolve.score_pending(cdir, cfg)
    assert [r["id"] for r in summary["rejected"]] == [dup["child_id"]] and summary["rejected"][0]["reason"].startswith("duplicate:")
    assert [e["id"] for e in summary["evaluated"]] == [fresh["child_id"]]
    assert summary["retry_slots"] == 1
    req2 = evolve.next_generation(cdir, cfg, n=2, seed=1)
    retry = req2["proposals"][0]
    assert retry.get("retry_of") == dup["child_id"] and retry["attempt"] == 2 and "MUST differ" in retry["note"]
    Path(retry["child_path"]).write_text(seed_code + "\n# still the same\n", encoding="utf-8")
    Path(req2["proposals"][1]["child_path"]).write_text(
        "def construct(N):\n    import math\n    p = 97\n    return sorted({(i * i) % p for i in range(1, 12)} & set(range(N)))\n",
        encoding="utf-8")
    summary2 = evolve.score_pending(cdir, cfg)
    assert [r["id"] for r in summary2["rejected"]] == [retry["child_id"]]
    assert summary2["retry_slots"] == 0  # attempt 2 of 2: no more retries
    st = evolve.status(cdir, cfg)
    assert st["rejected"] == 2


def test_cascade_stops_on_cheap_stage(tmp_path):
    cdir = tmp_path / "camp"
    d = cdir / "experiments" / "evolve"
    d.mkdir(parents=True)
    (d / "cheap.py").write_text(
        "import importlib.util\n"
        "def evaluate(p):\n"
        "    spec = importlib.util.spec_from_file_location('c', p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "    return {'score': float(m.VALUE > 0), 'valid': True, 'artifacts': 'sign check'}\n", encoding="utf-8")
    (d / "main.py").write_text(
        "import importlib.util\n"
        "def evaluate(p):\n"
        "    spec = importlib.util.spec_from_file_location('c', p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "    return {'score': str(int(m.VALUE)), 'valid': True, 'exact': True}\n", encoding="utf-8")
    (d / "seed.py").write_text("VALUE = 3\n", encoding="utf-8")
    cfg = evolve.EvolveConfig(name="casc", evaluator="experiments/evolve/main.py", seed_programs=["experiments/evolve/seed.py"],
                              cascade=[evolve.CascadeStage(evaluator="experiments/evolve/cheap.py", threshold=0.5)])
    st = evolve.init(cdir, cfg)
    seed = next(iter(st.programs.values()))
    assert seed.valid and seed.score == "3" and seed.stage_scores == [1.0]
    req = evolve.next_generation(cdir, cfg, n=1, seed=0)
    Path(req["proposals"][0]["child_path"]).write_text("VALUE = -7\n", encoding="utf-8")
    summary = evolve.score_pending(cdir, cfg)
    e = summary["evaluated"][0]
    assert e["valid"] is False and "cascade stage 1" in e["error"] and e["stage_scores"] == [0.0]
    (d / "cheap.py").write_text("def evaluate(p): return {'score': 1.0, 'valid': True}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="cascade evaluator"):
        evolve.next_generation(cdir, cfg, n=1)


def test_meta_request_written_and_recommendations_injected(campaign):
    cdir, cfg = campaign
    cfg = cfg.model_copy(update={"meta_interval": 1})
    st = evolve.init(cdir, cfg)
    req = evolve.next_generation(cdir, cfg, n=1, seed=0)
    Path(req["proposals"][0]["child_path"]).write_text(CHILD_REVERSED, encoding="utf-8")
    summary = evolve.score_pending(cdir, cfg)
    assert summary["meta_request"] and Path(summary["meta_request"]).exists()
    data = json.loads(Path(summary["meta_request"]).read_text(encoding="utf-8"))
    assert data["generation"] == 1 and "instructions" in data
    (st.root / "meta.md").write_text("# meta\n- prefer descending scans\n- avoid small N tweaks\n- x\n- y\n- z\n- too many\n", encoding="utf-8")
    req2 = evolve.next_generation(cdir, cfg, n=1, seed=1)
    assert req2["meta_recommendations"] == ["prefer descending scans", "avoid small N tweaks", "x", "y", "z"]
    assert evolve.status(cdir, cfg)["meta_recommendations"][0] == "prefer descending scans"


def test_islands_bins_and_migration(campaign):
    cdir, cfg = campaign
    cfg = cfg.model_copy(update={"islands": 2, "migration_interval": 2, "seed_programs": cfg.seed_programs * 2})
    st = evolve.init(cdir, cfg)
    islands = sorted(p.island for p in st.programs.values())
    assert islands == [0, 1] and all(p.bin_key.startswith(f"i{p.island}|") for p in st.programs.values())
    req1 = evolve.next_generation(cdir, cfg, n=2, seed=0)
    assert [p["island"] for p in req1["proposals"]] == [0, 1] and req1["migrated"] == []
    for prop in req1["proposals"]:
        Path(prop["child_path"]).write_text(CHILD_REVERSED if prop["island"] == 0 else CHILD_REVERSED.replace("2 * x", "x + x"), encoding="utf-8")
    evolve.score_pending(cdir, cfg)
    req2 = evolve.next_generation(cdir, cfg, n=2, seed=1)
    assert len(req2["migrated"]) == 2
    st = evolve.EvolveStore.load(cdir, cfg)
    moved = [st.programs[pid] for pid in req2["migrated"]]
    assert all(m.migrated_from and m.island == (st.programs[m.migrated_from].island + 1) % 2 for m in moved)


def test_checkpoint_resume_and_mine(campaign):
    cdir, cfg = campaign
    evolve.init(cdir, cfg)
    req = evolve.next_generation(cdir, cfg, n=1, seed=0)
    Path(req["proposals"][0]["child_path"]).write_text(CHILD_REVERSED, encoding="utf-8")
    evolve.score_pending(cdir, cfg)
    cp = evolve.checkpoint(cdir, cfg)
    assert cp.name == "gen0001" and (cp / "population.jsonl").exists()
    evolve.next_generation(cdir, cfg, n=1, seed=2)
    assert evolve.status(cdir, cfg)["generation"] == 2
    out = evolve.resume(cdir, cfg)
    assert out["restored_from"] == "gen0001" and evolve.status(cdir, cfg)["generation"] == 1
    md = evolve.mine(cdir, cfg, top=2, oeis=False)
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# Structure mining") and "```python" in text and "Integer sequences found" in text
    with pytest.raises(RuntimeError, match="no checkpoint"):
        evolve.resume(cdir, cfg, from_gen=99)


def test_run_headless_argv_and_stdin_prompt(campaign, monkeypatch):
    cdir, cfg = campaign
    evolve.init(cdir, cfg)
    calls: list[dict] = []
    real_run = subprocess.run

    def fake_run(argv, **kwargs):
        if not (isinstance(argv, list) and argv and str(argv[0]).startswith("claude")):
            return real_run(argv, **kwargs)  # the evaluator subprocess is real
        calls.append({"argv": argv, "kwargs": kwargs})
        Path(kwargs["input"].rsplit("exactly this path: ", 1)[1].split("\n", 1)[0]).write_text(CHILD_REVERSED, encoding="utf-8")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    summaries = evolve.run_headless(cdir, cfg.model_copy(update={"children_per_gen": 1}), generations=1, claude_bin="claude-not-on-path")
    assert len(calls) == 1
    argv, kwargs = calls[0]["argv"], calls[0]["kwargs"]
    assert argv[0] == "claude-not-on-path" and "-p" in argv and "--allowedTools" in argv and "shell" not in kwargs
    assert "--disallowedTools" in argv and "Bash,Edit,Agent" in argv
    assert "Write the child program" in kwargs["input"] and kwargs["input"].startswith(cfg.mutation_prompt[:30])
    assert summaries[0]["evaluated"] and summaries[0]["evaluated"][0]["valid"]
    assert list((cdir / "experiments" / "evolve" / "sidon100" / "programs").glob("*.prompt.md"))


def test_cli_new_commands(campaign, capsys):
    cdir, cfg = campaign
    cfgp = str(cdir / "experiments" / "evolve" / "sidon100.json")
    assert cli.main(["init", "--dir", str(cdir), "--config", cfgp]) == 0
    capsys.readouterr()
    assert cli.main(["checkpoint", "--dir", str(cdir), "--config", cfgp]) == 0
    assert cli.main(["mine", "--dir", str(cdir), "--config", cfgp, "--no-oeis"]) == 0
    assert cli.main(["meta-request", "--dir", str(cdir), "--config", cfgp]) == 0
    assert cli.main(["init", "--dir", str(cdir), "--config", cfgp, "--new-version", "b"]) == 0
    capsys.readouterr()
    assert cli.main(["status", "--dir", str(cdir), "--config", cfgp, "--version", "b"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["name"] == "sidon100-vb" and st["population"] == 1
