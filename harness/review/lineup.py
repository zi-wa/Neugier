"""Decoy-lineup review: the referee is refereed (Round-2 Step 21 / X1).

When a review round opens, the harness prepares a **lineup**: the real proof
artifact plus ``k`` decoys — mutants of the real proof with one planted flaw each
at a known step — plus one clean **control** (a known-correct proof of a
different statement). Items are written under ``reviews/roundN/lineup/{A,B,…}.md``
in seeded random order; the mapping is sealed in ``lineup.sealed.json`` (which the
barrier hook denies to referees) and committed to ``barrier.json`` as
``sha256(salt + real)``. A skeptic reviews every item and emits one verdict block
per item (``item: A``). :func:`score_lineup` then measures recall on the planted
flaws and false alarms on the control; a skeptic whose reliability is below
``budgets.lineup_min_recall`` is **inadmissible** and its verdict on the real
item does not count.

Design notes (see the plan, §8.1 X1): deterministic mutation operators keep the
planted flaw's location and witness keywords machine-checkable; benign,
semantics-preserving edits are applied to *every* item (including the real one)
so pairwise diffs do not single out the real proof; detection is two-stage
(step number match, then witness keyword/fuzzy match), following the
injected-error review benchmark of arXiv 2606.19749 (local math edits, fuzzy
locate + judge) and ProcessBench's all-correct control (arXiv 2412.06559).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import random
import re
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

from harness.ledger.ledger import atomic_write_json
from harness.ledger.schema import utc_now_iso
from harness.proof.lint import parse_proof
from harness.review.verdict import blocks_for_role, ensure_list, iter_errors, role_reports, step_of
from harness.verify.exact import sha256_text

SEALED = "lineup.sealed.json"
UNSEALED = "lineup.unsealed.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LETTERS = "ABCDEFGHIJ"

_STEP_LINE_RE = re.compile(r"^\*\*Step\s+(\d+)\.\*\*\s*(.*)$")
_JUST_RE = re.compile(r"^\(([^)]*)\)\s*")
_QUANT = [
    (re.compile(r"\bfor every\b", re.IGNORECASE), "there exists"),
    (re.compile(r"\bfor all\b", re.IGNORECASE), "there exists"),
    (re.compile(r"\bthere exists\b", re.IGNORECASE), "for every"),
    (re.compile(r"∀"), "∃"),
    (re.compile(r"∃"), "∀"),
]
_INEQ_RE = re.compile(r"(≤|≥|<=|>=|\\le\b|\\ge\b|<|>)")
_HYP_CHECK_RE = re.compile(r"[^.;]*\b(hypothes|holds|satisfied|verified|since|because|by assumption|both)\b[^.;]*[.;]?", re.IGNORECASE)


class LineupError(Exception):
    pass


@dataclass
class Mutation:
    op: str
    step: int | None
    expected_witness_keywords: list[str]
    note: str = ""


@dataclass
class LineupScore:
    agent_id: str
    round: int
    items: list[str]
    planted: int
    detected: int
    recall: float
    false_alarms: int
    reliability: float
    admissible: bool
    min_recall: float
    real_verdict: str | None
    per_item: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------ step helpers --

def _split_steps(lines: list[str]) -> list[tuple[int, int, str]]:
    """``(line_index, step_number, rest)`` for each ``**Step k.**`` line."""
    out = []
    for i, ln in enumerate(lines):
        m = _STEP_LINE_RE.match(ln)
        if m:
            out.append((i, int(m.group(1)), m.group(2)))
    return out


def _set_step(lines: list[str], idx: int, n: int, rest: str) -> None:
    lines[idx] = f"**Step {n}.** {rest}"


def _claim_id(text: str) -> str:
    doc = parse_proof(text)
    return doc.claim or "T-???"


# ------------------------------------------------------- deterministic ops --

def op_drop_hypothesis_check(text: str, rng: random.Random) -> tuple[str, Mutation] | None:
    lines = text.splitlines()
    cands = [(i, n, rest) for i, n, rest in _split_steps(lines) if "<cite" in rest.lower()]
    for i, n, rest in cands:
        m = re.search(r"(<cite[^>]*>)(.*?)(</cite>)", rest, re.IGNORECASE | re.DOTALL)
        inner = m.group(2) if m else rest
        new_inner = _HYP_CHECK_RE.sub("", inner, count=1)
        if new_inner.strip() and new_inner != inner:
            new_rest = rest.replace(inner, new_inner, 1) if m else new_inner
            _set_step(lines, i, n, new_rest)
            key = re.search(r'id="([^"]+)"', rest)
            return "\n".join(lines) + "\n", Mutation(
                "drop_hypothesis_check", n,
                ["hypothes", "check", "cite", "satisf", "verified", "assum"] + ([key.group(1)] if key else []),
                "hypothesis check of the cited theorem removed",
            )
    return None


def op_swap_quantifier(text: str, rng: random.Random) -> tuple[str, Mutation] | None:
    lines = text.splitlines()
    for i, n, rest in _split_steps(lines):
        if "<key-original-step>" in rest.lower():
            continue
        for rx, repl in _QUANT:
            if rx.search(rest):
                _set_step(lines, i, n, rx.sub(repl, rest, count=1))
                return "\n".join(lines) + "\n", Mutation(
                    "swap_quantifier", n, ["quantifier", "for all", "for every", "exists", "order", "∀", "∃", "swap"],
                    "∀/∃ swapped",
                )
    return None


def op_perturb_constant(text: str, rng: random.Random) -> tuple[str, Mutation] | None:
    lines = text.splitlines()
    for i, n, rest in _split_steps(lines):
        if not _INEQ_RE.search(rest) or "<cite" in rest.lower():
            continue
        subs = [(r"-\s*1\b", "+ 1", "+ 1"), (r"\+\s*1\b", "- 1", "- 1"), (r"\^2\b", "^3", "^3"), (r"\b1/2\b", "1/3", "1/3"),
                (r"\b2\s*\|", "3|", "3|")]
        for pat, repl, lit in subs:
            if re.search(pat, rest):
                _set_step(lines, i, n, re.sub(pat, repl, rest, count=1))
                return "\n".join(lines) + "\n", Mutation(
                    "perturb_constant", n, ["constant", "exponent", "inequality", "off by", "coefficient", lit.replace(" ", "")],
                    f"constant changed to {lit}",
                )
        m = re.search(r"(?<![\w-])(\d+)(?![\w])", re.sub(r"Step\s+\d+", "", rest))
        if m and not re.search(r"[A-Z]-\d{3}", rest):
            val = int(m.group(1))
            new = str(val + 1)
            new_rest = re.sub(rf"(?<![\w-]){val}(?![\w])", new, rest, count=1)
            if new_rest != rest:
                _set_step(lines, i, n, new_rest)
                return "\n".join(lines) + "\n", Mutation(
                    "perturb_constant", n, ["constant", "inequality", "off by", "arithmetic", new],
                    f"{val} -> {new}",
                )
    return None


def op_clearly_ify(text: str, rng: random.Random) -> tuple[str, Mutation] | None:
    lines = text.splitlines()
    steps = _split_steps(lines)
    cands = [(i, n, rest) for i, n, rest in steps if _JUST_RE.match(rest) and "<cite" not in rest.lower()]
    if not cands:
        return None
    i, n, rest = cands[len(cands) // 2]
    body = _JUST_RE.sub("", rest).strip()
    sentences = [s for s in re.split(r"(?<=[.;])\s+", body) if s.strip()]
    last = sentences[-1] if sentences else body
    _set_step(lines, i, n, f"Clearly, {last[0].lower() + last[1:] if last else 'the claim follows'}")
    return "\n".join(lines) + "\n", Mutation(
        "clearly_ify", n, ["clearly", "unjustified", "justification", "gap", "no argument", "hedge", "not justified"],
        "justification replaced by 'Clearly'",
    )


def op_make_circular(text: str, rng: random.Random) -> tuple[str, Mutation] | None:
    lines = text.splitlines()
    claim = _claim_id(text)
    steps = _split_steps(lines)
    cands = [(i, n, rest) for i, n, rest in steps if _JUST_RE.match(rest) and "<cite" not in rest.lower()]
    if not cands:
        return None
    i, n, rest = cands[-1]
    body = _JUST_RE.sub("", rest).strip()
    _set_step(lines, i, n, f"(Theorem {claim}) By the theorem being proved, {body[0].lower() + body[1:] if body else 'the claim holds'}")
    return "\n".join(lines) + "\n", Mutation(
        "make_circular", n, ["circular", claim, "assumes the theorem", "theorem being proved", "begs the question", "circularity"],
        "step invokes the theorem itself",
    )


def op_drop_edge_case(text: str, rng: random.Random) -> tuple[str, Mutation] | None:
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower().startswith("## edge cases")), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    bullets = [j for j in range(start + 1, end) if lines[j].lstrip().startswith(("-", "*"))]
    if not bullets:
        return None
    j = bullets[0]
    bullet = lines[j].lstrip("-* ").strip()
    tokens = [t for t in re.findall(r"[A-Za-z|=<>0-9]+", bullet)[:3] if t]
    del lines[j]
    return "\n".join(lines) + "\n", Mutation(
        "drop_edge_case", None, tokens + ["edge case", "missing case", "exhaustive", "boundary", "degenerate", "not checked"],
        f"edge case removed: {bullet[:60]}",
    )


def op_drop_hypothesis_use(text: str, rng: random.Random) -> tuple[str, Mutation] | None:
    doc = parse_proof(text)
    hyps = [str(h) for h in (doc.frontmatter.get("uses_hypotheses") or [])]
    if not hyps:
        return None
    lines = text.splitlines()
    h = hyps[-1]
    changed = False
    for j, ln in enumerate(lines):
        if "hypothesis use" in ln.lower() and h.lower() in ln.lower():
            parts = [p for p in ln.split(";") if h.lower() not in p.lower()]
            lines[j] = ";".join(parts) if len(parts) > 0 and any(p.strip() for p in parts) else "- Hypothesis use: (see steps)"
            changed = True
            break
    step_no = None
    for i, n, rest in _split_steps(lines):
        if "<key-original-step>" in rest.lower():
            continue
        sentences = [s for s in re.split(r"(?<=[.;])\s+", rest) if s.strip()]
        keep = [s for s in sentences if h.lower() not in s.lower()]
        if len(keep) < len(sentences) and keep:
            _set_step(lines, i, n, " ".join(keep))
            step_no = n
            changed = True
            break
    if not changed:
        return None
    return "\n".join(lines) + "\n", Mutation(
        "drop_hypothesis_use", step_no, [h, "unused", "not used", "stronger", "hypothesis", "without using"],
        f"use of hypothesis {h!r} removed",
    )


DETERMINISTIC_OPS = {
    "drop_hypothesis_check": op_drop_hypothesis_check,
    "swap_quantifier": op_swap_quantifier,
    "perturb_constant": op_perturb_constant,
    "make_circular": op_make_circular,
    "drop_hypothesis_use": op_drop_hypothesis_use,
    "drop_edge_case": op_drop_edge_case,
    "clearly_ify": op_clearly_ify,
}


def applicable_ops(text: str) -> list[str]:
    rng = random.Random(0)
    return [name for name, fn in DETERMINISTIC_OPS.items() if fn(text, rng) is not None]


def apply_op(text: str, op: str, rng: random.Random | None = None) -> tuple[str, Mutation]:
    fn = DETERMINISTIC_OPS[op]
    res = fn(text, rng or random.Random(0))
    if res is None:
        raise LineupError(f"operator {op} is not applicable to this artifact")
    return res


# ---------------------------------------------------------------- benign --

def benign_reflow(text: str, rng: random.Random) -> str:
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if heads:
        i = rng.choice(heads)
        if i > 0 and lines[i - 1].strip():
            lines.insert(i, "")
        elif i > 1 and not lines[i - 1].strip() and not lines[i - 2].strip():
            del lines[i - 1]
    return "\n".join(lines) + "\n"


def benign_rename_algebra(text: str, rng: random.Random) -> str:
    variants = ["(algebraic manipulation)", "(elementary algebra)", "(algebra)"]
    lines = text.splitlines()
    idx = [i for i, ln in enumerate(lines) if _STEP_LINE_RE.match(ln) and "(algebra)" in ln]
    if idx:
        i = rng.choice(idx)
        lines[i] = lines[i].replace("(algebra)", rng.choice(variants), 1)
    return "\n".join(lines) + "\n"


def benign_shuffle_edge_bullets(text: str, rng: random.Random) -> str:
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower().startswith("## edge cases")), None)
    if start is None:
        return text
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    bullets = [j for j in range(start + 1, end) if lines[j].lstrip().startswith(("-", "*"))]
    if len(bullets) >= 2:
        a, b = rng.sample(bullets, 2)
        lines[a], lines[b] = lines[b], lines[a]
    return "\n".join(lines) + "\n"


BENIGN_OPS = {
    "reflow": benign_reflow,
    "rename_algebra": benign_rename_algebra,
    "shuffle_edge_bullets": benign_shuffle_edge_bullets,
}


# ----------------------------------------------------------------- build --

def _round_dir(campaign_dir: Path, round_n: int) -> Path:
    return Path(campaign_dir) / "reviews" / f"round{round_n}"


def _control_text() -> str:
    files = sorted(FIXTURES.glob("control_*.md"))
    if not files:
        raise LineupError("no control fixtures packaged under harness/review/fixtures")
    return files[0].read_text(encoding="utf-8")


def commitment(salt: str, real: str) -> str:
    return sha256_text(salt + ":" + real)


def build_lineup(
    campaign_dir: Path | str,
    round_n: int,
    artifact_rel: str,
    k: int = 2,
    *,
    seed: int | None = None,
    control: bool = True,
    ops: list[str] | None = None,
) -> dict:
    """Write ``reviews/roundN/lineup/<L>.md`` items and the sealed spec; update barrier.json."""
    from harness.review.barrier import load_manifest, save_manifest

    campaign_dir = Path(campaign_dir)
    art = campaign_dir / artifact_rel
    if not art.is_file():
        raise LineupError(f"artifact {artifact_rel!r} not found")
    text = art.read_text(encoding="utf-8")
    seed_val = seed if seed is not None else secrets.randbelow(2**31)
    rng = random.Random(seed_val)
    avail = applicable_ops(text)
    chosen = [o for o in (ops or []) if o in avail] or []
    remaining = [o for o in avail if o not in chosen]
    rng.shuffle(remaining)
    chosen += remaining[: max(0, k - len(chosen))]
    if len(chosen) < k:
        raise LineupError(f"only {len(chosen)} applicable mutation operator(s) for {k} decoys (available: {avail})")

    items: list[tuple[str, dict, str]] = []  # (text, spec, kind)
    items.append((text, {"kind": "real"}, "real"))
    for op in chosen:
        mutated, mut = apply_op(text, op, rng)
        items.append((mutated, {"kind": "decoy", "op": op, "step": mut.step, "expected_witness_keywords": mut.expected_witness_keywords, "note": mut.note}, "decoy"))
    if control:
        items.append((_control_text(), {"kind": "control", "source": "harness/review/fixtures"}, "control"))

    # benign edits on every item, then shuffle letters
    benign: dict[str, list[str]] = {}
    processed = []
    for t, spec, kind in items:
        names = rng.sample(list(BENIGN_OPS), k=min(2, len(BENIGN_OPS)))
        for name in names:
            t = BENIGN_OPS[name](t, rng)
        processed.append((t, spec, kind, names))
    rng.shuffle(processed)
    letters = LETTERS[: len(processed)]
    rdir = _round_dir(campaign_dir, round_n)
    ldir = rdir / "lineup"
    ldir.mkdir(parents=True, exist_ok=True)
    for old in ldir.glob("*.md"):
        old.unlink()
    spec_items: dict[str, dict] = {}
    real = None
    for letter, (t, spec, kind, names) in zip(letters, processed):
        (ldir / f"{letter}.md").write_text(t, encoding="utf-8")
        entry = dict(spec)
        entry["diff_sha256"] = sha256_text(t)
        spec_items[letter] = entry
        benign[letter] = names
        if kind == "real":
            real = letter
    salt = secrets.token_hex(8)
    sealed = {
        "version": 1, "round": round_n, "claim": _claim_id(text), "artifact": artifact_rel, "seed": seed_val,
        "real": real, "items": spec_items, "benign": benign, "salt": salt, "created": utc_now_iso(),
    }
    atomic_write_json(rdir / SEALED, sealed)
    try:
        manifest = load_manifest(campaign_dir, round_n)
    except Exception:
        manifest = None
    if manifest is not None:
        manifest["lineup"] = {"items": list(letters), "real_commitment": commitment(salt, real or ""), "sealed": f"reviews/round{round_n}/{SEALED}"}
        for key, role in manifest.get("roles", {}).items():
            if key.split(":", 1)[0] == "skeptic":
                role["allow"] = [p for p in role.get("allow", []) if p not in manifest.get("artifacts", [])]
        save_manifest(campaign_dir, round_n, manifest)
    return sealed


def load_sealed(campaign_dir: Path | str, round_n: int) -> dict:
    path = _round_dir(Path(campaign_dir), round_n) / SEALED
    if not path.exists():
        raise LineupError(f"no lineup for round {round_n} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- score --

def _witness_matches(witness: str, keywords: list[str]) -> bool:
    w = (witness or "").lower()
    if not w:
        return False
    for kw in keywords:
        k = str(kw).lower()
        if not k:
            continue
        if k in w:
            return True
        if difflib.SequenceMatcher(None, k, w).ratio() >= 0.5 and len(k) >= 6:
            return True
        toks = [t for t in re.findall(r"[a-z0-9|=<>+-]+", k) if len(t) >= 4]
        if toks and all(t in w for t in toks):
            return True
    return False


def _blocks_by_item(report_text: str) -> dict[str, dict]:
    from harness.review.verdict import parse_verdict_blocks

    out: dict[str, dict] = {}
    for block in parse_verdict_blocks(report_text):
        item = block.get("item")
        if item:
            out[str(item).strip().upper()] = block
    return out


def score_report(report_text: str, sealed: dict, *, min_recall: float, agent_id: str, round_n: int) -> LineupScore:
    blocks = _blocks_by_item(report_text)
    items = sorted(sealed["items"])
    per_item = []
    planted = 0
    detected = 0
    false_alarms = 0
    real_verdict = None
    for letter in items:
        spec = sealed["items"][letter]
        block = blocks.get(letter)
        verdict = block.get("verdict") if block else None
        row = {"item": letter, "kind": spec["kind"], "verdict": verdict, "step_hit": None, "keyword_hit": None}
        if spec["kind"] == "decoy":
            planted += 1
            hit = False
            if block:
                errs = list(iter_errors(block, "critical_errors")) + list(iter_errors(block, "justification_gaps"))
                for e in errs:
                    step_ok = spec.get("step") is None or step_of(e) == spec.get("step")
                    kw_ok = _witness_matches(str(e.get("witness", "")), spec.get("expected_witness_keywords", []))
                    row["step_hit"] = row["step_hit"] or step_ok
                    row["keyword_hit"] = row["keyword_hit"] or kw_ok
                    if step_ok and kw_ok:
                        hit = True
                        break
                if verdict == "pass":
                    hit = False
            detected += int(hit)
            row["detected"] = hit
        elif spec["kind"] == "control":
            n_crit = len(list(iter_errors(block, "critical_errors"))) if block else 0
            false_alarms += n_crit
            row["false_alarms"] = n_crit
        elif spec["kind"] == "real":
            real_verdict = verdict
        per_item.append(row)
    recall = detected / planted if planted else 1.0
    reliability = recall * max(0.5, 1.0 - 0.25 * false_alarms)
    return LineupScore(
        agent_id=agent_id, round=round_n, items=items, planted=planted, detected=detected, recall=round(recall, 4),
        false_alarms=false_alarms, reliability=round(reliability, 4), admissible=reliability >= min_recall,
        min_recall=min_recall, real_verdict=real_verdict, per_item=per_item,
    )


def _agent_of_report(path: Path) -> str:
    m = re.match(r"skeptic\.(.+)\.md$", path.name)
    return m.group(1) if m else "skeptic"


def score_lineup(campaign_dir: Path | str, round_n: int, agent_id: str | None = None, *, min_recall: float | None = None) -> list[LineupScore]:
    """Score every skeptic report of the round (or one agent); writes ``lineup_score.<agent>.json``."""
    from harness.ledger.ledger import load_budgets

    campaign_dir = Path(campaign_dir)
    sealed = load_sealed(campaign_dir, round_n)
    rdir = _round_dir(campaign_dir, round_n)
    if min_recall is None:
        min_recall = float(load_budgets(campaign_dir).get("lineup_min_recall", 0.8))
    scores: list[LineupScore] = []
    for path in role_reports(rdir, "skeptic"):
        agent = _agent_of_report(path)
        if agent_id and agent != agent_id:
            continue
        score = score_report(path.read_text(encoding="utf-8", errors="replace"), sealed, min_recall=min_recall, agent_id=agent, round_n=round_n)
        atomic_write_json(rdir / f"lineup_score.{agent}.json", score.to_dict())
        scores.append(score)
    return scores


def unseal(campaign_dir: Path | str, round_n: int) -> dict:
    """Reveal the real item to the judge; refused while a skeptic role has no report or no score."""
    from harness.review.barrier import load_manifest

    campaign_dir = Path(campaign_dir)
    sealed = load_sealed(campaign_dir, round_n)
    rdir = _round_dir(campaign_dir, round_n)
    manifest = load_manifest(campaign_dir, round_n)
    for key, role in manifest.get("roles", {}).items():
        if key.split(":", 1)[0] != "skeptic":
            continue
        deliverable = role.get("deliverable")
        if deliverable and not (campaign_dir / deliverable).exists():
            raise LineupError(f"cannot unseal: {key} has not delivered {deliverable}")
        agent = role.get("agent_id") or key.split(":", 1)[-1]
        if not (rdir / f"lineup_score.{agent}.json").exists():
            raise LineupError(f"cannot unseal: {key} is not scored yet (`harness review score-lineup --round {round_n}`)")
    lineup = manifest.get("lineup") or {}
    if lineup.get("real_commitment") != commitment(sealed["salt"], sealed["real"]):
        raise LineupError("commitment mismatch: the sealed lineup does not match barrier.json")
    out = {"round": round_n, "real": sealed["real"], "items": sealed["items"], "unsealed": utc_now_iso()}
    atomic_write_json(rdir / UNSEALED, out)
    return out


def verify_semantic(campaign_dir: Path | str, round_n: int, item: str, step: int) -> list[str]:
    """Check that a saboteur-edited item differs from its original only inside ``step`` (Round-2 X1, optional)."""
    rdir = _round_dir(Path(campaign_dir), round_n)
    orig = rdir / "lineup" / ".work" / f"{item}.orig.md"
    cur = rdir / "lineup" / f"{item}.md"
    if not orig.exists() or not cur.exists():
        return [f"missing {orig.name if not orig.exists() else cur.name}"]
    a = orig.read_text(encoding="utf-8").splitlines()
    b = cur.read_text(encoding="utf-8").splitlines()
    if parse_proof("\n".join(a)).frontmatter != parse_proof("\n".join(b)).frontmatter:
        return ["frontmatter changed"]
    problems = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        for ln in a[i1:i2] + b[j1:j2]:
            m = _STEP_LINE_RE.match(ln)
            if not (m and int(m.group(1)) == step) and not ln.lower().startswith("- hypothesis use"):
                problems.append(f"change outside step {step}: {ln[:60]!r}")
    return problems


# ---------------------------------------------------------------- checks --

def lineup_checks(campaign_dir: Path | str, round_n: int, manifest: dict) -> list[str]:
    """Phase-exit problems for a round with a lineup (called from ``check_round``)."""
    campaign_dir = Path(campaign_dir)
    lineup = manifest.get("lineup")
    if not lineup:
        return []
    rdir = _round_dir(campaign_dir, round_n)
    problems: list[str] = []
    if not (rdir / SEALED).exists():
        return ["lineup declared in barrier.json but lineup.sealed.json is missing"]
    sealed = load_sealed(campaign_dir, round_n)
    if lineup.get("real_commitment") != commitment(sealed["salt"], sealed["real"]):
        problems.append("lineup commitment in barrier.json does not match lineup.sealed.json")
    for path in role_reports(rdir, "skeptic"):
        agent = _agent_of_report(path)
        sp = rdir / f"lineup_score.{agent}.json"
        if not sp.exists():
            problems.append(f"skeptic report {path.name} is not scored against the lineup (`harness review score-lineup --round {round_n}`)")
            continue
        data = json.loads(sp.read_text(encoding="utf-8"))
        if data.get("admissible") is False:
            problems.append(
                f"skeptic {agent} is inadmissible (reliability {data.get('reliability')} < {data.get('min_recall')}): "
                "its verdict does not count; respawn a fresh skeptic"
            )
        if data.get("real_verdict") is None:
            problems.append(f"skeptic {agent} gave no verdict block for the real item")
    return problems


def status(campaign_dir: Path | str, round_n: int) -> dict:
    campaign_dir = Path(campaign_dir)
    rdir = _round_dir(campaign_dir, round_n)
    out: dict = {"round": round_n, "lineup": (rdir / SEALED).exists(), "unsealed": (rdir / UNSEALED).exists(), "scores": []}
    for sp in sorted(rdir.glob("lineup_score.*.json")):
        d = json.loads(sp.read_text(encoding="utf-8"))
        out["scores"].append({k: d.get(k) for k in ("agent_id", "recall", "false_alarms", "reliability", "admissible", "real_verdict")})
    if (rdir / SEALED).exists():
        sealed = load_sealed(campaign_dir, round_n)
        out["items"] = {k: v["kind"] if (rdir / UNSEALED).exists() else "?" for k, v in sealed["items"].items()}
    return out
