# Borrowed mechanisms — sources and what Neugier took from them

Round 2 (2026-09-04) added six in-house mechanisms (X1–X6) and fourteen borrowed ones (Y1–Y14). Every row below was
confirmed from the source text fetched by tool during the planning session; the quoted fragments are verbatim. The table
is kept so that the README and the paper template can cite precedents honestly, and so that a later audit can re-check them.

| Source | Verbatim fragment (fetched) | Used in |
|---|---|---|
| Huang & Yang, arXiv 2507.15855 §2.2–2.3 (IMO-grade verifier) | "we run the verifier five times and accept a solution only if it passes every time." / "Critical errors are something that is demonstratively false or with clear logical fallacies" | Y1 k-of-k skeptic passes; Y3 typed defect classes |
| AIM, arXiv 2505.22451 (Method) | "The verifier performs multiple independent reviews in parallel, and the proof is rejected if any one of these reviews deems it incorrect." / "valid conjectures are promoted to lemmas" | Y1 unanimity; Y7 lemma bank |
| ProofCouncil, arXiv 2607.09474 | "we reset the critic every k rounds. In our experiments, we use k=3." / "a fresh critic is called for an additional audit" | Y1 fresh-context skeptics, respawn |
| ProofGrader, proofgrader.github.io (arXiv 2510.13888) | "The marking scheme proves crucial—it provides the majority of the performance gain." (MAE 1.680 → 1.069 → 0.964) / "the median of five independent runs consistently improves accuracy while reducing variance" | Y2 pre-registered marking schemes |
| Benchmarking Agentic Review Systems, arXiv 2606.19749 | injected errors = "local math edits (sign flips, index/subscript changes, numeric edits, computation errors)"; detection = "a fuzzy substring match" then "an LLM judge"; best recall 71.6 %, union 83.3 %; manual audit 82.5 % valid | X1 decoy lineup (deterministic mutation operators, two-stage detection) |
| ProcessBench, arXiv 2412.06559 (search snippet) | "or conclude that all steps are correct" (all-correct control) | X1 control item |
| t46/claim-prediction-market (README) | "Brier score 0.177 on 35 ARA-generated claims"; personas "Skeptic, Optimist, Methodologist, DomainExpert, BaseRate"; predictions "before an agent executes high-cost experiments" | X2 credences, panel, Brier calibration |
| The Optimist (TxGraffiti successor), arXiv 2411.09158 §2.1/§3.5/§3.8 | "Truth Test: The conjectured inequality must hold for all graphs in the database." / "Significance Test: The conjecture must provide a stronger bound for at least one graph" / "The touch number … holds as an equality" / "incorporates the new graph into its knowledge base and updates all conjectures" | X3 conjecture repair (truth/significance tests, touch number, regression set) |
| teorth/erdosproblems wiki | 1(a)/1(b)/1(c)/1(d) placement; 🟢 full / 🟡 partial / 🔴 incorrect / ⚪ unverified; "Many problems on the site lack a thorough literature review"; "Absence of past progress may reflect obscurity rather than difficulty" | X4 stakes tiers and `\unverified{}` marker; novelty classes |
| Bubeck et al., arXiv 2511.16072 §II.3 | "we soon learned that the same tight bound…had appeared on Arxiv nearly 3 years previously" | Y4 final-statement re-check |
| Kosmos, arXiv 2511.02824 §2.1 | "Each statement and figure in the report cites either a publication … or a Jupyter notebook"; "79.4% of the statements … accurate … 85.5% … data analysis … 82.1% … literature … 57.9% … synthesis" | X5 coverage by type; Y9 provenance table and sampled accuracy audit |
| leanblueprint README | `\uses`, `\leanok` ("fully formalized"), `\notready`; statuses `stated` (green) `can_state` (blue) `not_ready` (#FFAA33) `proved` (#9CEC8B) `can_prove` (#A3D6FF) `defined` (#B0ECA3) `fully_proved` (#1CAC78) `mathlib` (darkgreen) | X5 blueprint graph, computed `fully_proved` |
| DeepMind formal search, arXiv 2605.22763 §2/§A.1 | rating agents rank on "plausibility, clarity, and novelty"; "Elo ratings … P-UCB"; `Elo_s = 1200 + 400 log10 λ` | Y6 sketch tournament |
| AI co-scientist, arXiv 2502.18864 §3.3.3 | "initial Elo rating of 1200"; "multi-turn scientific debates … Lower-ranked hypotheses undergo single-turn comparisons" | Y6 pairwise vs debate tiers |
| DeepMind co-mathematician, arXiv 2605.06651 §3.3–3.4 | "surfaces an alert to the user and explicitly asks for help in the chat"; "the workstream is marked as unfinished, with an escalation message clearly surfaced to the user" | X6 metered human escalations |
| karpathy/autoresearch `program.md` | "Modify train.py — this is the only file you edit."; "NEVER STOP: … do NOT pause to ask the human if you should continue." | X6 human-owned `HUMAN.md`, non-blocking escalation |
| OpenEvolve `configs/default_config.yaml` | `cascade_evaluation: true`, `cascade_thresholds: [0.5, 0.75, 0.9]`, `include_artifacts: true`, `max_artifact_bytes: 20480` | Y5 cascade evaluation, artifacts |
| ShinkaEvolve README | `meta_rec_interval: 10`, `meta_max_recommendations: 5`, `code_embed_sim_threshold: 0.99`, `max_novelty_attempts: 3` | Y5 meta recommendations, novelty rejection |
| flonat-research hooks | promise-checker: "catches 'performative compliance': Claude says it remembered/noted/saved" | Y14 structural promise checks |
| Agents4Science 2025 | "Requiring disclosures of AI involvement in the research process, to be released to the public" | Y10 AI-involvement disclosure appendix |
| Claude Code docs (workflows, sub-agents, hooks) | `.claude/workflows/` = "shared with everyone who clones the repo"; `Date.now()`/`Math.random()` throw inside scripts (deterministic re-runs); `isolation: worktree`; `SubagentStop` exit 2 blocks | Y12 saved workflows, worktree provers |
| `claude plugin eval --help` (v2.1.259, local) | `evals/**/case.yaml` or `prompt.md + graders/*.md`, `--ablation with-without`, `--runs`, `--max-cost-usd`, `--report`; on this account: "`plugin eval` is currently in early access" | Y13 eval suite + in-house runner `harness evals run` |

## Honest novelty of the in-house mechanisms

- **X1 Lineup review.** Error-injection benchmarks for reviewers exist (arXiv 2606.19749, ProcessBench). We found no harness that builds decoys
  from the *live* artifact during a run and gates whether a referee's verdict is admitted by its recall on the planted flaws.
- **X2 Pre-registered credences.** Credence + Brier exists as a hobby project (claim-prediction-market). Binding credences to ledger claims
  and using the calibration history in budgeting and warnings is ours.
- **X3 Conjecture repair.** Exists for graph-invariant conjectures (The Optimist). Natural-language statements with ledger lineage
  (`repaired_from`, `repair_op`) and the regression-set truth test are ours.
- **X4 Stakes-dependent review regime.** Community norms exist (erdosproblems wiki tiers). Automatic scaling of review intensity with
  stakes is ours.
- **X5 Coverage + blueprint.** Kosmos audits after the fact; leanblueprint draws graphs from `\uses`. Computing both from the ledger, with
  `fully_proved` derived rather than declared, is ours.
- **X6 Office hours.** Escalation exists (co-mathematician). A metered budget of human attention, with a human-owned policy file, is ours.

## Rule for citing measurements

Recall, Brier scores, coverage percentages and with/without eval deltas may be quoted only from files the harness generated
(`reviews/roundN/lineup_score.*.json`, `calibration.json`, `reviews/roundN/coverage-*.json`, `evals/results/**/aggregate.json`).
If the file does not exist, the number is "not yet measured".
