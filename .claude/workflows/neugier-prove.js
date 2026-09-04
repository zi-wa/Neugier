// Neugier sketch-first prove phase as a Workflow script (Round-2 Y6 + Y12; opt-in via `/prove --workflow`).
//
// Sketch → Falsify → Rate → Prove. Persona provers write sketches; the falsifier attacks every sketch lemma; judge-class
// raters compare sketches pairwise (three axes) and write match files; the skill then runs `harness prove elo` to select
// which sketches get the full-proof budget; selected provers write full proofs (optionally in isolated git worktrees —
// pass args.isolation = 'worktree'; the skill collects results with `harness prove collect --commits ...`).
export const meta = {
  name: 'neugier-prove',
  description: 'Sketch-first proving: persona sketches, cheap falsification of sketch lemmas, pairwise rating, full proofs for the Elo-selected sketches.',
  phases: [{ title: 'Sketch' }, { title: 'Falsify' }, { title: 'Rate' }, { title: 'Prove' }],
}

const SKETCH_SCHEMA = { type: 'object', properties: { persona: { type: 'string' }, path: { type: 'string' }, lemmas: { type: 'array' } }, required: ['persona', 'path'] }
const MATCH_SCHEMA = { type: 'object', properties: { a: { type: 'string' }, b: { type: 'string' }, winner: { type: 'string' }, axis: { type: 'string' }, file: { type: 'string' } }, required: ['a', 'b', 'winner', 'file'] }
const PROOF_SCHEMA = { type: 'object', properties: { persona: { type: 'string' }, path: { type: 'string' }, commit: { type: 'string' }, files: { type: 'array' } }, required: ['persona', 'path'] }

// args: { slug, claim, personas: [{name, route}], selected?: [names], isolation?: 'worktree', debateTop?: 3 }
const { slug, claim, personas, selected, isolation, debateTop } = args
const base = `campaigns/${slug}`
const tdir = `${base}/reviews/tournament-${claim}`

let result = {}
if (!selected) {
  await phase('Sketch')
  const sketches = await parallel(
    personas.map((p) => () =>
      agent(
        `Campaign ${slug}, claim ${claim}. You are the ${p.name} prover in SKETCH mode on route ${p.route} (see ${base}/ideas.md). ` +
          `Write ${base}/proofs/${claim}.sketch.${p.name}.md with frontmatter (kind: sketch, claim, persona, route, key_idea, lemmas[{label, statement, needs, cheapest_falsification}]) and the lemma DAG. No ledger writes, no full proof.`,
        { agentType: 'prover', label: `sketch:${p.name}`, phase: 'Sketch', schema: SKETCH_SCHEMA },
      ),
    ),
  )

  await phase('Falsify')
  await agent(
    `Campaign ${slug}, claim ${claim}. For every sketch lemma in ${base}/proofs/${claim}.sketch.*.md run a cheap falsification (<= 5 min each) and write reports to ${tdir}/falsify/<persona>-<label>.json (harness falsify run --out ...).`,
    { agentType: 'falsifier', label: 'falsify-sketches', phase: 'Falsify' },
  )

  await phase('Rate')
  const names = sketches.map((s) => s.persona)
  const pairs = []
  for (let i = 0; i < names.length; i++) for (let j = i + 1; j < names.length; j++) pairs.push([names[i], names[j]])
  const axes = ['plausibility', 'clarity', 'novelty']
  const matches = await parallel(
    pairs.flatMap(([a, b]) =>
      axes.map((axis) => () =>
        agent(
          `Campaign ${slug}, claim ${claim}. RATER mode: compare sketches ${base}/proofs/${claim}.sketch.${a}.md (a) and ${base}/proofs/${claim}.sketch.${b}.md (b) on the axis "${axis}" only. ` +
            `Write ${tdir}/match-${a}-${b}-${axis}-pairwise.json with {a, b, winner: a|b|draw, axis, tier: pairwise, rationale, steal_from_loser, rater}.`,
          { agentType: 'judge', label: `rate:${a}-${b}:${axis}`, phase: 'Rate', schema: MATCH_SCHEMA },
        ),
      ),
    ),
  )
  result = { sketches, matches, next: `harness prove elo --campaign ${slug} --claim ${claim} (then re-run this workflow with args.selected = tournament.json.selected)` }
} else {
  await phase('Prove')
  const proofs = await parallel(
    selected.map((name) => () =>
      agent(
        `Campaign ${slug}, claim ${claim}. You are the ${name} prover. Expand your selected sketch ${base}/proofs/${claim}.sketch.${name}.md into a complete proof artifact ${base}/proofs/${claim}.${name}.md per skills/references/proof-standards.md; read the cross-pollination notes in ${tdir}/tournament.json; run the falsifier on every lemma; ` +
          (isolation === 'worktree'
            ? `you are in an isolated worktree: do NOT write ledger.json; record intended ledger operations in ${base}/proofs/${claim}.${name}.ledger-ops.jsonl and commit your files; return the commit sha.`
            : `attach proof evidence and promote to proof-drafted (harness ledger evidence / promote).`),
        { agentType: 'prover', label: `prove:${name}`, phase: 'Prove', schema: PROOF_SCHEMA, ...(isolation === 'worktree' ? { isolation: 'worktree' } : {}) },
      ),
    ),
  )
  result = { proofs, next: isolation === 'worktree' ? `harness prove collect --campaign ${slug} --claim ${claim} --commits ${proofs.map((p) => p.commit).filter(Boolean).join(',')}` : 'harness campaign check' }
}
return result
