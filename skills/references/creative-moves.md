# Creative moves catalog (rule R3)

Creativity is enforced structurally: before committing to an attack, the strategist/prover must produce **at least five
distinct routes through different lenses plus one deliberately unconventional route**, each citing the moves used below,
each with a cheap falsification test and a pre-registered credence. Dead routes stay in `ideas.md` with the reason, so they are
not retried. `python -m harness ideas dedup --campaign <slug>` flags near-duplicate routes (TF-IDF ≥ 0.8) and shared lenses;
`campaign check` prints them as advisories. Before choosing moves, read `harness library moves-stats` (which moves produced
key steps in past campaigns) and `harness library lessons --query <topic>`.

## Route format (required; machine-read by `harness ideas`)

```markdown
## Route 3: Entropy reformulation — lens: information-theoretic
- Moves: M12 (change the ambient object), M21 (entropy), M31 (technique transfer from Li 2026 arXiv:2607.29042)
- Idea: replace |A+A| by H(X+X') for X uniform on A; prove the entropic inequality, then transfer via ...
- Why it might work: ...
- Cheap falsification (≤ 30 min): compute H(X+X') for random A, |A| ≤ 12; if the entropic version fails on a small A, drop.
- Cost estimate: 2 h explore / 6 h prove
- Kill criterion: entropic inequality false for some |A| ≤ 12, or transfer lemma needs |A| > 10^6.
- Credence: p_true=0.35 p_budget=0.2 (strategist) — the entropic form is known to be weaker in some regimes
- Status: untested | tested-ok | dead: <reason> | proved <claim-id> | key-step <claim-id>
```

`Status` is updated as the campaign proceeds (the experimentalist after the cheap test, the prover when a route yields a
proof or the key step); `campaign finish` records every route's moves and final status in `library/moves.jsonl`.

## Lenses (pick different ones for different routes)

combinatorial · probabilistic · analytic/Fourier · algebraic/polynomial · geometric/topological · information-theoretic ·
computational/evolutionary · logical/model-theoretic · dynamical/ergodic · arithmetic/local-global

## Moves

### A. Pólya moves (reshaping the problem)
- **M1 Specialize** to the smallest nontrivial case; solve it completely; look for the mechanism.
- **M2 Generalize to simplify**: a stronger statement with a cleaner induction (add a parameter, prove for all fields, all dimensions).
- **M3 Extremal case**: what does an extremal object look like? Prove structure first, then the bound.
- **M4 Work backwards** from the conclusion: what would the last step have to be?
- **M5 Auxiliary problem**: find a problem whose solution would obviously imply this one and is "shaped" better.
- **M6 Vary the data**: perturb hypotheses; which hypothesis is doing the work? (Also detects unused hypotheses.)
- **M7 Analogy**: finite field ↔ integers ↔ reals ↔ function fields; graphs ↔ hypergraphs ↔ matrices ↔ tensors.

### B. Structural moves (changing the object)
- **M10 Dualize**: LP duality, Fourier duality, incidence duality, dual code/design, polar sets.
- **M11 Linearize**: encode the object as a matrix/tensor; use rank, spectrum, determinant.
- **M12 Change the ambient object**: set → measure → random variable → distribution; graph → polynomial → variety.
- **M13 Symmetrize / desymmetrize**: average over a group; or break symmetry to get a foothold.
- **M14 Tensorize / power trick**: prove for products, take roots (Bourgain-style amplification).
- **M15 Discretize ↔ continuize**: pass to the limiting object (graphon, measure, flag algebra) or to a finite model.
- **M16 Relax then round**: continuous/SDP/LP relaxation; rounding with an exact certificate.

### C. Probabilistic moves
- **M20 Random construction** with alteration; **M21 Entropy** counting (Shearer, submodularity);
  **M22 Local lemma / dependent random choice**; **M23 Concentration + union bound**; **M24 Second-moment / Janson**.

### D. Analytic moves
- **M30 Fourier analysis / additive energy**; **M31 Generating functions + singularity analysis**;
  **M32 Compactness / limiting argument**; **M33 Smoothing / mollification of the extremal problem**;
  **M34 Variational: perturb the extremizer, derive Euler–Lagrange conditions.**

### E. Algebraic moves
- **M40 Polynomial method / combinatorial Nullstellensatz / slice rank**; **M41 Characters and Gauss sums**;
  **M42 Symmetric functions and invariants**; **M43 Galois / finite-field structure (subfields, Frobenius)**;
  **M44 Representation theory of the symmetry group.**

### F. Combinatorial moves
- **M50 Density increment**; **M51 Regularity + counting**; **M52 Container method**; **M53 Flag algebras**;
  **M54 Sunflowers / shifting / compression**; **M55 Explicit algebraic constructions (Sidon, Singer, BCH, Cayley graphs).**

### G. Computational moves
- **M60 Exhaustive small cases + OEIS lookup** (`python -m harness lit search --engine oeis`), then guess the pattern and prove it.
- **M61 Evolutionary program search** over constructions with an exact scorer (`python -m harness evolve`); mine the elite
  population for structure (`harness evolve mine`), then prove the structure.
- **M62 SAT / ILP / z3 encoding** of existence questions; extract certificates.
- **M63 Numerical optimization of a variational problem, then rationalize** (`interval_eval`, `certify_bound`).
- **M64 Inverse search**: enumerate objects satisfying a necessary condition and look for the sufficient one.
- **M65 Conjecture repair**: when a conjecture is refuted, run `harness ledger repair <id>` and try the three operators
  (add-hypothesis from the counterexample's features, weaken-bound to the strongest surviving inequality, absorb-and-regenerate).

### H. Meta moves (where new ideas actually come from)
- **M70 Technique transfer**: take the survey's *technique tags*; list techniques never applied to this target; try the top 3.
- **M71 "What would the strongest recent paper do here?"** Emulate its first step on our object.
- **M72 Inverse problem**: characterize when the inequality is tight; the characterization often suggests the proof.
- **M73 Cross-field import**: information theory for additive combinatorics, algebraic geometry for incidence problems, coding
  theory for packings, statistical physics for extremal graph theory.
- **M74 Adversary game**: model the claim as a two-player game; strategies become constructions.
- **M75 Wrong-but-instructive**: write the simplest false proof; the point where it breaks names the real difficulty.
- **M76 Weaken the goal**: prove the claim up to a constant, for almost all n, for a positive-density subset; publishable partials.

## Discipline

- A route without a cheap falsification test is not a route; a route without a credence is not a route.
- Do not investigate a route whose falsification test failed; log it (`ideas.md`, status `dead`, reason) and move on.
- Parallel persona provers (combinatorialist / analyst / algebraist / experimentalist) should each take a *different* route and
  first write sketches; the sketch tournament (`harness prove elo`) decides who gets the full-proof budget and cross-pollinates.
