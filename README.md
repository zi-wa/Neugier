# Neugier — 자율 수학 *연구* 하네스 / Autonomous Mathematical Research Harness

Neugier는 Claude Code 위에서 동작하는 **논문급 수학 연구 하네스**입니다. 문제 풀이기가 아니라 연구 캠페인을 수행합니다:
노다지 주제 발굴 → 인용문 기반 문헌 조사 → 해석 고정(interpretation lock) 계획 → 반증 우선 탐색(정확한 검증기를 갖춘 진화 탐색 포함)
→ 증명 → **정보 차단 아래의 적대적 심사** → 원장(ledger)이 허용하는 주장만 담은 LaTeX 논문.

Neugier is a Claude Code plugin/harness for *paper-grade* mathematical research. It runs research campaigns, not problem
solving: goldmine topic scouting → excerpt-anchored survey → interpretation-locked plan → falsification-first exploration
(evolutionary search with exact verifiers) → proofs → **adversarial review behind an information barrier** → a LaTeX paper that
may only assert what the claim ledger allows.

## Quick start (Windows; Linux/macOS analogous)

```powershell
git clone <this repo> Neugier; cd Neugier
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1   # .venv (uv), deps, bin\tectonic.exe, .claude junctions — nothing global
claude                                                            # or: claude --plugin-dir .
```
Then in Claude Code:

| Command | What it does |
|---|---|
| `/research auto` | full campaign; the scout picks a goldmine target |
| `/research "<topic>"` | full campaign on your topic |
| `/scout`, `/survey`, `/plan-research`, `/explore`, `/prove <id>`, `/review <id\|file>`, `/paper` | single phases |
| `/status` | dashboard |

Requirements: Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/) on PATH (the bootstrap falls back to `python -m venv`), git, internet.
`python` must be callable for the hooks (stdlib only).

## What makes it different

- **Claim ledger as source of truth** (`campaigns/<slug>/ledger.json`): `idea → conjectured → numerically-supported → proof-drafted →
  referee-passed → formalized | refuted | known-in-literature`. Promotions require evidence files (computation, proof, referee
  verdicts with round numbers); the paper linter refuses theorems whose claim is not `referee-passed`.
- **Interpretation lock**: `statement.md` (conventions, edge cases, excluded trivial readings, executable definition tests) is
  audited by the skeptic and content-hashed before any proof effort.
- **Falsification first**: every conjecture and lemma is attacked computationally (`harness falsify`) before proof effort and again in review.
- **Adversarial review with an information barrier**: skeptic (step-level OPEN/VERIFIED/FLAWED state machine with witnesses),
  falsifier, novelty-checker (multi-engine search + citation walks, memo with class 1a/1b/1c/1d), replicator (blind re-derivation);
  a judge applies the escalation ladder PASS / REVISE_PROOF / REVISE_PLAN / REWRITE / PIVOT under a review budget.
- **Anti-hallucination layer**: no literature claim without a fetched verbatim excerpt; citation content check; no arithmetic in prose
  (numbers come from `experiments/results.json` and are cross-checked by the linter); hedge-word lint; independent re-extraction.
- **Creativity enforced**: ≥ 5 routes through different lenses + 1 unconventional, each with a cheap falsification test
  (`skills/references/creative-moves.md`); parallel persona provers + tournament.
- **Curiosity over compliance** (rule R6): agents start from their own questions (`questions.md`, ledger kind `question`), predict
  before they experiment and log surprises, choose actions by information gain, and may spend a 30% detour budget chasing a
  surprise without asking; protocols are guardrails, not scripts (`skills/references/curiosity.md`).
- **Process enforced by hooks**: global installs blocked (R2), standing instructions re-injected after context compaction, and a
  Stop hook that refuses to end a phase whose exit criteria are unmet.
- **Reproducibility appendix** generated from the ledger; **cross-run memory** (`library/`) of rejected topics, results and facts.
- **Windows-first hygiene**: everything in the project (`.venv`, `bin/tectonic.exe`, `.cache/`), UTF-8 everywhere.

## Layout

```
agents/      13 subagents (scout, librarian, fetcher, strategist, experimentalist, prover, skeptic, falsifier,
             novelty-checker, replicator, judge, writer, copyeditor)
skills/      /research /scout /survey /plan-research /explore /prove /adversarial-review /paper /status
             references/ proof-standards · referee-checklist · goldmine-rubric · creative-moves · novelty-protocol · latex-style
hooks/       enforce_venv.py · inject_context.py · gate_stop.py · hooks.json
harness/     python -m harness {lit|ledger|falsify|evolve|paper|library|campaign}
campaigns/   one directory per campaign (statement.md, survey.md, plan.md, ideas.md, experiments/, proofs/, reviews/, paper/, ledger.json, log.md)
library/     rejected.jsonl · results.jsonl · facts.jsonl (cross-campaign memory)
docs/research/ design plan and survey of prior harnesses
```

## CLI cheatsheet (`PY = .venv\Scripts\python.exe`)

```
PY -m harness lit search --engine arxiv|openalex|zbmath|oeis|mo "<query>"     PY -m harness lit fetch 2607.29042 --out DIR
PY -m harness lit resolve "<title|arXiv id|DOI>"                             PY -m harness lit checkbib refs.bib
PY -m harness campaign create SLUG --title T | status | check | lock-statement | activate
PY -m harness ledger --campaign SLUG add|evidence|promote|show|md|assertable|check|graph
PY -m harness falsify run conjecture.py --strategy all --time-limit 60        PY -m harness falsify template out.py
PY -m harness evolve template DIR | init | next | score | status | run        (agent-driven evolutionary search)
PY -m harness paper init|repro|build|check --campaign SLUG                    PY -m harness library search facts "<q>"
```

## Development

```
PY -m pytest -q -m "not live"      # offline tests (~250)
PY -m pytest -q -m live            # hits arXiv/OpenAlex/zbMATH/OEIS
```

## Distribution

The repository root is a Claude Code plugin (`.claude-plugin/plugin.json`, `agents/`, `skills/`, `hooks/hooks.json`).
Publish it on GitHub, point `marketplace.json` at the repo, then users run `/plugin marketplace add <owner>/<repo>` and
`/plugin install neugier`, followed by `scripts/bootstrap.*` inside their clone for the Python/LaTeX runtime.

## Honesty contract

Every campaign ends with an outcome class — `autonomous-new-result | partial | rediscovery | literature-find | negative` — set
strictly from the ledger. "Unverified" is always an acceptable answer; a plausible-sounding fact never is.
