"""SubagentStop hook: a referee or judge may not stop without its deliverable (Round-1 Step 5 / A11).

While a review round is open, a subagent whose ``agent_type`` is a barrier role must have written its
report (the manifest's ``deliverable``, or any ``reviews/roundN/<role>*.md``) ending in a valid verdict
block; the judge's ``judge.md`` must end with a ``VERDICT: …`` line. Otherwise exit 2 with a
``[Neugier subagent gate k/2]`` message; after ``MAX_SUBAGENT_BLOCKS`` blocks the gate releases and
leaves a note in ``reviews/roundN/hook_errors.log`` so ``harness review check`` surfaces it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    active_campaign, agent_role, campaign_dir_of, claude_agent_id, find_open_barrier, judge_verdict_min,
    project_root, read_input, resolve_role_key, utf8_stdio, verdict_block_looks_valid_min, verdict_block_min,
)

MAX_SUBAGENT_BLOCKS = 2
GATED_ROLES = ("skeptic", "falsifier", "novelty", "replicator", "judge")


def _reports(round_dir: Path, role: str) -> list[Path]:
    return sorted(p for p in round_dir.glob(f"{role}*.md") if p.name == f"{role}.md" or p.name.startswith(f"{role}."))


def _deliverable_ok(cdir: Path, round_dir: Path, manifest: dict, role: str, role_key: str) -> tuple[bool, str]:
    role_entry = manifest.get("roles", {}).get(role_key, {})
    candidates: list[Path] = []
    deliverable = role_entry.get("deliverable")
    if deliverable and (cdir / deliverable).exists():
        candidates.append(cdir / deliverable)
    candidates += [p for p in _reports(round_dir, role) if p not in candidates]
    if not candidates:
        expected = deliverable or f"reviews/{round_dir.name}/{role}.md"
        return False, f"no report found; write {expected}"
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if role == "judge":
            if judge_verdict_min(text):
                return True, ""
            continue
        block = verdict_block_min(text)
        if verdict_block_looks_valid_min(block, role):
            return True, ""
    if role == "judge":
        return False, "judge.md must end with exactly one line `VERDICT: PASS|REVISE_PROOF|REVISE_PLAN|REWRITE|PIVOT`"
    return False, ("the report must end with the referee-checklist §7 yaml block (role, claim, round, verdict pass|fail|revise"
                   + ("|n/a" if role == "replicator" else "") + ", critical_errors, justification_gaps, checked)")


def main() -> int:
    utf8_stdio()
    data = read_input()
    role = agent_role(data)
    if role not in GATED_ROLES:
        return 0
    root = project_root(data)
    slug = active_campaign(root)
    if not slug:
        return 0
    found = find_open_barrier(root, slug)
    if found is None or found == "ambiguous":
        return 0
    round_n, manifest, round_dir = found
    cdir = campaign_dir_of(root, slug)
    agent = claude_agent_id(data)
    role_key = resolve_role_key(round_dir, manifest, role, agent) or role
    ok, why = _deliverable_ok(cdir, round_dir, manifest, role, role_key)
    if ok:
        return 0
    counter = round_dir / f".stop_attempts_{role_key.replace(':', '_')}"
    try:
        n = int(counter.read_text(encoding="utf-8").strip() or 0)
    except Exception:
        n = 0
    n += 1
    try:
        counter.write_text(str(n), encoding="utf-8")
    except Exception:
        pass
    if n > MAX_SUBAGENT_BLOCKS:
        try:
            with open(round_dir / "hook_errors.log", "a", encoding="utf-8") as fh:
                fh.write(f"subagent gate released {role_key} after {n - 1} blocks without a valid deliverable: {why}\n")
        except Exception:
            pass
        return 0
    sys.stderr.write(
        f"[Neugier subagent gate {n}/{MAX_SUBAGENT_BLOCKS}] {role_key} cannot stop yet: {why}. "
        f"Finish the review of round {round_n} and write the deliverable, then stop.\n"
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
