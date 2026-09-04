"""Blueprint-style dependency graph of the claim ledger (Round-2 Step 24 / X5b).

The Lean blueprint tool (``leanprover-community/leanblueprint``) colours each
node of a project's dependency graph by a status lattice — ``can_state``,
``stated``, ``not_ready``, ``can_prove``, ``proved``, ``fully_proved``,
``defined``, ``mathlib`` — where **fully_proved** means the node *and every
dependency* are done. Neugier computes the same lattice from the ledger:

============================ =====================================================
ledger                        blueprint status (colour)
============================ =====================================================
kind ``definition``           ``defined`` (#B0ECA3)
``known-in-literature``       ``mathlib`` (darkgreen)
``refuted`` / ``dead``        ``refuted`` (#F4CCCC, red stroke)
a dependency missing/refuted  ``not_ready`` (#FFAA33)
referee-passed/formalized,
 all deps fully proved,
 no ``assumes:``, not stale   ``fully_proved`` (#1CAC78)
referee-passed/formalized     ``proved`` (#9CEC8B)
``proof-drafted``             ``can_prove`` (#A3D6FF)
conjectured/num.-supported    ``stated`` (green)
idea / question               ``can_state`` (blue)
============================ =====================================================

so a green theorem can never rest on an amber lemma. ``render_mermaid`` /
``render_dot`` draw the graph (``harness ledger graph --format mermaid``); the
paper's ``conditional`` environment is required for referee-passed claims that
are not ``fully_proved`` (:mod:`harness.paper.check`).
"""
from __future__ import annotations

COLORS = {
    "fully_proved": "#1CAC78",
    "proved": "#9CEC8B",
    "can_prove": "#A3D6FF",
    "stated": "#7ED957",
    "can_state": "#6FA8DC",
    "not_ready": "#FFAA33",
    "defined": "#B0ECA3",
    "mathlib": "#006400",
    "refuted": "#F4CCCC",
}
DONE = {"referee-passed", "formalized", "known-in-literature"}


def _assumed(claim) -> set[str]:
    return {t.split(":", 1)[1] for t in claim.tags if t.startswith("assumes:")}


def blueprint_statuses(store) -> dict[str, str]:
    """Blueprint status for every claim id (memoised transitive computation)."""
    claims = store.ledger.claims
    memo: dict[str, str] = {}
    visiting: set[str] = set()

    def status_of(cid: str) -> str:
        if cid in memo:
            return memo[cid]
        c = claims.get(cid)
        if c is None:
            return "missing"
        if cid in visiting:  # cycle: treat as not ready
            return "not_ready"
        visiting.add(cid)
        try:
            if c.kind == "definition":
                out = "defined"
            elif c.status == "known-in-literature":
                out = "mathlib"
            elif c.status in ("refuted", "dead"):
                out = "refuted"
            else:
                dep_status = {d: status_of(d) for d in c.depends_on}
                if any(s in ("missing", "refuted", "not_ready") for s in dep_status.values()):
                    out = "not_ready"
                elif c.status in ("referee-passed", "formalized"):
                    assumed = _assumed(c)
                    deps_full = all(
                        s in ("fully_proved", "mathlib", "defined") and d not in assumed for d, s in dep_status.items()
                    )
                    out = "fully_proved" if deps_full and not assumed and not c.stale else "proved"
                elif c.status == "proof-drafted":
                    out = "can_prove"
                elif c.status in ("conjectured", "numerically-supported"):
                    out = "stated"
                else:
                    out = "can_state"
        finally:
            visiting.discard(cid)
        memo[cid] = out
        return out

    for cid in claims:
        status_of(cid)
    return memo


def blueprint_status(store, cid: str) -> str:
    return blueprint_statuses(store).get(cid, "missing")


def fully_proved(store) -> set[str]:
    return {cid for cid, s in blueprint_statuses(store).items() if s == "fully_proved"}


def _node_id(cid: str) -> str:
    return cid.replace("-", "_").replace(".", "_")


def _label(claim) -> str:
    stmt = " ".join(claim.statement.split())
    if len(stmt) > 48:
        stmt = stmt[:45] + "…"
    return f"{claim.id} {claim.kind}<br/>{stmt}".replace('"', "'")


def render_mermaid(store, *, statements: bool = True) -> str:
    statuses = blueprint_statuses(store)
    lines = ["flowchart TD"]
    for name, color in COLORS.items():
        fg = "#ffffff" if name in ("fully_proved", "mathlib") else "#000000"
        stroke = ",stroke:#c00000,stroke-width:2px" if name == "refuted" else ""
        lines.append(f"  classDef {name} fill:{color},color:{fg}{stroke}")
    for cid in store.topological_order():
        c = store.ledger.claims[cid]
        st = statuses[cid]
        label = _label(c) if statements else f"{c.id} {c.kind}"
        lines.append(f'  {_node_id(cid)}["{label}<br/><i>{st}</i>"]')
        lines.append(f"  class {_node_id(cid)} {st}")
        if c.stale:
            lines.append(f"  style {_node_id(cid)} stroke-dasharray: 5 5")
    for cid in store.topological_order():
        c = store.ledger.claims[cid]
        assumed = _assumed(c)
        for dep in c.depends_on:
            arrow = "-.->" if dep in assumed else "-->"
            lines.append(f"  {_node_id(dep)} {arrow} {_node_id(cid)}")
    return "\n".join(lines) + "\n"


def render_dot(store) -> str:
    statuses = blueprint_statuses(store)
    lines = ["digraph ledger {", "  rankdir=TB;", "  node [shape=box, style=\"filled,rounded\", fontname=\"Helvetica\"];"]
    for cid in store.topological_order():
        c = store.ledger.claims[cid]
        st = statuses[cid]
        color = COLORS.get(st, "#dddddd")
        fontcolor = "#ffffff" if st in ("fully_proved", "mathlib") else "#000000"
        extra = ', style="filled,rounded,dashed"' if c.stale else ""
        pen = ', color="#c00000", penwidth=2' if st == "refuted" else ""
        lines.append(f'  "{cid}" [label="{cid} ({c.kind})\\n{st}", fillcolor="{color}", fontcolor="{fontcolor}"{extra}{pen}];')
    for cid in store.topological_order():
        c = store.ledger.claims[cid]
        assumed = _assumed(c)
        for dep in c.depends_on:
            style = ' [style=dashed, label="assumes"]' if dep in assumed else ""
            lines.append(f'  "{dep}" -> "{cid}"{style};')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_text(store) -> str:
    statuses = blueprint_statuses(store)
    dag = store.dag()
    out = []
    for cid in store.topological_order():
        node = dag[cid]
        out.append(f"{cid} [{node['kind']}/{node['status']} -> {statuses[cid]}] depends_on={node['depends_on']}")
    return "\n".join(out) + "\n"
