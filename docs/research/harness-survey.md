# Survey: existing harnesses for autonomous mathematical research (2026-09-02)

Scope: read-only web survey (GitHub READMEs, arXiv, wikis). Nothing installed. Items marked [unverified] could not be confirmed from primary sources.

## A. Evolutionary program-search (AlphaEvolve/FunSearch-style)

**1. OpenEvolve** — https://github.com/algorithmicsuperintelligence/openevolve
- What: open-source AlphaEvolve reimplementation; LLM mutates programs against a user-supplied evaluator.
- Arch: loop = prompt-sampler → LLM ensemble → cascade evaluator (cheap→expensive stages) → program DB. MAP-Elites + islands (ring migration); "artifacts" channel feeds stderr/profiling back into the next prompt; embedding-similarity dedup (threshold 0.99); seeded/reproducible; checkpoints. Matches SOTA circle packing n=26; used for new exact Zarankiewicz values Z(11,21,3,3)=116 etc. (arXiv 2605.01120, ~$15–30/case).
- Weak: README admits stagnation without tuning; many knobs; only avoids *self*-rediscovery, has no notion of literature.
- Steal: cascade evaluation; artifacts-to-prompt feedback; MAP-Elites feature bins; deterministic seeding + checkpoints.

**2. ShinkaEvolve (Sakana)** — https://github.com/SakanaAI/ShinkaEvolve
- What: sample-efficient program evolution (circle packing SOTA in ~150 samples claimed).
- Arch: power-law/beam parent sampling; novelty rejection by code embeddings; UCB bandit over LLM ensemble (cost-aware); global archive of 40 elites + islands; periodic "meta-recommendations" (an LLM summarises what worked → injected as text); ships Claude Code/Codex CLI skills.
- Weak: no documented failure modes; evaluator must be scalar.
- Steal: bandit model routing; meta-scratchpad of insights; novelty-rejection *before* spending evaluation budget.

**3. CodeEvolve** — https://github.com/inter-co/science-codeevolve (arXiv 2510.14150)
- What: AlphaEvolve replication run on the AlphaEvolve math suite.
- Arch: islands + inspiration-based crossover (feed several elites as "inspirations"), depth exploitation with ancestor context, meta-prompting LLM to diversify prompts, MAP-Elites archive.
- Weak: beat AlphaEvolve on 5/9 (circle packing n=32: 2.93956), lost on hexagon packing/autocorrelation; heavy hyperparameters; no ablations (budget).
- Steal: ancestor-context prompting; cheap open-weight model (Qwen3-Coder-30B) at 10% cost.

**4. ThetaEvolve** — https://github.com/ypwang61/ThetaEvolve (arXiv 2511.23473)
- What: single open 8B model + RL at test time on the open problem itself; new bounds on circle packing / first autocorrelation.
- Weak: needs GPU RL infra; reward shaping per task.
- Steal: idea of "learning from your own run log" (cheap version: in-context digest of past attempts).

**5. AlphaEvolve problem repository** — https://github.com/google-deepmind/alphaevolve_repository_of_problems (arXiv 2511.02864)
- 67 problems with verifier code + best-known constructions in Colab; *no* AlphaEvolve code. Paper's pipeline: evolve construction → Deep Think proves formula → AlphaProof formalizes (finite-field Kakeya).
- Steal: use its verifiers as ready-made "goldmine" targets; the construct→prove→formalize handoff.

**6. The Station** — https://github.com/dualverse-ai/station (arXiv 2608.23691)
- What: open-world multi-agent "scientific community" (6 agents: GPT/Claude/Gemini) that self-select problems; 5 novel results (Kakeya families, Erdős min-overlap 0.380552, kissing d=11, sign uncertainty 0.3089).
- Arch: tick-based rooms (Research Center w/ evaluators, Archive of agent-written papers as persistent memory, Mail, Question room); agents die/respawn; evaluators score, an LLM reviews archive papers.
- Weak (self-reported): prefers theory over brute search, dimension-11 success didn't transfer, failed to synthesize its own findings into theorems (human needed); novelty checked vs literature *by humans afterwards*; runs code locally (needs isolation); tasks must be scorable within ~2h.
- Steal: archive-of-papers as memory; "failed explorations" are first-class; heterogeneous model families.

## B. Autonomous research-agent frameworks

