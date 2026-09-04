---
name: status
description: Show the active campaign's dashboard — phase, unmet exit criteria, statement lock, ledger summary and claim table, latest review verdict, and next action. Read-only.
argument-hint: "[slug]"
effort: low
---

# /status

`PY` = `.venv/Scripts/python.exe`. Slug: `$ARGUMENTS` or `PY -m harness campaign active`.

Run and present (in Korean, concise):
1. `PY -m harness campaign status <slug>` — phase, unmet criteria, lock, targets, outcome.
2. `PY -m harness ledger md --campaign <slug>` — claim table; and `... ledger check --campaign <slug>` — evidence-hash integrity.
3. Latest `reviews/round*/judge.md` verdict line, if any; `blocked.md` if present.
4. Next action: the phase's skill (`/scout`, `/survey`, `/plan-research`, `/explore`, `/prove`, `/review`, `/paper`) or `/research --resume`.
Do not modify anything.
