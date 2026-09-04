"""Build the LaTeX paper with tectonic, and render the amsart template.

Functions
---------
find_tectonic() -> Path | None
    Locate the tectonic binary: ``harness.BIN`` first, then ``PATH``.
render_template(...)
    Fill ``templates/main.tex`` placeholders and write ``paper_dir/main.tex``.
build(paper_dir, main="main.tex", timeout=600) -> BuildResult
    Run tectonic against ``paper_dir/main`` and report the outcome.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "main.tex"


class BuildResult(BaseModel):
    """Outcome of a single tectonic build invocation."""

    ok: bool
    pdf: Path | None = None
    log: str = ""
    engine: str = ""
    seconds: float = 0.0


def find_tectonic() -> Path | None:
    """Locate the tectonic executable.

    Looks in ``harness.BIN`` (``tectonic.exe`` on Windows, ``tectonic``
    elsewhere) first, then falls back to ``PATH``.
    """
    from harness import BIN

    for name in ("tectonic.exe", "tectonic"):
        candidate = BIN / name
        if candidate.exists():
            return candidate
    found = shutil.which("tectonic")
    if found:
        return Path(found)
    return None


def render_template(
    paper_dir: Path,
    title: str,
    author: str,
    abstract: str,
    body: str,
    tools: str,
    date: str | None = None,
    force: bool = False,
) -> Path:
    """Fill the amsart template placeholders and write ``paper_dir/main.tex``.

    Does not overwrite an existing ``main.tex`` unless ``force=True``.
    """
    paper_dir = Path(paper_dir)
    paper_dir.mkdir(parents=True, exist_ok=True)
    out_path = paper_dir / "main.tex"
    if out_path.exists() and not force:
        return out_path

    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    filled = (
        template_text.replace("{{TITLE}}", title)
        .replace("{{AUTHOR}}", author)
        .replace("{{ABSTRACT}}", abstract)
        .replace("{{DATE}}", date if date is not None else r"\today")
        .replace("{{BODY}}", body)
        .replace("{{TOOLS}}", tools)
    )
    out_path.write_text(filled, encoding="utf-8")
    return out_path


def build(paper_dir: Path, main: str = "main.tex", timeout: int = 600) -> BuildResult:
    """Compile ``paper_dir/main`` with tectonic.

    Runs ``tectonic --keep-logs --keep-intermediates -o <paper_dir> main.tex``
    with ``cwd=paper_dir`` and ``TECTONIC_CACHE_DIR`` pointed at the project
    cache. The tectonic v1 CLI runs bibtex automatically when ``\\bibliography``
    is present. Writes ``paper_dir/build.log`` with the combined stdout/stderr.
    """
    from harness import CACHE

    paper_dir = Path(paper_dir)
    tectonic = find_tectonic()
    if tectonic is None:
        log = "tectonic executable not found (checked harness.BIN and PATH)"
        (paper_dir / "build.log").write_text(log, encoding="utf-8")
        return BuildResult(ok=False, pdf=None, log=log, engine="", seconds=0.0)

    cache_dir = CACHE / "tectonic"
    cache_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["TECTONIC_CACHE_DIR"] = str(cache_dir)
    env.setdefault("PYTHONUTF8", "1")

    cmd = [str(tectonic), "--keep-logs", "--keep-intermediates", "-o", str(paper_dir), main]

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(paper_dir),
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        returncode_ok = proc.returncode == 0
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        combined = f"tectonic timed out after {timeout}s\n{stdout}\n{stderr}"
        returncode_ok = False
    seconds = time.monotonic() - start

    (paper_dir / "build.log").write_text(combined, encoding="utf-8")

    pdf_path = paper_dir / Path(main).with_suffix(".pdf").name
    pdf = pdf_path if pdf_path.exists() else None
    ok = returncode_ok and pdf is not None

    return BuildResult(ok=ok, pdf=pdf, log=combined, engine=str(tectonic), seconds=seconds)
