"""Citation walk over OpenAlex (Round-1 Step 13 / novelty-protocol §3 in one command).

``cite_walk(seed, direction, hops, max_n)`` performs a breadth-first walk from a
seed work (arXiv id, DOI or OpenAlex id) over ``cited_by`` (forward) and/or
``references`` (backward) edges, up to ``hops`` levels, keeping at most ``max_n``
new works per hop. Every node carries its hop distance and the id it was reached
through, so the novelty memo can cite exactly what was read.
"""
from __future__ import annotations

from harness.lit import openalex


def cite_walk(seed: str, direction: str = "both", hops: int = 1, max_n: int = 50) -> dict:
    if direction not in ("cited-by", "references", "both"):
        raise ValueError("direction must be cited-by | references | both")
    hops = max(1, min(int(hops), 2))
    root = openalex.get_work(seed)
    seed_id = root.id if root else seed
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    if root:
        nodes[root.id] = {"id": root.id, "title": root.title, "year": root.year, "hop": 0, "via": None, "direction": "seed",
                          "doi": root.doi, "arxiv_id": root.arxiv_id, "cited_by_count": root.cited_by_count}
    frontier = [seed_id]
    for hop in range(1, hops + 1):
        nxt: list[str] = []
        for wid in frontier:
            for kind in (("cited-by", "references") if direction == "both" else (direction,)):
                papers = openalex.cited_by(wid, per_page=max_n) if kind == "cited-by" else openalex.references(wid)
                for p in papers[:max_n]:
                    edges.append({"from": wid, "to": p.id, "kind": kind, "hop": hop})
                    if p.id not in nodes:
                        nodes[p.id] = {"id": p.id, "title": p.title, "year": p.year, "hop": hop, "via": wid, "direction": kind,
                                       "doi": p.doi, "arxiv_id": p.arxiv_id, "cited_by_count": p.cited_by_count}
                        nxt.append(p.id)
        frontier = nxt
        if not frontier:
            break
    ordered = sorted(nodes.values(), key=lambda n: (n["hop"], -(n.get("cited_by_count") or 0), n["id"]))
    return {"seed": seed_id, "direction": direction, "hops": hops, "max_per_hop": max_n, "nodes": ordered, "edges": edges,
            "counts": {h: sum(1 for n in ordered if n["hop"] == h) for h in range(0, hops + 1)}}
