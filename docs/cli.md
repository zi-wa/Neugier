# CLI and layout

`PY = .venv/Scripts/python.exe` (Linux/macOS: `.venv/bin/python`). Every group is `PY -m harness <group> …`; the console
script `neugier` is an alias.

| Group | Commands |
|---|---|
| `campaign` | `create · activate · phase [--gate] · check · status · budget --set · lock-statement · freeze · targets · suggest-stakes · attest · ack-human · outcome · finish` |
| `ledger` | `add · evidence · promote · update --stakes · reverify · credence · calibration · repair · attest · graph --format mermaid · assertable · md · check` |
| `review` | `open · lineup build\|unseal\|status\|verify · score-lineup · commit-blind · waive · regime · check · close · status` |
| `proof` / `prove` | `proof check · proof coverage` · `prove elo · prove collect` |
| curiosity | `questions list\|next\|surprise\|detour\|answer\|park\|budget\|for-human\|human-answers` · `ideas list\|dedup\|graph` |
| `lit` | `search · get · fetch · cache-path · verify-excerpt · excerpt · cite-walk · resolve · checkbib` |
| computation | `falsify run [--regression] · evolve init\|next\|score\|status\|checkpoint\|resume\|mine\|meta-request` |
| `paper` | `repro · build · check [--strict] · audit sample\|check · init · all` |
| `library` | `add-fact · find-lemma · lessons · moves-stats · list {rejected,results,facts,questions,calibration,lemmas,lessons,moves}` |
| ops | `doctor [--offline] · headless · evals list\|run` |

## Repository layout

```
agents/            13 agent prompts — scout, librarian, fetcher, strategist, experimentalist, prover,
                   skeptic, falsifier, novelty-checker, replicator, judge, writer, copyeditor
skills/            /research /scout /survey /plan-research /explore /prove /review /paper /status
skills/references/ proof standards, referee checklist, technique pitfalls, creative moves, curiosity,
                   novelty protocol, goldmine rubric, LaTeX style
hooks/             enforce_venv · barrier · guard_frozen · gate_stop · gate_subagent · inject_context
harness/           Python runtime (~16k lines): ledger, lit, verify, search, proof, prove, review,
                   paper, library, text, questions, ideas, campaign, doctor, headless, evals
.claude/workflows/ neugier-review.js · neugier-prove.js  (opt-in deterministic orchestration)
evals/             plugin-eval cases and the in-house runner
tests/             40 test modules; tests/fixtures/planted/ is a campaign with known flaws
docs/research/     design plan, harness survey, borrowed mechanisms
```

`campaigns/`, `library/`, `bin/`, `.cache/` and `.venv/` are created locally and never committed.

## A campaign directory

```
campaigns/<slug>/
  campaign.json      phase, budgets, frozen files, rubric hashes, outcome class
  statement.md       the interpretation lock (frozen; hash checked)
  HUMAN.md           the human's policy and answers (agents read, never write)
  survey.md refs.bib plan.md ideas.md questions.md log.md
  experiments/       scripts, results.json, falsify/, evolve/, repair/
  proofs/            <ID>.md, <ID>.rubric.md, <ID>.sketch.<persona>.md
  reviews/roundN/    barrier.json, access.log, lineup/, skeptic.*.md, judge.md, coverage-*.json
  paper/             main.tex, appendices, main.pdf, check.json, audit.json
  ledger.json        the source of truth
```

## Running it unattended

```powershell
.venv\Scripts\python.exe -m harness headless --slug <slug> --max-iterations 20 --max-turns 200
```

Stops on `done`, on `blocked.md`, or after three iterations without progress; writes `campaigns/<slug>/headless.log`.
`scripts/run_campaign.ps1` is a thin wrapper.
