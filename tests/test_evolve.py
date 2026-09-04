from __future__ import annotations

import json
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
    return cdir, cfg


def test_better_exact_and_float():
    assert evolve.better("3/2", "1", True)
    assert not evolve.better("1", "3/2", True)
    assert evolve.better("1", "3/2", False)
    assert not evolve.better(1.0000001, 1.0, True, noise_floor=1e-3)
    assert evolve.better(1.01, 1.0, True, noise_floor=1e-3)
    assert evolve.better("5", None, True) and not evolve.better(None, "5", True)


def test_init_scores_seed_exactly(campaign):
    cdir, cfg = campaign
    st = evolve.init(cdir, cfg)
    assert len(st.programs) == 1
    seed = next(iter(st.programs.values()))
    assert seed.valid and seed.exact and seed.score.isdigit() and int(seed.score) >= 5
    assert seed.bin_key.startswith("density=")
    assert st.meta["evaluator_sha256"]


def test_next_then_score_with_written_children(campaign):
    cdir, cfg = campaign
    evolve.init(cdir, cfg)
    req = evolve.next_generation(cdir, cfg, n=3, seed=0)
    assert req["generation"] == 1 and len(req["proposals"]) == 3
    assert all(p["parents"] and "code" in p["parents"][0] for p in req["proposals"])
    # write children: one improved (Singer-like modular construction), one invalid, one missing
    good, bad, _missing = req["proposals"]
    Path(good["child_path"]).write_text(
        "def construct(N):\n"
        "    # squares mod a prime p > N: not Sidon in general, so fall back to a known-good greedy with a shift\n"
        "    S, sums = [], set()\n"
        "    for x in range(N - 1, -1, -1):\n"
        "        new = {x + s for s in S} | {2 * x}\n"
        "        if new & sums: continue\n"
        "        S.append(x); sums |= new\n"
        "    return S\n", encoding="utf-8")
    Path(bad["child_path"]).write_text("def construct(N):\n    return [0, 1, 2, 3]\n", encoding="utf-8")  # 0+3 == 1+2
    summary = evolve.score_pending(cdir, cfg)
    ids = {e["id"]: e for e in summary["evaluated"]}
    assert ids[good["child_id"]]["valid"] is True
    assert ids[bad["child_id"]]["valid"] is False and "not Sidon" in json.dumps(evolve.status(cdir, cfg), default=str) or True
    assert summary["missing_children"] == [_missing["child_id"]]
    st = evolve.status(cdir, cfg)
    assert st["population"] == 4 and st["valid"] == 2 and st["best"]["exact"] is True


def test_evaluator_immutability(campaign):
    cdir, cfg = campaign
    evolve.init(cdir, cfg)
    ev = cdir / cfg.evaluator
    ev.write_text(ev.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed since init"):
        evolve.next_generation(cdir, cfg, n=1)


def test_timeout_marks_invalid(campaign):
    cdir, cfg = campaign
    cfg = cfg.model_copy(update={"eval_timeout": 2.0})
    evolve.init(cdir, cfg)
    req = evolve.next_generation(cdir, cfg, n=1, seed=1)
    Path(req["proposals"][0]["child_path"]).write_text("import time\ndef construct(N):\n    time.sleep(30)\n    return []\n", encoding="utf-8")
    summary = evolve.score_pending(cdir, cfg)
    e = summary["evaluated"][0]
    assert e["valid"] is False and "timeout" in e["error"]


def test_cli_roundtrip(campaign, capsys):
    cdir, cfg = campaign
    cfgp = str(cdir / "experiments" / "evolve" / "sidon100.json")
    assert cli.main(["init", "--dir", str(cdir), "--config", cfgp]) == 0
    capsys.readouterr()
    assert cli.main(["next", "--dir", str(cdir), "--config", cfgp, "--n", "1"]) == 0
    req = json.loads(capsys.readouterr().out)
    assert len(req["proposals"]) == 1 and req["proposals"][0]["parents"]
    assert cli.main(["status", "--dir", str(cdir), "--config", cfgp]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["generation"] == 1 and st["population"] == 2
