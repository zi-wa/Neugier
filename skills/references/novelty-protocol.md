# Novelty protocol (literature gate)

Run **before** proof effort (in Plan) and **again before writing** (in Review, by `novelty-checker`). The output is a memo,
`reviews/roundN/novelty.md` (or `survey.md` §Novelty in Plan), never a yes/no. Documented failures this protocol exists to
prevent: "Erdősgate" (Oct 2025: existing references presented as solutions), Erdős #1026 (key 2024 paper missed by "deep
research" tools, found by Google Scholar), #851 (search confused with a different problem), ≈24 wiki entries of class 1b.

## 1. Build the query set (write it down)

For the target and for each key lemma:
- **Natural names** of the objects (e.g. "sum-free set", "Sidon set", "cap set") and their historical names.
- **Notation variants**: `|A+A|`, "sumset", "doubling", "additive energy"; `R(k,l)`, "Ramsey number"; etc.
- **The specific quantity**: the constant, exponent, or bound with its number (`1.96365`, `n^{1/3}`), and the neighbours.
- **The theorem shape** in words: "lower bound for … via …", "counterexample to …".
- **Synonyms across fields** (e.g. "Kakeya" / "Besicovitch" / "Nikodym"; "kissing number" / "spherical code").
Aim for 8–15 distinct queries. Record them verbatim in the memo.

## 2. Engines (all of them; not just one)

| Engine | Command / tool | Why |
|---|---|---|
| arXiv API | `python -m harness lit search --engine arxiv --max 50 "<q>"` (also `sort=submittedDate`) | preprints, last 24 months matter most |
| OpenAlex | `--engine openalex` | coverage of journals + citation graph |
| zbMATH Open | `--engine zbmath` | reviews of older results; MSC codes |
| Web search (Google Scholar coverage) | `WebSearch` with the quantity/number and the natural name | the #1026 lesson |
| MathOverflow | `--engine mo` | folklore results and "this is known, see …" answers |
| OEIS | `--engine oeis` / `oeis-conjectures` | sequences and their references |
| erdosproblems yaml + AI wiki | `.cache/sources/erdosproblems/data/problems.yaml`; wiki page | status, `ai_attempts`, prior AI failures |
| formal-conjectures | repo search | whether a formal statement exists and is marked solved |

## 3. Citation walk (snowballing)

1. Pick ≥ 3 **seed papers** (the best-known result, the most recent progress, a survey).
2. **Backward**: read their reference lists for anything with a matching title/quantity (fetch the TeX source:
   `python -m harness lit fetch <id>`; grep with `excerpt`).
3. **Forward**: `openalex.cited_by` on each seed; for the last 3 years read every title/abstract.
4. Two hops for the most relevant hit.
5. Surveys' "open problems" / "recent progress" sections are read in full.

## 4. Compare, do not skim

For every candidate hit, fetch the source and extract the **exact statement** (`theorem_environments`, `excerpt`) and record:
statement · hypotheses · bound/constant · method · year · locator. Then classify against our claim:

- `1a` **standalone**: nothing comparable; our result is new as stated.
- `1b` **comparable literature exists**: a weaker/stronger/incomparable version exists — cite it, state precisely the delta.
- `1c` **already known** as stated (or stronger) — the campaign result becomes `known-in-literature`; a paper is only justified
  if the *method* is new and the memo says why.
- `1d` **misread**: the literature resolves the intended problem; our statement differs from the intended one.

## 5. Memo format

```markdown
# Novelty memo — <claim id> — round N — <date>
## Queries (verbatim, engine, #hits)
## Seeds and citation walk (ids, hops, what was read)
## Closest prior results
| Source | Statement (excerpt, locator) | Relation to ours | Delta |
## Classification: 1a | 1b | 1c | 1d   (confidence 0–1)
## What was NOT checked (timebox reached, paywalled sources, languages)
## Recommended bib additions (resolved keys)
```

Every prior-result row must carry a verbatim excerpt obtained by tool this session; no excerpt → row marked `unverified` and
excluded from the classification.

## 6. Rules

- Timebox: Plan-phase gate 45 min; Review-phase gate 90 min. Unfinished → say what was not covered.
- A `1a` classification with fewer than 8 queries or without a forward walk is invalid.
- The novelty memo is written by a fresh agent that has not seen the prover's reasoning.
- Record every new confirmed fact in `library/facts.jsonl` (`python -m harness library add-fact ...`) so future campaigns reuse it.
