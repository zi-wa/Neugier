# Technique pitfalls (marking-scheme companion)

Used by the strategist when writing a claim's pre-registered marking scheme (`proofs/<ID>.rubric.md`, written
*before* any proof exists) and by the skeptic while running the step-level state machine. Each section names the
failure modes a proof using that technique must visibly rule out, and the **witness shape** a referee must produce
when the proof does not. Tags are the `## ` headings; a proof's frontmatter lists them under `technique:`.

These are generic mathematical checks, not literature claims; nothing here needs a citation.

## induction
- Base case actually verified for the *smallest* parameter the statement covers (n = 0 vs n = 1; empty set).
- The inductive hypothesis is used for a strictly smaller parameter; strong induction is named if used.
- The inductive step does not silently assume the hypothesis for *all* smaller cases when only one is available.
- Parameters other than the induction variable stay fixed (no hidden second induction).
- Witness shape: the parameter value at which the step first fails, or the unproved base case.

## compactness-limits
- The space is actually compact / the sequence actually has a convergent subsequence (named theorem, hypotheses checked).
- Limits and quantifiers commute only when uniformity is proved; "choose N large enough" says what N depends on.
- Error terms are uniform in every parameter they must be uniform in (∀ε ∃N vs ∃N ∀ε).
- Passing to the limit preserves the inequality's *non-strict* form only.
- Witness shape: the quantity that is not uniform, with a family of examples where it blows up.

## probabilistic-method
- The probability space is defined (uniform over what? independent of what?).
- Expectation bounds are turned into existence only when the bad-event probability is < 1 (or the union bound is summed correctly).
- Dependencies are tracked when using concentration (independence or bounded differences verified).
- Alteration steps remove all violating substructures and the count removed is bounded.
- Witness shape: the event whose probability is overestimated, or the dependency that breaks independence.

## quantifier-order
- Every chosen object states what it depends on; the dependency order is a DAG.
- ∀x∃y is never silently upgraded to ∃y∀x.
- Constants introduced as "absolute" do not depend on the variable being quantified.
- Witness shape: the pair of quantifiers whose order was swapped, with the step number.

## case-analysis
- The cases are exhaustive (stated why) and the boundary cases belong to exactly one case.
- Each case is closed by its own argument; no case reuses a conclusion from another case that needed different hypotheses.
- Degenerate cases (n ≤ 2, empty set, equality) are handled explicitly.
- Witness shape: an object in no case, or in a case whose argument does not apply to it.

## extremal
- The extremal object exists (finite search space, or compactness argument).
- "Minimal counterexample" arguments prove that every smaller object satisfies the claim, not just some.
- Perturbing the extremizer stays inside the admissible class.
- Witness shape: an admissible perturbation that improves the objective, or a class with no extremizer.

## polynomial-method
- Degree bounds are computed, not asserted; the polynomial is nonzero (a coefficient exhibited).
- Vanishing multiplicities are counted correctly (Schwartz–Zippel-type steps need the field size vs degree comparison stated).
- The field / characteristic matters: an argument over Q is re-checked over F_p and vice versa.
- Witness shape: the coefficient that vanishes, or the field where the degree comparison fails.

## double-counting
- Both counts count the *same* set of incidences with the same multiplicity.
- Inequalities used for one side are in the correct direction.
- Witness shape: an incidence counted twice on one side and once on the other.

## asymptotics
- Every O(·), o(·), ≪ says what it is uniform in and where the implied constant comes from.
- Error terms are not dropped when they are of the same order as the main term.
- Asymptotic equalities are not applied to finitely many small cases that the statement covers.
- Witness shape: the parameter range where the error term dominates.

## density-increment
- The increment is strictly positive and bounded below by a function of the density, so the iteration terminates.
- The structure passed to the next iteration is of the same type (subspace, progression) with the same hypotheses.
- Iteration count times per-step loss stays below the density (the bookkeeping is written down).
- Witness shape: the iteration bound that exceeds the available density.

## computation-certificate
- The certificate (SAT model, LP dual, exact rational value) is checked by an independent verifier, not the searcher.
- Floating-point outputs are converted to exact arithmetic or intervals before they support an inequality.
- The searched range is stated and the claim does not extend beyond it without a proof.
- Witness shape: the input outside the searched range, or the floating-point comparison without an exact check.

## reduction
- The reduction maps every instance of the target problem to an instance the solved lemma covers (hypotheses transfer).
- The direction of the implication is the one needed.
- Witness shape: an instance whose image violates a hypothesis of the lemma.
