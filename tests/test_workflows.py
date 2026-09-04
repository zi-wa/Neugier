"""Round-2 Step 30: saved Workflow scripts are well-formed (static checks; no JS runtime)."""
from __future__ import annotations

import re
from pathlib import Path

import harness

WF = Path(harness.ROOT) / ".claude" / "workflows"


def _scripts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WF.glob("*.js"))}


def test_scripts_exist_and_start_with_meta():
    scripts = _scripts()
    assert {"neugier-review.js", "neugier-prove.js"} <= set(scripts)
    for name, text in scripts.items():
        assert re.search(r"^export const meta = \{", text, re.MULTILINE), name
        assert "name: 'neugier-" in text and "phases:" in text


def test_no_nondeterministic_calls():
    for name, text in _scripts().items():
        assert "Date.now" not in text and "Math.random" not in text and "new Date()" not in text, name


def test_phase_titles_match_phase_calls():
    for name, text in _scripts().items():
        titles = re.findall(r"\{ title: '([^']+)' \}", text)
        calls = re.findall(r"await phase\('([^']+)'\)", text)
        assert titles and set(calls) <= set(titles), (name, titles, calls)


def test_agent_types_exist_in_agents_dir():
    agents = {p.stem for p in (Path(harness.ROOT) / "agents").glob("*.md")}
    for name, text in _scripts().items():
        for t in set(re.findall(r"agentType: '([a-z\-]+)'", text)):
            assert t in agents, (name, t)
