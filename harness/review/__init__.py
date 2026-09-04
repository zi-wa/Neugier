"""Adversarial-review tooling: verdict parsers, review regimes, barrier manifests, lineups.

Modules in this package import only the standard library, pydantic and pyyaml —
never :mod:`harness.campaign` at module level — so the ledger can call them
without import cycles (``campaign`` imports ``ledger`` imports ``review``).
"""
