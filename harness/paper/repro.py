"""Generate the reproducibility appendix (``paper/appendix-repro.tex``).

``write_appendix(campaign_dir)`` reads ``ledger.json`` and
``experiments/results.json`` directly as JSON (the ledger module is not
imported here, so this works even before/independently of it), captures the
current Python environment (version, platform, ``pip list --format=json``
from ``sys.executable``), and writes a small ``\\input``-able ``.tex`` file
with: an environment table, a table of computation/falsification/formalization
ledger evidence, a table of ``results.json`` entries, and a "how to reproduce"
list of ``python <path>`` invocations. All inserted strings are LaTeX-escaped.
"""
from __future__ import annotations

import hashlib
import json
import platform
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


def _pip_list() -> list[tuple[str, str]]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if proc.returncode != 0 or not proc.stdout:
            return []
        data = json.loads(proc.stdout)
        return [(str(d.get("name", "")), str(d.get("version", ""))) for d in data]
    except Exception:
        return []


def _environment_rows() -> list[tuple[str, str]]:
    return [
        ("Python version", sys.version.split()[0]),
        ("Platform", platform.platform()),
        ("Interpreter", sys.executable),
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
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _extract_evidence(ledger_data: dict, campaign_dir: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Return (evidence rows, distinct .py script paths worth re-running)."""
    rows: list[dict[str, str]] = []
    scripts: list[str] = []

    claims = ledger_data.get("claims", {})
    if isinstance(claims, dict):
        items = list(claims.items())
    elif isinstance(claims, list):
        items = [(c.get("id", c.get("claim_id", "?")), c) for c in claims if isinstance(c, dict)]
    else:
        items = []

    for claim_id, claim in items:
        if not isinstance(claim, dict):
            continue
        evidence_list = claim.get("evidence", [])
        if not isinstance(evidence_list, list):
            continue
        for ev in evidence_list:
            if not isinstance(ev, dict):
                continue
            ev_type = str(ev.get("type") or ev.get("kind") or "")
            if ev_type not in _EVIDENCE_TYPES:
                continue
            path = str(ev.get("path") or ev.get("file") or "")
            sha = str(ev.get("sha256") or ev.get("hash") or "")
            if not sha and path:
                sha = _hash_file(campaign_dir / path)
            summary = str(ev.get("summary") or ev.get("description") or ev.get("note") or "")
            rows.append(
                {
                    "claim_id": str(claim_id),
                    "type": ev_type,
                    "path": path,
                    "sha12": sha[:12],
                    "summary": summary,
                }
            )
            if path.endswith(".py") and ev_type in ("computation", "falsification") and path not in scripts:
                scripts.append(path)
    return rows, scripts


def _format_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _results_rows(results: dict) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for key, value in results.items():
        source = ""
        if isinstance(value, dict) and "value" in value and "source" in value:
            source = str(value.get("source", ""))
            value = value.get("value")
        rows.append((str(key), _format_value(value), source))
    return rows


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def _render_table(headers: list[str], rows: list[tuple[str, ...]], empty_note: str) -> str:
    if not rows:
        return empty_note + "\n"
    ncols = len(headers)
    colspec = "l" * ncols
    lines = [r"\begin{tabular}{" + colspec + "}", r"\toprule"]
    lines.append(" & ".join(escape_latex(h) for h in headers) + r" \\")
    lines.append(r"\midrule")
    for row in rows:
        lines.append(" & ".join(escape_latex(c) for c in row) + r" \\")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    return "\n".join(lines) + "\n"


def _render_appendix_tex(
    env_rows: list[tuple[str, str]],
    pkgs: list[tuple[str, str]],
    evidence_rows: list[dict[str, str]],
    results_rows: list[tuple[str, str, str]],
    scripts: list[str],
) -> str:
    parts: list[str] = []

    parts.append(r"\subsection{Environment}")
    parts.append(_render_table(["Item", "Value"], env_rows, "No environment information recorded."))

    parts.append(r"\subsection{Installed packages}")
    if pkgs:
        pkg_rows = [(name, version) for name, version in pkgs]
        parts.append(_render_table(["Package", "Version"], pkg_rows, "No package list recorded."))
    else:
        parts.append("Package list unavailable (\\texttt{pip list} could not be run).\n")

    parts.append(r"\subsection{Ledger evidence}")
    ev_rows = [
        (e["claim_id"], e["type"], e["path"], e["sha12"], e["summary"]) for e in evidence_rows
    ]
    parts.append(
        _render_table(
            ["Claim", "Type", "Path", "SHA-256", "Summary"],
            ev_rows,
            "No computation, falsification, or formalization evidence recorded in the ledger.",
        )
    )

    parts.append(r"\subsection{Computed quantities}")
    parts.append(
        _render_table(
            ["Key", "Value", "Source"],
            results_rows,
            "No entries found in \\texttt{experiments/results.json}.",
        )
    )

    parts.append(r"\subsection{How to reproduce}")
    if scripts:
        parts.append(r"\begin{enumerate}")
        for path in scripts:
            parts.append(r"\item \texttt{python " + escape_latex(path) + "}")
        parts.append(r"\end{enumerate}")
    else:
        parts.append("No computation scripts were recorded in the ledger.\n")

    return "\n".join(parts) + "\n"


def write_appendix(campaign_dir: Path) -> Path:
    """Write ``campaign_dir/paper/appendix-repro.tex`` and return its path."""
    campaign_dir = Path(campaign_dir)
    paper_dir = campaign_dir / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    out_path = paper_dir / "appendix-repro.tex"

    env_rows = _environment_rows()
    pkgs = _pip_list()

    ledger_data = _read_json(campaign_dir / "ledger.json")
    evidence_rows, scripts = _extract_evidence(ledger_data, campaign_dir)

    results = _read_json(campaign_dir / "experiments" / "results.json")
    results_rows = _results_rows(results)

    tex = _render_appendix_tex(env_rows, pkgs, evidence_rows, results_rows, scripts)
    out_path.write_text(tex, encoding="utf-8")
    return out_path
