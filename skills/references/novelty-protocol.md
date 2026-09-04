# Novelty protocol (literature gate)

Run **before** proof effort (in Plan) and **again before writing** (in Review, by `novelty-checker`). The output is a memo,
`reviews/roundN/novelty.md` (or `survey.md` §Novelty in Plan), never a yes/no. Documented failures this protocol exists to
prevent: "Erdősgate" (Oct 2025: existing references presented as solutions), Erdős #1026 (key 2024 paper missed by "deep
research" tools, found by Google Scholar), #851 (search confused with a different problem), ≈24 wiki entries of class 1b, and
the clique-avoiding-codes case (arXiv 2511.16072 §II.3: a bound that "had appeared on Arxiv nearly 3 years previously" was found
only when the *final statement* was searched, not the topic).

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
| Lemma bank | `python -m harness library find-lemma "<statement>"` | what earlier campaigns already proved or found |

## 3. Citation walk (snowballing)

1. Pick ≥ 3 **seed papers** (the best-known result, the most recent progress, a survey).
2. `python -m harness lit cite-walk <seed> --direction both --hops 1 --max 50` for each seed (forward = works citing it, backward =
   its references), then read every title/abstract of the last 3 years; two hops (`--hops 2`) for the most relevant hit.
   Tier-2 claims (`stakes: 2`) **require** a two-hop walk; record `citation_hops:` in the verdict block.
3. Fetch the source of every candidate (`python -m harness lit fetch <id>` into the campaign cache); grep with `excerpt`.
4. Surveys' "open problems" / "recent progress" sections are read in full.

## 4. Compare, do not skim

For every candidate hit, fetch the source and extract the **exact statement** (`theorem_environments`, `excerpt`) and record:
statement · hypotheses · bound/constant · method · year · locator. Then classify against our claim:

- `1a` **standalone**: nothing comparable; our result is new as stated.
- `1b` **comparable literature exists**: a weaker/stronger/incomparable version exists — cite it, state precisely the delta.
- `1c` **already known** as stated (or stronger) — the campaign result becomes `known-in-literature`; a paper is only justified
  if the *method* is new and the memo says why.
- `1d` **misread**: the literature resolves the intended problem; our statement differs from the intended one.

## 5. Final-statement re-check (Review phase)

The Plan-phase memo searched the topic before the result existed. In Review, add a **`## Final-statement queries`** section
with ≥ 3 queries that contain the claim's *specific quantities* — the values of the `results.json` keys the proof's `numerics:`
references (the harness checks that they appear) — and the exact final wording of the theorem. Record the sha256 of the
artifact you classified as `artifact_sha256:` in the verdict block; `harness review check` requires it at tier 2.

## 6. Memo format

```markdown
# Novelty memo — <claim id> — round N — <date>
## Queries (verbatim, engine, #hits)
## Seeds and citation walk (ids, hops, what was read)
## Closest prior results
| Source | Statement (excerpt, locator) | Relation to ours | Delta |
## Final-statement queries
- "<exact quantity> <object>" …
## Classification: 1a | 1b | 1c | 1d   (confidence 0–1)
## What was NOT checked (timebox reached, paywalled sources, languages)
## Recommended bib additions (resolved keys)
```

followed by the verdict block (referee-checklist §7) with `class:`, `citation_hops:`, `artifact_sha256:`.
Every prior-result row must carry a verbatim excerpt obtained by tool this session and verified against the cached source
(`harness lit verify-excerpt`); no verified excerpt → row marked `unverified` and excluded from the classification.

## 7. Rules

- Timebox: Plan-phase gate 45 min; Review-phase gate 90 min. Unfinished → say what was not covered.
- A `1a` classification with fewer than 8 queries or without a forward walk is invalid.
- The novelty memo is written by a fresh agent that has not seen the prover's reasoning (the barrier hook enforces it).
- Record every new confirmed fact in `library/facts.jsonl` (`python -m harness library add-fact --campaign <slug> …`; the
  excerpt must verify against the cache) so future campaigns reuse it.
