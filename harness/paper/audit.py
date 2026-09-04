"""Sampled accuracy audit of the paper's prose (Round-2 Step 25 / Y9).

Kosmos (arXiv 2511.02824) reported the fraction of report statements that
independent scientists found accurate. Neugier does the same before the paper
leaves the harness: ``harness paper audit sample`` draws ``n`` sentences from the
Results/Proof sections deterministically (sorted by ``sha256(seed + sentence)``),
writes ``paper/audit.json``, and the copyeditor labels each one
``supported | refuted | unclear`` with a pointer to the evidence (a
``results.json`` key, a claim id, a verified excerpt). ``paper check --strict``
fails on any ``refuted`` sentence; the appendix prints "audited accuracy k/n".
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from harness.paper.check import _COMMENT_RE, flatten_tex

DEFAULT_SECTIONS = ("results", "main", "proof", "argument", "theorem", "construction", "bound")
_SECTION_RE = re.compile(r"\\(?:sub)?section\*?\{([^}]*)\}")
_MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$]*\$|\\\[.*?\\\]|\\\(.*?\\\)", re.DOTALL)
_CMD_RE = re.compile(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})*")
LABELS = ("supported", "refuted", "unclear")


class Sentence(BaseModel):
    id: int
    section: str
    line: int
    text: str
    sha12: str
    label: str | None = None
    evidence: str | None = None
    note: str = ""


class Audit(BaseModel):
    seed: str
    n: int
    generated: str
    sections: list[str]
    sentences: list[Sentence] = Field(default_factory=list)


def _norm(s: str) -> str:
    s = _MATH_RE.sub(" MATH ", s)
    s = _CMD_RE.sub(" ", s)
    return " ".join(s.split()).lower()


def extract_sentences(paper_dir: Path | str, sections: tuple[str, ...] | list[str] = DEFAULT_SECTIONS) -> list[dict]:
    """Sentences (≥ 6 words) from sections whose title matches one of ``sections`` (case-insensitive)."""
    paper_dir = Path(paper_dir)
    main = paper_dir / "main.tex"
    if not main.exists():
        return []
    raw = flatten_tex(main, paper_dir)
    lines = raw.split("\n")
    out: list[dict] = []
    current = ""
    active = False
    buf: list[tuple[int, str]] = []

    def flush() -> None:
        if not buf:
            return
        text = " ".join(t for _, t in buf)
        first_line = buf[0][0]
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z\\])", text):
            s = sent.strip()
            if len(_norm(s).split()) >= 6 and not s.startswith("\\"):
                out.append({"section": current, "line": first_line, "text": s})
        buf.clear()

    for i, ln in enumerate(lines, 1):
        stripped = _COMMENT_RE.sub("", ln).strip()
        sm = _SECTION_RE.search(stripped)
        if sm:
            flush()
            current = sm.group(1)
            active = any(k in current.lower() for k in sections)
            continue
        if not active:
            continue
        if not stripped or stripped.startswith("\\begin{") or stripped.startswith("\\end{"):
            if stripped.startswith(("\\begin{", "\\end{")) or not stripped:
                flush()
            continue
        buf.append((i, stripped))
    flush()
    return out


def sample(sentences: list[dict], n: int, seed: str) -> list[dict]:
    """Deterministic sample: the ``n`` sentences with the smallest ``sha256(seed + normalized text)``."""
    keyed = []
    for s in sentences:
        h = hashlib.sha256((seed + "|" + _norm(s["text"])).encode("utf-8")).hexdigest()
        keyed.append((h, s))
    keyed.sort(key=lambda t: t[0])
    return [dict(s, sha12=h[:12]) for h, s in keyed[:n]]


def write_sample(paper_dir: Path | str, n: int = 30, seed: str | None = None, sections=DEFAULT_SECTIONS) -> Path:
    from datetime import datetime, timezone

    from harness.ledger.ledger import atomic_write_json

    paper_dir = Path(paper_dir)
    seed = seed or paper_dir.parent.name
    picked = sample(extract_sentences(paper_dir, sections), n, seed)
    audit = Audit(seed=seed, n=len(picked), generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  sections=list(sections),
                  sentences=[Sentence(id=i + 1, section=s["section"], line=s["line"], text=s["text"], sha12=s["sha12"])
                             for i, s in enumerate(picked)])
    out = paper_dir / "audit.json"
    atomic_write_json(out, json.loads(audit.model_dump_json()))
    return out


def load_audit(paper_dir: Path | str) -> Audit | None:
    p = Path(paper_dir) / "audit.json"
    if not p.exists():
        return None
    try:
        return Audit.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def validate_audit(paper_dir: Path | str) -> tuple[dict, list[str]]:
    """``(counts, issues)``; issues are ``E_AUDIT_REFUTED: …``, ``W_AUDIT_INCOMPLETE: …``, ``W_AUDIT_STALE: …``."""
    paper_dir = Path(paper_dir)
    audit = load_audit(paper_dir)
    counts = {"supported": 0, "refuted": 0, "unclear": 0, "unlabeled": 0, "n": 0}
    if audit is None:
        return counts, []
    issues: list[str] = []
    current = {_norm(s["text"]) for s in extract_sentences(paper_dir, tuple(audit.sections))}
    for s in audit.sentences:
        counts["n"] += 1
        if s.label not in LABELS:
            counts["unlabeled"] += 1
        else:
            counts[s.label] += 1
        if s.label == "refuted":
            issues.append(f"E_AUDIT_REFUTED: sentence #{s.id} (line {s.line}) was refuted by the copyeditor: {s.text[:80]!r}")
        elif s.label == "supported" and not (s.evidence or "").strip():
            issues.append(f"W_AUDIT_INCOMPLETE: sentence #{s.id} is marked supported without an evidence pointer")
        if _norm(s.text) not in current:
            issues.append(f"W_AUDIT_STALE: sentence #{s.id} no longer occurs in the paper; re-sample")
    if counts["unlabeled"]:
        issues.append(f"W_AUDIT_INCOMPLETE: {counts['unlabeled']} of {counts['n']} sampled sentences are unlabeled")
    return counts, issues
