"""The claim ledger store: load/save/mutate ``campaigns/<slug>/ledger.json``.

Every mutating method (:meth:`LedgerStore.add`, :meth:`~LedgerStore.add_evidence`,
:meth:`~LedgerStore.promote`, :meth:`~LedgerStore.update_statement`,
:meth:`~LedgerStore.reverify`, :meth:`~LedgerStore.set_stakes`) validates its
rule set, mutates the in-memory ledger, appends a history entry to the affected
claim(s) *and* an append-only line to ``ledger.audit.jsonl`` (next to the ledger
file), then persists the whole ledger atomically. This keeps the ledger durable
after every single CLI invocation without every caller having to remember to
call :meth:`~LedgerStore.save` themselves.

Promotion is evidence-gated (rule R5d): a status is reached only through the
evidence its rule demands, never through a stated confidence. Since Round 2:

* ``add`` may create claims only at ``idea``/``conjectured`` (or at
  ``known-in-literature`` when a verified excerpt is supplied in the same call);
  every other status is reached via ``promote``.
* An ``excerpt`` evidence is verified against the cached source text
  (:mod:`harness.lit.cache`); ``known-in-literature`` requires ``verified is True``.
* A referee round needs skeptic, falsifier, novelty, replicator and judge; the
  replicator may answer ``n/a`` when there is nothing to replicate (the review
  regime, Round-2 Step 18, can demand more skeptic passes and forbid ``n/a``).
* ``stale`` is cleared only by :meth:`~LedgerStore.reverify`, which requires a
  complete referee round recorded *after* the staleness event.
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

REFEREE_ROUND_ROLES = ("skeptic", "falsifier", "novelty", "replicator", "judge")
# Statuses a claim may be *created* at. Everything else is reached via promote().
ADD_ALLOWED_STATUSES = {"idea", "conjectured"}
REPAIR_OPS = ("add-hypothesis", "weaken-bound", "absorb-and-regenerate")
STALE_OPS = {"mark-stale", "cascade-stale", "cascade-refute"}


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


def round_float(x: float, digits: int = 4) -> float:
    return float(f"{x:.{digits}f}")


def load_budgets(campaign_dir: Path | None) -> dict:
    """``budgets`` from ``campaigns/<slug>/campaign.json`` (pure json; ``{}`` if absent)."""
    if campaign_dir is None:
        return {}
    path = Path(campaign_dir) / "campaign.json"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    budgets = data.get("budgets") if isinstance(data, dict) else None
    return budgets if isinstance(budgets, dict) else {}


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

    def _record(
        self,
        claim: Claim,
        op: str,
        from_: str | None,
        to: str | None,
        detail: str,
        extra: dict | None = None,
    ) -> dict:
        ts = utc_now_iso()
        entry = {"ts": ts, "op": op, "claim_id": claim.id, "from": from_, "to": to, "detail": detail}
        if extra:
            for k, v in extra.items():
                entry.setdefault(k, v)
        claim.history.append(entry)
        claim.updated = ts
        self._audit(entry)
        return entry

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
        *,
        evidence: Evidence | None = None,
        campaign_dir: Path | None = None,
        repaired_from: str | None = None,
        repair_op: str | None = None,
        stakes: int | None = None,
        require_verified_excerpt: bool = True,
    ) -> Claim:
        """Create a claim.

        ``status`` may be ``idea`` or ``conjectured``. ``known-in-literature`` is
        accepted only together with an excerpt ``evidence`` (and ``campaign_dir``):
        the claim is created, the excerpt verified and attached, and the claim
        promoted in one call, so the promotion rule still applies. Any other
        status is rejected — reach it via :meth:`promote`.
        """
        if kind not in KIND_PREFIX:
            raise LedgerError(f"unknown claim kind: {kind!r}")
        target_status: str | None = None
        if status not in ADD_ALLOWED_STATUSES:
            if status == "known-in-literature" and evidence is not None and evidence.type == "excerpt":
                if campaign_dir is None:
                    raise LedgerError("adding a known-in-literature claim requires campaign_dir for excerpt verification")
                target_status = "known-in-literature"
                status = "idea"
            else:
                raise LedgerError(
                    f"claims may only be created with status {sorted(ADD_ALLOWED_STATUSES)} "
                    f"(got {status!r}); promote with evidence instead "
                    "(known-in-literature is allowed only with an excerpt evidence in the same call)"
                )
        depends_on = list(depends_on)
        for dep in depends_on:
            if dep not in self.ledger.claims:
                raise LedgerError(f"depends_on references unknown claim id: {dep!r}")

        tags = list(tags)
        if repaired_from is not None:
            parent = self.ledger.claims.get(repaired_from)
            if parent is None:
                raise LedgerError(f"repaired_from references unknown claim id: {repaired_from!r}")
            if parent.status != "refuted":
                raise LedgerError(f"repaired_from {repaired_from} must be 'refuted' (is {parent.status!r})")
            if repair_op not in REPAIR_OPS:
                raise LedgerError(f"repair_op must be one of {REPAIR_OPS} when repaired_from is given (got {repair_op!r})")
            tag = f"repaired:{repaired_from}"
            if tag not in tags:
                tags.append(tag)
        elif repair_op is not None:
            raise LedgerError("repair_op requires repaired_from")
        if stakes is not None and stakes not in (0, 1, 2):
            raise LedgerError(f"stakes must be 0, 1 or 2 (got {stakes!r})")

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
            tags=tags,
            notes=notes,
            hash=statement_hash(statement),
            created=now,
            updated=now,
            stakes=stakes if stakes is not None else 1,
            repaired_from=repaired_from,
            repair_op=repair_op,  # type: ignore[arg-type]
        )
        self.ledger.claims[new_id] = claim
        detail = f"created {kind} claim"
        if repaired_from:
            detail += f" (repair of {repaired_from} via {repair_op})"
        self._record(claim, "add", None, status, detail)
        self.save()
        if target_status is not None:
            assert evidence is not None and campaign_dir is not None
            self.add_evidence(new_id, evidence, campaign_dir, require_verified_excerpt=require_verified_excerpt)
            self.promote(new_id, target_status, campaign_dir)  # type: ignore[arg-type]
        return self.get(new_id)

    # ---------------------------------------------------------------- evidence --

    def add_evidence(
        self,
        claim_id: str,
        evidence: Evidence,
        campaign_dir: Path,
        *,
        require_verified_excerpt: bool = True,
    ) -> Claim:
        """Attach evidence after validating the rules for its type.

        Excerpts are verified against the cached source text every time (a
        caller-supplied ``verified`` is ignored). With ``require_verified_excerpt``
        (the default) an excerpt that is not found — or whose source is not cached
        — is rejected; pass ``False`` (CLI ``--unverified-ok``) to record it as
        unverified, in which case it never counts toward ``known-in-literature``.
        """
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
            from harness.lit.cache import verify_excerpt  # local import: lit is heavier than the ledger

            check = verify_excerpt(evidence.excerpt, evidence.source_id, campaign_dir)
            evidence.verified = check.verified
            evidence.source_path = check.source_path
            evidence.source_sha256 = check.source_sha256
            evidence.excerpt_hash = check.excerpt_hash
            if require_verified_excerpt and check.verified is not True:
                raise LedgerError(
                    f"excerpt for source {evidence.source_id!r} is not verified ({check.method}: {check.detail}). "
                    "Fetch the source into the campaign cache first (`harness lit fetch <source-id>`) so the "
                    "excerpt can be matched against it, or pass --unverified-ok to record it as unverified "
                    "(unverified excerpts never count toward known-in-literature)"
                )
        if evidence.type == "referee":
            if not evidence.role:
                raise LedgerError("evidence type 'referee' requires role")
            if not evidence.verdict:
                raise LedgerError("evidence type 'referee' requires verdict")
            if evidence.verdict == "n/a" and evidence.role != "replicator":
                raise LedgerError("verdict 'n/a' is allowed only for role 'replicator' (nothing to replicate)")
            if evidence.reliability is not None and not 0.0 <= evidence.reliability <= 1.0:
                raise LedgerError("reliability must be within [0, 1]")
            if evidence.role == "skeptic" and evidence.round is not None:
                self._check_lineup_evidence(evidence, campaign_dir)

        if evidence.path is not None:
            full = _resolve_under(campaign_dir, evidence.path)
            evidence.file_hash = file_hash(full)

        claim.evidence.append(evidence)
        extra = {}
        if evidence.type == "excerpt":
            extra = {"verified": evidence.verified, "excerpt_hash": evidence.excerpt_hash}
        if evidence.type == "referee":
            extra = {"role": evidence.role, "verdict": evidence.verdict, "round": evidence.round,
                     "agent_id": evidence.agent_id, "reliability": evidence.reliability}
        self._record(
            claim, "add_evidence", None, evidence.type,
            evidence.summary or f"{evidence.type} evidence added", extra,
        )
        self.save()
        return claim

    @staticmethod
    def _check_lineup_evidence(evidence: Evidence, campaign_dir: Path) -> None:
        """Under a decoy-lineup round a skeptic verdict must carry its lineup score (Round-2 X1)."""
        manifest_path = Path(campaign_dir) / "reviews" / f"round{evidence.round}" / "barrier.json"
        if not manifest_path.exists():
            return
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError):
            return
        if not manifest.get("lineup"):
            return
        if not evidence.agent_id:
            raise LedgerError("skeptic evidence under a lineup round needs --agent-id (the fresh context that was scored)")
        if evidence.reliability is None:
            raise LedgerError("skeptic evidence under a lineup round needs --reliability from `harness review score-lineup`")
        min_recall = float(load_budgets(campaign_dir).get("lineup_min_recall", 0.8))
        expected = evidence.reliability >= min_recall
        if evidence.admissible is None:
            evidence.admissible = expected
        elif evidence.admissible != expected:
            raise LedgerError(
                f"admissible={evidence.admissible} contradicts reliability {evidence.reliability} vs lineup_min_recall {min_recall}"
            )
        score_path = Path(campaign_dir) / "reviews" / f"round{evidence.round}" / f"lineup_score.{evidence.agent_id}.json"
        if score_path.exists():
            try:
                with open(score_path, "r", encoding="utf-8") as fh:
                    recorded = json.load(fh)
                if abs(float(recorded.get("reliability", -1)) - float(evidence.reliability)) > 1e-6:
                    raise LedgerError(
                        f"reliability {evidence.reliability} does not match {score_path.name} ({recorded.get('reliability')})"
                    )
            except (OSError, ValueError):
                pass

    # --------------------------------------------------------------- credences --

    def record_credence(
        self,
        claim_id: str,
        *,
        role: str,
        why: str,
        p_true: float | None = None,
        p_budget: float | None = None,
        p_pass: float | None = None,
        round: int | None = None,
        panel: dict[str, float] | None = None,
    ) -> dict:
        """Append an immutable pre-registered credence to the claim's history (Round-2 X2)."""
        if not role.strip():
            raise LedgerError("credence needs the role that makes the prediction")
        if not why.strip():
            raise LedgerError("credence needs a one-line rationale (--why)")
        vals = {"p_true": p_true, "p_budget": p_budget, "p_pass": p_pass}
        if all(v is None for v in vals.values()):
            raise LedgerError("give at least one of p_true, p_budget, p_pass")
        for k, v in vals.items():
            if v is not None and not 0.0 <= float(v) <= 1.0:
                raise LedgerError(f"{k} must be within [0, 1] (got {v})")
        if p_pass is not None and round is None:
            raise LedgerError("p_pass needs --round (the review round it predicts)")
        spread = None
        if panel:
            for k, v in panel.items():
                if not 0.0 <= float(v) <= 1.0:
                    raise LedgerError(f"panel credence {k}={v} must be within [0, 1]")
            spread = round_float(max(panel.values()) - min(panel.values()))
        claim = self.get(claim_id)
        extra = {"role": role.strip(), "p_true": p_true, "p_budget": p_budget, "p_pass": p_pass, "round": round,
                 "panel": dict(panel) if panel else None, "spread": spread}
        entry = self._record(claim, "credence", None, None, why.strip(), extra)
        self.save()
        return entry

    def latest_credence(self, claim_id: str, field: str = "p_true") -> dict | None:
        from harness.ledger.calibration import latest_credence

        return latest_credence(self.get(claim_id), field)

    def uncredenced(self) -> list[str]:
        """Targets/conjectures/bounds/constructions at >= conjectured without a p_true credence."""
        from harness.ledger.calibration import latest_credence

        rank = pipeline_rank("conjectured")
        out = []
        for c in self.ledger.claims.values():
            if c.kind in ("target", "conjecture", "bound", "construction") and (pipeline_rank(c.status) or -1) >= rank \
                    and latest_credence(c, "p_true") is None:
                out.append(c.id)
        return sorted(out)

    # ------------------------------------------------------------------ stakes --

    def set_stakes(self, claim_id: str, stakes: int) -> Claim:
        """Set the stakes tier (0 routine, 1 standard, 2 extraordinary) — drives the review regime."""
        if stakes not in (0, 1, 2):
            raise LedgerError(f"stakes must be 0, 1 or 2 (got {stakes!r})")
        claim = self.get(claim_id)
        old = claim.stakes
        claim.stakes = stakes  # type: ignore[assignment]
        self._record(claim, "stakes", str(old), str(stakes), "stakes changed")
        self.save()
        return claim

    def attest(self, claim_id: str, human: str, note: str = "") -> Claim:
        """Record a human sign-off (only humans call this; agents are denied by hook)."""
        if not human.strip():
            raise LedgerError("attestation requires the human's name")
        claim = self.get(claim_id)
        claim.attestation = {"by": human.strip(), "ts": utc_now_iso(), "note": note}
        self._record(claim, "attest", None, human.strip(), note or "human attestation recorded")
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

    @staticmethod
    def _round_status(
        evidences: list[Evidence],
        *,
        skeptic_passes: int,
        replicator_required: bool,
    ) -> list[str]:
        """Missing items for one referee round (empty list = round complete)."""
        missing: list[str] = []
        skeptics = [ev for ev in evidences if ev.role == "skeptic" and ev.admissible is not False]
        passes = [ev for ev in skeptics if ev.verdict == "pass"]
        dissent = [ev for ev in skeptics if ev.verdict in ("fail", "revise")]
        # distinct fresh contexts: named agent_ids count separately; anonymous passes count as one
        distinct = {ev.agent_id for ev in passes if ev.agent_id}
        if any(not ev.agent_id for ev in passes):
            distinct.add("#anonymous")
        if dissent:
            missing.append(f"skeptic unanimity broken ({len(dissent)} admissible skeptic verdict(s) not 'pass')")
        if len(distinct) < skeptic_passes:
            missing.append(
                f"{skeptic_passes} admissible skeptic pass(es) from distinct agent_ids (have {len(distinct)}; "
                "the regime for this claim's stakes decides k — see `harness review regime`)"
            )
        for role in ("falsifier", "novelty", "judge"):
            if not any(ev.role == role and ev.verdict == "pass" for ev in evidences):
                missing.append(f"{role} pass")
        rep = [ev for ev in evidences if ev.role == "replicator"]
        if replicator_required and not rep:
            missing.append("replicator verdict (pass, or n/a when there is nothing to replicate)")
        elif rep and not any(ev.verdict in ("pass", "n/a") for ev in rep):
            missing.append("replicator pass (or n/a)")
        return missing

    def _referee_round_complete(
        self,
        claim: Claim,
        *,
        skeptic_passes: int = 1,
        replicator_required: bool = False,
        evidences: list[Evidence] | None = None,
    ) -> tuple[int | None, list[str]]:
        """Return ``(round, [])`` for the highest complete referee round, else
        ``(None, missing-for-latest-round)``.

        A round is complete when every admissible skeptic verdict is ``pass`` and at
        least ``skeptic_passes`` of them come from distinct ``agent_id``s (unanimity,
        cf. Huang & Yang arXiv 2507.15855 and AIM arXiv 2505.22451), falsifier, novelty
        and judge passed, and the replicator passed (or answered ``n/a`` when not required).
        """
        rounds: dict[int, list[Evidence]] = {}
        for ev in (claim.evidence if evidences is None else evidences):
            if ev.type == "referee" and ev.round is not None and ev.role:
                rounds.setdefault(ev.round, []).append(ev)
        if not rounds:
            return None, ["no referee evidence recorded"]
        complete = [
            r for r, evs in rounds.items()
            if not self._round_status(evs, skeptic_passes=skeptic_passes, replicator_required=replicator_required)
        ]
        if complete:
            return max(complete), []
        latest = max(rounds)
        missing = self._round_status(rounds[latest], skeptic_passes=skeptic_passes, replicator_required=replicator_required)
        return None, [f"{m} in round {latest}" for m in missing]

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
            from harness.review.regime import regime_for  # stakes-scaled scrutiny (Round-2 X4)

            regime = regime_for(claim.stakes, load_budgets(campaign_dir))
            round_ok, round_missing = self._referee_round_complete(
                claim, skeptic_passes=regime.skeptic_passes, replicator_required=regime.replicator_required,
            )
            if round_ok is None:
                missing.append(
                    f"requires a complete referee round under {regime.describe()} "
                    "(all in the same round, plus a judge pass); missing: " + ", ".join(round_missing)
                )
            else:
                from harness.review.barrier import check_round, manifest_path  # lazy: review must not import ledger at import time

                if manifest_path(campaign_dir, round_ok).exists():
                    for problem in check_round(campaign_dir, round_ok, self):
                        if not problem.startswith("ledger integrity"):
                            missing.append(f"review round {round_ok}: {problem}")
            dep_problems = self._unmet_dependency_statuses(claim, DEPENDS_OK_FOR_REFEREE_PASSED)
            if dep_problems:
                missing.append(
                    "every depends_on claim must be referee-passed/formalized/known-in-literature "
                    "(or listed as an assumption via tag 'assumes:<id>'); unmet: " + ", ".join(dep_problems)
                )
            if claim.stale:
                missing.append(
                    "claim is stale (an upstream dependency changed since this proof/review); "
                    "run `ledger reverify` after a fresh complete referee round"
                )
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
            if not any(ev.type == "excerpt" and ev.verified is True for ev in claim.evidence):
                unverified = sum(1 for ev in claim.evidence if ev.type == "excerpt")
                missing.append(
                    "requires >=1 excerpt evidence verified against the cached source text"
                    + (f" ({unverified} unverified excerpt(s) do not count)" if unverified else "")
                )
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

    # ---------------------------------------------------------------- reverify --

    def _last_stale_ts(self, claim: Claim) -> str | None:
        stamps = [h.get("ts", "") for h in claim.history if h.get("op") in STALE_OPS]
        return max(stamps) if stamps else None

    def reverify(self, claim_id: str) -> Claim:
        """Clear ``stale`` — only when a complete referee round was recorded after the
        staleness event (all its referee evidence rows added later than that event)."""
        claim = self.get(claim_id)
        if not claim.stale:
            raise LedgerError(f"{claim_id} is not stale")
        since = self._last_stale_ts(claim) or ""
        fresh = [ev for ev in claim.evidence if ev.type == "referee" and ev.added > since]
        round_ok, missing = self._referee_round_complete(claim, evidences=fresh)
        if round_ok is None:
            raise LedgerError(
                f"cannot reverify {claim_id}: no complete referee round recorded after the staleness event "
                f"({since or 'unknown time'}); missing: " + ", ".join(missing)
            )
        claim.stale = False
        self._record(claim, "reverify", "stale", "fresh", f"re-verified by referee round {round_ok}")
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
        from harness.ledger.calibration import latest_credence

        by_status: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        stale = 0
        credences: dict[str, float] = {}
        for c in self.ledger.claims.values():
            by_status[c.status] = by_status.get(c.status, 0) + 1
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
            stale += int(c.stale)
            cred = latest_credence(c, "p_true")
            if cred is not None:
                credences[c.id] = cred["p_true"]
        return {"total": len(self.ledger.claims), "by_status": by_status, "by_kind": by_kind, "stale": stale,
                "credences": credences, "uncredenced": self.uncredenced()}

    def to_markdown(self) -> str:
        from harness.ledger.calibration import latest_credence

        lines = ["| id | kind | status | stakes | p_true | stale | #evidence | statement |", "|---|---|---|---|---|---|---|---|"]
        for cid in sorted(self.ledger.claims):
            c = self.ledger.claims[cid]
            stmt = c.statement.replace("\n", " ").replace("|", "\\|")
            if len(stmt) > 100:
                stmt = stmt[:97] + "..."
            cred = latest_credence(c, "p_true")
            p = f"{cred['p_true']:.2f}" if cred else "-"
            lines.append(f"| {c.id} | {c.kind} | {c.status} | {c.stakes} | {p} | {c.stale} | {len(c.evidence)} | {stmt} |")
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
