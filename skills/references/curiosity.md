# Curiosity over compliance (rule R6)

**Principle.** The protocols in this harness are guardrails a referee needs to see; they are not the path. A research agent
acts on *genuine questions* — what is surprising, what does not fit, what it most wants to know — and chooses its next action
by expected information gain, not by the next checklist item. The user's instruction: the model should act on curiosity rather
than on commands. The only things curiosity never overrides are the rigor rules: R5 (evidence), the ledger promotion rules,
the interpretation lock, the referees' information barrier, containment (R2), and hard budget caps.

The question ledger is machine-read (`python -m harness questions …`); keep the formats below exactly.

## 1. The question ledger — `campaigns/<slug>/questions.md`

Every agent that touches the mathematics **starts** by writing the questions it actually has, before doing anything else, and
**ends** by updating them. Questions are also ledger claims of kind `question` (ids `Q-nnn`) so they can be linked from
targets, lemmas and evidence (`python -m harness ledger add --kind question --statement "..."`).

```markdown
## Q-003: Why does the greedy Sidon construction plateau near density 0.29 for N ≤ 2000?
- Curiosity: 3/3   (3 = the answer would change the plan; 1 = mild; "n/5" scales are accepted)
- Stake: 4/5       (optional: how much the campaign's outcome depends on the answer; default 3)
- Expectation: density decays like c/sqrt(N) with c ≈ 1; a plateau would be surprising.
- Credence: 0.3    (optional: your pre-registered probability that the expectation is right — this is what makes information gain computable)
- Cheapest test: run seed.py for N = 100..5000, fit exponent (≤ 15 min).
- Status: open | answered → <evidence path or claim id> | parked → <why> | dropped → <reason>
- Raised by: experimentalist, 2026-09-02, explore
```

Rules: ≥ 3 open questions after Plan; each has an *expectation* (so surprise is measurable) and a *cheapest test* with a
duration; answered questions point to evidence (`harness questions answer Q-003 --ref results.json#key`); dropped questions say why.
Questions can be about anything: the object, a paper's proof, a strange number, a mismatch between two sources, a route that
failed for an unclear reason. Questions raised by the prover must be answered or parked before the prove phase can exit.

## 2. Predictions and the surprise log

Before every experiment, write the prediction. After, compare. Record the pair — matched or not — so the explore phase can
prove it predicted before it measured (the explore gate requires at least one recorded pair):

```markdown
## Prediction (Q-003): greedy density at N = 5000
- Predicted: 0.014
- Observed: 0.29
- Surprise: 3/3
- Follow-up: Q-007
```

Any material deviation is a `## Surprise` block (same fields; `harness questions surprise --question Q-003 --prediction …
--observation … --score 3 --follow-up Q-007`). Surprises are the most valuable output of the Explore phase; the strategist
reads them before re-planning; the prover reads them for lemma candidates. A 3/3 surprise **without a follow-up** makes
`campaign check` print a re-planning advisory. Anomalies to watch for: numbers that deviate from the predicted growth rate,
near-misses of a known bound, unexpected symmetry or structure in elite constructions, integer sequences absent from OEIS,
two sources that disagree, a lemma that is "too easy".

## 3. Choosing the next action (information gain)

`python -m harness questions next --campaign <slug>` ranks open questions by
**expected information gain = uncertainty × stake / max(cost minutes, 5)**, where uncertainty is `4·p·(1−p)` when a
credence `p` is recorded and `curiosity/scale` otherwise: a question whose expectation is maximally uncertain, high-stakes and
cheap to test comes first. It also warns when the role that raised a question has a poor calibration record. At each decision
point compare its top items with the plan's next step, do the highest-gain thing, and write one line in `log.md`:
`decision: <action> — because <one reason>`. The plan's ordering is a default, not an order.

## 4. Detour budget

Each phase carries a curiosity budget: **30 % of the phase's time by default** (`budgets.curiosity_fraction` ×
`budgets.hours_per_phase[phase]`) that any agent may spend on a question outside the plan **without asking**. Log it:

```markdown
## Detour (explore, 40 min): Q-003
- What I did: ...
- What I learned: ...
- Plan impact: none | re-plan requested (reason) | new target proposed (id)
```

(`harness questions detour --phase explore --minutes 40 --question Q-003 --what … --learned …`; `harness questions budget`
shows what is left.) A detour that produces a surprise with curiosity 3/3 may trigger re-planning (`strategist`), even
mid-phase. Detours count against the phase budget; the hard cap still holds.

## 5. Question-driven planning

Targets in `plan.md` are phrased as questions ("Is the extremal configuration always symmetric?"), routes are attempts to
answer them, and kill criteria say which answer would make the question uninteresting. The scout records, separately from the
rubric, which candidates it finds most puzzling (**intrinsic interest**, 0–3): with verifiability V ≥ 2, a genuinely intriguing
target beats a marginally higher-scoring dull one. The scout also reads `harness library list questions` — open questions
left by earlier campaigns are goldmine sources in their own right.

## 6. Curiosity of referees

Referees are curious adversarially: *where does this break? what is the strangest instance? what would I need to see to believe
step k?* Their protocols (`referee-checklist.md`) are unchanged; curiosity there means digging where the proof is weakest, not
where the checklist points.

## 7. What curiosity is not

Not an excuse to skip evidence (a hunch is a question, not a fact), not a reason to edit `statement.md`, not a license to
exceed hard budgets, and not "exploring" by reading the prover's reasoning when you are a referee.

## 8. Credence and calibration (pre-registration)

Before budget is spent on a target, a route, or a proof attempt, the responsible agent writes down what it expects and how
sure it is — and the harness scores it afterwards:

- targets/conjectures/bounds/constructions: `harness ledger credence <ID> --role strategist --p-true 0.35 --p-budget 0.2
  --why "…" [--panel skeptic=0.2,optimist=0.6,base-rate=0.3]` (the plan gate requires `p_true` on every such claim);
- routes: a `- Credence: p_true=0.35 p_budget=0.2 (strategist) — why` line in `ideas.md` (required for every route);
- proof attempts: `--p-pass 0.7 --round N` by the prover before each review round.

Credences are immutable history entries. `harness ledger calibration` computes Brier scores per role and field once claims
resolve; `campaign finish` appends them to `library/calibration.jsonl`, and `questions next` discounts roles whose record is
poor. Precedent: t46/claim-prediction-market (Brier 0.177 on 35 claims; predictions "before an agent executes high-cost
experiments"). Writing 0.5 everywhere is visible: the panel spread and the Brier record show it.

## 9. Asking the human (metered escalation)

The human is the scarcest resource. `campaigns/<slug>/HUMAN.md` is theirs: agents read it at every phase start (`## Policy`)
and never edit it (a hook denies writes). At most `budgets.human_interrupts` (default 3) escalations per campaign:
`harness questions for-human --q Q-003 --stake 5 --would-change "…" --cheapest "…" --best-guess "…" --p 0.3`. Each is a
**concrete mathematical question**, never "I'm stuck": what the answer would change, the cheapest thing the human could do,
and our own best guess. It is written to `ASK-HUMAN.md`; the campaign **keeps working** on other targets meanwhile. The human
answers under `## Answers` as `### H-001` blocks; `harness questions human-answers` (run by the context hook) pulls answers back
into the question ledger. (Cf. the DeepMind co-mathematician's escalations, and autoresearch's human-owned `program.md` with its
"never stop to ask" rule.)
