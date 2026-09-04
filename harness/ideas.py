"""Attack routes in ``campaigns/<slug>/ideas.md`` as data (Round-2 Y8/X2/Y11).

Route block format (``skills/references/creative-moves.md``)::

    ## Route 3: Entropy reformulation — lens: information-theoretic
    - Moves: M12 (change the ambient object), M21 (entropy), M31 (technique transfer …)
    - Idea: …
    - Why it might work: …
    - Cheap falsification (≤ 30 min): …
    - Cost estimate: 2 h explore / 6 h prove
    - Kill criterion: …
    - Credence: p_true=0.35 p_budget=0.2 (strategist) — why …      (X2, pre-registered)
    - Status: untested | tested-ok | dead: <reason> | proved <claim-id> | key-step <claim-id>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from harness import CAMPAIGNS
from harness.text.similarity import near_duplicates, proximity_graph

ROUTE_STATUSES = ("untested", "tested-ok", "dead", "proved", "key-step")
_ROUTE_RE = re.compile(r"^##\s+Route\s+(\d+)\s*[:.\-–—]\s*(.*)$")
_LENS_RE = re.compile(r"(?:—|-|–)\s*lens\s*:\s*([A-Za-z/\- ]+)$", re.IGNORECASE)
_FIELD_RE = re.compile(r"^\s*[-*]\s*([A-Za-z][A-Za-z ()≤<=0-9/_-]*?)\s*:\s*(.*)$")
_MOVE_RE = re.compile(r"\bM\d{1,2}\b")
_CRED_RE = re.compile(r"p_true\s*=\s*([01](?:\.\d+)?)|p_budget\s*=\s*([01](?:\.\d+)?)|\(([a-z\-]+)\)")
_CLAIM_RE = re.compile(r"\b[A-Z]-\d{3,}\b")


class Credence(BaseModel):
    p_true: float | None = None
    p_budget: float | None = None
    role: str = ""
    why: str = ""


class Route(BaseModel):
    index: int
    title: str
    lens: str = ""
    moves: list[str] = Field(default_factory=list)
    idea: str = ""
    falsification: str = ""
    cost: str = ""
    kill: str = ""
    status: str = "untested"
    status_note: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    credence: Credence | None = None
    line: int = 0

    def text_for_similarity(self) -> str:
        return " ".join([self.title, self.lens, self.idea, self.falsification])


def parse_routes(text: str) -> list[Route]:
    routes: list[Route] = []
    cur: Route | None = None
    fields: dict[str, str] = {}
    last: str | None = None

    def flush() -> None:
        nonlocal cur, fields
        if cur is None:
            return
        cur.moves = sorted(set(_MOVE_RE.findall(fields.get("moves", ""))), key=lambda m: int(m[1:]))
        cur.idea = fields.get("idea", "")
        cur.falsification = next((v for k, v in fields.items() if k.startswith("cheap falsification")), "")
        cur.cost = fields.get("cost estimate", "") or fields.get("cost", "")
        cur.kill = fields.get("kill criterion", "")
        st = fields.get("status", "untested").strip()
        m = re.match(r"^(untested|tested-ok|dead|proved|key-step)\b\s*[:\-–—]?\s*(.*)$", st, re.IGNORECASE)
        if m:
            cur.status = m.group(1).lower()
            cur.status_note = m.group(2).strip()
        cur.claim_ids = sorted(set(_CLAIM_RE.findall(fields.get("status", "") + " " + fields.get("claims", ""))))
        cred = fields.get("credence")
        if cred:
            c = Credence()
            for pt, pb, role in _CRED_RE.findall(cred):
                if pt:
                    c.p_true = float(pt)
                if pb:
                    c.p_budget = float(pb)
                if role:
                    c.role = role
            why = re.split(r"\s[—–-]\s", cred, maxsplit=1)
            c.why = why[1].strip() if len(why) > 1 else ""
            cur.credence = c
        routes.append(cur)
        cur, fields = None, {}

    for i, ln in enumerate((text or "").splitlines(), 1):
        if ln.startswith("## "):
            flush()
            last = None
            m = _ROUTE_RE.match(ln)
            if m:
                title = m.group(2).strip()
                lens = ""
                lm = _LENS_RE.search(title)
                if lm:
                    lens = lm.group(1).strip()
                    title = title[: lm.start()].strip()
                cur = Route(index=int(m.group(1)), title=title, lens=lens, line=i)
            continue
        if cur is None:
            continue
        fm = _FIELD_RE.match(ln)
        if fm:
            last = fm.group(1).strip().lower()
            fields[last] = fm.group(2).strip()
        elif last and ln.strip():
            fields[last] = (fields[last] + " " + ln.strip()).strip()
    flush()
    return routes


def dedup(routes: list[Route], threshold: float = 0.8) -> list[dict]:
    items = [r.text_for_similarity() for r in routes]
    out = []
    for i, j, score in near_duplicates(items, threshold):
        out.append({"a": routes[i].index, "b": routes[j].index, "score": score,
                    "a_title": routes[i].title, "b_title": routes[j].title})
    return out


def advisories(campaign_dir: Path, threshold: float = 0.8) -> list[str]:
    path = Path(campaign_dir) / "ideas.md"
    if not path.exists():
        return []
    routes = parse_routes(path.read_text(encoding="utf-8"))
    out = [f"routes {d['a']} and {d['b']} look like near-duplicates (similarity {d['score']}); rule R3 wants distinct lenses"
           for d in dedup(routes, threshold)]
    lenses = [r.lens.lower() for r in routes if r.lens]
    dup_lens = {l for l in lenses if lenses.count(l) > 1}
    if dup_lens:
        out.append(f"several routes share a lens ({', '.join(sorted(dup_lens))}); rule R3 asks for different lenses")
    missing = [r.index for r in routes if not r.falsification]
    if missing:
        out.append(f"routes without a cheap falsification test are not routes (creative-moves.md): {missing}")
    return out


def load_routes(campaign_dir: Path) -> list[Route]:
    path = Path(campaign_dir) / "ideas.md"
    return parse_routes(path.read_text(encoding="utf-8")) if path.exists() else []


# -------------------------------------------------------------------- CLI --

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness ideas", description="attack routes in ideas.md")
    p.add_argument("--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="routes as JSON")
    d = sub.add_parser("dedup", help="near-duplicate route pairs (exit 3 if any)")
    d.add_argument("--threshold", type=float, default=0.8)
    g = sub.add_parser("graph", help="proximity clusters of routes")
    g.add_argument("--threshold", type=float, default=0.5)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, tok in enumerate(argv):
        if tok == "--campaign" and i + 1 < len(argv) and i != 0:
            argv = [tok, argv[i + 1]] + argv[:i] + argv[i + 2:]
            break
    args = build_parser().parse_args(argv)
    cdir = Path(CAMPAIGNS) / args.campaign
    routes = load_routes(cdir)
    if args.cmd == "list":
        print(json.dumps([r.model_dump() for r in routes], ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "dedup":
        pairs = dedup(routes, args.threshold)
        print(json.dumps(pairs, ensure_ascii=False, indent=2))
        return 3 if pairs else 0
    if args.cmd == "graph":
        print(json.dumps(proximity_graph([r.text_for_similarity() for r in routes], args.threshold), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
