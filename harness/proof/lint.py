"""Proof-artifact linter (Round-1 Step 6 / A6) and the shared proof parser.

A proof artifact (``campaigns/<slug>/proofs/<ID>.md``) must follow
``skills/references/proof-standards.md`` §1 before it may enter adversarial review:
YAML frontmatter, numbered ``**Step k.**`` lines each naming a justification,
``<cite id claim excerpt-hash>`` tags that resolve to verified excerpts in the
ledger, exactly one ``<key-original-step>`` for a theorem, every hypothesis used,
every number tracked in ``experiments/results.json``, no hedges, no priming
(motivation/confidence) language that would bias a referee.

:func:`parse_proof` is also used by the coverage metric (Round-2 X5): every step
carries a ``kind`` (definition | algebra | computation | derived | cited |
hypothesis | key | synthesis) derived from its parenthesised justification.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from harness.paper.check import _HEDGE_RE

REQUIRED_KEYS = ("claim", "statement", "depends_on", "assumes", "uses_hypotheses", "numerics", "version")
SKETCH_KEYS = ("kind", "claim", "persona", "route", "key_idea", "lemmas")
REQUIRED_SECTIONS = ("## Proof", "## Edge cases checked", "## Self-check log")

_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_STEP_RE = re.compile(r"^\*\*Step\s+(\d+)\.\*\*\s*(.*)$", re.MULTILINE)
_CONCL_RE = re.compile(r"^\*\*Conclusion\.\*\*", re.MULTILINE)
_JUST_RE = re.compile(r"^\(([^)]*)\)")
_CITE_RE = re.compile(r"<cite\b([^>]*)>", re.IGNORECASE)
_ATTR_RE = re.compile(r'([A-Za-z_-]+)\s*=\s*"([^"]*)"')
_KEY_RE = re.compile(r"<key-original-step>", re.IGNORECASE)
_RESULTS_KEY_RE = re.compile(r"results\.json#([A-Za-z0-9_.\-]+)")
_PRIMING_RE = re.compile(
    r"\b(we (believe|hope|expect|are confident|think|feel)|intuitively|heuristically|it seems|probably|likely|"
    r"should work|we tried|after (some|much) experimentation|our confidence|we are (fairly |quite )?(sure|certain))\b",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^##\s+(.*)$", re.MULTILINE)
_BIBKEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


@dataclass
class Issue:
    code: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "line": self.line}


@dataclass
class Step:
    n: int
    kind: str
    ref: str | None
    text: str
    line: int


@dataclass
class Cite:
    id: str | None
    claim: str | None
    excerpt_hash: str | None
    line: int


@dataclass
class ProofDoc:
    frontmatter: dict
    steps: list[Step] = field(default_factory=list)
    cites: list[Cite] = field(default_factory=list)
    key_steps: list[int] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    body: str = ""
    kind: str = "proof"  # proof | sketch
    has_conclusion: bool = False
    frontmatter_error: str | None = None

    @property
    def claim(self) -> str | None:
        v = self.frontmatter.get("claim")
        return str(v) if v is not None else None


@dataclass
class LintReport:
    path: str
    ok: bool
    errors: list[Issue]
    warnings: list[Issue]
    doc: ProofDoc | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path, "ok": self.ok,
            "errors": [e.to_dict() for e in self.errors], "warnings": [w.to_dict() for w in self.warnings],
            "steps": len(self.doc.steps) if self.doc else 0,
            "kinds": {s.n: s.kind for s in self.doc.steps} if self.doc else {},
        }


# ---------------------------------------------------------------- parsing --

def _kind_of(justification: str | None, rest: str) -> tuple[str, str | None]:
    if _KEY_RE.search(rest[:40]) or (justification is None and _KEY_RE.search(rest)):
        return "key", None
    if justification is None:
        if _CITE_RE.search(rest):
            return "cited", None
        return "synthesis", None
    j = justification.strip()
    low = j.lower()
    if low.startswith("definition") or low.startswith("def."):
        return "definition", j
    if low.startswith(("algebra", "arithmetic", "rearrang", "expanding", "simplif")):
        return "algebra", j
    if low.startswith("computation"):
        return "computation", j
    if low.startswith(("step", "steps", "by step", "from step")):
        return "derived", j
    if low.startswith(("cited", "cite", "by [")):
        return "cited", j
    if low.startswith(("hypothesis", "assumption", "by hypothesis", "by assumption")):
        return "hypothesis", j
    return "synthesis", j


def _lenient_frontmatter(block: str) -> dict:
    out: dict = {}
    for ln in block.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", ln)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            items = [s.strip().strip('"').strip("'") for s in re.split(r",(?![^\[]*\])", inner)] if inner else []
            out[key] = [i for i in items if i]
        elif (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            out[key] = raw[1:-1]
        elif re.fullmatch(r"-?\d+", raw):
            out[key] = int(raw)
        else:
            out[key] = raw
    return out


def parse_proof(text: str) -> ProofDoc:
    fm: dict = {}
    fm_error = None
    body = text
    m = _FM_RE.match(text)
    if m:
        try:
            loaded = yaml.safe_load(m.group(1))
            fm = loaded if isinstance(loaded, dict) else {}
            if not isinstance(loaded, dict):
                fm_error = "frontmatter is not a mapping"
        except yaml.YAMLError:
            # math-heavy values such as `[finite, |S|>=2]` are not valid YAML; fall back to a lenient
            # line parser (key: scalar | [a, b, c] | "quoted") so the artifact is still machine-read.
            fm = _lenient_frontmatter(m.group(1))
            if not fm:
                fm_error = "frontmatter is not valid YAML and could not be parsed leniently"
        body = text[m.end():]
    else:
        fm_error = "missing YAML frontmatter (--- … ---)"
    doc = ProofDoc(frontmatter=fm, body=body, frontmatter_error=fm_error)
    doc.kind = "sketch" if str(fm.get("kind", "")).lower() == "sketch" else "proof"
    offset = text[: len(text) - len(body)].count("\n")

    headings = list(_HEADING_RE.finditer(body))
    for i, h in enumerate(headings):
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        doc.sections[h.group(1).strip()] = body[start:end]

    for sm in _STEP_RE.finditer(body):
        n = int(sm.group(1))
        rest = sm.group(2)
        jm = _JUST_RE.match(rest)
        just = jm.group(1) if jm else None
        kind, ref = _kind_of(just, rest)
        line = offset + body[: sm.start()].count("\n") + 1
        doc.steps.append(Step(n=n, kind=kind, ref=ref, text=rest, line=line))
        if _KEY_RE.search(rest):
            doc.key_steps.append(n)
    for cm in _CITE_RE.finditer(body):
        attrs = dict(_ATTR_RE.findall(cm.group(1)))
        line = offset + body[: cm.start()].count("\n") + 1
        doc.cites.append(Cite(id=attrs.get("id"), claim=attrs.get("claim"), excerpt_hash=attrs.get("excerpt-hash"), line=line))
    # key steps that are not on a step line (multi-line tags)
    for km in _KEY_RE.finditer(body):
        line = offset + body[: km.start()].count("\n") + 1
        if not any(s.line == line for s in doc.steps):
            prev = [s for s in doc.steps if s.line < line]
            if prev and prev[-1].n not in doc.key_steps:
                doc.key_steps.append(prev[-1].n)
    doc.has_conclusion = _CONCL_RE.search(body) is not None
    return doc


# ---------------------------------------------------------------- linting --

def _bib_keys(campaign_dir: Path | None) -> set[str]:
    if campaign_dir is None:
        return set()
    p = Path(campaign_dir) / "refs.bib"
    if not p.exists():
        return set()
    return set(_BIBKEY_RE.findall(p.read_text(encoding="utf-8", errors="replace")))


def _results_keys(campaign_dir: Path | None) -> set[str] | None:
    if campaign_dir is None:
        return None
    p = Path(campaign_dir) / "experiments" / "results.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return set()
    return set(data.keys()) if isinstance(data, dict) else set()


def _claim_kind(store, claim_id: str | None) -> str | None:
    if claim_id is None:
        return None
    if store is not None and claim_id in store.ledger.claims:
        return store.ledger.claims[claim_id].kind
    prefix = claim_id.split("-", 1)[0].upper()
    return {"T": "theorem", "P": "proposition", "G": "target", "L": "lemma", "C": "conjecture", "B": "bound", "K": "construction"}.get(prefix)


def lint_sketch(doc: ProofDoc, path: str) -> LintReport:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    for key in SKETCH_KEYS:
        if key not in doc.frontmatter:
            errors.append(Issue("E_SKETCH_HEADER", f"sketch frontmatter lacks '{key}'"))
    lemmas = doc.frontmatter.get("lemmas") or []
    if not isinstance(lemmas, list) or not lemmas:
        errors.append(Issue("E_SKETCH_LEMMAS", "a sketch lists at least one lemma with statement/needs/cheapest_falsification"))
    else:
        for i, lem in enumerate(lemmas):
            if not isinstance(lem, dict) or not lem.get("statement") or not lem.get("cheapest_falsification"):
                errors.append(Issue("E_SKETCH_LEMMAS", f"lemma #{i + 1} needs 'statement' and 'cheapest_falsification'"))
    if _PRIMING_RE.search(doc.body):
        warnings.append(Issue("W_SKETCH_PRIMING", "priming language in the sketch (fine for raters, remove before the proof)"))
    return LintReport(path=path, ok=not errors, errors=errors, warnings=warnings, doc=doc)


def lint_proof(path: Path | str, campaign_dir: Path | str | None = None, store=None) -> LintReport:
    """Lint a proof artifact; ``store`` (LedgerStore) enables claim/cite resolution."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    doc = parse_proof(text)
    if doc.kind == "sketch":
        return lint_sketch(doc, str(path))
    errors: list[Issue] = []
    warnings: list[Issue] = []
    fm = doc.frontmatter
    if doc.frontmatter_error:
        errors.append(Issue("E_PROOF_HEADER", doc.frontmatter_error, 1))
    for key in REQUIRED_KEYS:
        if key not in fm:
            errors.append(Issue("E_PROOF_HEADER", f"frontmatter lacks '{key}'", 1))
    claim_id = doc.claim
    claim = None
    if store is not None and claim_id is not None:
        claim = store.ledger.claims.get(claim_id)
        if claim is None:
            errors.append(Issue("E_PROOF_CLAIM_UNKNOWN", f"claim {claim_id!r} is not in the ledger", 1))
        else:
            from harness.ledger.ledger import normalize_statement

            if fm.get("statement") and normalize_statement(str(fm["statement"])) != normalize_statement(claim.statement):
                warnings.append(Issue("W_PROOF_STATEMENT_DRIFT", "frontmatter statement differs from the ledger statement (interpretation lock)", 1))
            for dep in list(fm.get("depends_on") or []):
                if str(dep) not in store.ledger.claims:
                    errors.append(Issue("E_PROOF_DEPENDS_UNKNOWN", f"depends_on references unknown claim {dep!r}", 1))
            assumed_tags = {t.split(":", 1)[1] for t in claim.tags if t.startswith("assumes:")}
            for a in list(fm.get("assumes") or []):
                if str(a) not in assumed_tags:
                    warnings.append(Issue("W_PROOF_ASSUMES_TAG", f"assumes {a} but the ledger claim lacks tag 'assumes:{a}'", 1))

    # sections
    for sec in REQUIRED_SECTIONS:
        name = sec[3:]
        if name not in doc.sections:
            errors.append(Issue("E_PROOF_SECTION_MISSING", f"missing section '{sec}'"))

    # steps
    if not doc.steps:
        errors.append(Issue("E_PROOF_STEPS", "no numbered '**Step k.**' lines found"))
    else:
        nums = [s.n for s in doc.steps]
        if nums != list(range(1, len(nums) + 1)):
            errors.append(Issue("E_PROOF_STEPS", f"steps must be numbered consecutively from 1; got {nums}", doc.steps[0].line))
        for s in doc.steps:
            if s.kind == "synthesis" and s.ref is None:
                errors.append(Issue("E_PROOF_STEPS", f"Step {s.n} names no justification: use (definition D-001), (algebra), (Step k), (cited: key), (computation: results.json#key) or <key-original-step>", s.line))
        if not doc.has_conclusion:
            errors.append(Issue("E_PROOF_STEPS", "missing '**Conclusion.**' line"))

    # key original step
    kind = _claim_kind(store, claim_id)
    n_key = len(doc.key_steps)
    if kind in ("theorem", "proposition", "target", "conjecture", "bound", "construction", None):
        if n_key != 1:
            errors.append(Issue("E_PROOF_KEYSTEP", f"a theorem-level proof needs exactly one <key-original-step> (found {n_key})"))
    elif n_key > 1:
        errors.append(Issue("E_PROOF_KEYSTEP", f"a lemma proof may mark at most one <key-original-step> (found {n_key})"))

    # citations
    bibkeys = _bib_keys(Path(campaign_dir) if campaign_dir else None)
    for c in doc.cites:
        if not c.id or not c.claim or not c.excerpt_hash:
            errors.append(Issue("E_PROOF_CITE", "<cite> needs id=\"bibkey\" claim=\"F-xxx\" excerpt-hash=\"…\"", c.line))
            continue
        if store is not None:
            fact = store.ledger.claims.get(c.claim)
            if fact is None:
                errors.append(Issue("E_PROOF_CITE", f"<cite claim={c.claim}> is not a ledger claim", c.line))
                continue
            if fact.status != "known-in-literature":
                errors.append(Issue("E_PROOF_CITE", f"<cite claim={c.claim}>: claim status is {fact.status!r}, needs known-in-literature", c.line))
            hashes = {ev.excerpt_hash for ev in fact.evidence if ev.type == "excerpt" and ev.verified is True and ev.excerpt_hash}
            if not any(h.startswith(c.excerpt_hash) or c.excerpt_hash.startswith(h) for h in hashes):
                errors.append(Issue("E_PROOF_CITE", f"<cite claim={c.claim}> excerpt-hash {c.excerpt_hash!r} matches no verified excerpt on that claim", c.line))
        if bibkeys and c.id not in bibkeys:
            warnings.append(Issue("W_PROOF_CITE_BIBKEY", f"<cite id={c.id}> is not a key in refs.bib", c.line))

    # hypotheses
    selfcheck = doc.sections.get("Self-check log", "")
    for h in list(fm.get("uses_hypotheses") or []):
        hs = str(h).strip()
        if hs and hs.lower() not in selfcheck.lower():
            errors.append(Issue("E_PROOF_HYPOTHESIS_UNUSED", f"hypothesis {hs!r} is not accounted for in '## Self-check log' (Hypothesis use: … → Step k)"))

    # numerics
    mentioned = set(_RESULTS_KEY_RE.findall(doc.body))
    declared = {str(n).split("#", 1)[1] if "#" in str(n) else str(n) for n in list(fm.get("numerics") or [])}
    for key in sorted(mentioned - declared):
        errors.append(Issue("E_PROOF_NUMERIC_UNTRACKED", f"results.json#{key} is used but not listed under 'numerics:'"))
    rkeys = _results_keys(Path(campaign_dir) if campaign_dir else None)
    if rkeys is not None:
        for key in sorted(declared | mentioned):
            if key not in rkeys:
                errors.append(Issue("E_PROOF_NUMERIC_UNTRACKED", f"results.json has no key {key!r} (rule R5b: numbers come from code)"))
    elif campaign_dir is not None and (declared or mentioned):
        errors.append(Issue("E_PROOF_NUMERIC_UNTRACKED", "experiments/results.json does not exist but the proof references numerics"))

    # hedges and priming
    for s in doc.steps:
        if _HEDGE_RE.search(s.text) and not _CITE_RE.search(s.text):
            errors.append(Issue("E_PROOF_HEDGE", f"Step {s.n}: hedge word — replace with the argument, a <cite>, or a results.json key", s.line))
    for sec_name, sec_text in doc.sections.items():
        if sec_name.lower().startswith("self-check"):
            continue
        for pm in _PRIMING_RE.finditer(sec_text):
            errors.append(Issue("E_PROOF_PRIMING", f"priming/confidence language ({pm.group(0)!r}) primes the referee; remove it"))
            break
    if _PRIMING_RE.search(doc.body.split("## ", 1)[0]):
        errors.append(Issue("E_PROOF_PRIMING", "priming/confidence language before the first section"))

    if list(fm.get("assumes") or []):
        warnings.append(Issue("W_PROOF_CONDITIONAL", f"proof assumes unproven claims {fm.get('assumes')}: the result is conditional and the paper must say so"))
    if "technique" not in fm:
        warnings.append(Issue("W_TECHNIQUE_MISSING", "frontmatter has no 'technique:' tags (used by the marking scheme and pitfalls checklist)"))

    return LintReport(path=str(path), ok=not errors, errors=errors, warnings=warnings, doc=doc)


def lint_claim_proofs(store, campaign_dir: Path | str, claim_id: str) -> list[LintReport]:
    """Lint every ``.md`` proof evidence file of a claim (``.tex`` legacy artifacts are skipped)."""
    reports: list[LintReport] = []
    claim = store.get(claim_id)
    for ev in claim.evidence:
        if ev.type == "proof" and ev.path and ev.path.lower().endswith(".md"):
            full = Path(campaign_dir) / ev.path
            if full.exists():
                reports.append(lint_proof(full, campaign_dir, store))
    return reports