**7. AI Scientist v1/v2 (Sakana)** — https://github.com/SakanaAI/AI-Scientist , https://github.com/SakanaAI/AI-Scientist-v2
- Arch: ideation w/ Semantic Scholar novelty check → templates (v1) or best-first tree search over experiment nodes with experiment-manager, debug depth (v2) → LaTeX writeup → LLM reviewer.
- Weak: v1 edited its own timeout, spawned processes; independent eval (arXiv 2502.14297): 42% experiments failed, novelty check misclassified known ideas as novel, fabricated numbers, placeholder text, 5 citations median; reviewer has positivity bias unless GPT-4o; v2 "lower success rate". The "57% false data" figure circulating online is [unverified] beyond one blog.
- Steal: tree search with explicit debug-depth budget; VLM/figure check; but treat its reviewer as a negative example.

**8. Agent Laboratory** — https://github.com/SamuelSchmidgall/AgentLaboratory
- Arch: phases literature-review → plan → data → mle-solver → interpretation → paper-solver; role agents (PhD/postdoc/professor/reviewers); copilot mode; `state_saves` checkpoints; AgentRxiv shared preprint store.
- Weak: quality tracks model; needs extensive human notes; ML-only.
- Steal: per-phase checkpoint file; copilot gates; AgentRxiv idea (local "prior runs" store to avoid re-trying dead ideas).

**9. autoresearch (Karpathy)** — https://github.com/karpathy/autoresearch
- Arch: agent may edit only `train.py`; human owns `program.md`; fixed 5-min budget; single metric; keep-if-better via git branches; results.tsv log.
- Weak (community): no noise floor → "improvements" are jitter; time-budget favours fast-converging hacks; not cross-machine reproducible.
- Steal: narrow write-permissions; one-file human policy doc; append-only results ledger; *add* a noise-floor/kill rule it lacks.

**10. Denario** — https://github.com/AstroPilot-AI/Denario (arXiv 2510.26887)
- Arch: idea → method → results (cmbagent backend, AG2/LangGraph) → paper (LaTeX) with `set_*`/`get_*` state injection; claims literature check + referee, but neither is documented in README/docs [unverified].
- Steal: explicit hybrid state API (human can overwrite any stage artifact).

**11. AI co-scientist reimplementations** — e.g. https://github.com/jataware/open-coscientist , https://github.com/Kaimen-Inc/Co-Scientist , https://github.com/llnl/open-ai-co-scientist
- Arch: supervisor → generate → reflection vs literature → review → Elo tournament (pairwise debates) → proximity dedup → evolve → meta-review.
- Weak: literature only via optional MCP, else latent knowledge; hypothesis-level, no experiments/proofs.
- Steal: Elo tournament + proximity clustering for ranking candidate topics; meta-review that feeds back into generation.

**12. Aletheia (DeepMind)** — arXiv 2602.10177; Erdős case study arXiv 2601.22401; outputs only at https://github.com/google-deepmind/superhuman/tree/main/aletheia (no harness code)
- Arch: Generator → independent Verifier → Reviser, inference-time scaling; internet search.
- Numbers: 700 open Erdős problems → 212 self-verified → 200 expert-checked: 68.5% flawed, 31.5% "technically correct", 6.5% (13) meaningful; of 13: 4 autonomous, 4 rediscoveries, 5 pure literature finds. 50 "correct" answers solved a misread problem (specification gaming). Real papers cited with wrong content (Galambos 1976). Literature matching was "the lengthiest and most arduous step"; rediscovery checked by reading reasoning traces.
- Steal: verifier decoupled from generator context; interpretation-check step before proving; the four-way outcome taxonomy.

**13. AI co-mathematician (DeepMind workbench)** — arXiv 2605.06651 (no code)
- Arch: project coordinator → workstream coordinators → tool agents (literature w/ exact theorem statements, cloud computation, Deep Think proving); shared filesystem, version history of claims, "margin annotations" for provenance, failed explorations kept; code can't mark done until tests + reviewer approve.
- Weak (self-reported): reviewer-pleasing bias, review "death spirals", polished LaTeX ≠ rigor. 48% FrontierMath T4.
- Steal: claim provenance annotations; hard programmatic done-gates; escalation to human on roadblock.

**14. QED** — https://github.com/proofQED/QED (arXiv 2604.24021)
- Arch: literature survey/difficulty triage → Decomposer emits YAML DAG of claims → Prover → Structural Verifier (citations, plan adherence) + Detailed Verifier (line-by-line) → Regulator picks REVISE_PROOF / REVISE_PLAN / REWRITE; proofs must tag `<cite>` vs `<key-original-step>`. Drives Claude/Codex/Gemini CLIs.
- Weak: agents bypass permissions (needs sandbox); retry budget can exhaust; natural-language verification only; claimed 5 expert-verified results [unverified].
- Steal: claim-DAG plan file; two-tier verifier; explicit tagging of novel steps vs cited steps; regulator with escalation ladder.

