# ClaudeMath — Autonomous Mathematical *Research* Harness (Plan)

## Context

The user wants a Claude Code harness that maximizes capability for **paper-grade mathematical research** (not problem solving). It must: (1) discover rich, under-explored "goldmine" topics; (2) build a research plan; (3) reason rigorously and creatively; (4) run an **adversarial verification** process; (5) produce a TeX paper; (6) reason internally in English; (7) be packaged for later distribution. Prior-work search/reading is required. The user asked me to survey existing harnesses and improve on them, and to work autonomously.

Working directory `C:\Users\admin\Desktop\ClaudeMath` is empty (greenfield, not git). A subagent saved its survey to `C:\Users\admin\.claude\plans\velvet-prancing-barto-agent-aebf9c6bf76b798d4.md`; it will be moved into the project as `docs/research/harness-survey.md` for reference.

### Environment facts verified this session
| Item | Status |
|---|---|
| Python 3.13.13, `uv` 0.11.14, Node 24, git 2.52 | available |
| numpy only; sympy/scipy/mpmath/networkx/z3/pysat/pymupdf missing | install into `.venv` |
| No LaTeX, no Lean, no poppler | ship **tectonic 0.17.0** single binary in `bin/`; `TECTONIC_CACHE_DIR` confirmed (default is `%LOCALAPPDATA%`) |
| Default encoding **cp949** | all scripts `encoding="utf-8"`, `PYTHONUTF8=1` in bootstrap |
| 32 cores, 31 GB RAM, 578 GB free | heavy computational search feasible |
| APIs OK: arXiv (https, e-print TeX source, HTML full text via WebFetch), OpenAlex, zbMATH Open, OEIS JSON, MathOverflow (SE API), erdosproblems.com | Semantic Scholar 429s without key → optional with backoff |
| Built-in PDF `Read` fails | prefer arXiv TeX source / HTML; fallback `pymupdf` in venv |
| Claude Code 2.1.258 formats confirmed | subagent frontmatter (`model`, `effort`, `tools`, `maxTurns`, `memory`, `hooks`), skills (`context: fork`, `effort`, `${CLAUDE_SKILL_DIR}`), hooks (PreToolUse deny JSON; **Stop/SubagentStop can block via exit 2**, cap 8; `SessionStart` matcher `compact` re-injects context), plugin layout (`.claude-plugin/plugin.json`, `agents/`, `skills/`, `hooks/hooks.json`, `bin/` on PATH), headless `claude -p --agents --max-turns --output-format stream-json --resume` |

## Standing user rules

**R1. No waste, but use better models freely** (user: "더 좋은 모델 써도 돼"). Default for every research agent is the top model (`inherit`) at high+ effort; `sonnet` only for mechanical plumbing where reasoning quality cannot matter:

| Task class | Model | Effort |
|---|---|---|
| Mechanical plumbing: file fetching, bib formatting, batch mutation proposals in evolutionary search, trivial edits | `sonnet` | low–medium |
| Everything research-relevant: scouting, literature extraction (fidelity matters), planning, experiments, proofs, all referees, judge, writing, copyediting | `inherit` (top model) | high–max |

Building the harness: I (top model) write all prompts, rubrics, schemas, hooks and math-relevant code; `sonnet` subagents only for API-client boilerplate and tests, which I review.

**R2. Installs, bulky data, risky files stay inside the project** (not a hard "never touch outside" rule). `.venv` via `uv`; `bin/tectonic.exe` + `TECTONIC_CACHE_DIR=.cache/tectonic`; downloads in `.cache/` and `campaigns/*/cache/` (git-ignored); optional Lean later under project-local `ELAN_HOME`; hooks only in project `.claude/settings.json`; no PATH/registry/`setx`/global package-manager changes. The `enforce_venv` hook denies only global installs (bare `pip install`, `npm -g`, `winget/choco/scoop`, default `elan`/`cargo install`) and permanent system changes.

