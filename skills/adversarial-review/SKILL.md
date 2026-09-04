---
name: adversarial-review
description: Adversarial verification of a proof or result behind an information barrier — skeptic (step-level state machine), falsifier (computational counterexample search), novelty-checker (multi-engine literature hunt) and replicator (blinded re-derivation) run in parallel in fresh contexts seeing only statement.md and the artifact; a judge adjudicates with the escalation ladder (PASS / REVISE_PROOF / REVISE_PLAN / REWRITE / PIVOT) and records ledger evidence. Works inside a campaign (/review <claim-id>) or standalone on any proof file (/review path/to/proof.md).
argument-hint: "<claim-id | path/to/proof.md> [--rounds n] [--no-novelty]"
effort: max
---

# /review — Phase 6 (also standalone)

`PY` = `.venv/Scripts/python.exe`. Target: `$ARGUMENTS`.

## Setup
- Inside a campaign: set phase `review`; open the gate; artifact = `proofs/<ID>.md`; round N = 1 + max existing round.
- Standalone (a file path outside a campaign): `PY -m harness campaign create review-<name> --title "standalone review"`,
  copy the file to `proofs/X-001.md`, write a minimal `statement.md` from the artifact's header (no conventions invented — if
  the statement is ambiguous, say so in the report), add claim `X-001` to the ledger with the proof as evidence.
- Budget: `budgets.max_review_rounds` (default 3), or `--rounds`.

## Information barrier (non-negotiable)
Referee prompts contain **only**: slug, round, the paths `campaigns/<slug>/statement.md` and the artifact path(s), the
ledger fact ids they may consult for excerpts, the reference doc path `skills/references/referee-checklist.md`
(+ `novelty-protocol.md` for the novelty-checker), the output path, and the time budget. Nothing about routes, motivation,
confidence, earlier rounds' discussion, or what you think of the proof. Each referee is a fresh `Agent` call.

## Round N
1. Spawn **in parallel**: `skeptic` → `reviews/roundN/skeptic.md`; `falsifier` → `reviews/roundN/falsifier.md`;
   `novelty-checker` → `reviews/roundN/novelty.md` (skip with `--no-novelty` only if a previous round already produced a memo for
   the *same* statement); `replicator` (two-stage, blind first) → `reviews/roundN/replicator.md`.
2. When all four reports exist, spawn `judge` with all reports, the artifact, `statement.md`, `campaign.json` and (round ≥ 2)
   `reviews/roundN/response.md`. It writes `reviews/roundN/judge.md` ending in `VERDICT: …`, records referee evidence for each
   role in the ledger with `--round N`, and promotes to `referee-passed` on PASS.
3. Act on the verdict:
   - `PASS` → done (claim `referee-passed`). Mirror new facts into the library.
   - `REVISE_PROOF` / `REWRITE` and N < max → spawn `prover` with the referee reports; it writes `reviews/round(N+1)/response.md`
     and an updated artifact (version bumped, evidence hash updated) → run round N+1.
   - `REVISE_PLAN` → return to `/plan-research` (re-plan routes) then `/explore`/`/prove`.
   - `PIVOT`, or N = max without PASS → the claim stays at its current status (downgrade if the judge says so); record the reason
     in `log.md` and the library; continue with the campaign's backup target or proceed to `/paper` with the honest outcome class.
4. `PY -m harness campaign check <slug>` must pass (round files complete and either a referee-passed claim or `VERDICT: PIVOT`).

## Report (Korean)
Verdict, upheld critical errors (with witnesses), novelty class and closest prior work, replication result, and what happens next.
