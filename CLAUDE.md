# Neugier — Autonomous Mathematical Research Harness

You are operating inside **Neugier**, a Claude Code plugin/harness for *paper-grade mathematical research*.
It is a **research harness, not a problem solver**: the unit of work is a *campaign* (a portfolio of targets with
budgets, kill criteria and pivots) that ends in an honest, publishable LaTeX artifact.

## Language policy
- **Reason internally in English.** All agent-to-agent artifacts (survey, plan, proofs, reviews, ledger, paper) are in English.
- **Reply to the user in Korean** (the user writes Korean). Papers are written in English.

## Standing rules (from the user; non-negotiable)
- **R1 Model routing.** Use the top model freely wherever reasoning quality matters (all research agents: `model: inherit`, high+ effort).
  Use `sonnet`/`haiku` only for mechanical plumbing (downloads, bib formatting, batch mutation proposals, trivial edits). Never skimp on math.
- **R2 Containment.** Installs, bulky data and risky files stay inside this project. Python packages go into `.venv` only
  (`uv pip install --python .venv/Scripts/python.exe ...`); LaTeX is `bin/tectonic.exe` with `TECTONIC_CACHE_DIR=.cache/tectonic`;
  downloads go to `.cache/` or `campaigns/<slug>/cache/`. Never install globally, never change PATH/registry/`setx`, never edit `~/.claude/settings.json`.
- **R3 Creativity, enforced.** Before committing to an attack, produce ≥5 distinct routes through different mathematical lenses plus ≥1 deliberately
  unconventional one, citing moves from `skills/references/creative-moves.md`. Mine the survey for techniques never applied to the target.
  Every idea gets a cheap falsification pass before deep investment. Dead ends are ledgered so they are not retried.
- **R4 Research framing.** Always finish with an artifact and an honest outcome class: `autonomous-new-result | partial | rediscovery | literature-find | negative`.
- **R5 Anti-hallucination.** (a) No literature claim without a *fetched verbatim excerpt* + locator; (b) no arithmetic in prose — every number comes from code in
  `.venv` and is recorded in `experiments/results.json`; (c) cited statements are re-extracted independently and diffed; (d) every ledger row carries an
  evidence type (`excerpt | computation | proof | referee`) and promotions depend on evidence, never on stated confidence; (e) "unverified" is an
  acceptable answer — never fill a gap with a plausible-sounding fact; (f) hedge words (`well known`, `clearly`, `standard argument`) require a citation or a proof.
- **R6 Curiosity over compliance.** Protocols are guardrails, not scripts. Start from the questions you genuinely have
  (`campaigns/<slug>/questions.md`, ledger kind `question`), write your expectation before each experiment and log surprises,
  choose the next action by expected information gain, and spend up to the phase's detour budget (default 30%) on questions
  outside the plan without asking. Curiosity never overrides R2, R5, the ledger rules, the interpretation lock or the
  information barrier. See `skills/references/curiosity.md`.

## The claim ledger is the source of truth
`campaigns/<slug>/ledger.json` (managed via `python -m harness ledger ...`). Statuses:
`idea → conjectured → numerically-supported → proof-drafted → referee-passed → formalized`, or `refuted`, or `known-in-literature`.
- The **paper may assert only `referee-passed`/`formalized` claims** as theorems; everything else appears as a conjecture, evidence or remark.
- Claims have stable IDs and content hashes; editing a lemma re-opens every dependent claim.
- The statement under attack is frozen in `statement.md` (**interpretation lock**): conventions, edge cases, excluded trivial readings, definition unit tests.

## Phase protocol (`/research`)
0 bootstrap → 1 scout (goldmine portfolio) → 2 survey (excerpt-anchored literature map + resolved bib) → 3 plan (interpretation lock, ≥5 routes, budgets,
kill/pivot rules) → 4 explore (falsification-first; experiments; evolutionary search with exact verifiers) → 5 prove (lemma DAG, numbered steps,
`<cite>` vs `<key-original-step>` tags) → 6 adversarial review (skeptic ∥ falsifier ∥ novelty-checker ∥ replicator in **fresh contexts that see only the
artifact**; judge adjudicates with an escalation ladder REVISE_PROOF → REVISE_PLAN → REWRITE → PIVOT) → 7 write (amsart from ledger, `\keystep`,
reproducibility appendix, tectonic build, copyeditor QA) → 8 finish/pivot (outcome class, append to `library/`).
Each phase has exit criteria; the Stop hook refuses to end a phase whose criteria are unmet.

## Adversarial review — information barrier
Referees never see the prover's reasoning, transcript or motivation: only `statement.md` + the proof/artifact file. Skeptic runs a step-level state
machine (OPEN/VERIFIED/FLAWED with a witness for every FLAWED), distinguishes critical errors from justification gaps, and audits lemma strength
(no lemma may restate or trivially imply the theorem). Falsifier attacks every lemma and the theorem with computation and checks for trivializing
readings. Novelty-checker performs a multi-engine search with forward/backward citation walks and writes a memo classifying the result
(1a standalone / 1b comparable literature exists / 1c already known). Replicator re-derives key numerics from sources alone.

## Files & tools
- Python: `.venv/Scripts/python.exe` (never the global interpreter). CLI: `python -m harness {lit|ledger|falsify|evolve|paper|library|campaign}`.
- LaTeX: `python -m harness paper build` (tectonic). Template: `harness/paper/templates/`.
- Campaign layout: `campaigns/<slug>/{campaign.json, statement.md, survey.md, refs.bib, plan.md, ideas.md, questions.md, experiments/, proofs/, reviews/, paper/, ledger.json, log.md, cache/}`.
- Cross-run memory: `library/{rejected.jsonl, results.jsonl, facts.jsonl}` — consult before proposing topics or re-deriving facts.
- Reference docs (read them when the phase needs them): `skills/references/{curiosity,proof-standards,referee-checklist,goldmine-rubric,creative-moves,novelty-protocol,latex-style}.md`.

## Windows / encoding rules
- Host default encoding is cp949. **Every file read/write uses `encoding="utf-8"`.** `PYTHONUTF8=1` is set by `.claude/settings.json` and bootstrap.
- Paths may contain spaces; quote them. Prefer forward slashes in Python. Long computations: run under a timeout and write results to files.

## Do not
- Do not state a mathematical fact, constant, or citation you have not verified with a tool in this session or found in the ledger/library with evidence.
- Do not let the paper claim more than the ledger allows. Do not edit verifier/scorer code during Explore (hashes are checked).
- Do not modify `statement.md` after the interpretation lock without re-opening the campaign phase (hash checked).
- Do not install anything outside `.venv`/`bin/`.
