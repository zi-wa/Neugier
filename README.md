<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.svg">
  <img alt="Neugier — curiosity, refereed" src="docs/assets/banner-light.svg" width="760">
</picture>

<p align="center">
  <a href="https://github.com/zi-wa/Neugier/actions/workflows/tests.yml"><img src="https://github.com/zi-wa/Neugier/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <img src="https://img.shields.io/badge/Claude%20Code-plugin-D97757?logo=claude&logoColor=white" alt="Claude Code plugin">
  <img src="https://img.shields.io/badge/API%20key-not%20required-16A34A" alt="No API key required">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-3DA639?logo=opensourceinitiative&logoColor=white" alt="MIT license"></a>
</p>

</div>

**Neugier** runs mathematical research campaigns on Claude Code. It is not a problem solver: every statement enters a
**claim ledger** as a conjecture, only evidence promotes it, and the LaTeX paper refuses to typeset a theorem the ledger
has not refereed. Referees work in fresh contexts behind a hook-enforced information barrier — and are themselves scored
on a lineup of decoys with planted flaws before their verdict is allowed to count.

[Quick start](#quick-start) · [How it fits together](#how-it-fits-together) · [Features](docs/features.md) · [What is enforced](docs/enforcement.md) · [CLI](docs/cli.md) · [한국어](README_ko.md)

## Install

**Linux / macOS / WSL**

```bash
curl -fsSL https://raw.githubusercontent.com/zi-wa/Neugier/main/install.sh | sh
```

**Windows**

```powershell
irm https://raw.githubusercontent.com/zi-wa/Neugier/main/install.ps1 | iex
```

The installer clones the repository into `~/Neugier` (override with `NEUGIER_DIR`) and runs its bootstrap. Everything
it creates stays inside that directory: `.venv`, `bin/tectonic`, `.cache`. Nothing is installed globally, no PATH or
profile is touched, nothing runs elevated. By hand instead: `git clone`, then `scripts/bootstrap.sh` (or `.ps1`).

## Quick start

```powershell
cd ~/Neugier
claude --plugin-dir .
```

```text
/research auto            # the scout picks a target and runs the whole campaign
/research "sum-free subsets of finite abelian groups"
/status                   # phase, unmet criteria, budgets, questions, calibration
```

Or install it as a plugin: `/plugin marketplace add zi-wa/Neugier` then `/plugin install neugier@neugier-marketplace`.
Unattended: `python -m harness headless --slug <slug> --max-iterations 20`.

## How it fits together

- **Claim ledger** — `idea → conjectured → numerically-supported → proof-drafted → referee-passed`; nothing skips a step, and `fully_proved` is computed from the dependency graph rather than declared.
- **Information barrier** — referees see `statement.md` and the artifact, nothing else; a PreToolUse hook checks and logs every access.
- **Refereed referees** — skeptics judge a lineup of the real proof, mutants with planted flaws and a control; low recall means no vote.
- **Falsification first** — counterexample search on the theorem and every lemma before proof effort; refuted conjectures enter a repair loop.
- **Literature with receipts** — an excerpt counts only if it is found verbatim in a source fetched into the campaign cache.
- **Curiosity engine** — agents work from a question ledger ranked by information gain, with pre-registered credences scored by Brier afterwards.
- **Honest ending** — a validated outcome class (`autonomous-new-result`, `partial`, `rediscovery`, `literature-find`, `negative`) plus provenance, disclosure and open-question appendices.

Review intensity is not fixed: each claim carries stakes 0/1/2, and the regime (skeptic count, decoys, replicator, citation
hops, final-statement re-search, human sign-off) follows from them.

## Documentation

| If you want to | Read |
|---|---|
| see what the harness does, with real output | [docs/features.md](docs/features.md) |
| know what is enforced by code and what is only a prompt | [docs/enforcement.md](docs/enforcement.md) |
| drive it from the command line | [docs/cli.md](docs/cli.md) |
| know where each mechanism came from | [docs/research/borrowed-mechanisms.md](docs/research/borrowed-mechanisms.md) |
| understand the agent contract | [CLAUDE.md](CLAUDE.md), [skills/references/](skills/references) |

## Development

```powershell
.venv\Scripts\python.exe -m pytest -m "not live"     # 361 offline tests
.venv\Scripts\python.exe -m pytest -m live           # 5 network tests
```

Every file I/O uses `encoding="utf-8"` (the host default is cp949); hooks use the standard library only; the distribution
is `neugier-harness` with console script `neugier`.

## Citation and license

```bibtex
@software{neugier2026,
  title = {Neugier: an adversarially refereed mathematical research harness},
  author = {zi-wa}, year = {2026}, version = {0.2.0},
  url = {https://github.com/zi-wa/Neugier}
}
```

MIT — see [LICENSE](LICENSE). An independent project that runs on Claude Code; not affiliated with or endorsed by Anthropic.
