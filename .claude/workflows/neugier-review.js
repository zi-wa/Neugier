// Neugier review round as a deterministic, resumable Workflow script (Round-2 Y12; opt-in via `/review --workflow`).
//
// The orchestrating skill runs `harness review open --campaign <slug> --claim <id> --artifact <path>` BEFORE calling this
// workflow (the script has no filesystem access) and `harness review score-lineup`, `lineup unseal`, `review check`
// AFTER it. Referees see only what the barrier manifest allows; their PreToolUse hooks enforce it and log access.
// No clock or randomness calls: all timestamps and round numbers come from `args` so reruns are deterministic.
export const meta = {
  name: 'neugier-review',
  description: 'Adversarial review round: skeptics + falsifier + novelty + replicator in parallel behind the information barrier, then the judge.',
  phases: [{ title: 'Review' }, { title: 'Judge' }],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    role: { type: 'string' },
    claim: { type: 'string' },
    round: { type: 'number' },
    verdict: { type: 'string' },
    deliverable: { type: 'string' },
    critical_errors: { type: 'array' },
  },
  required: ['role', 'claim', 'round', 'verdict', 'deliverable'],
}

const JUDGE_SCHEMA = {
  type: 'object',
  properties: { decision: { type: 'string' }, upheld: { type: 'array' }, deliverable: { type: 'string' } },
  required: ['decision', 'deliverable'],
}

// args: { slug, claim, round, artifact, lineupDir, skeptics: [{agentId, deliverable}], factIds: [...], timeBudget, checklist }
const { slug, claim, round, artifact, lineupDir, skeptics, factIds, timeBudget, checklist } = args
const base = `campaigns/${slug}`
const common =
  `Campaign ${slug}, review round ${round}, claim ${claim}. You may read ONLY: ${base}/statement.md, ` +
  `the artifact(s) named below, ledger facts ${JSON.stringify(factIds || [])} via ` +
  `\`.venv/Scripts/python.exe -m harness ledger show <id> --campaign ${slug}\`, and ${checklist || 'skills/references/referee-checklist.md'}. ` +
  `Never read plan.md, ideas.md, log.md, questions.md, survey.md or earlier reviews. Time budget: ${timeBudget || '60 min'}. ` +
  `End your report with the yaml verdict block (referee-checklist.md §7).`

await phase('Review')
const skepticJobs = (skeptics || [{ agentId: 'SK-1', deliverable: `${base}/reviews/round${round}/skeptic.SK-1.md` }]).map(
  (s) => () =>
    agent(
      `${common}\nYou are skeptic ${s.agentId}. ` +
        (lineupDir
          ? `Review EVERY item in ${lineupDir} (they may be the real proof, mutants with one planted flaw, or a control on a different statement); emit one verdict block per item with \`item: <letter>\` and \`agent_id: ${s.agentId}\`. Never diff items against each other; do not read ${base}/proofs/.`
          : `Review ${base}/${artifact}; include \`agent_id: ${s.agentId}\` in the verdict block.`) +
        `\nWrite ${s.deliverable}.`,
      { agentType: 'skeptic', label: `skeptic:${s.agentId}`, phase: 'Review', schema: VERDICT_SCHEMA },
    ),
)
const others = [
  () =>
    agent(`${common}\nYou are the falsifier. Attack ${base}/${artifact} and every lemma computationally (harness falsify). Write ${base}/reviews/round${round}/falsifier.md.`, {
      agentType: 'falsifier', label: 'falsifier', phase: 'Review', schema: VERDICT_SCHEMA,
    }),
  () =>
    agent(`${common}\nYou are the novelty checker. Follow skills/references/novelty-protocol.md, include a "## Final-statement queries" section and \`artifact_sha256\` in the verdict block. Write ${base}/reviews/round${round}/novelty.md.`, {
      agentType: 'novelty-checker', label: 'novelty', phase: 'Review', schema: VERDICT_SCHEMA,
    }),
  () =>
    agent(`${common}\nYou are the replicator. Stage A: from statement.md and the cited sources ONLY, re-derive the key numerics into ${base}/reviews/round${round}/replicate/values.json and run \`harness review commit-blind --campaign ${slug} --round ${round} --file reviews/round${round}/replicate/values.json\`. Only then (stage B) open ${base}/${artifact} and diff. Write ${base}/reviews/round${round}/replicator.md (verdict pass | fail | revise | n/a).`, {
      agentType: 'replicator', label: 'replicator', phase: 'Review', schema: VERDICT_SCHEMA,
    }),
]
const verdicts = await parallel([...skepticJobs, ...others])

await phase('Judge')
const judge = await agent(
  `Campaign ${slug}, round ${round}, claim ${claim}. Adjudicate the referee reports in ${base}/reviews/round${round}/ ` +
    `(run \`harness review score-lineup\` and \`harness review lineup unseal\` first when a lineup exists; use only admissible skeptic verdicts). ` +
    `Follow referee-checklist.md §8: write the structured yaml block (upheld / rebutted / moot / verdict) and end ${base}/reviews/round${round}/judge.md with exactly one line VERDICT: PASS|REVISE_PROOF|REVISE_PLAN|REWRITE|PIVOT. ` +
    `Record referee evidence with \`harness ledger evidence ... --round ${round}\` (skeptics with --agent-id/--reliability) and promote on PASS.`,
  { agentType: 'judge', label: 'judge', phase: 'Judge', schema: JUDGE_SCHEMA },
)
return { round, claim, verdicts, decision: judge.decision, judge: judge.deliverable }
