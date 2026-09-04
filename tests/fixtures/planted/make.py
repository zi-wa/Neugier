"""Generate the planted-flaw fixture campaign (Round-1 Step 15 / C5).

Run:  .venv/Scripts/python.exe tests/fixtures/planted/make.py
Writes a complete ``campaigns/planted``-shaped directory next to this file with:

* ``statement.md`` — a locked interpretation of a small sumset statement;
* a ledger with a theorem ``T-001`` that depends on a **circular** lemma ``L-001``
  (its proof invokes the theorem), a **false** lemma ``L-002`` (counterexample at
  a small parameter, with a conjecture module), an **unused hypothesis** in the
  theorem's proof, and a **citation whose excerpt is not in the cached source**
  (``F-001`` is recorded as unverified);
* a pre-registered rubric, ``HUMAN.md``, sketches + tournament matches, and a
  round-1 review with a skeptic step table and a replicator block.

The unit tests in ``tests/test_planted.py`` assert that the harness catches each
planted flaw mechanically; ``evals/`` reuses the directory for agent-level evals.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from harness.ledger.ledger import LedgerStore  # noqa: E402
from harness.ledger.schema import Evidence  # noqa: E402

STATEMENT = """# Statement (interpretation lock)

**Claim T-001.** For every finite set S of integers with |S| >= 2, |S+S| >= 2|S| - 1.

## Conventions
- S+S = {a + b : a, b in S} (a = b allowed).
- |X| is cardinality; sets are finite.

## Edge cases
- |S| = 2 gives |S+S| = 3.
- Arithmetic progressions attain equality.

## Excluded trivial readings
- S may not be taken multiset-valued; sums are not counted with multiplicity.

