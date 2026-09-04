"""Post-proof exact-statement novelty re-check (Round-2 Step 19 / Y4).

Bubeck et al. (arXiv 2511.16072, §II.3) report a bound that "had appeared on
Arxiv nearly 3 years previously" — the literature search had been run on the
*topic* before the result existed, not on the *final statement*. The review-phase
novelty memo must therefore contain a ``## Final-statement queries`` section with
at least ``min_queries`` queries that mention the claim's specific quantities
(values of the ``results.json`` keys the proof's ``numerics:`` references), and its
verdict block must carry ``artifact_sha256`` equal to the artifact under review —
proof that the memo was written after the proof.
"""
from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

from harness.proof.lint import parse_proof
from harness.review.verdict import novelty_memo_path, parse_verdict_blocks
from harness.verify.exact import sha256_file

SECTION_RE = re.compile(r"^##\s*Final-statement queries\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL | re.IGNORECASE)


def _value_strings(value) -> list[str]:
    out: list[str] = []
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    if isinstance(value, bool):
        return [str(value).lower()]
    if isinstance(value, (int, str)):
        s = str(value).strip()
        if s:
            out.append(s)
        try:
            f = Fraction(s)
            if f.denominator != 1:
                out.append(f"{float(f):.4g}")
        except (ValueError, ZeroDivisionError):
            pass
        return out
    if isinstance(value, float):
        out.append(repr(value))
        out.append(f"{value:.4g}")
        return out
    if isinstance(value, (list, tuple)):
        for v in value[:8]:
            out.extend(_value_strings(v))
    return out


def required_quantities(campaign_dir: Path | str, artifact_rel: str) -> list[str]:
    """String forms of the results.json values that the proof's ``numerics:`` references."""
    campaign_dir = Path(campaign_dir)
    art = campaign_dir / artifact_rel
    if not art.exists():
        return []
    doc = parse_proof(art.read_text(encoding="utf-8", errors="replace"))
    keys = [str(n).split("#", 1)[1] if "#" in str(n) else str(n) for n in (doc.frontmatter.get("numerics") or [])]
    results_path = campaign_dir / "experiments" / "results.json"
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        results = {}
    out: list[str] = []
    for k in keys:
        if k in results:
            out.extend(_value_strings(results[k]))
    seen: set[str] = set()
    uniq = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def check_final_statement_queries(memo_text: str, quantities: list[str], min_queries: int = 3) -> list[str]:
    problems: list[str] = []
    m = SECTION_RE.search(memo_text or "")
    if not m:
        return ["novelty memo has no '## Final-statement queries' section (search the exact final statement and its numbers, not the topic)"]
    lines = [ln.strip() for ln in m.group(1).splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", ln)]
    if quantities:
        hits = [ln for ln in lines if any(q in ln for q in quantities)]
        if len(hits) < min_queries:
            problems.append(
                f"'## Final-statement queries' lists {len(hits)} query(ies) containing the proof's quantities "
                f"({', '.join(quantities[:4])}{'…' if len(quantities) > 4 else ''}); need at least {min_queries}"
            )
    elif len(lines) < min_queries:
        problems.append(f"'## Final-statement queries' lists {len(lines)} query(ies); need at least {min_queries}")
    return problems


def memo_artifact_sha(memo_text: str) -> str | None:
    for block in reversed(parse_verdict_blocks(memo_text)):
        sha = block.get("artifact_sha256")
        if sha:
            return str(sha)
    return None


def novelty_recheck(campaign_dir: Path | str, round_n: int, manifest: dict, *, required: bool) -> list[str]:
    """Problems (when ``required``) or warnings-as-problems prefixed ``advisory:`` (when not)."""
    campaign_dir = Path(campaign_dir)
    memo = novelty_memo_path(campaign_dir, round_n)
    if memo is None:
        return []
    text = memo.read_text(encoding="utf-8", errors="replace")
    artifacts = list(manifest.get("artifacts") or [])
    quantities: list[str] = []
    for a in artifacts:
        quantities.extend(required_quantities(campaign_dir, a))
    problems = check_final_statement_queries(text, quantities)
    sha = memo_artifact_sha(text)
    if artifacts:
        current = sha256_file(campaign_dir / artifacts[0]) if (campaign_dir / artifacts[0]).exists() else None
        if sha is None:
            problems.append("novelty memo verdict block lacks artifact_sha256 (proves the memo was written after the proof)")
        elif current and not (sha.startswith(current) or current.startswith(sha)):
            problems.append("novelty memo artifact_sha256 does not match the artifact under review (memo predates the final proof?)")
    if required:
        return [f"final-statement re-check: {p}" for p in problems]
    return [f"advisory: final-statement re-check: {p}" for p in problems]
