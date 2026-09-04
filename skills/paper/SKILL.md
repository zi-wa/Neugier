---
name: paper
description: Write, build and QA the campaign paper — amsart from the ledger (only referee-passed/formalized claims as theorems), key-step marking, auto-generated reproducibility appendix, tectonic build, strict lint (labels, cites, claim statuses, untracked numbers, hedge words), and a copyeditor pass that cross-checks proofs, citations and the outcome class.
argument-hint: "[--title t] [--author a]"
effort: high
---

# /paper — Phase 7

`PY` = `.venv/Scripts/python.exe`. Set phase `write`; open the gate.

1. Confirm what may be asserted: `PY -m harness ledger assertable --campaign <slug>`. If empty, the paper is a
   conjecture/evidence/negative-result paper — say so to the user and proceed with honest framing (outcome class from `campaign.json`).
2. Spawn `writer` with: slug, title/author (from `$ARGUMENTS` or the campaign title), `skills/references/latex-style.md`, and the
   requirement that it iterate `paper repro → build → check --strict` until `check.json` is ok.
3. Spawn `copyeditor` with: slug and `skills/references/latex-style.md`; it writes `paper/qa.md`. If it lists required writer fixes,
   send them to the writer (one more pass), then re-run the copyeditor. Maximum two cycles; otherwise report the residual issues.
4. Verify yourself: `paper/main.pdf` exists and opens (size > 20 KB), `check.json` ok, `refs.bib` passes `lit checkbib`, the
   abstract's claim matches the outcome class, a `\keystep` exists for every new theorem.
5. `PY -m harness campaign check <slug>` must pass. Report in Korean: paper path, asserted theorem ids, outcome class, remaining
   warnings.