## Definition unit tests
See experiments/statement_tests.py.
"""

PROOF = """---
claim: T-001
statement: "For every finite set S of integers with |S| >= 2, |S+S| >= 2|S| - 1."
depends_on: [L-001, L-002, F-001]
assumes: []
uses_hypotheses: [finite, "|S| >= 2", "S contains 0"]
numerics: [results.json#small_cases]
version: 1
technique: [extremal, double-counting]
---

## Proof

**Setup.** Let S be a finite set of integers with |S| >= 2.

**Step 1.** (definition D-001) S+S = {a+b : a, b in S}.
**Step 2.** (hypothesis) S is finite and |S| >= 2, so min S and max S exist and differ.
**Step 3.** (L-001) By Lemma L-001, |S+S| >= 2|S| - 1 whenever |S| >= 2.
**Step 4.** (L-002) By Lemma L-002, every element of S+S is attained by at most two ordered pairs.
**Step 5.** <cite id="Freiman1973" claim="F-001" excerpt-hash="deadbeef0000"> Freiman's theorem gives the structure of sets with small doubling; its hypotheses (finite S, doubling constant bounded) hold here. </cite>
**Step 6.** <key-original-step> Combine Steps 3 and 4 with the compression map that fixes min S and max S. </key-original-step>
**Conclusion.** |S+S| >= 2|S| - 1 (results.json#small_cases confirms n <= 12).

## Edge cases checked
- |S| = 2: S+S has 3 elements.
- Arithmetic progression: equality.

## Self-check log
- Hypothesis use: finite -> Step 2; |S| >= 2 -> Step 2.
- Numeric spot-check: results.json#small_cases (n <= 12) consistent.
"""

LEMMA_CIRCULAR = """---
claim: L-001
statement: "For every finite S with |S| >= 2, |S+S| >= 2|S| - 1."
depends_on: []
assumes: []
uses_hypotheses: [finite, "|S| >= 2"]
numerics: []
version: 1
technique: [extremal]
---

## Proof

**Step 1.** (Theorem T-001) By the theorem being proved, |S+S| >= 2|S| - 1.
**Conclusion.** The lemma follows.

## Edge cases checked
- none

## Self-check log
- Hypothesis use: finite -> Step 1; |S| >= 2 -> Step 1.
"""

LEMMA_FALSE = """---
claim: L-002
statement: "For every finite S of integers, every element of S+S is a+b for at most two ordered pairs (a, b)."
depends_on: []
assumes: []
uses_hypotheses: [finite]
numerics: []
version: 1
technique: [double-counting]
---

## Proof

**Step 1.** (algebra) Fix s in S+S; the pairs (a, s-a) with a in S are determined by a.
**Step 2.** (Step 1) Since a and s-a play symmetric roles, at most two ordered pairs exist.
**Conclusion.** The lemma follows.

## Edge cases checked
- S = {0, 1}: the sum 1 has the two pairs (0,1), (1,0).

## Self-check log
- Hypothesis use: finite -> Step 1.
"""

FALSE_MODULE = '''"""Falsification module for the planted false lemma L-002: the sum s in S+S is attained by at most two ordered pairs.

Counterexample: S = {0, 1, 2}, s = 2 is attained by (0,2), (1,1), (2,0) — three ordered pairs."""
from itertools import combinations


def space():
    for n in range(1, 6):
        for size in range(1, 4):
            for S in combinations(range(n + 1), size):
                yield tuple(S)


def predicate(S):
    counts = {}
    for a in S:
        for b in S:
            counts[a + b] = counts.get(a + b, 0) + 1
    return max(counts.values()) <= 2


def describe(S):
    counts = {}
    for a in S:
        for b in S:
            counts[a + b] = counts.get(a + b, 0) + 1
    s = max(counts, key=counts.get)
    return f"S={set(S)}: sum {s} attained by {counts[s]} ordered pairs"


def features(S):
    return {"size": len(S), "is_ap": len(S) < 3 or len({b - a for a, b in zip(S, S[1:])}) == 1}
'''

RUBRIC = """---
claim: T-001
technique: [extremal, double-counting]
required_hypotheses: [finite, "|S| >= 2"]
must_establish:
  - "2|S|-1 distinct sums are exhibited explicitly"
  - "the equality case is characterized"
hard_step: "exhibiting 2|S|-1 distinct sums without circularity"
version: 1
---
## Marking scheme
- M1: the proof exhibits 2|S|-1 pairwise distinct elements of S+S.
- M2: every lemma used is strictly weaker than the theorem (no circularity).
- M3: every hypothesis in uses_hypotheses is used in a step.

## Pitfalls
- extremal: the extremal object exists (finite search space); minimal counterexample arguments prove every smaller object satisfies the claim.
- double-counting: both counts count the same incidences with the same multiplicity.
"""

SKEPTIC = """# Skeptic report — T-001 — round 1

## Interpretation audit
The proof header matches statement.md. The hypothesis "S contains 0" is not in the statement and is not used.

| Step | Status | Justification checked | Witness (if FLAWED) |
|---|---|---|---|
| 1 | VERIFIED | definition D-001 matches statement.md | |
| 2 | VERIFIED | hypotheses | |
| 3 | FLAWED (critical) | L-001 restates the theorem | Lemma L-001's proof invokes T-001 (circular) |
| 4 | FLAWED (critical) | L-002 is false | S = {0,1,2}: sum 2 has three ordered pairs |
| 5 | OPEN | excerpt for F-001 is not verified in the ledger | |
| 6 | OPEN | depends on Steps 3, 4 | |

```yaml
role: skeptic
claim: T-001
round: 1
agent_id: SK-planted
verdict: fail
critical_errors:
  - step: 3
    witness: "circular: Lemma L-001 is proved from Theorem T-001 itself"
  - step: 4
    witness: "Lemma L-002 is false: S = {0,1,2}, the sum 2 is attained by three ordered pairs"
justification_gaps:
  - step: 5
    witness: "the Freiman excerpt is not present in the cached source; hypothesis check unverifiable"
interpretation_issues:
  - "uses_hypotheses lists 'S contains 0', which the statement does not assume and the proof never uses"
checked:
  - "All 6 steps processed; 2 VERIFIED, 2 OPEN, 2 FLAWED-critical"
confidence: 0.9
```
"""

REPLICATOR = """# Replicator — T-001 — round 1

Stage A (blind): from statement.md, |S+S| for all S ⊂ {0..7} with |S| = 2..4 was recomputed (values.json).

```yaml
role: replicator
claim: T-001
round: 1
verdict: pass
reproduced: [results.json#small_cases]
checked:
  - "results.json#small_cases recomputed exactly for n <= 12"
```
"""

NOVELTY = """# Novelty memo — T-001 — round 1

## Queries (verbatim, engine, #hits)
- "Cauchy-Davenport integers sumset lower bound" (arxiv, 12)
- "|A+A| >= 2|A|-1" (openalex, 30)
- "sumset cardinality 2|A|-1 equality arithmetic progression" (zbmath, 8)

## Closest prior results
| Source | Statement (excerpt, locator) | Relation to ours | Delta |
| unverified | (no cached excerpt) | Cauchy-Davenport for integers is classical | none |

## Final-statement queries
- "|S+S| >= 2|S| - 1" integers finite
- Cauchy Davenport theorem integers equality
- sumset lower bound 2n-1

## Classification: 1c   (confidence 0.95)

```yaml
role: novelty
claim: T-001
round: 1
verdict: fail
class: 1c
confidence: 0.95
```
"""

SKETCH_ANALYST = """---
kind: sketch
claim: T-001
persona: analyst
route: 1
key_idea: order S and exhibit the two monotone families of sums
lemmas:
  - label: S1
    statement: "the sums min+s (s in S) are pairwise distinct"
    needs: [D-001]
    cheapest_falsification: "brute force |S| <= 6"
  - label: S2
    statement: "the sums s+max (s > min) exceed every min+s'"
    needs: [D-001]
    cheapest_falsification: "brute force |S| <= 6"
---
S1, S2 -> T-001 by counting.
"""

SKETCH_ALGEBRAIST = """---
kind: sketch
claim: T-001
persona: algebraist
route: 3
key_idea: polynomial method over F_p
lemmas:
  - label: S1
    statement: "for every prime p > 2 max S, |S+S mod p| = |S+S|"
    needs: [D-001]
    cheapest_falsification: "brute force |S| <= 6, p <= 31"
---
Reduce to F_p and apply Cauchy-Davenport.
"""


def build(dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    for sub in ("experiments/falsify", "proofs", "reviews/round1/replicate", "reviews/tournament-T-001/falsify", "paper", "cache"):
        (dest / sub).mkdir(parents=True, exist_ok=True)
    (dest / "statement.md").write_text(STATEMENT, encoding="utf-8")
    (dest / "campaign.json").write_text(json.dumps({
        "slug": "planted", "title": "Planted-flaw fixture: sumset lower bound", "created": "2026-09-04T00:00:00+00:00",
        "phase": "review", "phase_history": [{"phase": "review", "entered": "2026-09-04T00:00:00+00:00", "exited": None}],
        "budgets": {"hours_total": 8, "max_review_rounds": 3, "decoys_per_round": 2, "skeptic_passes": 2},
        "active_targets": ["T-001"], "outcome_class": None, "statement_hash": None, "notes": "", "frozen": {}, "rubric_hashes": {},
    }, indent=2), encoding="utf-8")
    (dest / "cache" / "Freiman1973.txt").write_text(
        "Freiman, G. A. Foundations of a structural theory of set addition. Chapter 1 discusses sets with small doubling "
        "in the integers; the excerpt claimed by the planted proof does not occur in this cached text.\n", encoding="utf-8")
    (dest / "experiments" / "results.json").write_text(json.dumps({
        "statement_tests": {"passed": True, "n": 3, "source": "experiments/statement_tests.py"},
        "small_cases": {"value": True, "source": "experiments/small_cases.py", "args": ["--n", "12"], "seed": 0, "exact": True},
    }, indent=2), encoding="utf-8")
    (dest / "experiments" / "statement_tests.py").write_text("def test_sumset_pair():\n    assert {0, 1, 2} == {a + b for a in {0, 1} for b in {0, 1}}\n", encoding="utf-8")
    (dest / "experiments" / "small_cases.py").write_text("print('exhaustive n<=12: ok')\n", encoding="utf-8")
    (dest / "experiments" / "falsify" / "L-002.py").write_text(FALSE_MODULE, encoding="utf-8")
    (dest / "proofs" / "T-001.md").write_text(PROOF, encoding="utf-8")
    (dest / "proofs" / "L-001.md").write_text(LEMMA_CIRCULAR, encoding="utf-8")
    (dest / "proofs" / "L-002.md").write_text(LEMMA_FALSE, encoding="utf-8")
    (dest / "proofs" / "T-001.rubric.md").write_text(RUBRIC, encoding="utf-8")
    (dest / "proofs" / "T-001.sketch.analyst.md").write_text(SKETCH_ANALYST, encoding="utf-8")
    (dest / "proofs" / "T-001.sketch.algebraist.md").write_text(SKETCH_ALGEBRAIST, encoding="utf-8")
    (dest / "HUMAN.md").write_text("# HUMAN.md\n\n## Policy\nPrefer elementary arguments.\n\n## Answers\n", encoding="utf-8")
    (dest / "questions.md").write_text(
        "# Questions — planted\n\n## Q-001: Is the bound tight only for arithmetic progressions?\n- Curiosity: 3/3\n"
        "- Expectation: yes\n- Cheapest test: enumerate |S| <= 6 (10 min)\n- Status: open\n- Raised by: experimentalist, 2026-09-04, explore\n\n"
        "## Prediction (Q-001): equality cases for |S| <= 6\n- Predicted: only APs\n- Observed: only APs\n- Surprise: 1/3\n", encoding="utf-8")
    (dest / "ideas.md").write_text(
        "# Ideas — planted\n\n## Route 1: Monotone families — lens: combinatorial\n- Moves: M1, M3\n- Idea: order S and exhibit 2|S|-1 sums.\n"
        "- Cheap falsification (≤ 10 min): brute force |S| <= 6\n- Credence: p_true=0.9 p_budget=0.8 (strategist) — classical\n- Status: key-step T-001\n\n"
        "## Route 3: Polynomial method — lens: algebraic\n- Moves: M40\n- Idea: reduce mod p.\n- Cheap falsification (≤ 10 min): p <= 31\n"
        "- Credence: p_true=0.6 p_budget=0.3 (strategist) — heavier machinery\n- Status: untested\n", encoding="utf-8")
    (dest / "log.md").write_text("# Campaign Log: planted\n\n## Log\n- phase -> review\n", encoding="utf-8")

    store = LedgerStore(dest / "ledger.json", campaign="planted")
    defn = store.add(kind="definition", statement="S+S = {a + b : a, b in S}.")
    fact = store.add(kind="fact", statement="Freiman's theorem: sets with small doubling are contained in generalized arithmetic progressions.")
    store.add_evidence(fact.id, Evidence(type="excerpt", source_id="Freiman1973", locator="Ch. 1",
                                         excerpt="Every finite set A of integers with |A+A| <= K|A| is contained in a generalized arithmetic progression of dimension d(K) and size f(K)|A|."),
                       dest, require_verified_excerpt=False)
    lem_c = store.add(kind="lemma", statement="For every finite S with |S| >= 2, |S+S| >= 2|S| - 1.")
    lem_f = store.add(kind="lemma", statement="For every finite S of integers, every element of S+S is a+b for at most two ordered pairs (a, b).", status="conjectured")
    thm = store.add(kind="theorem", statement="For every finite set S of integers with |S| >= 2, |S+S| >= 2|S| - 1.",
                    depends_on=[lem_c.id, lem_f.id, fact.id], tags=[f"assumes:{fact.id}", f"assumes:{lem_f.id}"], stakes=1)
    store.record_credence(thm.id, role="strategist", why="classical statement, planted flaws in the proof", p_true=0.95, p_budget=0.8)
    store.add_evidence(lem_c.id, Evidence(type="proof", path="proofs/L-001.md", summary="circular"), dest)
    store.promote(lem_c.id, "proof-drafted", dest)
    store.add_evidence(thm.id, Evidence(type="proof", path="proofs/T-001.md", summary="planted proof"), dest)
    store.add_evidence(thm.id, Evidence(type="computation", path="experiments/small_cases.py", summary="n <= 12"), dest)
    store.promote(thm.id, "proof-drafted", dest)
    for name, text in (("skeptic.SK-planted.md", SKEPTIC), ("replicator.md", REPLICATOR), ("novelty.md", NOVELTY)):
        (dest / "reviews" / "round1" / name).write_text(text, encoding="utf-8")
    (dest / "reviews" / "round1" / "replicate" / "values.json").write_text(json.dumps({"small_cases": True}), encoding="utf-8")
    (dest / "reviews" / "tournament-T-001" / "match-analyst-algebraist-plausibility-pairwise.json").write_text(json.dumps({
        "a": "analyst", "b": "algebraist", "winner": "a", "axis": "plausibility", "tier": "pairwise",
        "rationale": "the monotone-family argument is elementary and complete", "steal_from_loser": "the mod-p reduction for a generalization", "rater": "J1",
    }), encoding="utf-8")
    ids = {"definition": defn.id, "fact": fact.id, "circular": lem_c.id, "false": lem_f.id, "theorem": thm.id}
    (dest / "PLANTED.json").write_text(json.dumps({
        "ids": ids,
        "flaws": {
            "circular_lemma": {"claim": lem_c.id, "witness": "proofs/L-001.md Step 1 invokes T-001"},
            "false_lemma": {"claim": lem_f.id, "counterexample": "S={0,1,2}", "module": "experiments/falsify/L-002.py"},
            "unused_hypothesis": {"claim": thm.id, "hypothesis": "S contains 0"},
            "unverified_citation": {"claim": fact.id, "source": "Freiman1973", "cache": "cache/Freiman1973.txt"},
            "already_known": {"claim": thm.id, "novelty_class": "1c"},
        },
    }, indent=2), encoding="utf-8")
    return dest


if __name__ == "__main__":
    out = build(HERE / "campaign")
    print(f"planted fixture written to {out}")
