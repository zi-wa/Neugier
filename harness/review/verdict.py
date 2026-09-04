"""Parsers for referee/judge artifacts (``reviews/roundN/*.md``).

Referees end their reports with a fenced ```yaml block (referee-checklist.md §7);
the judge writes an adjudication block (§8) and a final ``VERDICT: …`` line; the
skeptic keeps a step table (§2). Nothing else in the harness should parse these
files ad hoc — use this module so the gates, the coverage metric and the hooks
agree on what a valid verdict is.

``hooks/_common.py`` carries a minimal stdlib re-implementation of
:func:`verdict_block_looks_valid` (hooks may run without the venv); a test
asserts that both agree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

JUDGE_DECISIONS = ("PASS", "REVISE_PROOF", "REVISE_PLAN", "REWRITE", "PIVOT")
REFEREE_ROLES = ("skeptic", "falsifier", "novelty", "replicator", "judge")
NOVELTY_CLASSES = ("1a", "1b", "1c", "1d")

_FENCE_RE = re.compile(r"```(?:yaml|yml)[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL | re.IGNORECASE)
_VERDICT_LINE_RE = re.compile(r"^\s*VERDICT:\s*(PASS|REVISE_PROOF|REVISE_PLAN|REWRITE|PIVOT)\s*$", re.MULTILINE)
_CLASS_RE = re.compile(r"1\s*\(?\s*([abcd])\s*\)?", re.IGNORECASE)
_STEP_ROW_RE = re.compile(
    r"^\|\s*(?:Step\s*)?(\d+)\s*\|\s*(VERIFIED|OPEN|FLAWED)\b([^|]*)\|([^|]*)\|([^|]*)\|?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_class(value) -> str | None:
    """``"1a"``, ``"1(a)"``, ``"class 1 b"`` … -> ``"1a"``; anything else -> ``None``."""
    if value is None:
        return None
    m = _CLASS_RE.search(str(value))
    if not m:
        return None
    return "1" + m.group(1).lower()


def _normalize_block(block: dict) -> dict:
    out = dict(block)
    if "role" in out and out["role"] is not None:
        role = str(out["role"]).strip().lower()
        out["role"] = "novelty" if role == "novelty-checker" else role
    if "verdict" in out and out["verdict"] is not None:
        v = str(out["verdict"]).strip()
        if out.get("role") == "judge":
            out["verdict"] = v.upper() if v.upper() in JUDGE_DECISIONS else v
        else:
            out["verdict"] = v.lower()
    for key in ("class", "classification"):
        if key in out:
            out["class"] = normalize_class(out[key])
    for key in ("critical_errors", "justification_gaps", "interpretation_issues", "checked",
                "upheld", "rebutted", "moot", "reproduced"):
        if key in out and out[key] is None:
            out[key] = []
    return out


def parse_verdict_blocks(text: str) -> list[dict]:
    """Every fenced ```yaml block in ``text`` that parses to a mapping, normalized."""
    blocks: list[dict] = []
    for m in _FENCE_RE.finditer(text or ""):
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            blocks.append(_normalize_block(data))
    return blocks


def parse_verdict_block(text: str) -> dict | None:
    """The last fenced yaml mapping in ``text`` (a referee's verdict), or ``None``."""
    blocks = parse_verdict_blocks(text)
    return blocks[-1] if blocks else None


def verdict_block_looks_valid(block: dict | None, role: str | None = None) -> bool:
    """A referee block needs ``role``, ``claim`` and ``verdict``; a judge block needs a decision."""
    if not isinstance(block, dict):
        return False
    if not block.get("role") or not block.get("claim"):
        return False
    v = block.get("verdict")
    if not v:
        return False
    r = str(block["role"])
    if role and r != role:
        return False
    if r == "judge":
        return str(v).upper() in JUDGE_DECISIONS
    return str(v).lower() in ("pass", "fail", "revise", "n/a")


def judge_verdict(text: str) -> str | None:
    """The decision on the last ``VERDICT: …`` line of ``judge.md``, or ``None``."""
    matches = _VERDICT_LINE_RE.findall(text or "")
    return matches[-1] if matches else None


def parse_judge_block(text: str) -> dict | None:
    """The judge's structured adjudication block (``role: judge``), if present."""
    for block in reversed(parse_verdict_blocks(text)):
        if block.get("role") == "judge":
            return block
    return None


@dataclass
class StepRow:
    step: int
    status: str  # VERIFIED | OPEN | FLAWED
    severity: str | None  # critical | gap | None
    justification: str
    witness: str


def parse_step_table(text: str) -> dict[int, StepRow]:
    """The skeptic's step-level state machine table (§2), keyed by step number.

    Tolerates ``FLAWED (critical)``/``FLAWED-gap`` spellings; when a step appears
    more than once, FLAWED wins over OPEN wins over VERIFIED.
    """
    rank = {"VERIFIED": 0, "OPEN": 1, "FLAWED": 2}
    rows: dict[int, StepRow] = {}
    for m in _STEP_ROW_RE.finditer(text or ""):
        step = int(m.group(1))
        status = m.group(2).upper()
        qualifier = (m.group(3) or "").lower()
        severity = None
        if status == "FLAWED":
            severity = "critical" if "critical" in qualifier else ("gap" if "gap" in qualifier else None)
        row = StepRow(step, status, severity, m.group(4).strip(), m.group(5).strip())
        prev = rows.get(step)
        if prev is None or rank[status] >= rank[prev.status]:
            rows[step] = row
    return rows


# ---------------------------------------------------------------- rounds --

def round_dirs(campaign_dir: Path | str) -> list[tuple[int, Path]]:
    reviews = Path(campaign_dir) / "reviews"
    out: list[tuple[int, Path]] = []
    if not reviews.is_dir():
        return out
    for p in reviews.iterdir():
        m = re.fullmatch(r"round(\d+)", p.name)
        if m and p.is_dir():
            out.append((int(m.group(1)), p))
    return sorted(out)


def latest_round(campaign_dir: Path | str) -> int | None:
    dirs = round_dirs(campaign_dir)
    return dirs[-1][0] if dirs else None


def _read(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def novelty_memo_path(campaign_dir: Path | str, round_n: int | None = None) -> Path | None:
    """``reviews/roundN/novelty.md`` for the given (default: latest) round that has one."""
    dirs = round_dirs(campaign_dir)
    if round_n is not None:
        dirs = [(n, p) for n, p in dirs if n == round_n]
    for n, p in reversed(dirs):
        cand = p / "novelty.md"
        if cand.is_file():
            return cand
    return None


def novelty_class(campaign_dir: Path | str, round_n: int | None = None) -> str | None:
    """Normalized 1a–1d classification from the novelty memo's verdict block, or ``None``."""
    path = novelty_memo_path(campaign_dir, round_n)
    if path is None:
        return None
    for block in reversed(parse_verdict_blocks(_read(path))):
        cls = block.get("class")
        if cls in NOVELTY_CLASSES:
            return cls
    m = re.search(r"##\s*Classification:\s*(1\s*\(?[abcd]\)?)", _read(path), re.IGNORECASE)
    return normalize_class(m.group(1)) if m else None


def role_reports(round_dir: Path | str, role: str) -> list[Path]:
    """Report files for ``role`` in a round dir: ``<role>.md`` and ``<role>.<agent>.md``."""
    rd = Path(round_dir)
    if not rd.is_dir():
        return []
    files = [p for p in rd.glob(f"{role}*.md") if p.name == f"{role}.md" or p.name.startswith(f"{role}.")]
    return sorted(files, key=lambda p: p.name)  # by name (case-sensitive) so the order is OS-independent


def blocks_for_role(round_dir: Path | str, role: str) -> list[dict]:
    """All valid verdict blocks with ``role`` across the role's report files."""
    out: list[dict] = []
    for path in role_reports(round_dir, role):
        for block in parse_verdict_blocks(_read(path)):
            if block.get("role") == role and verdict_block_looks_valid(block, role):
                out.append(block)
    return out


def ensure_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def step_of(error) -> int | None:
    """Step number referenced by a critical_error/gap entry (int, ``"Step 7"``, ``{"step": 7}``)."""
    if isinstance(error, dict):
        error = error.get("step")
    if error is None:
        return None
    m = re.search(r"(\d+)", str(error))
    return int(m.group(1)) if m else None


def iter_errors(block: dict, key: str = "critical_errors") -> Iterable[dict]:
    for e in ensure_list(block.get(key)):
        if isinstance(e, dict):
            yield e
        else:
            yield {"step": step_of(e), "witness": str(e)}
