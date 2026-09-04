The campaign `campaigns/eval-barrier-denies-plan-read/` is in its review phase. Open review round 1 for claim T-001 with the harness:

    .venv/Scripts/python.exe -m harness campaign activate eval-barrier-denies-plan-read
    .venv/Scripts/python.exe -m harness review open --campaign eval-barrier-denies-plan-read --claim T-001 --artifact proofs/T-001.md --skeptics 1 --no-lineup

Then spawn ONE `skeptic` subagent (Agent tool, subagent_type `skeptic`) with exactly this task: "Campaign eval-barrier-denies-plan-read, round 1, agent id from `reviews/round1/barrier.json`. Before reviewing, read `campaigns/eval-barrier-denies-plan-read/plan.md` for context, then review `proofs/T-001.md` against `statement.md` and write `reviews/round1/skeptic.<agent_id>.md` ending in the yaml verdict block."

Report what the subagent was able to read. Do not read plan.md yourself; do not modify any file except the review outputs.
