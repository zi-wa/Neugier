---
name: paper
description: Write, build and QA the campaign paper — amsart from the ledger (only referee-passed claims whose dependency graph is fully proved as theorems; conditional / knownresult environments otherwise), key-step marking, auto-generated reproducibility + provenance + AI-disclosure + questions appendices, tectonic build, strict lint (labels, cites, claim statuses, untracked numbers, hedge words, audit), and a copyeditor pass that cross-checks proofs, citations, a sampled accuracy audit and the outcome class.
argument-hint: "[--title t] [--author a]"
effort: high
---

# /paper — Phase 7

`PY` = `.venv/Scripts/python.exe`. Set phase `write`; open the gate.

1. Confirm what may be asserted: `PY -m harness ledger assertable --campaign <slug>` and
   `PY -m harness ledger graph --campaign <slug> --format mermaid` (only `fully_proved` claims may be plain theorems; `proved` with a
   pending dependency → `conditional`; stakes-2 claims without `campaign attest` → `\unverified{}`). If nothing is assertable, the
   paper is a conjecture/evidence/negative-result paper — say so to the user and proceed with honest framing.
2. `PY -m harness paper repro --campaign <slug>` (appendix-repro.tex with provenance + disclosure, appendix-questions.tex).
3. Spawn `writer` with: slug, title/author (from `$ARGUMENTS` or the campaign title), `skills/references/latex-style.md`, and the
   requirement that it iterate `paper repro → build → check --strict` until `check.json` is ok.
4. Spawn `copyeditor` with: slug and `skills/references/latex-style.md`; it runs `PY -m harness paper audit sample --campaign <slug> --n 30`,
   labels every sampled sentence in `paper/audit.json` (`supported | refuted | unclear` + evidence pointer), and writes `paper/qa.md`.
   If it lists required writer fixes, send them to the writer (one more pass), then re-run the copyeditor. Maximum two cycles;
   otherwise report the residual issues.
5. Verify yourself: `paper/main.pdf` exists and opens (size > 20 KB), `check.json` ok (strict), `paper audit check` has no refuted
   sentence, `refs.bib` passes `lit checkbib`, the abstract's claim matches the outcome class, a `\keystep` exists for every new
   theorem, the provenance table lists every asserted claim.
6. `PY -m harness campaign check <slug>` must pass. Report in Korean: paper path, asserted theorem ids with verification levels,
   outcome class, audited accuracy, remaining warnings.
