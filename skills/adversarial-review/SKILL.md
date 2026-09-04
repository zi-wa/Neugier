---
name: adversarial-review
description: Adversarial verification of a proof or result behind an ENFORCED information barrier — k fresh-context skeptics reviewing a decoy lineup (the referee is refereed), falsifier (computational counterexample search), novelty-checker (multi-engine search + citation walks + final-statement re-check) and replicator (blind re-derivation committed before it sees the proof) run in parallel seeing only statement.md, the marking scheme and the artifact; every file access is logged by a hook; a judge adjudicates with a structured verdict block and the escalation ladder (PASS / REVISE_PROOF / REVISE_PLAN / REWRITE / PIVOT). Works inside a campaign (/review <claim-id>) or standalone on any proof file (/review path/to/proof.md).
argument-hint: "<claim-id | path/to/proof.md> [--rounds n] [--no-novelty] [--workflow]"
effort: max
---

# /review — Phase 6 (also standalone)

`PY` = `.venv/Scripts/python.exe`. Target: `$ARGUMENTS`.

## Setup
- Inside a campaign: set phase `review`; open the gate; artifact = `proofs/<ID>.md`; round N = 1 + max existing round.
- Standalone (a file path outside a campaign): `PY -m harness campaign create review-<name> --title "standalone review"`,
  copy the file to `proofs/X-001.md`, write a minimal `statement.md` from the artifact's header (no conventions invented — if
  the statement is ambiguous, say so in the report), add claim `X-001` to the ledger with the proof as evidence.
- Budget and regime: `PY -m harness review regime --campaign <slug> --claim <ID>` prints the tier (from the claim's `stakes`):
  how many skeptic passes, whether a decoy lineup is built, whether the replicator is required, citation hops, whether the
  final-statement re-check and a human attestation are needed. `budgets.max_review_rounds` (default 3), or `--rounds`.

## Information barrier (enforced)
`PY -m harness review open --campaign <slug> --claim <ID> --artifact proofs/<ID>.md` writes `reviews/roundN/barrier.json`
(per-role allowlists, replicator stages, the decoy lineup when the regime asks for one) and prints the skeptic agent ids and
deliverable paths. From then on `hooks/barrier.py` checks every Read/Glob/Grep/Bash/Write of every referee subagent against
the manifest and logs it to `reviews/roundN/access.log`; an unwaived denial fails the round (`review check`).
Referee prompts contain **only**: slug, round, their agent id, the paths they may read (`statement.md`, the artifact or the
lineup directory, `proofs/<ID>.rubric.md`), the ledger fact ids they may consult for excerpts, the reference doc paths
(`skills/references/referee-checklist.md`, `technique-pitfalls.md`; + `novelty-protocol.md` for the novelty-checker), the
output path, and the time budget. Nothing about routes, motivation, confidence, earlier rounds' discussion, or what you think
of the proof. Each referee is a fresh `Agent` call.

## Round N
1. `PY -m harness review open …` (add `--seed <int>` for a reproducible lineup, `--no-lineup` to skip decoys at tier 0).
2. Spawn **in parallel**:
   - `skeptic` × k (k = regime `skeptic_passes`), each with its own `agent_id` from the manifest → `reviews/roundN/skeptic.<agent_id>.md`.
     In lineup mode each skeptic reviews every item under `reviews/roundN/lineup/` and emits one verdict block per item
     (`item:` letter); it never sees `proofs/`.
   - `falsifier` → `reviews/roundN/falsifier.md` (attacks the real artifact and every lemma; recomputes numbers).
   - `novelty-checker` → `reviews/roundN/novelty.md` (skip with `--no-novelty` only if a previous round already produced a memo for
     the *same* statement; never at tier 2 — the final-statement re-check is mandatory there).
   - `replicator` (two-stage) → `reviews/roundN/replicator.md`: stage A blind values → `harness review commit-blind` → stage B diff.
3. When the skeptic reports exist: `PY -m harness review score-lineup --campaign <slug> --round N`. An **inadmissible** skeptic
   (reliability below `budgets.lineup_min_recall`) is recorded with `ledger evidence … --inadmissible` and a fresh skeptic is
   spawned (at most `budgets.max_skeptic_respawns`). Then `PY -m harness review lineup unseal --round N` reveals the real item for the judge.
4. Spawn `judge` with all reports, the artifact, `statement.md`, `campaign.json`, the lineup scores and (round ≥ 2)
   `reviews/roundN/response.md`. It writes `reviews/roundN/judge.md` with the structured block (`upheld / rebutted / moot`)
   and the final `VERDICT: …` line, records referee evidence for each role (`--round N`; skeptics with `--agent-id` and
   `--reliability`), and promotes to `referee-passed` on PASS (the ledger re-checks the regime and the round).
5. `PY -m harness review check --campaign <slug> --round N` and `PY -m harness review close --round N`.
   `PY -m harness proof coverage <ID> --campaign <slug> --round N` records the verification coverage for the paper.
6. Act on the verdict:
   - `PASS` → done (claim `referee-passed`). Mirror new facts into the library.
   - `REVISE_PROOF` / `REWRITE` and N < max → spawn `prover` with the referee reports; it writes `reviews/round(N+1)/response.md`
     and an updated artifact (version bumped, `harness proof check` passing, evidence hash updated, a new `--p-pass` credence) → run round N+1.
   - `REVISE_PLAN` → return to `/plan-research` (re-plan routes) then `/explore`/`/prove`.
   - `PIVOT`, or N = max without PASS → the claim stays at its current status (downgrade if the judge says so); record the reason
     in `log.md` and the library; continue with the campaign's backup target or proceed to `/paper` with the honest outcome class.
7. `PY -m harness campaign check <slug>` must pass (manifest, access log, judge block, round cap, novelty class; either a
   referee-passed claim or `VERDICT: PIVOT`).

## `--workflow`
If `$ARGUMENTS` contains `--workflow` and the `Workflow` tool is available: run steps 1 and 3–5 yourself and call the saved
workflow `neugier-review` for step 2 (+ the judge) with `args = {slug, claim, round, artifact, lineupDir?, skeptics: [{agentId, deliverable}], factIds, timeBudget}`.
The manual path above is the default.

## Report (Korean)
Verdict, upheld critical errors (with witnesses), skeptic reliabilities, novelty class and closest prior work, replication
result, coverage line, and what happens next.
