# What is actually enforced

Saying exactly what is enforced is the point of the project. Nothing in the left column is aspirational; nothing in the
right column pretends to be more than a prompt.

| Enforced by code or hooks | Prompt-level only | Non-goals |
|---|---|---|
| venv-only Python, no global installs | model routing | referees from different model families |
| phase gates + Stop hook (owned by the session that opened the phase); subagent deliverable gate | how well the detour budget is spent | Lean 4 formalization (deferred; schema only) |
| referee barrier + access log (a tripwire, not a sandbox) | judge reasoning quality | network sandboxing of experiments |
| replicator blind commit before artifact access | novelty search breadth | official `claude plugin eval` (early access) |
| round cap; stakes-derived regime; k-of-k admissible skeptics | marking-scheme quality | |
| lineup reliability gate; sealed lineup + commitment hash | credence honesty (visible via panel spread and Brier) | |
| judge block consistency; quoted rebuttals | | |
| final-statement re-check + artifact hash at stakes 2 | | |
| verified excerpts; proof linter; frozen scorers, statement, rubrics, `HUMAN.md` | | |
| computed `fully_proved`; conditional/knownresult/`\unverified` rules; sampled-audit errors | | |
| repair children need truth **and** significance evidence | | |
| human-only attestation; escalation budget | | |
| budgets, overrun notes, validated outcome class, lessons required to finish | | |

## Measurements

Recall, Brier scores, coverage percentages and eval deltas may be quoted only from files the harness generated
(`reviews/roundN/lineup_score.*.json`, `calibration.json`, `reviews/roundN/coverage-*.json`, `evals/results/**`).
No full campaign has been run end to end yet, so the project publishes no performance numbers.

## Known limits

- The barrier is a tripwire, not a sandbox: it denies and logs referee tool calls, but a determined agent with shell
  access can still construct paths it does not name. The round fails when the log shows an unwaived denial.
- With `claude --plugin-dir .` inside this repo, hooks are registered twice (plugin and project). The access log
  deduplicates; the Stop gate counts attempts twice.
- Several Claude Code sessions can share one project directory. A phase gate belongs to the session that opened it
  (`harness campaign phase <slug> <phase> --gate`) and never blocks or clears another session's.
- `formalized` exists in the schema, but no Lean lane ships; never claim formalization.
