"""Scaffold the planted fixture campaign for an eval case.

Usage (official runner `scaffold_script`, cwd = workspace root):
    python evals/_lib/scaffold.py <case> [--workspace DIR]

Copies tests/fixtures/planted/campaign -> <workspace>/campaigns/eval-<case>/ (regenerating the fixture
from make.py when the copy is missing), writes campaigns/ACTIVE, and for the paper case adds a main.tex
with an unbound theorem.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "planted"

UNBOUND_TEX = r"""\documentclass{amsart}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\newcommand{\claim}[1]{}
\newcommand{\keystep}[1]{#1}
\begin{document}
\section{Main results}
\begin{theorem}
For every finite set $S$ of integers with $|S| \ge 2$, $|S+S| \ge 2|S| - 1$.
\end{theorem}
\begin{proof}
Order the elements and count the two monotone families of sums. \keystep{monotone families}
\end{proof}
\end{document}
"""


def scaffold(case: str, workspace: Path | None = None) -> Path:
    workspace = Path(workspace or Path.cwd())
    src = FIXTURE / "campaign"
    if not src.exists():
        sys.path.insert(0, str(FIXTURE))
        from make import build  # type: ignore

        build(src)
    dest = workspace / "campaigns" / f"eval-{case}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    (workspace / "campaigns").mkdir(parents=True, exist_ok=True)
    (workspace / "campaigns" / "ACTIVE").write_text(f"eval-{case}", encoding="utf-8")
    if case.startswith("paper-check"):
        (dest / "paper").mkdir(exist_ok=True)
        (dest / "paper" / "main.tex").write_text(UNBOUND_TEX, encoding="utf-8")
        (dest / "paper" / "refs.bib").write_text("", encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("case")
    p.add_argument("--workspace", default=None)
    a = p.parse_args(argv)
    out = scaffold(a.case, Path(a.workspace) if a.workspace else None)
    print(f"scaffolded {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
