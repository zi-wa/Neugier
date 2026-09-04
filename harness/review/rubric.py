"""Pre-registered marking schemes (Round-2 Step 20 / Y2).

Before any proof exists, the strategist writes ``proofs/<ID>.rubric.md``::

    ---
    claim: T-001
    technique: [extremal, double-counting]
    required_hypotheses: [finite, "|S| >= 2"]
    must_establish:
      - "the compression map does not increase |S+S|"
      - "the equality case is an arithmetic progression"
    hard_step: "compression preserves the sumset bound"
    version: 1
    ---
    ## Marking scheme
    - …what a correct proof must show, in checkable items…
    ## Pitfalls
    - extremal: …copied from skills/references/technique-pitfalls.md…

ProofGrader (proofgrader.github.io) found the marking scheme to be the largest single driver
of grader reliability; here it is written *before* the proof (so it cannot be tailored to it),
frozen at statement lock (``campaign.json["rubric_hashes"]``), and given to every skeptic as
mandatory rows of ``checked``.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

import harness
from harness.proof.lint import _lenient_frontmatter, _PRIMING_RE

PITFALLS_DOC = Path(harness.ROOT) / "skills" / "references" / "technique-pitfalls.md"
_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


class Rubric(BaseModel):
    claim: str
    technique: list[str] = Field(default_factory=list)
    required_hypotheses: list[str] = Field(default_factory=list)
    must_establish: list[str] = Field(default_factory=list)
    hard_step: str = ""
    version: int = 1
    marking_scheme: str = ""
    pitfalls: str = ""


class RubricError(Exception):
    pass


def rubric_path(campaign_dir: Path | str, claim_id: str) -> Path:
    return Path(campaign_dir) / "proofs" / f"{claim_id}.rubric.md"


def _frontmatter(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m:
        raise RubricError("rubric lacks YAML frontmatter")
    try:
        import yaml

        data = yaml.safe_load(m.group(1))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    data = _lenient_frontmatter(m.group(1))
    if not data:
        raise RubricError("rubric frontmatter could not be parsed")
    return data


def _section(text: str, name: str) -> str:
    m = re.search(rf"^##\s*{re.escape(name)}\s*$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def parse_rubric(path: Path | str) -> Rubric:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    fm = _frontmatter(text)
    if not fm.get("claim"):
        raise RubricError("rubric frontmatter needs 'claim'")

    def _list(v) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.strip("[]").split(",") if s.strip()]
        return [str(x).strip() for x in v if str(x).strip()]

    r = Rubric(
        claim=str(fm["claim"]), technique=_list(fm.get("technique")), required_hypotheses=_list(fm.get("required_hypotheses")),
        must_establish=_list(fm.get("must_establish")), hard_step=str(fm.get("hard_step") or ""),
        version=int(fm.get("version") or 1), marking_scheme=_section(text, "Marking scheme"), pitfalls=_section(text, "Pitfalls"),
    )
    if not r.marking_scheme:
        raise RubricError("rubric needs a '## Marking scheme' section")
    return r


def technique_tags(doc: Path | str = PITFALLS_DOC) -> list[str]:
    text = Path(doc).read_text(encoding="utf-8", errors="replace")
    return re.findall(r"^##\s+([a-z][a-z0-9-]*)\s*$", text, re.MULTILINE)


def pitfalls_for(tags: list[str], doc: Path | str = PITFALLS_DOC) -> str:
    text = Path(doc).read_text(encoding="utf-8", errors="replace")
    out: list[str] = []
    for tag in tags:
        m = re.search(rf"^##\s+{re.escape(tag)}\s*$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
        if m:
            out.append(f"## {tag}\n{m.group(1).strip()}")
    return "\n\n".join(out)


def lint_rubric(path: Path | str) -> list[str]:
    """Problems with a rubric file (errors only): parse, unknown technique tags, priming language."""
    problems: list[str] = []
    try:
        r = parse_rubric(path)
    except RubricError as exc:
        return [str(exc)]
    known = set(technique_tags()) if PITFALLS_DOC.exists() else set()
    for t in r.technique:
        if known and t not in known:
            problems.append(f"unknown technique tag {t!r}; known: {', '.join(sorted(known))}")
    if not r.must_establish:
        problems.append("rubric lists nothing under must_establish")
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    body = text.split("---", 2)[-1] if text.startswith("---") else text
    if _PRIMING_RE.search(body):
        problems.append("rubric contains priming/confidence language (route hints leak to the skeptic); state what must be established, not how you hope to do it")
    return problems


def _norm(s: str) -> str:
    return "".join(s.lower().replace("≥", ">=").replace("≤", "<=").split())


def check_rubric_against_proof(rubric: Rubric, frontmatter: dict) -> list[str]:
    """Warnings comparing a proof's frontmatter with its pre-registered rubric."""
    warnings: list[str] = []
    used = {_norm(str(h)) for h in (frontmatter.get("uses_hypotheses") or [])}
    for h in rubric.required_hypotheses:
        if _norm(h) not in used:
            warnings.append(f"W_RUBRIC_HYP_UNUSED: rubric requires hypothesis {h!r} but the proof does not list it under uses_hypotheses")
    tech = {str(t).strip().lower() for t in (frontmatter.get("technique") or [])}
    if rubric.technique and tech and not (set(t.lower() for t in rubric.technique) & tech):
        warnings.append(f"W_RUBRIC_TECHNIQUE_DRIFT: rubric anticipated {rubric.technique}, proof uses {sorted(tech)} (re-derive the pitfalls list)")
    return warnings
