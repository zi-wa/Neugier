# Curiosity over compliance (rule R6)

**Principle.** The protocols in this harness are guardrails a referee needs to see; they are not the path. A research agent
acts on *genuine questions* — what is surprising, what does not fit, what it most wants to know — and chooses its next action
by expected information gain, not by the next checklist item. The user's instruction: the model should act on curiosity rather
than on commands. The only things curiosity never overrides are the rigor rules: R5 (evidence), the ledger promotion rules,
the interpretation lock, the referees' information barrier, containment (R2), and hard budget caps.

## 1. The question ledger — `campaigns/<slug>/questions.md`

Every agent that touches the mathematics **starts** by writing the questions it actually has, before doing anything else, and
**ends** by updating them. Questions are also ledger claims of kind `question` (ids `Q-nnn`) so they can be linked from
targets, lemmas and evidence (`python -m harness ledger add --kind question --statement "..."`).

```markdown
## Q-003: Why does the greedy Sidon construction plateau near density 0.29 for N ≤ 2000?
- Curiosity: 3/3   (3 = the answer would change the plan; 1 = mild)
- Expectation: density decays like c/sqrt(N) with c ≈ 1; a plateau would be surprising.
- Cheapest test: run seed.py for N = 100..5000, fit exponent (≤ 15 min).
- Status: open | answered → <evidence path or claim id> | dropped → <reason>
- Raised by: experimentalist, 2026-09-02, explore
```

Rules: ≥ 3 open questions after Plan; each has an *expectation* (so surprise is measurable) and a *cheapest test*; answered
questions point to evidence; dropped questions say why. Questions can be about anything: the object, a paper's proof, a
strange number, a mismatch between two sources, a route that failed for an unclear reason.

## 2. Surprise log

Before every experiment, write the prediction. After, compare. Any material deviation becomes a `## Surprise` entry in
`questions.md` (prediction · observation · follow-up question · curiosity score). Surprises are the most valuable output of the
Explore phase; the strategist reads them before re-planning; the prover reads them for lemma candidates. Anomalies to watch for:
numbers that deviate from the predicted growth rate, near-misses of a known bound, unexpected symmetry or structure in elite
constructions, integer sequences absent from OEIS, two sources that disagree, a lemma that is "too easy".

## 3. Choosing the next action (information gain)

At each decision point list 3–5 candidate actions and rate each: **(a)** probability that its outcome changes what we do next,
**(b)** cost. Do the highest (a)/(b). Write one line in `log.md`: `decision: <action> — because <one reason>`. The plan's
ordering is a default, not an order.

## 4. Detour budget

Each phase carries a curiosity budget: **30 % of the phase's time by default** (`budgets.curiosity_fraction` in `campaign.json`)
that any agent may spend on a question outside the plan **without asking**. Log it:

```markdown
## Detour (explore, 40 min): Q-003
- What I did: ...
- What I learned: ...
- Plan impact: none | re-plan requested (reason) | new target proposed (id)
```

A detour that produces a surprise with curiosity 3/3 may trigger re-planning (`strategist`), even mid-phase. Detours count
against the phase budget; the hard cap still holds.

## 5. Question-driven planning

Targets in `plan.md` are phrased as questions ("Is the extremal configuration always symmetric?"), routes are attempts to
answer them, and kill criteria say which answer would make the question uninteresting. The scout records, separately from the
rubric, which candidates it finds most puzzling (**intrinsic interest**, 0–3): with verifiability V ≥ 2, a genuinely intriguing
target beats a marginally higher-scoring dull one.

## 6. Curiosity of referees

Referees are curious adversarially: *where does this break? what is the strangest instance? what would I need to see to believe
step k?* Their protocols (`referee-checklist.md`) are unchanged; curiosity there means digging where the proof is weakest, not
where the checklist points.

## 7. What curiosity is not

Not an excuse to skip evidence (a hunch is a question, not a fact), not a reason to edit `statement.md`, not a license to
exceed hard budgets, and not "exploring" by reading the prover's reasoning when you are a referee.