**R3. Creative thinking, enforced structurally:** divergent-before-convergent (≥5 distinct lenses + ≥1 unconventional route before committing), a reformulation-move catalog agents must cite, technique-transfer mining from the survey, parallel persona provers + tournament, and every idea immediately sanity-checked by the falsifier (ideas ledgered as `idea → tested → promising/dead`).

**R5. Hallucination-reduction layer** (user: "할루시네이션 줄이는 방법도 만들어") — separate from, and upstream of, adversarial review:
- **No literature claim without a fetched excerpt.** `librarian` may record a known result only as `{claim, source_id, verbatim_excerpt, locator}` where the excerpt comes from fetched TeX/HTML/PDF text; `harness ledger add` validates the schema and stores the excerpt hash. "It is well known that…" without a source is rejected by the ledger and flagged by copyeditor lint.
- **Citation content check.** The resolver verifies not only that the paper exists (title/author/year via arXiv/OpenAlex/zbMATH) but that the cited paper actually contains the attributed statement (excerpt match); mismatches are logged (Aletheia's Galambos-1976 failure).
- **No arithmetic in prose.** Every number, bound, constant and formula evaluation is produced by code in `.venv` and recorded in `experiments/results.json`; `check.py` cross-checks every number in the paper against that file; formulas are numerically spot-checked with sympy/mpmath at random points before entering the ledger.
- **Independent re-derivation of key facts.** Statements of cited theorems, constants and definitions used in a proof are re-extracted by a second fresh agent from the source and diffed; disagreement → `unverified`. `replicator` re-derives key numerics from the statement alone.
- **Calibrated confidence + evidence type on every ledger row** (`evidence: excerpt | computation | proof | referee`); promotion rules depend on evidence, never on stated confidence; "unknown/unverified" is an allowed and encouraged answer.
- **Structured outputs, validated.** Agents emit YAML/JSON for claims, lemmas, citations and review verdicts; the CLI rejects malformed or unsupported entries so the model cannot "narrate" a fact into existence.
- **Definition and statement unit tests** (interpretation lock) so the objects being reasoned about are pinned to executable checks.
- **Hedge-word and unsupported-attribution lint** in copyeditor (`well known`, `clearly`, `standard argument`, `by [ref]` with no excerpt) plus a final "every theorem has proof-or-verified-citation" pass.
- **Context hygiene.** Long runs re-inject the ledger/statement after compaction so agents work from the file of record, not from fading memory.
- **Cross-run fact store** (`library/facts.jsonl`) with provenance, so verified facts are reused instead of re-remembered.

**R4.** Research harness, not solver: unit of work is a *campaign* with a target portfolio, budgets, kill criteria and pivots; always ends with an honest publishable artifact. Internal reasoning in English; replies to the user in Korean; paper in English.

## Evidence base (two research sweeps, sourced)

**Where AI produced genuinely new math (2025–26)** — all with a machine-checkable certificate/exact scorer: Ramsey lower bounds, Zarankiewicz numbers, degree–diameter graphs, kissing numbers/packings, finite-field Kakeya/Nikodym, autocorrelation/Sidon constants, packing/covering, matrix-multiplication tensor ranks, Hadamard/designs, OEIS conjectures, elementary Erdős number theory, unit-distance certificates, superpermutations, Formal Conjectures open set (arXiv 2511.02864, 2603.09172, 2605.01120, 2606.15860, 2506.13242, 2605.22763, 2605.13171). → Scout rubric weights **"exact verifier exists/can be written"** highest.

**Documented failure modes → countermeasures**

| Failure (source) | Countermeasure |
|---|---|
| Specification gaming / wrong reading (Aletheia 2602.10177: 68.5% of self-verified outputs flawed, 6.5% meaningful; ~25% of "correct" solved a misread problem) | **Interpretation lock**: frozen `statement.md` (conventions, edge cases, trivializing readings excluded, definition unit tests), skeptic-approved, content-hashed; gate rejects downstream drift |
| Fabricated/misattributed citations (Aletheia, Nexus 2605.22763) | **Citation resolver**: every bib entry resolved via arXiv/OpenAlex/zbMATH with title+author match, else removed |
| Rediscovery / missed literature ("Erdősgate", Tao #1026, Erdős wiki class 1b ≈24 cases) | **Novelty gate** (before proving and before writing): multi-engine search, multiple phrasings + object names, forward/backward citation walk from seed papers, OEIS/erdosproblems/Formal Conjectures lookup, Tao-wiki red flags (short proof, proves more than asked, unused hypotheses); output = written memo + class 1a/1b/1c, not a boolean |
| Circular/hallucinated helper lemmas (Nexus) | Lemma-strength audit; acyclic lemma DAG; each lemma strictly weaker than the theorem |
| Verifier exploitation (float tolerance, solver failures; AlphaEvolve/Tao) | Exact/rational/interval arithmetic; solver outputs are candidates; verifier code hashed in ledger and immutable during Explore |
| Reasoning traces poison judges (Aletheia) | Information barrier: referees are fresh subagents seeing statement+proof only |
| NL verification alone insufficient (31.5%) | Step-level state machine OPEN/VERIFIED/FLAWED with witnesses (2606.10799); critical-error vs justification-gap classes (2507.15855); ≥2 independent referees + numeric falsification + blinded replicator re-deriving key numerics |
| Misformalization if Lean used (Formal Conjectures: 291 cases) | Statement fixed/unit-tested first; sudden trivial Lean success = red flag |
| Statement drift, context decay, repair cascades (LeanMarathon 2606.05400) | Ledger with stable IDs + hashes; editing a lemma re-opens dependents; `SessionStart(compact)` re-injects state |
| Overclaiming; AI prose hides the novel step (Tao) | Paper claims ≤ ledger status; `\keystep` marks the novel lemma and skeptic verifies it in isolation; outcome class (autonomous / partial / rediscovery / literature find / negative) |

**Reused ideas from existing harnesses**: OpenEvolve cascade evaluation + MAP-Elites + artifacts-to-prompt feedback; ShinkaEvolve novelty rejection before spending eval budget + meta-scratchpad; QED claim-DAG plan file + two-tier verifier + `<cite>`/`<key-original-step>` tagging + Regulator escalation ladder (REVISE_PROOF / REVISE_PLAN / REWRITE / PIVOT); co-scientist Elo tournament for ranking topics and sketches; Aletheia generator/verifier separation and outcome taxonomy; The Station's archive-of-papers as cross-run memory; autoresearch narrow write scope; erdosproblems wiki "what to do when AI solved it" checklist.

**Gaps no existing harness fills together (our differentiators)**: claim ledger with verification status; novelty gate before writing; interpretation lock; falsification-first; referee information barrier; kill criteria/pivoting with noise-floor tests; reproducibility appendix as a build artifact; cross-run literature memory; rigor-of-exposition gate; Windows/venv hygiene.

**Decision — evolutionary search**: do **not** depend on OpenEvolve (needs an OpenAI-compatible API key); write a lightweight loop whose mutation step is done by Claude subagents (interactive) or `claude -p` (headless), but keep OpenEvolve's evaluator interface (`evaluate(program_path) -> dict`) so the 67 AlphaEvolve-repository verifiers plug in directly.

## Architecture / file layout

Repo root = plugin root. Local use `claude --plugin-dir .` or plain `claude` (via `.claude/agents`, `.claude/skills` junctions → `../agents`, `../skills`, plus `.claude/settings.json` hooks). Distribution: GitHub + `marketplace.json` → `/plugin marketplace add <owner/repo>` → `/plugin install claudemath`.

```
ClaudeMath/
  CLAUDE.md                      # constitution: R1–R4, ledger discipline, phase protocol, encoding rules
  README.md                      # install/usage (KO+EN)
  .claude-plugin/plugin.json     # name: claudemath
  marketplace.json
  .claude/settings.json          # hooks via ${CLAUDE_PROJECT_DIR}, permissions; agents/ skills/ junctions
  bin/                           # tectonic.exe (git-ignored, bootstrap downloads)
  agents/
    scout.md            inherit/high  mines sources → scored opportunity portfolio (Elo-style pairwise ranking)
    librarian.md        inherit/high  search, fetch TeX/HTML, excerpt-anchored extraction, bib, citation content check
    strategist.md       inherit/xhigh statement fixing, targets, ≥5 routes, budgets, kill/pivot rules
    experimentalist.md  inherit/high  experiments in .venv, evolutionary search driver (sonnet mutators), OEIS
    prover.md           inherit/max   lemma DAG, numbered steps, <cite>/<key-original-step> tags
    skeptic.md          inherit/max   ADVERSARIAL step-level state machine, lemma-strength audit
    falsifier.md        inherit/high  ADVERSARIAL counterexample/SAT/brute-force attacks, trivial-reading check
    novelty-checker.md  inherit/high  ADVERSARIAL multi-engine literature hunt, snowballing, 1a/1b/1c memo
    replicator.md       inherit/high  blinded re-derivation of key numerics/cited statements from sources only
    judge.md            inherit/max   adjudicates rounds, escalation ladder, ledger transitions
    writer.md           inherit/high  amsart author constrained by ledger
    copyeditor.md       inherit/high  compile, refs, citation/number cross-checks, hedge lint, claim≤ledger audit
    fetcher.md          sonnet/low    mechanical: download sources, unpack e-prints, format bib entries
  skills/
    research/    /research [topic|auto]   full campaign orchestrator (phase loop, checkpoints)
    scout/       /scout [area]
    survey/      /survey <topic>
    plan-research/ /plan-research
    explore/     /explore [target]
    prove/       /prove <claim-id>
    adversarial-review/ /review <artifact>   standalone adversarial protocol
    paper/       /paper
    status/      /status
    references/  proof-standards.md referee-checklist.md goldmine-rubric.md creative-moves.md latex-style.md novelty-protocol.md
  hooks/
    hooks.json  enforce_venv.py  inject_context.py  gate_stop.py
  harness/                       # Python package (.venv)
    lit/      arxiv.py openalex.py zbmath.py oeis.py mathoverflow.py erdos.py (git-clone yaml) formal_conjectures.py alphaevolve_repo.py sources.py (tex/html/pdf→text) bib.py (resolver)
    ledger/   schema.py ledger.py  (claims, statuses, hashes, deps, evidence paths, audit log)
    verify/   falsify.py (numeric harness: brute force, SAT/z3, random search) exact.py (Fraction/mpmath interval)
    search/   evolve.py (population DB, MAP-Elites bins, cascade eval, artifacts feedback, checkpoints; OpenEvolve-compatible evaluator API)
    paper/    build.py (tectonic) check.py (labels/cites/claims) repro.py (reproducibility appendix) templates/amsart
    library/  memory.py (cross-campaign rejected-topics + results store: library/*.jsonl)
    cli.py    python -m harness {scout|lit|ledger|falsify|evolve|paper|repro|status}
  scripts/    bootstrap.ps1 / bootstrap.sh, run_headless.ps1 (claude -p phase driver)
  campaigns/<slug>/  campaign.json statement.md survey.md refs.bib plan.md ideas.md experiments/ proofs/ reviews/ paper/ ledger.json log.md cache/
  library/    rejected.jsonl results.jsonl   (cross-run memory)
  docs/research/harness-survey.md
  tests/
```

## Phase protocol (`/research`)

0. **Bootstrap** — venv, deps, tectonic, junctions; `campaigns/<slug>/`.
1. **Scout** — mine erdosproblems yaml, Formal Conjectures, AlphaEvolve repo verifiers, Epoch FM:OP, OEIS (`hard/more/unkn`, "Conjecture:"), Open Problem Garden, MathOverflow, recent arXiv techniques; skip `library/rejected.jsonl`; score with goldmine rubric (exact verifier, tractability signal, gap between bounds, novelty/impact, fit-to-compute); pairwise-tournament rank → `portfolio.md`.
2. **Survey** — search → fetch TeX/HTML → definitions, known results, best bounds, techniques (tagged), open questions → `survey.md`, `refs.bib` (resolved), seed ledger with `known` facts.
3. **Plan** — interpretation lock (`statement.md` + unit tests, skeptic-approved, hashed); targets with ≥5 divergent routes (R3); experiments; budgets; kill/pivot rules → `plan.md`.
4. **Explore** — falsification-first on every conjecture; experiments in venv; evolutionary loop for construction/bound targets (sonnet mutators, exact scorer, noise-floor test); OEIS lookups; ledger `numerically-supported` / `refuted`.
5. **Prove** — parallel persona provers → tournament → lemma DAG, numbered steps, tags; artifact = proof text only.
6. **Adversarial review** — skeptic ∥ falsifier ∥ novelty-checker ∥ replicator (fresh contexts, artifact only) → judge (escalation ladder, max rounds) → `referee-passed` or downgrade; optional Lean for key lemmas.
7. **Write** — amsart from ledger; `\keystep`; reproducibility appendix generated by `repro.py`; tectonic build; copyeditor QA.
8. **Finish/pivot** — kill criteria → pivot; end with paper + decision log + outcome class; append to `library/`.

Hooks: `enforce_venv` (PreToolUse Bash deny global installs); `inject_context` (SessionStart startup/resume/compact + UserPromptSubmit: R1–R4 standing instructions + active campaign summary); `gate_stop` (Stop/SubagentStop exit 2 with missing exit criteria while a phase is open; tracks attempts, writes `blocked.md` before the 8-block cap).

## Implementation steps (with model routing)

1. **Foundation** (me + sonnet): save R1–R4 to memory; `CLAUDE.md`, `.gitignore`, `scripts/bootstrap.*` (uv venv, deps: sympy scipy mpmath networkx python-sat z3-solver ortools pymupdf bibtexparser requests pydantic pyyaml pytest; tectonic → `bin/`; junctions; `PYTHONUTF8`); `git init`; move survey doc into `docs/research/`.
2. **Literature layer** (sonnet, I review): `harness/lit/*` clients, source fetcher (e-print tar → main .tex → clean text; HTML; PDF fallback), bib resolver; live smoke tests.
3. **Ledger + paper toolchain** (sonnet, I design schema): `harness/ledger`, `harness/paper/{build,check,repro}`, amsart template.
4. **Agents + skills + reference docs** (me): 12 agent prompts, 9 skills, 6 reference docs (proof standards, referee checklist w/ Erdős-wiki negative examples, goldmine rubric, creative moves, novelty protocol, LaTeX style).
5. **Hooks + plugin manifest** (sonnet, I review): 3 hook scripts, `hooks.json`, `.claude/settings.json`, `plugin.json`, `marketplace.json`.
6. **Search + falsification** (sonnet, I review): `harness/search/evolve.py` (+ adapter for AlphaEvolve-repository verifiers), `harness/verify/{falsify,exact}.py`, `harness/library/memory.py`, `run_headless.ps1`.
7. **End-to-end validation** (see below), README (KO/EN).
8. **First real campaign**: `/research auto` — scout picks a goldmine target; full loop; paper. (Uses top model where R1 says to.)

## Verification

- `pytest tests/`: API clients (recorded fixtures + live smoke), source extraction on a real arXiv e-print, ledger transitions/hash invalidation, tectonic build of the template, `check.py` catching an unresolved cite and an unverified claim.
- Hook tests: bare `pip install x` denied; `.venv\Scripts\python -m pip install x` and `uv pip install --python .venv x` allowed; Stop hook blocks when a phase is open and releases when criteria are met.
- Hallucination-layer tests: ledger rejects a literature claim without an excerpt; citation content check flags a real paper cited for a statement it does not contain; `check.py` flags a number in the paper absent from `results.json` and a "well known" without citation; second-agent re-extraction diff catches a mis-stated theorem.
- Adversarial protocol test: `/review` on a planted-flaw proof (circular lemma + false lemma + unused hypothesis + already-known result) → skeptic flags the circularity, falsifier finds the counterexample, novelty-checker finds the reference.
- Evolutionary loop test: reproduce a known construction from the AlphaEvolve repository (e.g., a small Ramsey/Zarankiewicz instance) with the exact scorer.
- Dry-run `/research` on a tractable topic end-to-end → compiled PDF whose claims match the ledger; then step 8.
