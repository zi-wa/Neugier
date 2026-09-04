"""SessionStart (startup|resume|compact) + UserPromptSubmit hook: inject standing instructions and campaign state.

SessionStart gets the full standing block (re-injected after context compaction so long campaigns keep their rules);
UserPromptSubmit gets a one-line state reminder only. Both carry the top open question (rule R6) so curiosity
survives compaction, and the human-escalation state (HUMAN.md / ASK-HUMAN.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import active_campaign, emit, project_root, read_input, run_harness  # noqa: E402

STANDING = """[Neugier standing instructions]
- Reason internally in English; reply to the user in Korean; papers in English.
- R1 Use the top model freely for anything research-relevant; sonnet/haiku only for mechanical plumbing.
- R2 Installs/bulky/risky files stay inside the project (.venv, bin/, .cache/). Never install globally.
- R3 Think creatively: >=5 distinct routes + 1 unconventional before committing; cite moves from skills/references/creative-moves.md; falsify ideas cheaply first.
- R4 Research framing: campaigns end with an artifact and an honest outcome class.
- R5 Anti-hallucination: no literature claim without a fetched verbatim excerpt; no arithmetic in prose (numbers come from code -> experiments/results.json); "unverified" is an acceptable answer; hedge words need citation or proof.
- R6 Curiosity over compliance: protocols are guardrails, not scripts. Start from your own questions (campaigns/<slug>/questions.md), predict before you experiment and log surprises, pick actions by information gain (`harness questions next`), use the 30% detour budget without asking. Curiosity never overrides R2/R5, the ledger, the interpretation lock or the information barrier.
- The claim ledger (campaigns/<slug>/ledger.json) is the source of truth; the paper may assert only referee-passed/formalized claims.
- Adversarial review: referees see only statement.md + the artifact, never the prover's reasoning.
- HUMAN.md is the human's file: read it at every phase start, never edit it; escalate concrete questions with `harness questions for-human` (budgeted) and keep working."""


def _human_line(cdir: Path) -> str:
    try:
        n_open = 0
        esc = cdir / "escalations.json"
        if esc.exists():
            data = json.loads(esc.read_text(encoding="utf-8"))
            n_open = sum(1 for e in data.get("escalations", []) if not e.get("answered"))
        human = cdir / "HUMAN.md"
        if human.exists():
            import time

            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(human.stat().st_mtime))
            return f"HUMAN.md updated {stamp}; {n_open} escalation(s) awaiting an answer"
        return f"{n_open} escalation(s) awaiting an answer"
    except Exception:
        return ""


def campaign_block(root: Path, brief: bool) -> str:
    slug = active_campaign(root)
    if not slug:
        return "" if brief else "[Neugier] No active campaign. Start one with /research <topic|auto> or /scout."
    cdir = root / "campaigns" / slug
    try:
        camp = json.loads((cdir / "campaign.json").read_text(encoding="utf-8"))
    except Exception:
        camp = {}
    phase = camp.get("phase", "?")
    gate_on = (cdir / ".gate").exists()
    gate_txt = "on" if gate_on else "off"
    rc, out = run_harness(root, ["campaign", "check", slug], timeout=25)
    unmet: list[str] = []
    if rc == 1:
        unmet = [ln.strip().lstrip("-").strip() for ln in out.splitlines() if ln.strip().startswith("-")]
    rcq, qline = run_harness(root, ["questions", "--campaign", slug, "next", "--brief"], timeout=15)
    qline = qline.strip().splitlines()[-1] if rcq == 0 and qline.strip() else ""
    # pull new human answers into the question ledger (cheap; no-op without HUMAN.md answers)
    run_harness(root, ["questions", "--campaign", slug, "human-answers"], timeout=15)
    human = _human_line(cdir)
    if brief:
        u = f"; {len(unmet)} exit criteria unmet" if unmet else "; exit criteria met"
        g = " (phase gate ON)" if gate_on else ""
        q = f" | {qline}" if qline else ""
        return f"[Neugier] active campaign '{slug}' phase={phase}{u}{g}. Ledger: campaigns/{slug}/ledger.json{q}"
    locked = "yes" if camp.get("statement_hash") else "no"
    lines = [
        f"[Neugier active campaign] slug={slug} phase={phase} gate={gate_txt}",
        f"targets={camp.get('active_targets') or []} outcome={camp.get('outcome_class')}",
        f"statement locked={locked}",
    ]
    if unmet:
        lines.append("Unmet exit criteria for this phase:")
        lines.extend(f"  - {u}" for u in unmet)
    if qline:
        lines.append(f"Curiosity: {qline}")
    if human:
        lines.append(f"Human: {human}")
    rc2, md = run_harness(root, ["ledger", "summary", "--campaign", slug], timeout=20)
    if rc2 == 0 and md.strip():
        lines.append("Ledger summary: " + " ".join(md.split()))
    lines.append(
        f"Files of record: campaigns/{slug}/statement.md, plan.md, ledger.json, questions.md, log.md, HUMAN.md - work from these, not from memory."
    )
    return "\n".join(lines)


def main() -> int:
    data = read_input()
    event = data.get("hook_event_name") or "SessionStart"
    root = project_root(data)
    if event == "UserPromptSubmit":
        ctx = campaign_block(root, brief=True)
    else:
        ctx = STANDING + "\n" + campaign_block(root, brief=False)
    if ctx.strip():
        emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": ctx}})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
