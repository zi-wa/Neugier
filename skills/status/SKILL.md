---
name: status
description: Show the active campaign's dashboard — phase, unmet exit criteria and advisories, budgets, frozen files, questions and detour budget, human escalations, calibration, ledger summary and claim table with blueprint statuses, latest review round (regime, lineup scores, verdict), and next action. Read-only.
argument-hint: "[slug]"
effort: low
---

# /status

`PY` = `.venv/Scripts/python.exe`. Slug: `$ARGUMENTS` or `PY -m harness campaign active`.

Run and present (in Korean, concise):
1. `PY -m harness campaign status <slug>` — phase, unmet criteria, budgets, frozen files, questions, human, calibration, ledger summary.
2. `PY -m harness ledger md --campaign <slug>` — claim table (stakes, credences); `PY -m harness ledger graph --campaign <slug>` — blueprint
   statuses; `... ledger check --campaign <slug>` — evidence-hash integrity.
3. `PY -m harness review status --campaign <slug>` — latest round: regime, roles, access-log counts, replicator stage, lineup scores,
   judge verdict, problems; `blocked.md` if present.
4. `PY -m harness questions next --campaign <slug>` — the top open questions by information gain; `ASK-HUMAN.md` if escalations are open.
5. Next action: the phase's skill (`/scout`, `/survey`, `/plan-research`, `/explore`, `/prove`, `/review`, `/paper`) or `/research --resume`.
Do not modify anything.
