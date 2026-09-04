"""Static checks over a rendered LaTeX paper.

``check(paper_dir, ledger_status=None, results=None, strict=False)`` flattens
``main.tex`` (resolving ``\\input``/``\\IfFileExists``), then runs a battery of
lint rules: undefined/unused labels, undefined/uncited bibliography entries,
theorems without a proof or citation, claims not bound to a passing ledger
entry, untracked numbers, hedge words, TODO markers and leftover
``{{PLACEHOLDER}}`` tokens. Writes ``paper_dir/check.json``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Data models
# --------------------------------------------------------------------------


class Issue(BaseModel):
    code: str
    message: str
    line: int | None = None
    context: str | None = None


class CheckReport(BaseModel):
    ok: bool
    errors: list[Issue] = Field(default_factory=list)
    warnings: list[Issue] = Field(default_factory=list)
    checked_at: str | None = None


# --------------------------------------------------------------------------
# Environment families
# --------------------------------------------------------------------------

# Require a proof-or-citation and a ledger-bound \claim{}.
THEOREM_LIKE = ("theorem", "lemma", "proposition", "corollary")
# A referee-passed claim whose dependency DAG is not fully proved (blueprint status != fully_proved).
CONDITIONAL_ENVS = ("conditional",)
# A result quoted from the literature: \cite required, optional \claim{F-…} must be known-in-literature.
KNOWN_ENVS = ("knownresult",)
# Exempt from the proof requirement and from strict claim-status enforcement.
EXEMPT_ENVS = ("conjecture", "question")
ALL_ENVS = THEOREM_LIKE + CONDITIONAL_ENVS + KNOWN_ENVS + EXEMPT_ENVS
_UNVERIFIED_RE = re.compile(r"\\unverified\b")

_ACCEPTABLE_CLAIM_STATUS = {"referee-passed", "formalized"}

# --------------------------------------------------------------------------
# Regexes
# --------------------------------------------------------------------------

_ENV_RE = re.compile(r"\\begin\{(" + "|".join(ALL_ENVS) + r")\}(.*?)\\end\{\1\}", re.DOTALL)
_PROOF_RE = re.compile(r"\\begin\{proof\}")
_CITE_ANY_RE = re.compile(r"\\cite[pt]?\*?(?:\[[^\]]*\])?\{")
_CITE_KEYS_RE = re.compile(r"\\cite[pt]?\*?(?:\[[^\]]*\])?\{([^}]*)\}")
_LABEL_RE = re.compile(r"\\label\{([^}]*)\}")
_REF_RE = re.compile(r"\\(?:ref|eqref|cref|Cref|autoref)\{([^}]*)\}")
_CLAIM_RE = re.compile(r"\\claim\{([^}]*)\}")
_KEYSTEP_RE = re.compile(r"\\keystep\{")
_TODO_RE = re.compile(r"TODO|FIXME|\?\?")
_PLACEHOLDER_RE = re.compile(r"\{\{[A-Za-z0-9_]+\}\}")
_HEDGE_RE = re.compile(
    r"\b(well[- ]known|clearly|obviously|it is easy to see|standard argument|trivially|one can show)\b",
    re.IGNORECASE,
)
_HEDGE_CITE_RE = re.compile(r"\\cite[pt]?\*?\{")
_HEDGE_REF_RE = re.compile(r"\\(?:ref|eqref|cref|Cref|autoref)\{")

_SKIP_CMDS = r"cite[pt]?\*?|label|ref|eqref|cref|Cref|autoref|url|numref"
_SKIP_SPAN_RE = re.compile(r"\\(?:" + _SKIP_CMDS + r")(?:\[[^\]]*\])?\{[^{}]*\}")
_COMMENT_RE = re.compile(r"(?<!\\)%.*")

_NUMBER_RE = re.compile(
    r"(?P<t10mant>-?\d+(?:\.\d+)?)\s*\\times\s*10\^\{?(?P<t10exp>-?\d+)\}?"
    r"|(?P<sci>-?\d+(?:\.\d+)?[eE][+-]?\d+)"
    r"|(?P<float>-?\d+\.\d+)"
    r"|(?P<int>-?\d+)"
)


# --------------------------------------------------------------------------
# tex flattening: \input{} and \IfFileExists{}{}{}
# --------------------------------------------------------------------------


def _match_group(s: str, brace_start: int) -> tuple[str, int]:
    """``s[brace_start] == '{'``; return (inner text, index just after the closing brace)."""
    if brace_start >= len(s) or s[brace_start] != "{":
        raise ValueError(f"expected '{{' at position {brace_start}")
    depth = 0
    i = brace_start
    n = len(s)
    while i < n:
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[brace_start + 1 : i], i + 1
        i += 1
    raise ValueError("unbalanced braces")


def _resolve_tex_path(paper_dir: Path, name: str) -> Path:
    p = paper_dir / name
    if not p.suffix:
        p = p.with_suffix(".tex")
    return p


def _expand_iffileexists(text: str, paper_dir: Path) -> str:
    out: list[str] = []
    i = 0
    marker = r"\IfFileExists{"
    while True:
        idx = text.find(marker, i)
        if idx == -1:
            out.append(text[i:])
            break
        out.append(text[i:idx])
        brace_start = idx + len(marker) - 1
        fname, after_fname = _match_group(text, brace_start)
        true_branch, after_true = _match_group(text, after_fname)
        false_branch, after_false = _match_group(text, after_true)
        candidate = _resolve_tex_path(paper_dir, fname)
        out.append(true_branch if candidate.exists() else false_branch)
        i = after_false
    return "".join(out)


def flatten_tex(main_path: Path, paper_dir: Path, _visited: set[Path] | None = None) -> str:
    """Read ``main_path`` and recursively inline ``\\input{}``/``\\IfFileExists{}``."""
    visited = _visited if _visited is not None else set()
    resolved = main_path.resolve()
    if resolved in visited or not main_path.exists():
        return ""
    visited.add(resolved)
    text = main_path.read_text(encoding="utf-8")
    text = _expand_iffileexists(text, paper_dir)

    def _input_sub(m: re.Match[str]) -> str:
        target = _resolve_tex_path(paper_dir, m.group(1))
        return flatten_tex(target, paper_dir, visited)

    text = re.sub(r"\\input\{([^}]*)\}", _input_sub, text)
    return text


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _context(text: str, pos: int, width: int = 200) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()[:width]


def _flatten_values(obj: object) -> list[object]:
    out: list[object] = []
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(_flatten_values(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_flatten_values(v))
    else:
        out.append(obj)
    return out


def _canon_str(s: str) -> str:
    s = s.strip()
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return ("-" + s) if neg else s


def _sig_digits(raw: str) -> int:
    s = raw.lstrip("-").replace(".", "").lstrip("0")
    return len(s)


def _load_ledger_status(paper_dir: Path) -> dict[str, str]:
    return {cid: m["status"] for cid, m in _load_ledger_meta(paper_dir).items()}


def _load_ledger_meta(paper_dir: Path) -> dict[str, dict]:
    """``{claim_id: {status, stakes, attested, fully_proved}}`` from the campaign ledger (empty if none)."""
    ledger_path = paper_dir.parent / "ledger.json"
    try:
        from harness.ledger.graph import blueprint_statuses  # type: ignore
        from harness.ledger.ledger import LedgerStore  # type: ignore
    except ImportError:
        return {}
    if not ledger_path.exists():
        return {}
    try:
        store = LedgerStore(ledger_path)
        data = store.load()
        bp = blueprint_statuses(store)
        return {
            cid: {
                "status": claim.status,
                "stakes": getattr(claim, "stakes", 1),
                "attested": bool(getattr(claim, "attestation", None)),
                "fully_proved": bp.get(cid) == "fully_proved",
                "blueprint": bp.get(cid),
            }
            for cid, claim in data.claims.items()
        }
    except Exception:
        return {}


def _meta_from_status(ledger_status: dict[str, str]) -> dict[str, dict]:
    return {cid: {"status": s, "stakes": 1, "attested": False, "fully_proved": s in _ACCEPTABLE_CLAIM_STATUS}
            for cid, s in ledger_status.items()}


def _load_results(paper_dir: Path, warnings: list[Issue]) -> dict:
    results_path = paper_dir.parent / "experiments" / "results.json"
    if not results_path.exists():
        warnings.append(
            Issue(
                code="W_RESULTS_MISSING",
                message=f"no results.json found at {results_path}; numeric claims cannot be cross-checked",
            )
        )
        return {}
    try:
        with open(results_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        warnings.append(
            Issue(code="W_RESULTS_MISSING", message=f"could not read/parse {results_path}: {exc}")
        )
        return {}


def _parse_bib(refs_path: Path) -> dict[str, dict]:
    if not refs_path.exists():
        return {}
    import bibtexparser

    with open(refs_path, encoding="utf-8") as f:
        db = bibtexparser.load(f)
    return {entry.get("ID", ""): entry for entry in db.entries if entry.get("ID")}


# --------------------------------------------------------------------------
# individual rule checks
# --------------------------------------------------------------------------


def _check_refs_labels(text: str, errors: list[Issue], warnings: list[Issue]) -> None:
    labels: dict[str, int] = {}
    for m in _LABEL_RE.finditer(text):
        for name in m.group(1).split(","):
            name = name.strip()
            if name and name not in labels:
                labels[name] = _line_no(text, m.start())

    refs: dict[str, int] = {}
    for m in _REF_RE.finditer(text):
        for name in m.group(1).split(","):
            name = name.strip()
            if name and name not in refs:
                refs[name] = _line_no(text, m.start())

    for name, line in refs.items():
        if name not in labels:
            errors.append(
                Issue(
                    code="E_UNDEF_REF",
                    message=f"reference to undefined label '{name}'",
                    line=line,
                    context=name,
                )
            )
    for name, line in labels.items():
        if name not in refs:
            warnings.append(
                Issue(
                    code="W_UNUSED_LABEL",
                    message=f"label '{name}' is defined but never referenced",
                    line=line,
                    context=name,
                )
            )


def _check_cites(text: str, bib_entries: dict[str, dict], errors: list[Issue], warnings: list[Issue]) -> None:
    cites: dict[str, int] = {}
    for m in _CITE_KEYS_RE.finditer(text):
        for key in m.group(1).split(","):
            key = key.strip()
            if key and key not in cites:
                cites[key] = _line_no(text, m.start())

    bib_keys = set(bib_entries)
    for key, line in cites.items():
        if key not in bib_keys:
            errors.append(
                Issue(
                    code="E_UNDEF_CITE",
                    message=f"citation key '{key}' not found in refs.bib",
                    line=line,
                    context=key,
                )
            )
    for key in sorted(bib_keys):
        if key not in cites:
            warnings.append(
                Issue(
                    code="W_UNCITED_BIB",
                    message=f"bibliography entry '{key}' is never cited",
                    context=key,
                )
            )


def _check_theorems_and_claims(
    text: str,
    ledger_status: dict[str, str],
    errors: list[Issue],
    warnings: list[Issue],
    ledger_meta: dict[str, dict] | None = None,
    strict: bool = False,
) -> None:
    meta = ledger_meta if ledger_meta is not None else _meta_from_status(ledger_status)
    matches = list(_ENV_RE.finditer(text))
    for idx, m in enumerate(matches):
        env = m.group(1)
        body = m.group(2)
        line = _line_no(text, m.start())
        claim_m = _CLAIM_RE.search(body)
        cid = claim_m.group(1).strip() if claim_m else None
        has_cite_in_body = bool(_CITE_ANY_RE.search(body))

        if env in KNOWN_ENVS:
            if not has_cite_in_body:
                errors.append(Issue(code="E_KNOWNRESULT_NO_CITE", message=f"knownresult at line {line} must \\cite its source", line=line, context=env))
            if cid is not None:
                status = ledger_status.get(cid)
                if status is None:
                    errors.append(Issue(code="E_CLAIM_UNKNOWN", message=f"\\claim{{{cid}}} in knownresult at line {line} is not present in the ledger", line=line, context=cid))
                elif status != "known-in-literature":
                    errors.append(Issue(code="E_CLAIM_STATUS", message=f"\\claim{{{cid}}} in knownresult at line {line} has status '{status}', not known-in-literature", line=line, context=cid))
            continue

        if env in THEOREM_LIKE or env in CONDITIONAL_ENVS:
            next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            between = text[m.end() : next_start]
            has_proof = bool(_PROOF_RE.search(between))
            if not has_proof and not has_cite_in_body:
                errors.append(
                    Issue(
                        code="E_THEOREM_NO_PROOF",
                        message=f"{env} at line {line} has neither a following \\begin{{proof}} nor a \\cite in its body",
                        line=line,
                        context=env,
                    )
                )
            if cid is None:
                errors.append(
                    Issue(
                        code="E_CLAIM_UNBOUND",
                        message=(
                            f"{env} at line {line} is not bound to a ledger claim with \\claim{{}}; results quoted from the "
                            "literature belong in a knownresult environment"
                        ),
                        line=line,
                        context=env,
                    )
                )
                continue
            status = ledger_status.get(cid)
            if status is None:
                errors.append(Issue(code="E_CLAIM_UNKNOWN", message=f"\\claim{{{cid}}} in {env} at line {line} is not present in the ledger", line=line, context=cid))
                continue
            if status not in _ACCEPTABLE_CLAIM_STATUS:
                errors.append(
                    Issue(
                        code="E_CLAIM_STATUS",
                        message=(
                            f"\\claim{{{cid}}} in {env} at line {line} has ledger status "
                            f"'{status}', not in {sorted(_ACCEPTABLE_CLAIM_STATUS)}"
                        ),
                        line=line,
                        context=cid,
                    )
                )
                continue
            info = meta.get(cid, {})
            fully = bool(info.get("fully_proved", True))
            if env in THEOREM_LIKE and not fully:
                errors.append(
                    Issue(
                        code="E_CLAIM_NOT_FULLY_PROVED",
                        message=(
                            f"\\claim{{{cid}}} in {env} at line {line} is referee-passed but its dependency graph is not fully "
                            f"proved (blueprint status {info.get('blueprint', 'proved')!r}); use \\begin{{conditional}}"
                        ),
                        line=line,
                        context=cid,
                    )
                )
            elif env in CONDITIONAL_ENVS and fully:
                warnings.append(Issue(code="W_CONDITIONAL_UNNEEDED", message=f"\\claim{{{cid}}} at line {line} is fully proved; a plain theorem environment would do", line=line, context=cid))
            if strict and int(info.get("stakes", 1) or 1) == 2 and not info.get("attested") and not _UNVERIFIED_RE.search(body):
                errors.append(
                    Issue(
                        code="E_HUMAN_ATTEST",
                        message=(
                            f"\\claim{{{cid}}} at line {line} has stakes 2 (extraordinary claim) and no human attestation; "
                            "mark it \\unverified{} or record `harness campaign attest`"
                        ),
                        line=line,
                        context=cid,
                    )
                )
        # EXEMPT_ENVS (conjecture/question): proof not required; any claim
        # status is acceptable; claims never need to exist at all.


def _check_keystep(text: str, ledger_status: dict[str, str], errors: list[Issue]) -> None:
    claim_ids = set(_CLAIM_RE.findall(text))
    any_asserted = any(ledger_status.get(cid) in _ACCEPTABLE_CLAIM_STATUS for cid in claim_ids)
    has_keystep = bool(_KEYSTEP_RE.search(text))
    if any_asserted and not has_keystep:
        errors.append(
            Issue(
                code="E_KEYSTEP_MISSING",
                message="the paper asserts a referee-passed/formalized claim but no \\keystep{} marks the genuinely new argument",
            )
        )


def _strip_for_numbers(text: str) -> str:
    text = _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), text)
    text = _SKIP_SPAN_RE.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _values_match(value: float, raw: str, known_floats: set[float], known_strs: set[str]) -> bool:
    is_exp_form = ("e" in raw.lower() and not raw.lower().startswith("0x")) or "\\times" in raw
    canon = raw if is_exp_form else _canon_str(raw)
    if canon in known_strs:
        return True
    for kv in known_floats:
        denom = max(abs(kv), abs(value), 1.0)
        if abs(value - kv) <= 1e-9 * denom:
            return True
    return False


def _check_numbers(text: str, results: dict, errors: list[Issue]) -> None:
    known_values = _flatten_values(results)
    known_floats: set[float] = set()
    known_strs: set[str] = set()
    for v in known_values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            known_floats.add(float(v))
            known_strs.add(_canon_str(str(v)))
        elif isinstance(v, str):
            try:
                fv = float(v)
            except ValueError:
                continue
            known_floats.add(fv)
            known_strs.add(v if "e" in v.lower() else _canon_str(v))

    stripped = _strip_for_numbers(text)
    for m in _NUMBER_RE.finditer(stripped):
        if m.group("t10mant") is not None:
            mantissa = float(m.group("t10mant"))
            exponent = int(m.group("t10exp"))
            value = mantissa * (10.0**exponent)
            raw = m.group(0)
            track = True
        elif m.group("sci") is not None:
            raw = m.group("sci")
            value = float(raw)
            track = True
        elif m.group("float") is not None:
            raw = m.group("float")
            value = float(raw)
            track = _sig_digits(raw) >= 4
        else:
            raw = m.group("int")
            ival = int(raw)
            value = float(ival)
            is_year = 1900 <= ival <= 2099
            track = abs(ival) >= 1000 and not is_year

        if not track:
            continue
        if _values_match(value, raw, known_floats, known_strs):
            continue
        errors.append(
            Issue(
                code="E_NUMBER_UNTRACKED",
                message=f"number '{raw}' does not appear in experiments/results.json",
                line=_line_no(stripped, m.start()),
                context=_context(text, m.start()),
            )
        )


def _check_hedges(text: str, strict: bool, errors: list[Issue], warnings: list[Issue]) -> None:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sent in sentences:
        if not _HEDGE_RE.search(sent):
            continue
        if _HEDGE_CITE_RE.search(sent) or _HEDGE_REF_RE.search(sent):
            continue
        issue = Issue(
            code="E_HEDGE" if strict else "W_HEDGE",
            message="hedge word used without a nearby \\cite or \\ref",
            context=sent.strip()[:200],
        )
        (errors if strict else warnings).append(issue)


def _check_todo(text: str, warnings: list[Issue]) -> None:
    for m in _TODO_RE.finditer(text):
        warnings.append(
            Issue(
                code="W_TODO",
                message=f"found marker '{m.group(0)}'",
                line=_line_no(text, m.start()),
                context=_context(text, m.start()),
            )
        )


def _check_placeholders(text: str, errors: list[Issue]) -> None:
    for m in _PLACEHOLDER_RE.finditer(text):
        errors.append(
            Issue(
                code="E_PLACEHOLDER",
                message=f"unresolved template placeholder {m.group(0)}",
                line=_line_no(text, m.start()),
                context=_context(text, m.start()),
            )
        )


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def check(
    paper_dir: Path,
    ledger_status: dict[str, str] | None = None,
    results: dict | None = None,
    strict: bool = False,
    ledger_meta: dict[str, dict] | None = None,
    fully_proved: set[str] | None = None,
) -> CheckReport:
    """Run all lint rules over ``paper_dir/main.tex`` and write ``check.json``."""
    paper_dir = Path(paper_dir)
    errors: list[Issue] = []
    warnings: list[Issue] = []

    main_path = paper_dir / "main.tex"
    if not main_path.exists():
        errors.append(Issue(code="E_NO_MAIN_TEX", message=f"{main_path} does not exist"))
        report = CheckReport(
            ok=False,
            errors=errors,
            warnings=warnings,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
        _write_report(paper_dir, report)
        return report

    raw = flatten_tex(main_path, paper_dir)
    # Strip comments (keeping newlines so line numbers stay stable) so that commented-out
    # examples, e.g. in the template preamble, are never linted as real content.
    text = "\n".join(_COMMENT_RE.sub("", ln) for ln in raw.split("\n"))

    bib_entries = _parse_bib(paper_dir / "refs.bib")
    if results is None:
        results = _load_results(paper_dir, warnings)
    if ledger_status is None:
        if ledger_meta is None:
            ledger_meta = _load_ledger_meta(paper_dir)
        ledger_status = {cid: m["status"] for cid, m in ledger_meta.items()}
    elif ledger_meta is None:
        ledger_meta = _meta_from_status(ledger_status)
    if fully_proved is not None:
        for cid, m in ledger_meta.items():
            m["fully_proved"] = cid in fully_proved

    _check_refs_labels(text, errors, warnings)
    _check_cites(text, bib_entries, errors, warnings)
    _check_theorems_and_claims(text, ledger_status, errors, warnings, ledger_meta, strict)
    _check_keystep(text, ledger_status, errors)
    _check_numbers(text, results, errors)
    _check_hedges(text, strict, errors, warnings)
    _check_todo(raw, warnings)  # TODO markers count even inside comments
    _check_placeholders(text, errors)

    report = CheckReport(
        ok=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_report(paper_dir, report)
    return report


def _write_report(paper_dir: Path, report: CheckReport) -> None:
    paper_dir = Path(paper_dir)
    paper_dir.mkdir(parents=True, exist_ok=True)
    out_path = paper_dir / "check.json"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))
