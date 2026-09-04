"""The claim ledger store: load/save/mutate ``campaigns/<slug>/ledger.json``.

Every mutating method (:meth:`LedgerStore.add`, :meth:`~LedgerStore.add_evidence`,
:meth:`~LedgerStore.promote`, :meth:`~LedgerStore.update_statement`) validates its
rule set, mutates the in-memory ledger, appends a history entry to the affected
claim(s) *and* an append-only line to ``ledger.audit.jsonl`` (next to the ledger
file), then persists the whole ledger atomically. This keeps the ledger durable
after every single CLI invocation without every caller having to remember to
call :meth:`~LedgerStore.save` themselves.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Sequence

from harness.ledger.schema import Claim, Evidence, Kind, Ledger, Status, utc_now_iso


class LedgerError(Exception):
    """Raised for any invalid ledger operation (bad id, cycle, unmet promotion rule, ...)."""


# id prefix by claim kind (spec: zero-padded 3 digits, monotonically increasing per prefix)
KIND_PREFIX: dict[str, str] = {
    "theorem": "T",
    "lemma": "L",
    "proposition": "P",
    "conjecture": "C",
    "fact": "F",
    "idea": "I",
    "definition": "D",
    "bound": "B",
    "construction": "K",
    "target": "G",
    "question": "Q",
}

# Linear pipeline order, used for ">=" comparisons and to tell a "demotion"
# apart from a promotion. "refuted", "known-in-literature" and "dead" are
# side branches outside this order and are never rank-compared.
PIPELINE_ORDER: list[str] = [
    "idea",
    "conjectured",
    "numerically-supported",
    "proof-drafted",
    "referee-passed",
    "formalized",
]

# depends_on status gates (a dependency listed under the tag "assumes:<id>"
# is exempt from these — it is an explicit, flagged assumption rather than
# something the promotion is claiming to have established).
DEPENDS_OK_FOR_PROOF_DRAFTED = {"proof-drafted", "referee-passed", "formalized", "known-in-literature"}
DEPENDS_OK_FOR_REFEREE_PASSED = {"referee-passed", "formalized", "known-in-literature"}

REFEREE_ROUND_ROLES = ("skeptic", "falsifier", "novelty", "judge")


def pipeline_rank(status: str) -> int | None:
    """Index of ``status`` in :data:`PIPELINE_ORDER`, or ``None`` for a side branch."""
    try:
        return PIPELINE_ORDER.index(status)
    except ValueError:
        return None


def normalize_statement(statement: str) -> str:
    """Whitespace-normalize a statement before hashing (collapse runs of whitespace)."""
    return " ".join(statement.split())


def statement_hash(statement: str) -> str:
    return hashlib.sha256(normalize_statement(statement).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, data: dict) -> None:
    """Write ``data`` as deterministic JSON to ``path`` atomically (temp file + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def _resolve_under(campaign_dir: Path, rel_path: str) -> Path:
    campaign_dir = Path(campaign_dir).resolve()
    full = (campaign_dir / rel_path).resolve()
    try:
        full.relative_to(campaign_dir)
    except ValueError as exc:
        raise LedgerError(f"evidence path {rel_path!r} is not inside campaign dir {campaign_dir}") from exc
    if not full.exists():
        raise LedgerError(f"evidence path {rel_path!r} does not exist under campaign dir {campaign_dir}")
    return full


class LedgerStore:
    """Load/save/mutate the claim ledger for one campaign."""

    AUDIT_FILENAME = "ledger.audit.jsonl"

    def __init__(self, path: Path, campaign: str | None = None) -> None:
        self.path = Path(path)
        self.audit_path = self.path.with_name(self.AUDIT_FILENAME)
        if self.path.exists():
            self.ledger = self._read()
        else:
            self.ledger = Ledger(campaign=campaign or self.path.parent.name, claims={})

    # ------------------------------------------------------------ persistence --

    def _read(self) -> Ledger:
        with open(self.path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return Ledger.model_validate(data)

    def load(self) -> Ledger:
        """Reload the ledger from disk, discarding any in-memory changes."""
        self.ledger = self._read()
        return self.ledger

    def save(self) -> None:
        """Write the ledger to disk atomically (temp file + ``os.replace``)."""
        atomic_write_json(self.path, self.ledger.model_dump(mode="json"))

    # ------------------------------------------------------------------ audit --

    def _audit(self, entry: dict) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False))
            fh.write("\n")

    def _record(self, claim: Claim, op: str, from_: str | None, to: str | None, detail: str) -> None:
        ts = utc_now_iso()
        entry = {"ts": ts, "op": op, "claim_id": claim.id, "from": from_, "to": to, "detail": detail}
        claim.history.append(entry)
        claim.updated = ts
        self._audit(entry)

    # ------------------------------------------------------------------ lookup --

    def get(self, claim_id: str) -> Claim:
        try:
            return self.ledger.claims[claim_id]
        except KeyError as exc:
            raise LedgerError(f"unknown claim id: {claim_id!r}") from exc

    # --------------------------------------------------------------------- add --

    def _next_id(self, kind: str) -> str:
        prefix = KIND_PREFIX[kind]
        pattern = re.compile(rf"^{prefix}-(\d{{3,}})$")
        best = 0
        for cid in self.ledger.claims:
            m = pattern.match(cid)
            if m:
                best = max(best, int(m.group(1)))
        return f"{prefix}-{best + 1:03d}"

    def _would_cycle(self, new_id: str, depends_on: list[str]) -> bool:
        """DFS over the dependency graph as it would look with ``new_id -> depends_on``
        added, detecting a cycle reachable from ``new_id``."""
        graph = {cid: list(c.depends_on) for cid, c in self.ledger.claims.items()}
        graph[new_id] = list(depends_on)
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for nxt in graph.get(node, []):
                if dfs(nxt):
                    return True
            visiting.discard(node)
            visited.add(node)
            return False

        return dfs(new_id)

    def add(
        self,
        kind: Kind,
        statement: str,
        depends_on: Sequence[str] = (),
        tags: Sequence[str] = (),
        status: Status = "idea",
        notes: str = "",
    ) -> Claim:
        if kind not in KIND_PREFIX:
            raise LedgerError(f"unknown claim kind: {kind!r}")
        depends_on = list(depends_on)
        for dep in depends_on:
            if dep not in self.ledger.claims:
                raise LedgerError(f"depends_on references unknown claim id: {dep!r}")

        new_id = self._next_id(kind)
        if self._would_cycle(new_id, depends_on):
            raise LedgerError(f"adding {new_id} with depends_on={depends_on} would create a dependency cycle")

        now = utc_now_iso()
        claim = Claim(
            id=new_id,
            kind=kind,
            statement=statement,
            status=status,
            depends_on=depends_on,
            tags=list(tags),
            notes=notes,
            hash=statement_hash(statement),
            created=now,
            updated=now,
        )
        self.ledger.claims[new_id] = claim
        self._record(claim, "add", None, status, f"created {kind} claim")
        self.save()
        return claim

    # ---------------------------------------------------------------- evidence --

    def add_evidence(self, claim_id: str, evidence: Evidence, campaign_dir: Path) -> Claim:
        claim = self.get(claim_id)
        campaign_dir = Path(campaign_dir)

        if evidence.type == "excerpt":
            if not evidence.source_id:
                raise LedgerError("evidence type 'excerpt' requires source_id")
            if not evidence.excerpt or len(evidence.excerpt) < 20:
                raise LedgerError(
                    "evidence type 'excerpt' requires a verbatim excerpt of at least 20 characters "
                    "(anti-hallucination rule R5: no literature claim without a fetched excerpt)"
                )
        if evidence.type == "referee":
            if not evidence.role:
                raise LedgerError("evidence type 'referee' requires role")
            if not evidence.verdict:
                raise LedgerError("evidence type 'referee' requires verdict")

        if evidence.path is not None:
            full = _resolve_under(campaign_dir, evidence.path)
            evidence.file_hash = file_hash(full)

        claim.evidence.append(evidence)
        self._record(
            claim, "add_evidence", None, evidence.type,
            evidence.summary or f"{evidence.type} evidence added",
        )
        self.save()
        return claim

    # ---------------------------------------------------------------- promote --

    def _has_evidence(
        self,
        claim: Claim,
        types: set[str],
        *,
        require_path: bool = False,
        campaign_dir: Path | None = None,
    ) -> bool:
        for ev in claim.evidence:
            if ev.type not in types:
                continue
            if require_path:
                if not ev.path:
                    continue
                if campaign_dir is not None and not (Path(campaign_dir) / ev.path).exists():
                    continue
            return True
        return False

    def _unmet_dependency_statuses(self, claim: Claim, allowed: set[str]) -> list[str]:
        assumed = {t.split(":", 1)[1] for t in claim.tags if t.startswith("assumes:")}
        problems: list[str] = []
        for dep_id in claim.depends_on:
            if dep_id in assumed:
                continue
            dep = self.ledger.claims.get(dep_id)
            got = dep.status if dep is not None else "missing"
            if dep is None or dep.status not in allowed:
                problems.append(f"{dep_id} (status={got}, needs one of {sorted(allowed)})")
        return problems

    def _referee_round_complete(self, claim: Claim) -> tuple[int | None, list[str]]:
        """Return ``(round, [])`` for the highest round where skeptic/falsifier/novelty
        all passed plus a judge pass; else ``(None, missing-for-latest-round)``."""
        rounds: dict[int, dict[str, str]] = {}
        for ev in claim.evidence:
            if ev.type == "referee" and ev.round is not None and ev.role:
                rounds.setdefault(ev.round, {})[ev.role] = ev.verdict or ""

        required = set(REFEREE_ROUND_ROLES)
        complete = [r for r, roles in rounds.items() if all(roles.get(role) == "pass" for role in required)]
        if complete:
            return max(complete), []
        if not rounds:
            return None, ["no referee evidence recorded"]
        latest = max(rounds)
        missing = [f"{role} pass in round {latest}" for role in required if rounds[latest].get(role) != "pass"]
        return None, missing

    def _promotion_requirements(self, claim: Claim, new_status: str, campaign_dir: Path) -> list[str]:
        missing: list[str] = []

        if new_status in ("idea", "conjectured"):
            return missing

        if new_status == "numerically-supported":
            if not self._has_evidence(claim, {"computation", "falsification"}, require_path=True, campaign_dir=campaign_dir):
                missing.append("requires >=1 evidence of type 'computation' or 'falsification' with an existing path")
            return missing

        if new_status == "proof-drafted":
            if not self._has_evidence(claim, {"proof"}, require_path=True, campaign_dir=campaign_dir):
                missing.append("requires >=1 evidence of type 'proof' with an existing path")
            dep_problems = self._unmet_dependency_statuses(claim, DEPENDS_OK_FOR_PROOF_DRAFTED)
            if dep_problems:
                missing.append(
                    "every depends_on claim must be proof-drafted/referee-passed/formalized/known-in-literature "
                    "(or listed as an assumption via tag 'assumes:<id>'); unmet: " + ", ".join(dep_problems)
                )
            return missing

        if new_status == "referee-passed":
            if claim.status != "proof-drafted":
                missing.append(f"current status must be 'proof-drafted' to submit for referee (is {claim.status!r})")
            round_ok, round_missing = self._referee_round_complete(claim)
            if round_ok is None:
                missing.append(
                    "requires skeptic/falsifier/novelty verdict='pass' evidence from the same round, "
                    "plus a judge pass in that round; missing: " + ", ".join(round_missing)
                )
            dep_problems = self._unmet_dependency_statuses(claim, DEPENDS_OK_FOR_REFEREE_PASSED)
            if dep_problems:
                missing.append(
                    "every depends_on claim must be referee-passed/formalized/known-in-literature "
                    "(or listed as an assumption via tag 'assumes:<id>'); unmet: " + ", ".join(dep_problems)
                )
            if claim.stale:
                missing.append("claim is stale (an upstream dependency changed since this proof/review); re-verify first")
            return missing

        if new_status == "formalized":
            if claim.status != "referee-passed":
                missing.append(f"current status must be 'referee-passed' (is {claim.status!r})")
            if not self._has_evidence(claim, {"formalization"}, require_path=True, campaign_dir=campaign_dir):
                missing.append("requires evidence of type 'formalization' with an existing path")
            return missing

        if new_status == "refuted":
            has_falsification = self._has_evidence(claim, {"falsification"}, require_path=True, campaign_dir=campaign_dir)
            has_referee_fail = any(
                ev.type == "referee" and ev.role == "falsifier" and ev.verdict == "fail" for ev in claim.evidence
            )
            if not (has_falsification or has_referee_fail):
                missing.append(
                    "requires evidence of type 'falsification' with an existing path (the counterexample), "
                    "or a referee evidence with role='falsifier' and verdict='fail'"
                )
            return missing

        if new_status == "known-in-literature":
            if not self._has_evidence(claim, {"excerpt"}):
                missing.append("requires >=1 evidence of type 'excerpt' (with source_id + excerpt)")
            return missing

        if new_status == "dead":
            if not self._has_evidence(claim, {"note"}):
                missing.append("requires a 'note' evidence explaining why the claim is dead")
            return missing

        missing.append(f"unknown target status: {new_status!r}")
        return missing

    def _cascade_refutation(self, claim_id: str) -> None:
        """After a claim is refuted, demote every transitive dependent whose status
        is proof-drafted or higher back to 'conjectured' and mark it stale."""
        threshold = pipeline_rank("proof-drafted")
        for dep_id in self.dependents(claim_id, transitive=True):
            dep = self.ledger.claims.get(dep_id)
            if dep is None:
                continue
            rank = pipeline_rank(dep.status)
            if rank is not None and rank >= threshold:
                old = dep.status
                dep.status = "conjectured"
                dep.stale = True
                self._record(dep, "cascade-refute", old, "conjectured", f"upstream claim {claim_id} was refuted")

    def promote(self, claim_id: str, new_status: Status, campaign_dir: Path) -> Claim:
        claim = self.get(claim_id)
        campaign_dir = Path(campaign_dir)
        old_status = claim.status

        old_rank = pipeline_rank(old_status)
        new_rank = pipeline_rank(new_status)
        is_demotion = old_rank is not None and new_rank is not None and new_rank < old_rank

        if not is_demotion:
            missing = self._promotion_requirements(claim, new_status, campaign_dir)
            if missing:
                raise LedgerError(f"cannot promote {claim_id} to {new_status!r}: " + "; ".join(missing))

        claim.status = new_status
        self._record(claim, "promote", old_status, new_status, "demotion" if is_demotion else "promotion")

        if new_status == "refuted":
            self._cascade_refutation(claim_id)

        self.save()
        return claim

    # ---------------------------------------------------------- update statement --

    def update_statement(self, claim_id: str, new_statement: str) -> Claim:
        claim = self.get(claim_id)
        new_hash = statement_hash(new_statement)
        changed = new_hash != claim.hash

        old_statement = claim.statement
        claim.statement = new_statement
        claim.hash = new_hash
        self._record(
            claim, "update_statement", old_statement[:100], new_statement[:100],
            "statement changed" if changed else "cosmetic edit only (hash unchanged)",
        )

        if changed:
            for dep_id in self.dependents(claim_id, transitive=True):
                dep = self.ledger.claims.get(dep_id)
                if dep is None:
                    continue
                dep.stale = True
                if dep.status in ("referee-passed", "formalized"):
                    old = dep.status
                    dep.status = "proof-drafted"
                    self._record(dep, "cascade-stale", old, "proof-drafted", f"upstream claim {claim_id} statement changed")
                else:
                    self._record(dep, "mark-stale", dep.status, dep.status, f"upstream claim {claim_id} statement changed")

        self.save()
        return claim

    # -------------------------------------------------------------------- dag --

    def dependents(self, claim_id: str, transitive: bool = True) -> list[str]:
        reverse: dict[str, list[str]] = {}
        for cid, c in self.ledger.claims.items():
            for dep in c.depends_on:
                reverse.setdefault(dep, []).append(cid)

        direct = reverse.get(claim_id, [])
        if not transitive:
            return list(direct)

        seen: set[str] = set()
        stack = list(direct)
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(reverse.get(cur, []))
        return sorted(seen)

    def dag(self) -> dict:
        return {
            cid: {
                "kind": c.kind,
                "status": c.status,
                "depends_on": list(c.depends_on),
                "dependents": self.dependents(cid, transitive=False),
            }
            for cid, c in self.ledger.claims.items()
        }

    def topological_order(self) -> list[str]:
        """Dependencies before dependents, in a stable (id-sorted) topological order."""
        indegree = {cid: 0 for cid in self.ledger.claims}
        forward: dict[str, list[str]] = {cid: [] for cid in self.ledger.claims}
        for cid, c in self.ledger.claims.items():
            for dep in c.depends_on:
                if dep in forward:
                    forward[dep].append(cid)
                    indegree[cid] += 1

        ready = sorted(cid for cid, deg in indegree.items() if deg == 0)
        order: list[str] = []
        while ready:
            ready.sort()
            node = ready.pop(0)
            order.append(node)
            for nxt in forward[node]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
        if len(order) != len(self.ledger.claims):
            raise LedgerError("ledger dependency graph contains a cycle")
        return order

    # ---------------------------------------------------------------- reports --

    def assertable(self) -> list[Claim]:
        """Claims the paper may state as theorems: referee-passed/formalized and not stale."""
        return [c for c in self.ledger.claims.values() if c.status in ("referee-passed", "formalized") and not c.stale]

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for c in self.ledger.claims.values():
            by_status[c.status] = by_status.get(c.status, 0) + 1
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        return {"total": len(self.ledger.claims), "by_status": by_status, "by_kind": by_kind}

    def to_markdown(self) -> str:
        lines = ["| id | kind | status | stale | #evidence | statement |", "|---|---|---|---|---|---|"]
        for cid in sorted(self.ledger.claims):
            c = self.ledger.claims[cid]
            stmt = c.statement.replace("\n", " ").replace("|", "\\|")
            if len(stmt) > 100:
                stmt = stmt[:97] + "..."
            lines.append(f"| {c.id} | {c.kind} | {c.status} | {c.stale} | {len(c.evidence)} | {stmt} |")
        return "\n".join(lines) + "\n"

    def check_integrity(self, campaign_dir: Path) -> list[str]:
        """Recompute evidence file hashes and report any that no longer match
        (missing file, or tampered content) — the 'check' CLI command."""
        campaign_dir = Path(campaign_dir)
        problems: list[str] = []
        for cid, c in self.ledger.claims.items():
            for i, ev in enumerate(c.evidence):
                if not ev.path or not ev.file_hash:
                    continue
                full = campaign_dir / ev.path
                if not full.exists():
                    problems.append(f"{cid} evidence[{i}] ({ev.type}): path {ev.path!r} no longer exists")
                    continue
                current = file_hash(full)
                if current != ev.file_hash:
                    problems.append(
                        f"{cid} evidence[{i}] ({ev.type}): file {ev.path!r} hash mismatch "
                        f"(recorded {ev.file_hash[:12]}..., now {current[:12]}...) — possible tampering"
                    )
        return problems
