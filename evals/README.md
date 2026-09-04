# Neugier evals

Agent-level evaluation cases in the `claude plugin eval` layout (`<case>/case.yaml` + `prompt.md` +
`graders/*.md`). Each case scaffolds the planted-flaw fixture campaign (`tests/fixtures/planted/campaign`)
into `campaigns/eval-<case>/` and asks the agent to perform one harness task; deterministic graders check
the files it produces. With `--ablation with-without` the official runner reports the score delta between
running with and without the plugin — the honest "does the harness help" number for the README.

`claude plugin eval` is in early access (per organization). Until it is enabled, the same cases run through
the in-house driver, which uses your Claude Code login (no API key):

    .venv/Scripts/python.exe -m harness evals run --case "review-*" --runs 1 [--without]
    .venv/Scripts/python.exe -m harness evals run --all --runs 3 --max-turns 40

Results: `evals/results/<timestamp>/aggregate.json` (per case, per arm, per run, grader scores) — the README
may quote numbers only from such files.

Cases:
- `review-planted-circular` — the skeptic must fail the planted proof and name the circular/false steps.
- `falsify-finds-counterexample` — the falsifier must find the counterexample to the planted false lemma.
- `paper-check-rejects-unbound-theorem` — the writer must run the paper linter and report the unbound theorem.
- `barrier-denies-plan-read` — a referee subagent behind the barrier must be denied `plan.md` (access.log).
