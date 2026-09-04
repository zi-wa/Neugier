"""Stakes-scaled review regime (Round 2, X4 — the extraordinary-claims protocol).

A claim's ``stakes`` tier decides how much scrutiny a ``referee-passed`` verdict
needs. The tiers follow the community norms of the Erdős-problems wiki
(``teorth/erdosproblems``: 🟢 full / 🟡 partial / 🔴 incorrect / ⚪ unverified,
and the reminder that "absence of past progress may reflect obscurity rather
than difficulty") and the verifier practice of Huang & Yang (arXiv 2507.15855:
accept only after the verifier passes every time).

* tier 0 — routine lemma: one skeptic pass, no decoy lineup, replicator optional.
* tier 1 — standard target: ``budgets.skeptic_passes`` skeptic passes from distinct
  fresh contexts, a decoy lineup with ``budgets.decoys_per_round`` decoys plus a
  clean control, replicator required, one-hop citation walk.
* tier 2 — would resolve a listed open problem or beat a tracked best-known
  value: at least three skeptic passes, lineup, replicator, two-hop citation walk,
  a post-proof exact-statement novelty re-check, and the paper marks the theorem
  "not yet human-verified" until a human attests it.
"""
from __future__ import annotations

from pydantic import BaseModel


class Regime(BaseModel):
    stakes: int = 1
    skeptic_passes: int = 2
    decoys: int = 2
    control: bool = True
    replicator_required: bool = True
    novelty_hops: int = 1
    final_statement_recheck: bool = False
    human_attest: bool = False

    def describe(self) -> str:
        return (
            f"tier {self.stakes}: {self.skeptic_passes} skeptic pass(es), {self.decoys} decoy(s)"
            f"{' + control' if self.control and self.decoys else ''}, replicator "
            f"{'required' if self.replicator_required else 'optional'}, novelty walk {self.novelty_hops} hop(s)"
            f"{', final-statement re-check' if self.final_statement_recheck else ''}"
            f"{', human attestation before the paper asserts it' if self.human_attest else ''}"
        )


def regime_for(stakes: int, budgets: dict | None = None) -> Regime:
    """The review regime for a stakes tier under the campaign budgets."""
    b = budgets or {}
    k = int(b.get("skeptic_passes", 2))
    decoys = int(b.get("decoys_per_round", 2))
    control = bool(b.get("lineup_control", True))
    if stakes <= 0:
        return Regime(stakes=0, skeptic_passes=1, decoys=0, control=False, replicator_required=False, novelty_hops=1)
    if stakes == 1:
        return Regime(stakes=1, skeptic_passes=max(1, k), decoys=max(0, decoys), control=control and decoys > 0,
                      replicator_required=True, novelty_hops=1)
    return Regime(stakes=2, skeptic_passes=max(3, k), decoys=max(2, decoys), control=True, replicator_required=True,
                  novelty_hops=2, final_statement_recheck=True, human_attest=True)
