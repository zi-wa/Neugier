"""Tests for harness.ledger — the claim ledger schema, store, and CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.ledger.cli as ledger_cli
from harness.ledger.ledger import LedgerError, LedgerStore
from harness.ledger.schema import Evidence

REFEREE_ROLES = ("skeptic", "falsifier", "novelty", "replicator", "judge")


def _mk_campaign(tmp_path: Path) -> Path:
    d = tmp_path / "camp"
    d.mkdir()
    return d


def _write(path: Path, text: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _store(campaign_dir: Path) -> LedgerStore:
    return LedgerStore(campaign_dir / "ledger.json", campaign="camp")


def _promote_to_proof_drafted(store: LedgerStore, claim_id: str, d: Path):
    _write(d / "proofs" / f"{claim_id}.tex", "\\begin{proof} x \\end{proof}")
    store.add_evidence(claim_id, Evidence(type="proof", path=f"proofs/{claim_id}.tex", summary="draft"), d)
    return store.promote(claim_id, "proof-drafted", d)


def _referee_pass_round(store: LedgerStore, claim_id: str, d: Path, round_: int = 1) -> None:
    for role in REFEREE_ROLES:
        store.add_evidence(
            claim_id, Evidence(type="referee", role=role, verdict="pass", round=round_, summary="ok"), d
        )


# --------------------------------------------------------------- id generation --

def test_id_generation_sequential_per_kind(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    c1 = store.add(kind="theorem", statement="A statement about primes.")
    c2 = store.add(kind="theorem", statement="Another statement about primes.")
    c3 = store.add(kind="lemma", statement="A helper lemma.")
    assert c1.id == "T-001"
    assert c2.id == "T-002"
    assert c3.id == "L-001"


def test_id_generation_all_kind_prefixes(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    expected = {
        "theorem": "T-001", "lemma": "L-001", "proposition": "P-001", "conjecture": "C-001",
        "fact": "F-001", "idea": "I-001", "definition": "D-001", "bound": "B-001",
        "construction": "K-001", "target": "G-001",
    }
    for kind, expected_id in expected.items():
        claim = store.add(kind=kind, statement=f"A {kind} statement here.")
        assert claim.id == expected_id


def test_id_generation_survives_reload(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    store.add(kind="conjecture", statement="Conjecture one.")
    store2 = _store(d)  # fresh instance must reload from disk
    c = store2.add(kind="conjecture", statement="Conjecture two.")
    assert c.id == "C-002"


def test_save_and_reload_round_trip(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="Persisted theorem.")
    assert (d / "ledger.json").exists()
    store2 = _store(d)
    assert store2.get(claim.id).statement == "Persisted theorem."


# -------------------------------------------------------------- dependencies --

def test_add_rejects_unknown_dependency(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    with pytest.raises(LedgerError):
        store.add(kind="lemma", statement="depends on nothing real", depends_on=["Z-999"])


def test_would_cycle_detects_cycle_directly(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="lemma", statement="Lemma A.")
    b = store.add(kind="lemma", statement="Lemma B.", depends_on=[a.id])
    assert store._would_cycle("new-node", [b.id]) is False
    # simulate a corrupted/hypothetical graph where a already depends on b too
    store.ledger.claims[a.id].depends_on.append(b.id)
    assert store._would_cycle("new-node", [a.id]) is True


def test_add_rejects_when_would_create_cycle(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="lemma", statement="Lemma A.")
    b = store.add(kind="lemma", statement="Lemma B.", depends_on=[a.id])
    # Manually corrupt the graph into a cycle (a -> b -> a); add() must refuse
    # any new node that would extend a cyclic subgraph reachable from it.
    store.ledger.claims[a.id].depends_on.append(b.id)
    with pytest.raises(LedgerError):
        store.add(kind="lemma", statement="Lemma C.", depends_on=[a.id])


# ------------------------------------------------------------------ evidence --

def test_excerpt_requires_source_id(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="A fact from the literature.")
    with pytest.raises(LedgerError):
        store.add_evidence(claim.id, Evidence(type="excerpt", summary="no source id", excerpt="x" * 25), d)


def test_excerpt_requires_min_length(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="A fact from the literature.")
    with pytest.raises(LedgerError):
        store.add_evidence(
            claim.id,
            Evidence(type="excerpt", summary="too short", source_id="smith2020", excerpt="too short"),
            d,
        )


def test_excerpt_with_source_id_and_min_length_succeeds(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="A fact from the literature.")
    _write(d / "cache" / "smith2020.txt", "preamble " + "x" * 25 + " postamble")
    updated = store.add_evidence(
        claim.id,
        Evidence(type="excerpt", summary="fine", source_id="smith2020", excerpt="x" * 25, locator="p. 12"),
        d,
    )
    assert updated.evidence[-1].type == "excerpt"
    assert updated.evidence[-1].file_hash is None  # no path given
    assert updated.evidence[-1].verified is True
    assert updated.evidence[-1].source_sha256
    assert len(updated.evidence[-1].excerpt_hash) == 12


def test_referee_evidence_requires_role_and_verdict(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="Some theorem.")
    with pytest.raises(LedgerError):
        store.add_evidence(claim.id, Evidence(type="referee", summary="missing role/verdict"), d)
    with pytest.raises(LedgerError):
        store.add_evidence(claim.id, Evidence(type="referee", role="skeptic", summary="missing verdict"), d)


def test_evidence_path_must_exist_under_campaign_dir(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="Needs a computation.")
    with pytest.raises(LedgerError):
        store.add_evidence(claim.id, Evidence(type="computation", path="nope.json", summary="missing"), d)


def test_evidence_path_cannot_escape_campaign_dir(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="Needs a computation.")
    outside = _write(tmp_path / "outside.json", "{}")
    with pytest.raises(LedgerError):
        store.add_evidence(
            claim.id, Evidence(type="computation", path="../outside.json", summary="escape"), d
        )
    assert outside.exists()  # sanity: the file really is outside campaign_dir


def test_evidence_file_hash_recorded(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="Needs a computation.")
    _write(d / "experiments" / "results.json", '{"n": 1}')
    updated = store.add_evidence(
        claim.id, Evidence(type="computation", path="experiments/results.json", summary="ran it"), d
    )
    assert updated.evidence[-1].file_hash is not None
    assert len(updated.evidence[-1].file_hash) == 64


# ----------------------------------------------------------------- promotion --

def test_promote_to_conjectured_always_allowed(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="conjecture", statement="P is true.")
    updated = store.promote(claim.id, "conjectured", d)
    assert updated.status == "conjectured"


def test_promote_numerically_supported_requires_computation_or_falsification(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="conjecture", statement="Q holds for all n < 10^6.")
    with pytest.raises(LedgerError):
        store.promote(claim.id, "numerically-supported", d)

    _write(d / "experiments" / "q.json", '{"checked": 1000000}')
    store.add_evidence(claim.id, Evidence(type="computation", path="experiments/q.json", summary="brute force"), d)
    updated = store.promote(claim.id, "numerically-supported", d)
    assert updated.status == "numerically-supported"


def test_promote_numerically_supported_via_falsification_evidence(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="bound", statement="A bound conjecture.")
    _write(d / "experiments" / "search.json", "{}")
    store.add_evidence(
        claim.id, Evidence(type="falsification", path="experiments/search.json", summary="tried to break it, failed"), d
    )
    updated = store.promote(claim.id, "numerically-supported", d)
    assert updated.status == "numerically-supported"


def test_promote_proof_drafted_requires_proof_evidence(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="Standalone theorem.")
    with pytest.raises(LedgerError):
        store.promote(claim.id, "proof-drafted", d)


def test_promote_proof_drafted_requires_proven_dependencies(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    lemma = store.add(kind="lemma", statement="Helper lemma.")
    thm = store.add(kind="theorem", statement="Main theorem.", depends_on=[lemma.id])

    _write(d / "proofs" / "thm.tex", "\\begin{proof} ... \\end{proof}")
    store.add_evidence(thm.id, Evidence(type="proof", path="proofs/thm.tex", summary="draft"), d)

    # lemma is still just an idea -> unmet dependency requirement
    with pytest.raises(LedgerError):
        store.promote(thm.id, "proof-drafted", d)

    _promote_to_proof_drafted(store, lemma.id, d)
    updated = store.promote(thm.id, "proof-drafted", d)
    assert updated.status == "proof-drafted"


def test_promote_proof_drafted_assumption_tag_exempts_dependency(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    rh = store.add(kind="conjecture", statement="Riemann Hypothesis.")
    thm = store.add(
        kind="theorem",
        statement="Conditional result assuming RH.",
        depends_on=[rh.id],
        tags=[f"assumes:{rh.id}"],
    )
    _write(d / "proofs" / "thm.tex", "\\begin{proof} conditional \\end{proof}")
    store.add_evidence(thm.id, Evidence(type="proof", path="proofs/thm.tex", summary="draft"), d)
    updated = store.promote(thm.id, "proof-drafted", d)
    assert updated.status == "proof-drafted"


def test_promote_referee_passed_requires_full_round_and_judge(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    thm = store.add(kind="theorem", statement="Theorem needing review.")
    _promote_to_proof_drafted(store, thm.id, d)

    store.add_evidence(thm.id, Evidence(type="referee", role="skeptic", verdict="pass", round=1, summary="ok"), d)
    store.add_evidence(thm.id, Evidence(type="referee", role="falsifier", verdict="pass", round=1, summary="ok"), d)
    with pytest.raises(LedgerError):
        store.promote(thm.id, "referee-passed", d)

    store.add_evidence(thm.id, Evidence(type="referee", role="novelty", verdict="pass", round=1, summary="ok"), d)
    store.add_evidence(thm.id, Evidence(type="referee", role="replicator", verdict="n/a", round=1, summary="ok"), d)
    store.add_evidence(thm.id, Evidence(type="referee", role="judge", verdict="pass", round=1, summary="ok"), d)

    updated = store.promote(thm.id, "referee-passed", d)
    assert updated.status == "referee-passed"


def test_promote_referee_passed_requires_current_status_proof_drafted(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    thm = store.add(kind="theorem", statement="Theorem still an idea.")
    _referee_pass_round(store, thm.id, d)
    with pytest.raises(LedgerError):
        store.promote(thm.id, "referee-passed", d)


def test_promote_referee_passed_requires_same_round_for_all_roles(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    thm = store.add(kind="theorem", statement="Theorem.")
    _promote_to_proof_drafted(store, thm.id, d)
    store.add_evidence(thm.id, Evidence(type="referee", role="skeptic", verdict="pass", round=1, summary="ok"), d)
    store.add_evidence(thm.id, Evidence(type="referee", role="falsifier", verdict="pass", round=1, summary="ok"), d)
    store.add_evidence(thm.id, Evidence(type="referee", role="novelty", verdict="pass", round=2, summary="ok"), d)
    store.add_evidence(thm.id, Evidence(type="referee", role="judge", verdict="pass", round=2, summary="ok"), d)
    with pytest.raises(LedgerError):
        store.promote(thm.id, "referee-passed", d)


def test_promote_referee_passed_requires_proven_dependencies(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    lemma = store.add(kind="lemma", statement="Helper lemma.")
    thm = store.add(kind="theorem", statement="Theorem.", depends_on=[lemma.id])
    _promote_to_proof_drafted(store, lemma.id, d)  # only proof-drafted, not referee-passed
    _promote_to_proof_drafted(store, thm.id, d)
    _referee_pass_round(store, thm.id, d)
    with pytest.raises(LedgerError):
        store.promote(thm.id, "referee-passed", d)


def test_promote_referee_passed_blocked_while_stale(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    lemma = store.add(kind="lemma", statement="Some lemma.")
    thm = store.add(kind="theorem", statement="Theorem.", depends_on=[lemma.id])

    _promote_to_proof_drafted(store, lemma.id, d)
    _referee_pass_round(store, lemma.id, d)
    store.promote(lemma.id, "referee-passed", d)

    _promote_to_proof_drafted(store, thm.id, d)
    _referee_pass_round(store, thm.id, d)

    # editing the lemma re-opens the theorem, even though the lemma itself
    # stays referee-passed (so the dependency-status check alone would pass)
    store.update_statement(lemma.id, "Some lemma, restated more precisely.")
    assert store.get(thm.id).stale is True
    assert store.get(lemma.id).status == "referee-passed"

    with pytest.raises(LedgerError):
        store.promote(thm.id, "referee-passed", d)


def test_promote_formalized_requires_referee_passed_and_formalization_evidence(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    thm = store.add(kind="theorem", statement="Theorem to formalize.")
    _promote_to_proof_drafted(store, thm.id, d)
    _referee_pass_round(store, thm.id, d)
    store.promote(thm.id, "referee-passed", d)

    with pytest.raises(LedgerError):
        store.promote(thm.id, "formalized", d)

    _write(d / "proofs" / "thm.lean", "theorem thm : True := trivial")
    store.add_evidence(thm.id, Evidence(type="formalization", path="proofs/thm.lean", summary="Lean proof"), d)
    updated = store.promote(thm.id, "formalized", d)
    assert updated.status == "formalized"


def test_promote_formalized_requires_current_status_referee_passed(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    thm = store.add(kind="theorem", statement="Theorem.")
    _promote_to_proof_drafted(store, thm.id, d)
    _write(d / "proofs" / "thm.lean", "theorem thm : True := trivial")
    store.add_evidence(thm.id, Evidence(type="formalization", path="proofs/thm.lean", summary="Lean proof"), d)
    with pytest.raises(LedgerError):
        store.promote(thm.id, "formalized", d)


def test_promote_refuted_requires_falsification_with_path(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="conjecture", statement="False conjecture.")
    with pytest.raises(LedgerError):
        store.promote(claim.id, "refuted", d)

    _write(d / "experiments" / "counterexample.json", '{"n": 42}')
    store.add_evidence(
        claim.id, Evidence(type="falsification", path="experiments/counterexample.json", summary="counterexample found"), d
    )
    updated = store.promote(claim.id, "refuted", d)
    assert updated.status == "refuted"


def test_promote_refuted_via_referee_fail(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="Broken theorem.")
    store.add_evidence(claim.id, Evidence(type="referee", role="falsifier", verdict="fail", round=1, summary="found a bug"), d)
    updated = store.promote(claim.id, "refuted", d)
    assert updated.status == "refuted"


def test_promote_known_in_literature_requires_excerpt(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="Already proved by Smith.")
    with pytest.raises(LedgerError):
        store.promote(claim.id, "known-in-literature", d)

    _write(d / "cache" / "smith2020.txt", "Theorem 1. " + "x" * 30 + " holds.")
    store.add_evidence(
        claim.id, Evidence(type="excerpt", source_id="smith2020", excerpt="x" * 30, summary="found it"), d
    )
    updated = store.promote(claim.id, "known-in-literature", d)
    assert updated.status == "known-in-literature"


def test_promote_dead_requires_note(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="idea", statement="Dead end idea.")
    with pytest.raises(LedgerError):
        store.promote(claim.id, "dead", d)

    store.add_evidence(claim.id, Evidence(type="note", summary="abandoned: route trivializes to a known result"), d)
    updated = store.promote(claim.id, "dead", d)
    assert updated.status == "dead"


def test_demotion_always_allowed_and_recorded(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="theorem", statement="Theorem.")
    _promote_to_proof_drafted(store, claim.id, d)
    _referee_pass_round(store, claim.id, d)
    store.promote(claim.id, "referee-passed", d)

    updated = store.promote(claim.id, "proof-drafted", d)
    assert updated.status == "proof-drafted"
    assert any(h["op"] == "promote" and h["detail"] == "demotion" for h in updated.history)


# ------------------------------------------------------------------ staleness --

def test_update_statement_propagates_staleness_transitively(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="lemma", statement="Base lemma.")
    b = store.add(kind="lemma", statement="Mid lemma.", depends_on=[a.id])
    c = store.add(kind="theorem", statement="Top theorem.", depends_on=[b.id])

    store.update_statement(a.id, "Base lemma, restated.")

    assert store.get(b.id).stale is True
    assert store.get(c.id).stale is True
    assert store.get(a.id).stale is False  # only dependents are marked, not the edited claim itself


def test_update_statement_demotes_referee_passed_dependents(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="lemma", statement="Base lemma.")
    b = store.add(kind="theorem", statement="Depends on base.", depends_on=[a.id])

    _promote_to_proof_drafted(store, a.id, d)
    _referee_pass_round(store, a.id, d)
    store.promote(a.id, "referee-passed", d)

    _promote_to_proof_drafted(store, b.id, d)
    _referee_pass_round(store, b.id, d)
    store.promote(b.id, "referee-passed", d)

    store.update_statement(a.id, "Base lemma, restated again.")

    updated_b = store.get(b.id)
    assert updated_b.status == "proof-drafted"
    assert updated_b.stale is True


def test_update_statement_no_change_does_not_mark_stale(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="lemma", statement="Base   lemma.")
    b = store.add(kind="lemma", statement="Depends.", depends_on=[a.id])
    # whitespace-only change -> same normalized hash -> no staleness
    store.update_statement(a.id, "Base lemma.")
    assert store.get(b.id).stale is False


def test_refutation_cascades_demotion_to_conjectured(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="lemma", statement="Key lemma.")
    b = store.add(kind="theorem", statement="Depends on key lemma.", depends_on=[a.id])

    _promote_to_proof_drafted(store, a.id, d)
    _promote_to_proof_drafted(store, b.id, d)

    _write(d / "experiments" / "counter.json", "{}")
    store.add_evidence(a.id, Evidence(type="falsification", path="experiments/counter.json", summary="counterexample"), d)
    store.promote(a.id, "refuted", d)

    updated_b = store.get(b.id)
    assert updated_b.status == "conjectured"
    assert updated_b.stale is True
    assert store.get(a.id).status == "refuted"


# ------------------------------------------------------------------------ audit --

def test_audit_log_grows_with_each_mutation(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    audit_path = d / "ledger.audit.jsonl"
    assert not audit_path.exists()

    claim = store.add(kind="idea", statement="An idea.")
    with open(audit_path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["op"] == "add"
    assert entry["claim_id"] == claim.id

    store.promote(claim.id, "conjectured", d)
    with open(audit_path, "r", encoding="utf-8") as fh:
        assert len(fh.readlines()) == 2

    store.add_evidence(claim.id, Evidence(type="note", summary="a note"), d)
    with open(audit_path, "r", encoding="utf-8") as fh:
        assert len(fh.readlines()) == 3


# --------------------------------------------------------------------- dag ---

def test_dependents_transitive_and_direct(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="lemma", statement="A.")
    b = store.add(kind="lemma", statement="B.", depends_on=[a.id])
    c = store.add(kind="theorem", statement="C.", depends_on=[b.id])

    assert store.dependents(a.id, transitive=False) == [b.id]
    assert store.dependents(a.id, transitive=True) == sorted([b.id, c.id])


def test_topological_order_respects_dependencies(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="lemma", statement="A.")
    b = store.add(kind="lemma", statement="B.", depends_on=[a.id])
    order = store.topological_order()
    assert order.index(a.id) < order.index(b.id)


# --------------------------------------------------------------- reports -----

def test_assertable_only_referee_passed_and_formalized(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="theorem", statement="Theorem A.")
    _promote_to_proof_drafted(store, a.id, d)
    assert store.assertable() == []

    _referee_pass_round(store, a.id, d)
    store.promote(a.id, "referee-passed", d)
    assert [c.id for c in store.assertable()] == [a.id]


def test_assertable_excludes_stale_claims(tmp_path):
    # A claim can never be both status=referee-passed/formalized and stale=True
    # through the public API (update_statement demotes such dependents in the
    # same step it marks them stale) -- so this exercises assertable()'s own
    # "not stale" filter directly, the same way a defensive check is tested.
    d = _mk_campaign(tmp_path)
    store = _store(d)
    a = store.add(kind="theorem", statement="Theorem A.")
    _promote_to_proof_drafted(store, a.id, d)
    _referee_pass_round(store, a.id, d)
    store.promote(a.id, "referee-passed", d)
    assert [c.id for c in store.assertable()] == [a.id]

    store.ledger.claims[a.id].stale = True
    assert store.assertable() == []


def test_update_statement_demotes_referee_passed_dependent_out_of_assertable(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    base = store.add(kind="lemma", statement="Base fact.")
    a = store.add(kind="theorem", statement="Depends on base.", depends_on=[base.id])

    _promote_to_proof_drafted(store, base.id, d)
    _referee_pass_round(store, base.id, d)
    store.promote(base.id, "referee-passed", d)

    _promote_to_proof_drafted(store, a.id, d)
    _referee_pass_round(store, a.id, d)
    store.promote(a.id, "referee-passed", d)
    assert {c.id for c in store.assertable()} == {base.id, a.id}

    # editing the base fact demotes+stales its dependent, dropping it out of
    # what the paper may assert, while the (unedited) base claim stays assertable
    store.update_statement(base.id, "Base fact, sharpened.")
    assert store.get(a.id).status == "proof-drafted"
    assert store.get(a.id).stale is True
    assert {c.id for c in store.assertable()} == {base.id}


def test_check_integrity_detects_tampering(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="Fact.")
    f = _write(d / "experiments" / "data.json", '{"n": 1}')
    store.add_evidence(claim.id, Evidence(type="computation", path="experiments/data.json", summary="ran"), d)

    assert store.check_integrity(d) == []

    with open(f, "w", encoding="utf-8") as fh:
        fh.write('{"n": 999}')

    problems = store.check_integrity(d)
    assert len(problems) == 1
    assert "hash mismatch" in problems[0]


def test_check_integrity_detects_missing_file(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    claim = store.add(kind="fact", statement="Fact.")
    f = _write(d / "experiments" / "data.json", "{}")
    store.add_evidence(claim.id, Evidence(type="computation", path="experiments/data.json", summary="ran"), d)
    f.unlink()
    problems = store.check_integrity(d)
    assert len(problems) == 1
    assert "no longer exists" in problems[0]


def test_to_markdown_truncates_long_statements(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    store.add(kind="idea", statement="x" * 200)
    md = store.to_markdown()
    assert "..." in md


def test_summary_counts_by_status_and_kind(tmp_path):
    d = _mk_campaign(tmp_path)
    store = _store(d)
    store.add(kind="lemma", statement="A.")
    store.add(kind="theorem", statement="B.")
    s = store.summary()
    assert s["total"] == 2
    assert s["by_kind"]["lemma"] == 1
    assert s["by_kind"]["theorem"] == 1
    assert s["by_status"]["idea"] == 2


# -------------------------------------------------------------------- CLI ----

def test_ledger_cli_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_cli, "CAMPAIGNS", tmp_path)
    assert ledger_cli.main(["--campaign", "demo", "init"]) == 0
    assert ledger_cli.main(["--campaign", "demo", "add", "--kind", "lemma", "--statement", "A lemma."]) == 0
    assert ledger_cli.main(["--campaign", "demo", "summary"]) == 0
    assert ledger_cli.main(["--campaign", "demo", "md"]) == 0
    assert ledger_cli.main(["--campaign", "demo", "show"]) == 0
    assert ledger_cli.main(["--campaign", "demo", "promote", "L-001", "not-a-status"]) == 1
