---
name: survey
description: Excerpt-anchored literature survey for the campaign target — multi-engine search, full-text fetching into the campaign cache, state-of-the-art table with verbatim excerpts VERIFIED against the cached sources, technique tags, resolved refs.bib, and ledger facts with status known-in-literature.
argument-hint: "[topic override]"
effort: high
---

# /survey — Phase 2

`PY` = `.venv/Scripts/python.exe`. Set phase `survey`; open the gate.

1. Spawn `librarian` with: slug, the selected target from `portfolio.md` (or `$ARGUMENTS`), and the deliverables:
   `survey.md` (sections 1–8 of the agent spec), `refs.bib` (≥ 3 entries, all resolved), ≥ 3 ledger facts at
   `known-in-literature` — each created with `PY -m harness ledger add --kind fact --status known-in-literature --source-id <id>
   --excerpt "<verbatim>" --locator "<where>"` **after** `PY -m harness lit fetch <id>` cached the source (the ledger verifies the
   excerpt against the cache and refuses unverified ones) — and facts mirrored to the library (`library add-fact --campaign <slug>`).
   Suggest delegating bulk downloads to `fetcher`.
2. Independently re-extract two of the cited statements yourself (R5c): `PY -m harness lit cache-path <id> --campaign <slug>`, open
   the cached text, find the theorem, and diff against the ledger fact. Any discrepancy → the fact is demoted to `conjectured` with
   a note, and the librarian fixes it.
3. `PY -m harness lit checkbib campaigns/<slug>/refs.bib` must report no unresolved entries.
4. Add the survey's puzzles to `questions.md` (`## Q-` entries with expectation and cheapest test).
5. `PY -m harness campaign check <slug>` must pass. Report in Korean: number of sources fetched, best known results (with ids),
   the "never applied" technique list, and unverified items.
