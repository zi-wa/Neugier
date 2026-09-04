"""Generate the reproducibility appendix (``paper/appendix-repro.tex``).

``write_appendix(campaign_dir)`` reads ``ledger.json``, ``campaign.json`` and
``experiments/results.json`` as JSON, captures the environment (Python, platform,
harness version, git revision + dirty flag, tectonic version, ``pip list``), and
writes an ``\\input``-able ``.tex`` file with:

* Environment, Installed packages
* Frozen files (scorers/verifiers/statement/rubrics with sha256) and evolutionary
  scorers (evaluator hashes, generations, best scores)
* Ledger evidence (computation / falsification / formalization) with the
  verification tier of each claim
* **Provenance** (Round-2 Y9): per asserted claim the blueprint status, review
  rounds, skeptic step coverage, verified citations, reproduced numerics,
  falsified lemmas, novelty class, referee reliability; the review-barrier
  summary per round; the audited-accuracy line from ``paper/audit.json``
* Computed quantities (with seeds), and "How to reproduce" with exact commands
* **AI involvement disclosure** (Round-2 Y10, :mod:`harness.paper.disclosure`)

All inserted strings are LaTeX-escaped. Sources are cited only when the key
exists in ``refs.bib`` (``kosmos2025``, ``agents4science2025``); otherwise a
plain-text attribution is used so ``paper check`` never sees an undefined cite.
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from pathlib import Path

_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

_EVIDENCE_TYPES = ("computation", "falsification", "formalization")


def escape_latex(value: object) -> str:
    """Escape LaTeX special characters ``_ % & # $ { } ~ ^ \\`` in ``value``."""
    s = "" if value is None else str(value)
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in s)


# --------------------------------------------------------------------------
# data gathering
# --------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
                              cwd=str(cwd) if cwd else None)
        return (proc.stdout or "").strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


def _pip_list() -> list[tuple[str, str]]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if proc.returncode != 0 or not proc.stdout:
            return []
        data = json.loads(proc.stdout)
        return [(str(d.get("name", "")), str(d.get("version", ""))) for d in data]
    except Exception:
        return []


def git_revision(campaign_dir: Path) -> str:
    rev = _run(["git", "rev-parse", "--short", "HEAD"], cwd=campaign_dir)
    if not rev:
        return "(no commits)"
    dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=campaign_dir)
    return rev + (" (dirty)" if dirty else "")


def tectonic_version() -> str:
    try:
        from harness.paper.build import find_tectonic

        t = find_tectonic()
    except Exception:
        t = None
    if t is None:
        return "not installed"
    out = _run([str(t), "--version"])
    return out.splitlines()[0] if out else "unknown"


def _harness_version() -> str:
    try:
        import harness

        return getattr(harness, "__version__", "unknown")
    except Exception:
        return "unknown"


def _environment_rows(campaign_dir: Path) -> list[tuple[str, str]]:
    return [
        ("Neugier harness", _harness_version()),
        ("Git revision", git_revision(campaign_dir)),
        ("Python version", sys.version.split()[0]),
        ("Platform", platform.platform()),
        ("Interpreter", sys.executable),
        ("LaTeX engine", "tectonic " + tectonic_version()),
    ]


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _hash_file(path: Path) -> str:
    try:
        from harness.verify.exact import sha256_file

        return sha256_file(path)
    except OSError:
        return ""


def _claims(ledger_data: dict) -> list[tuple[str, dict]]:
    claims = ledger_data.get("claims", {})
    if isinstance(claims, dict):
        return [(cid, c) for cid, c in claims.items() if isinstance(c, dict)]
    if isinstance(claims, list):
        return [(c.get("id", "?"), c) for c in claims if isinstance(c, dict)]
    return []


