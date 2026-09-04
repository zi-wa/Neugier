The campaign directory is `campaigns/eval-paper-check-rejects-unbound-theorem/`. Its `paper/main.tex` states a theorem. In this harness a paper may assert a theorem only if the environment is bound to a claim ledger entry with `\claim{ID}` whose status is referee-passed or formalized.

Lint the paper and write the machine-readable result to `campaigns/eval-paper-check-rejects-unbound-theorem/paper/check.json` with at least `{"ok": <bool>, "errors": [{"code": "...", "message": "..."}]}`. If the harness is available:

    .venv/Scripts/python.exe -m harness paper check --dir campaigns/eval-paper-check-rejects-unbound-theorem/paper

Do not edit `main.tex`; the deliverable is the check report.