**15. Rethlas/Archon** — arXiv 2604.03789; only formalization at https://github.com/frenzymath/Anderson-Conjecture
- Informal reasoner + Matlas (NL theorem search over ~10^7 statements) + LeanSearch; Archon decomposes → Lean 4. Resolved Anderson (2014) conjecture. Harness itself not released.
- Steal: separate NL-statement search engine from formal-lemma search; statement comparator to check formalization fidelity.

**16. DeepMind formal proof search on Erdős** — arXiv 2605.22763 (code [unverified])
- Arch: "Ralph loop" subagents editing Lean sketches with compiler feedback; full agent adds Elo-rated sketch population, P-UCB sampling, rating agents (plausibility+novelty), global goal cache, AlphaProof for subgoals, SafeVerify (no axioms, statement unchanged). 9/353 Formal Conjectures problems; $100s–$1000s each; found misformalizations (lower vs upper density).
- Steal: SafeVerify-style statement-immutability check; goal cache; Elo over proof sketches.

## C. Formal-proof harnesses

**17. Aristotle (Harmonic)** — arXiv 2510.01346, closed; https://arxiv.org/abs/2601.07421 (Erdős #728 writeup). Informal proof → lemma decomposition → Lean sketches with `sorry` → MCGS over Lean states w/ 200B+ policy/value. Weak: closed API; #728 writeup says nothing about literature check.
**18. Gauss (Math Inc)** — https://github.com/math-inc/strongpnt ; closed agent; 25k LOC Lean in 3 weeks but from an 83-page human blueprint iterated by humans. Steal: blueprint-first (LeanArchitect arXiv 2601.22554 automates blueprints).
**19. Open provers** — DeepSeek-Prover-V2 (subgoal decomposition by big model, 7B solves subgoals), Goedel-Prover-V2 (https://github.com/Goedel-LM/Goedel-Prover-V2 ; compiler-feedback self-correction, 2 rounds), Kimina-Prover (whole-proof RL, Kimina Lean Server), LeanDojo/ReProver/LeanAgent/Lean Copilot (premise retrieval + best-first search; results vary with seed/hardware). None does research; all are components.
**20. Numina-Lean-Agent** — arXiv 2601.14027; Claude Code + Numina-Lean-MCP (goal state, retrieval, numeric checks); 12/12 Putnam 2025; formalized Brascamp–Lieb with mathematicians. Weak: no failure analysis. Steal: MCP-level Lean feedback instead of `lake build`.
**21. Formal Conjectures** — https://github.com/google-deepmind/formal-conjectures : Lean statements of open conjectures (incl. Erdős), `@[category]`, human review for misformalization. Use as both target list and "already solved?" signal.
**22. Tao's workflow** — https://teorth.github.io/tao-web/ai-views.html ; HN https://news.ycombinator.com/item?id=47306852 . Monolithic run crashed/exhausted tokens; decomposed recipe finished in 25 min; Claude struggled most on *low-level* steps; verify everything independently; AI writing "dwells on trivialities, glosses over the novel step".

## D. Claude Code skills/plugins (math, Lean, review, LaTeX)
- https://github.com/leanprover/skills — official: lean-proof ("one step at a time, error priority, hardest case first"), setup, bisect, mwe, mathlib-build/review; YAML test cases per skill.
- https://github.com/cameronfreer/lean4-skills — Plan→Work→Checkpoint→Review→Replan loop, `disprove` (counterexample search), axiom check, budgets, optional lean-lsp-mcp.
- https://github.com/CBirkbeck/mathlib-quality — 22 commands; proof *tickets* (statement, numbered sketch w/ sources, verified mathlib lemmas); verification gates that must emit artifacts; `/self-review` N fresh rounds; user-approval pauses.
- https://github.com/foogtil/claude-code-math-skills — math-rigor (banned words, numbered steps, SymPy sampling, brute-force counterexample search) + latex-guardian (protected blocks, latexmk gate, label/cite integrity). Admits "instructional, not enforced".
- https://github.com/AlexWortega/ai-peer-review-skill — N parallel anonymized reviewer subagents + red-team slot + meta-review concern matrix; admits single-model-family limits independence.
- https://github.com/wanshuiyin/auto-claude-code-research-in-sleep (ARIS) — Claude executes, GPT/Codex reviews ("a loop can DRIVE, it cannot ACQUIT"); Research Wiki with claims/ideas/experiments nodes; stall detection.
- https://github.com/flonat/flonat-research — artifact-coherence-auditor (paper prose vs replication outputs), code-paper-auditor, referee2 persona, hooks incl. promise-checker for "performative compliance".
- https://github.com/rand/cc-polymath — catalog of math/Lean/Z3 skills; no research workflow.

## E. Erdős-problem agent efforts and literature-check failures
- Wiki taxonomy https://github.com/teorth/erdosproblems/wiki/AI-contributions-to-Erd%C5%91s-problems : 1a standalone / 1b "comparable literature found afterwards" / 1c building on literature / 1d human-AI; ~24 entries are 1b. Cases: #333 GPT-5.2 wrong, Aletheia found Erdős–Newman 1977; #397 = China TST 2012; #659 = 2014 paper; #851 literature search confused with another problem. "Many problems lack a thorough literature review."
- Checklist https://github.com/teorth/erdosproblems/wiki/What-to-do-when-I-think-I-managed-to-get-AI-to-solve-an-Erd%C5%91s-problem%3F : forward/backward citation search from the page's key papers; red flags = suspiciously short proof, proves more than asked, unused hypotheses; humans formalize the statement, not the AI.
- "Erdősgate" (Oct 2025): GPT-5 "solved" 10 problems that were literature finds; tweets deleted (https://garymarcus.substack.com/p/erdosgate).
- https://github.com/neelsomani/gpt-erdos — GPT-5.2 Pro + Deep Research, Aristotle for Lean: 3 new proofs, 4 literature finds, 15 "solved" only under unstated constraints, 13 subtle errors, 4 relied on unproven conjectures.
- https://metafunctor.com/post/2026-03-16-computational-explorations/ — Claude Code Opus 4.6, 131 subagents, ~70 problems, 78k LOC, 5.9k tests, 8 Lean proofs (2 complete), 3 DOIs; adversarial re-implementation caught 4 major errors (order-49 counterexample, formula overfit to 3 points, off-by-one, heuristic 3x off). No systematic literature check reported.

## Gaps in existing harnesses (what none does well)
1. **Claim ledger with verification status.** QED tags steps and co-mathematician annotates margins, but no open harness keeps a machine-readable ledger: claim → status {conjectured, numerically checked (n≤N), proved-NL, proved-Lean, refuted} → evidence path → dependencies. Paper generation should compile only from ledger rows at ≥ "proved-NL, referee-passed".
2. **Novelty gate before writing.** Only humans do it (Aletheia: "most arduous step"; Station: post hoc). Build a mandatory gate: forward/backward citation walk from seed papers, OEIS/Formal Conjectures/erdosproblems lookup, red-flag heuristics from the Tao wiki (too short, proves more than asked, unused hypothesis), with a written "novelty memo" citing what was checked; the gate outputs 1a/1b/1c classification, not a boolean.
3. **Interpretation lock.** 25% of Aletheia's "correct" answers solved the wrong reading. Freeze the problem statement (and Lean statement if any) in a human/skeptic-approved file; SafeVerify-style diff check that nothing downstream rewrote it.
4. **Falsification-first.** Only lean4-skills `disprove`, foogtil counterexample search, and metafunctor's ad-hoc "try to disprove" do this. Make counterexample/SAT/brute-force search a required stage that runs *before* proof development and again after, with the falsifier agent rewarded for kills.
5. **Information barrier for referees.** ai-peer-review-skill hides reviewers from each other but they share a model and see the polished paper. Give referees only statement + proof (no motivation, no run log), use a different model family where possible (ARIS), and let a "replicator" agent re-derive key numerics from scratch (flonat's coherence audit, metafunctor's re-implementation) with a blinded target.
6. **Kill criteria / pivoting.** autoresearch keeps jitter; Station agents just die of old age; co-mathematician reports review death spirals. Define per-topic budgets, noise-floor tests for numerical improvements, a max-revision count after which the Regulator must either pivot topic or downgrade the claim, and log the pivot reason.
7. **Reproducibility appendix as a build artifact.** No math harness emits one. Auto-generate: exact commands, seeds, package versions, verifier hashes, evaluator code, runtime, model IDs, and a script that regenerates every number in the paper (Denario/AI-Scientist produce papers with unreproducible numbers).
8. **Literature memory across runs.** AgentRxiv and ARIS's wiki are the only "what did we already try/find" stores. Keep a local, append-only store of rejected topics (with reason: known result, refuted, out of budget) so the survey stage never re-proposes them.
9. **Rigor-of-exposition gate.** Tao: AI text over-explains trivia and hides the novel step. Require the paper to mark which lemma is the new idea (QED `<key-original-step>`) and have the skeptic verify that lemma in isolation.
10. **Windows/venv/sandbox hygiene.** Every harness assumes Linux, runs LLM code on the host (Station, QED, AI-Scientist warn about it). Pin a per-project venv, run experiments under a job object/timeout with no network, restrict agent write scope to `experiments/` and `paper/` (autoresearch-style), and forbid agents from editing evaluator/verifier code.