def _extract_evidence(ledger_data: dict, campaign_dir: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Return (evidence rows, distinct .py script paths worth re-running)."""
    rows: list[dict[str, str]] = []
    scripts: list[str] = []
    for claim_id, claim in _claims(ledger_data):
        for ev in claim.get("evidence", []) or []:
            if not isinstance(ev, dict):
                continue
            ev_type = str(ev.get("type") or ev.get("kind") or "")
            if ev_type not in _EVIDENCE_TYPES:
                continue
            path = str(ev.get("path") or ev.get("file") or "")
            sha = str(ev.get("file_hash") or ev.get("sha256") or ev.get("hash") or "")
            if not sha and path:
                sha = _hash_file(campaign_dir / path)
            rows.append({"claim_id": str(claim_id), "type": ev_type, "path": path, "sha12": sha[:12],
                         "summary": str(ev.get("summary") or ev.get("description") or ev.get("note") or "")})
            if path.endswith(".py") and ev_type in ("computation", "falsification") and path not in scripts:
                scripts.append(path)
    return rows, scripts


def _format_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _results_rows(results: dict) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for key, value in results.items():
        source, seed = "", ""
        if isinstance(value, dict) and "value" in value:
            source = str(value.get("source", "") or "")
            seed = "" if value.get("seed") is None else str(value.get("seed"))
            value = value.get("value")
        rows.append((str(key), _format_value(value), source, seed))
    return rows


def _reproduce_commands(results: dict, scripts: list[str]) -> list[str]:
    cmds: list[str] = []
    seen: set[str] = set()
    for key, value in results.items():
        if isinstance(value, dict) and value.get("source"):
            src = str(value["source"])
            if not src.endswith(".py"):
                continue
            args = value.get("args")
            arg_s = " ".join(str(a) for a in args) if isinstance(args, (list, tuple)) else (str(args) if args else "")
            cmd = f"python {src}{(' ' + arg_s) if arg_s else ''}"
            if cmd not in seen:
                seen.add(cmd)
                cmds.append(cmd + f"   # -> results.json#{key}")
    for path in scripts:
        cmd = f"python {path}"
        if cmd not in seen:
            seen.add(cmd)
            cmds.append(cmd)
    return cmds


def _frozen_rows(campaign_dir: Path) -> list[tuple[str, str]]:
    camp = _read_json(campaign_dir / "campaign.json")
    rows = [(rel, str(sha)[:12]) for rel, sha in sorted((camp.get("frozen") or {}).items())]
    for cid, sha in sorted((camp.get("rubric_hashes") or {}).items()):
        rows.append((f"proofs/{cid}.rubric.md", str(sha)[:12]))
    return rows


def _evolve_rows(campaign_dir: Path) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    root = campaign_dir / "experiments" / "evolve"
    if not root.is_dir():
        return rows
    for meta_path in sorted(root.glob("*/meta.json")):
        meta = _read_json(meta_path)
        hist = meta.get("history") or []
        best = hist[-1].get("best") if hist and isinstance(hist[-1], dict) else None
        rows.append((meta_path.parent.name, str(meta.get("evaluator_sha256", ""))[:12], str(meta.get("generation", 0)),
                     json.dumps(best, ensure_ascii=False) if best else ""))
    return rows


# ------------------------------------------------------------ provenance --

def _bib_keys(paper_dir: Path) -> set[str]:
    p = paper_dir / "refs.bib"
    if not p.exists():
        return set()
    return set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", p.read_text(encoding="utf-8", errors="replace")))


def _attrib(paper_dir: Path, key: str, plain: str) -> str:
    return f"\\cite{{{key}}}" if key in _bib_keys(paper_dir) else escape_latex(plain)


def _provenance_rows(campaign_dir: Path) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    try:
        from harness.ledger.graph import blueprint_statuses
        from harness.ledger.ledger import LedgerStore
        from harness.proof.coverage import compute_coverage
        from harness.review.verdict import novelty_class
    except Exception:
        return rows
    ledger_path = campaign_dir / "ledger.json"
    if not ledger_path.exists():
        return rows
    try:
        store = LedgerStore(ledger_path)
        bp = blueprint_statuses(store)
    except Exception:  # noqa: BLE001 - a hand-written/legacy ledger must not break the appendix
        return rows
    for claim in store.assertable():
        rounds = sorted({ev.round for ev in claim.evidence if ev.type == "referee" and ev.round is not None})
        rels = [ev.reliability for ev in claim.evidence if ev.type == "referee" and ev.role == "skeptic" and ev.reliability is not None]
        rel = f"{sum(rels) / len(rels):.2f}" if rels else "—"
        try:
            cov = compute_coverage(campaign_dir, claim.id, rounds[-1] if rounds else None, store)
            steps = f"{cov.steps_verified_by_skeptic}/{cov.steps_total}"
            cites = f"{cov.cites_verified}/{cov.cites_total}"
            nums = f"{cov.numerics_reproduced}/{cov.numerics_total}"
            lems = f"{cov.lemmas_falsified}/{cov.lemmas_total}"
        except Exception:
            steps = cites = nums = lems = "n/a"
        cls = novelty_class(campaign_dir, rounds[-1] if rounds else None) or "—"
        tier = f"stakes {claim.stakes}" + (", attested" if claim.attestation else "")
        rows.append((claim.id, bp.get(claim.id, "?"), str(len(rounds)), steps, cites, nums, lems, cls, rel, tier))
    return rows


def _barrier_summary(campaign_dir: Path) -> list[str]:
    lines: list[str] = []
    try:
        from harness.review.barrier import read_access_log
        from harness.review.verdict import round_dirs
    except Exception:
        return lines
    for n, rdir in round_dirs(campaign_dir):
        manifest = _read_json(rdir / "barrier.json")
        if not manifest:
            continue
        rows = read_access_log(rdir)
        allows = sum(1 for r in rows if r.get("decision") == "allow")
        denies = sum(1 for r in rows if r.get("decision") == "deny")
        roles = sorted({str(r.get("role")) for r in rows if r.get("role")})
        rep = (manifest.get("roles") or {}).get("replicator") or {}
        blind = rep.get("blind_committed")
        lineup = manifest.get("lineup")
        scores = []
        for sp in sorted(rdir.glob("lineup_score.*.json")):
            d = _read_json(sp)
            scores.append(f"{d.get('agent_id')}: reliability {d.get('reliability')}{'' if d.get('admissible') else ' (inadmissible)'}")
        parts = [f"Round {n}: {len(roles)} referee context(s) behind the information barrier, {allows} logged access(es), "
                 f"{denies} denial(s), {len(manifest.get('waivers') or [])} waiver(s)"]
        if blind:
            parts.append(f"replicator blind values committed at {blind[:19]} before it saw the artifact")
        if lineup:
            parts.append(f"decoy lineup of {len(lineup.get('items') or [])} items" + (": " + "; ".join(scores) if scores else ""))
        lines.append(". ".join(parts) + ".")
    return lines


def _audit_line(paper_dir: Path) -> str:
    data = _read_json(paper_dir / "audit.json")
    if not data:
        return "No sampled accuracy audit was recorded."
    sents = data.get("sentences") or []
    supported = sum(1 for s in sents if s.get("label") == "supported")
    refuted = sum(1 for s in sents if s.get("label") == "refuted")
    unclear = sum(1 for s in sents if s.get("label") == "unclear")
    unlabeled = sum(1 for s in sents if not s.get("label"))
    return (f"Audited accuracy: {supported}/{len(sents)} sampled sentences supported by evidence ({refuted} refuted, "
            f"{unclear} unclear, {unlabeled} unlabeled; seed {escape_latex(data.get('seed'))}).")


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def _render_table(headers: list[str], rows: list[tuple[str, ...]], empty_note: str, small: bool = False) -> str:
    if not rows:
        return empty_note + "\n"
    ncols = len(headers)
    colspec = "l" * ncols
    lines = [r"{\small" if small else "", r"\begin{tabular}{" + colspec + "}", r"\toprule"]
    lines.append(" & ".join(escape_latex(h) for h in headers) + r" \\")
    lines.append(r"\midrule")
    for row in rows:
        lines.append(" & ".join(escape_latex(c) for c in row) + r" \\")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    if small:
        lines.append("}")
    return "\n".join(ln for ln in lines if ln) + "\n"


def _render_appendix_tex(campaign_dir: Path, paper_dir: Path) -> str:
    ledger_data = _read_json(campaign_dir / "ledger.json")
    evidence_rows, scripts = _extract_evidence(ledger_data, campaign_dir)
    results = _read_json(campaign_dir / "experiments" / "results.json")
    results_rows = _results_rows(results)
    parts: list[str] = []

    parts.append(r"\subsection{Environment}")
    parts.append(_render_table(["Item", "Value"], _environment_rows(campaign_dir), "No environment information recorded."))

    parts.append(r"\subsection{Installed packages}")
    pkgs = _pip_list()
    if pkgs:
        parts.append(_render_table(["Package", "Version"], [(n, v) for n, v in pkgs], "No package list recorded.", small=True))
    else:
        parts.append("Package list unavailable (\\texttt{pip list} could not be run).\n")

    parts.append(r"\subsection{Frozen files and scorers}")
    parts.append(_render_table(["File", "SHA-256"], _frozen_rows(campaign_dir), "No files were frozen."))
    parts.append(_render_table(["Evolutionary run", "Evaluator SHA-256", "Generations", "Best"], _evolve_rows(campaign_dir),
                               "No evolutionary search was run."))

    parts.append(r"\subsection{Ledger evidence}")
    ev_rows = [(e["claim_id"], e["type"], e["path"], e["sha12"], e["summary"]) for e in evidence_rows]
    parts.append(_render_table(["Claim", "Type", "Path", "SHA-256", "Summary"], ev_rows,
                               "No computation, falsification, or formalization evidence recorded in the ledger.", small=True))

    parts.append(r"\subsection{Provenance}\label{sec:provenance}")
    parts.append(
        "Every asserted claim below passed the adversarial review behind an information barrier; the columns report how "
        "much of its proof was independently verified, in the spirit of the per-statement audit of "
        + _attrib(paper_dir, "kosmos2025", "Kosmos (Mitchener et al., 2025)") + ".\n"
    )
    parts.append(_render_table(
        ["Claim", "Blueprint", "Rounds", "Steps verified", "Cites verified", "Numerics reproduced", "Lemmas falsified",
         "Novelty", "Referee reliability", "Tier"],
        _provenance_rows(campaign_dir), "No claim is asserted as a theorem.", small=True,
    ))
    for line in _barrier_summary(campaign_dir):
        parts.append(escape_latex(line) + "\n")
    parts.append(_audit_line(paper_dir) + "\n")

    parts.append(r"\subsection{Computed quantities}")
    parts.append(_render_table(["Key", "Value", "Source", "Seed"], results_rows,
                               "No entries found in \\texttt{experiments/results.json}.", small=True))

    parts.append(r"\subsection{How to reproduce}")
    cmds = _reproduce_commands(results, scripts)
    parts.append(f"Interpreter: \\texttt{{{escape_latex(sys.executable)}}}; run from the campaign directory.\n")
    if cmds:
        parts.append(r"\begin{enumerate}")
        for cmd in cmds:
            parts.append(r"\item \texttt{" + escape_latex(cmd) + "}")
        parts.append(r"\end{enumerate}")
    else:
        parts.append("No computation scripts were recorded in the ledger.\n")

    try:
        from harness.paper.disclosure import render_disclosure_tex, write_disclosure

        write_disclosure(campaign_dir)
        parts.append(render_disclosure_tex(campaign_dir, paper_dir))
    except Exception as exc:  # noqa: BLE001 - the appendix must still build
        parts.append(r"\subsection{AI involvement disclosure}\label{sec:disclosure}")
        parts.append(f"Disclosure could not be generated ({escape_latex(type(exc).__name__)}).\n")

    return "\n".join(parts) + "\n"


def write_appendix(campaign_dir: Path) -> Path:
    """Write ``campaign_dir/paper/appendix-repro.tex`` and return its path."""
    campaign_dir = Path(campaign_dir)
    paper_dir = campaign_dir / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    out_path = paper_dir / "appendix-repro.tex"
    out_path.write_text(_render_appendix_tex(campaign_dir, paper_dir), encoding="utf-8")
    return out_path
