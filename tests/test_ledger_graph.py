"""Round-2 Step 24: blueprint statuses and graph rendering (X5b)."""
from __future__ import annotations

from pathlib import Path

import harness.ledger.cli as ledger_cli
from harness.ledger import graph as G
from harness.ledger.ledger import LedgerStore
from harness.ledger.schema import Evidence


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _pass_round(store: LedgerStore, cid: str, d: Path) -> None:
    for role in ("skeptic", "falsifier", "novelty", "replicator", "judge"):
        store.add_evidence(cid, Evidence(type="referee", role=role, verdict="pass", round=1, agent_id="SK-1" if role == "skeptic" else None), d)
    store.add_evidence(cid, Evidence(type="referee", role="skeptic", verdict="pass", round=1, agent_id="SK-2"), d)


def _drafted(store: LedgerStore, cid: str, d: Path) -> None:
    _write(d / "proofs" / f"{cid}.md", "**Step 1.** (algebra) x.")
    store.add_evidence(cid, Evidence(type="proof", path=f"proofs/{cid}.md"), d)
    store.promote(cid, "proof-drafted", d)


def test_blueprint_statuses_transitive(tmp_path):
    d = tmp_path / "camp"
    d.mkdir()
    (d / "cache").mkdir()
    store = LedgerStore(d / "ledger.json", campaign="camp")
    defn = store.add(kind="definition", statement="D.")
    _write(d / "cache" / "src.txt", "the classical bound |S+S| >= 2|S| - 1 holds for all finite S")
    fact = store.add(kind="fact", statement="F.", status="known-in-literature",
                     evidence=Evidence(type="excerpt", source_id="src", excerpt="the classical bound |S+S| >= 2|S| - 1 holds"), campaign_dir=d)
    lem = store.add(kind="lemma", statement="L.", depends_on=[defn.id, fact.id])
    thm = store.add(kind="theorem", statement="T.", depends_on=[lem.id])
    idea = store.add(kind="idea", statement="I.")
    conj = store.add(kind="conjecture", statement="C.", status="conjectured", depends_on=[defn.id])
    st = G.blueprint_statuses(store)
    assert st[defn.id] == "defined" and st[fact.id] == "mathlib" and st[idea.id] == "can_state" and st[conj.id] == "stated"
    assert st[lem.id] == "can_state" and st[thm.id] == "can_state"
    _drafted(store, lem.id, d)
    assert G.blueprint_status(store, lem.id) == "can_prove"
    _pass_round(store, lem.id, d)
    store.promote(lem.id, "referee-passed", d)
    assert G.blueprint_status(store, lem.id) == "fully_proved"
    _drafted(store, thm.id, d)
    _pass_round(store, thm.id, d)
    store.promote(thm.id, "referee-passed", d)
    assert G.blueprint_status(store, thm.id) == "fully_proved" and thm.id in G.fully_proved(store)
    # an assumption blocks fully_proved even when the dependency is passed
    store.get(thm.id).tags.append(f"assumes:{lem.id}")
    store.save()
    assert G.blueprint_status(store, thm.id) == "proved"
    store.get(thm.id).tags.remove(f"assumes:{lem.id}")
    # staleness cascades: editing the lemma statement demotes the theorem
    store.update_statement(lem.id, "L (sharpened).")
    st = G.blueprint_statuses(store)
    assert st[thm.id] == "can_prove" and store.get(thm.id).stale
    # refuting the lemma makes dependents not_ready
    _write(d / "experiments" / "cex.json", "{}")
    store.add_evidence(lem.id, Evidence(type="falsification", path="experiments/cex.json"), d)
    store.promote(lem.id, "refuted", d)
    st = G.blueprint_statuses(store)
    assert st[lem.id] == "refuted" and st[thm.id] == "not_ready"


def test_render_mermaid_and_dot_and_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger_cli, "CAMPAIGNS", tmp_path / "campaigns")
    d = tmp_path / "campaigns" / "demo"
    d.mkdir(parents=True)
    store = LedgerStore(d / "ledger.json", campaign="demo")
    lem = store.add(kind="lemma", statement="A helper lemma about sums.")
    thm = store.add(kind="theorem", statement="The main theorem.", depends_on=[lem.id], tags=[f"assumes:{lem.id}"])
    store.get(thm.id).stale = True
    store.save()
    mer = G.render_mermaid(store)
    assert mer.startswith("flowchart TD") and "L_001" in mer and "-" not in mer.split("\n")[-2].split(" ")[0].strip("  ")
    assert "L_001 -.-> T_001" in mer and "stroke-dasharray" in mer and "classDef fully_proved" in mer
    dot = G.render_dot(store)
    assert dot.startswith("digraph") and '"L-001" -> "T-001" [style=dashed' in dot
    assert ledger_cli.main(["--campaign", "demo", "graph", "--format", "mermaid"]) == 0
    assert "flowchart TD" in capsys.readouterr().out
    out = tmp_path / "g.dot"
    assert ledger_cli.main(["--campaign", "demo", "graph", "--format", "dot", "--out", str(out)]) == 0
    assert out.exists()
    assert ledger_cli.main(["--campaign", "demo", "graph"]) == 0
    assert "-> can_state" in capsys.readouterr().out
