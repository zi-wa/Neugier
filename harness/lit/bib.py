"""Bibliography resolution and verification.

:func:`resolve` takes a loose query (arXiv id, DOI, or title) and tries to
match it against arXiv, then OpenAlex, then zbMATH, producing a
:class:`~harness.lit.models.BibEntry`. :func:`verify` re-checks an existing
entry's match quality. :func:`load_bib`/:func:`save_bib` round-trip a
``.bib`` file via bibtexparser, and :func:`check_bib` re-resolves every entry
in a file to flag ones that no longer (or never did) check out.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter

from harness.lit import arxiv, openalex, zbmath
from harness.lit.models import BibEntry, Paper

_ARXIV_ID_RE = re.compile(
    r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z\-\.]+/\d{7}(v\d+)?)$", re.IGNORECASE
)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

_STOPWORDS = {
    "a", "an", "the", "of", "on", "in", "for", "and", "to", "with", "is",
    "are", "at", "by", "from", "via", "as", "into",
}


def _ascii_only(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in norm if not unicodedata.combining(c))
    return stripped.encode("ascii", "ignore").decode("ascii")


def _normalize_title(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def _surnames(author_field: str) -> set[str]:
    out: set[str] = set()
    if not author_field:
        return out
    for name in re.split(r"\s+and\s+", author_field):
        name = name.strip()
        if not name:
            continue
        if "," in name:
            surname = name.split(",", 1)[0].strip()
        else:
            parts = name.split()
            surname = parts[-1] if parts else name
        surname = re.sub(r"[^a-z]", "", _ascii_only(surname).lower())
        if surname:
            out.add(surname)
    return out


def _best_title_match(query_title: str, candidates: list[Paper]) -> tuple[Paper, float] | None:
    scored = [(p, _title_similarity(query_title, p.title)) for p in candidates if p.title]
    if not scored:
        return None
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[0]


def _chain_search(title: str) -> tuple[Paper, str, float] | None:
    """Try arXiv, then OpenAlex, then zbMATH title search; first hit wins."""
    searches = (
        ("arxiv", lambda: arxiv.search(title, max_results=5)),
        ("openalex", lambda: openalex.search_works(title, per_page=5)),
        ("zbmath", lambda: zbmath.search(title, results_per_page=5)),
    )
    for resolver_name, search_fn in searches:
        best = _best_title_match(title, search_fn())
        if best is not None:
            paper, score = best
            return paper, resolver_name, score
    return None


def _make_key(paper: Paper) -> str:
    lastname = "Unknown"
    if paper.authors:
        full = paper.authors[0]
        if "," in full:
            lastname = full.split(",", 1)[0].strip()
        else:
            parts = full.split()
            lastname = parts[-1] if parts else full
    lastname = re.sub(r"[^A-Za-z]", "", _ascii_only(lastname)) or "Unknown"

    year = str(paper.year) if paper.year else "nd"

    title_words = re.findall(r"[A-Za-z]+", _ascii_only(paper.title))
    short_word = next(
        (w for w in title_words if w.lower() not in _STOPWORDS and len(w) > 2), None
    )
    if short_word is None and title_words:
        short_word = title_words[0]
    short_word = short_word.capitalize() if short_word else ""

    return f"{lastname}{year}{short_word}"


def _paper_to_bibentry(paper: Paper, resolver: str, score: float) -> BibEntry:
    fields: dict = {
        "title": paper.title,
        "author": " and ".join(paper.authors),
    }
    if paper.year:
        fields["year"] = str(paper.year)
    if paper.doi:
        fields["doi"] = paper.doi
    if paper.arxiv_id:
        fields["eprint"] = paper.arxiv_id
        fields["archivePrefix"] = "arXiv"
    if paper.url:
        fields["url"] = paper.url

    return BibEntry(
        key=_make_key(paper),
        entry_type="article",
        fields=fields,
        resolved=score >= 0.85,
        resolver=resolver,
        match_score=score,
    )


def resolve(query: str) -> BibEntry | None:
    """Resolve a loose query (arXiv id, DOI, or title) to a BibEntry.

    Tries arXiv, then OpenAlex, then zbMATH. Returns None if nothing matches.
    """
    q = query.strip()
    if not q:
        return None
    bare = q.removeprefix("arXiv:").removeprefix("arxiv:")

    if _ARXIV_ID_RE.match(bare):
        paper = arxiv.get(bare)
        if paper is not None:
            return _paper_to_bibentry(paper, "arxiv", 1.0)
    elif _DOI_RE.match(q):
        paper = openalex.get_work(q)
        if paper is not None:
            return _paper_to_bibentry(paper, "openalex", 1.0)

    found = _chain_search(q)
    if found is None:
        return None
    paper, resolver, score = found
    return _paper_to_bibentry(paper, resolver, score)


def to_bibtex(entry: BibEntry) -> str:
    """Render a BibEntry as a BibTeX record. The key is guaranteed ASCII."""
    lines = [f"@{entry.entry_type}{{{entry.key},"]
    items = list(entry.fields.items())
    for i, (k, v) in enumerate(items):
        val = str(v).replace("{", "(").replace("}", ")")
        comma = "," if i < len(items) - 1 else ""
        lines.append(f"  {k} = {{{val}}}{comma}")
    lines.append("}")
    return "\n".join(lines)


def verify(entry: BibEntry) -> float:
    """Re-resolve ``entry`` and recompute its match score in place.

    Score is title similarity (difflib ratio on normalized titles). Sets
    ``entry.resolved = True`` only when that score is >= 0.85 AND at least
    one author surname overlaps between the entry and the re-fetched record.
    Returns the title-similarity score (0.0 if nothing could be found).
    """
    title = entry.fields.get("title", "")
    if not title:
        entry.match_score = 0.0
        entry.resolved = False
        return 0.0

    candidate: Paper | None = None
    resolver: str | None = None

    arxiv_id = entry.fields.get("eprint") or entry.fields.get("arxiv")
    doi = entry.fields.get("doi")

    if arxiv_id:
        candidate = arxiv.get(str(arxiv_id))
        if candidate is not None:
            resolver = "arxiv"
    if candidate is None and doi:
        candidate = openalex.get_work(str(doi))
        if candidate is not None:
            resolver = "openalex"
    if candidate is None:
        found = _chain_search(title)
        if found is not None:
            candidate, resolver, _ = found

    if candidate is None:
        entry.match_score = 0.0
        entry.resolved = False
        return 0.0

    title_score = _title_similarity(title, candidate.title)
    entry_surnames = _surnames(entry.fields.get("author", ""))
    cand_surnames = _surnames(" and ".join(candidate.authors))
    author_overlap = bool(entry_surnames & cand_surnames)

    entry.match_score = title_score
    entry.resolver = resolver
    entry.resolved = title_score >= 0.85 and author_overlap
    return title_score


def load_bib(path: Path | str) -> list[BibEntry]:
    """Load a .bib file into a list of BibEntry (unresolved by default)."""
    path = Path(path)
    if not path.exists():
        return []
    parser = BibTexParser(common_strings=True)
    with open(path, encoding="utf-8") as f:
        db = bibtexparser.load(f, parser=parser)

    entries = []
    for rec in db.entries:
        rec = dict(rec)
        key = rec.pop("ID", "")
        entry_type = rec.pop("ENTRYTYPE", "article")
        entries.append(
            BibEntry(
                key=key, entry_type=entry_type, fields=rec,
                resolved=False, resolver=None, match_score=None,
            )
        )
    return entries


def save_bib(path: Path | str, entries: list[BibEntry]) -> None:
    """Write a list of BibEntry to a .bib file."""
    db = BibDatabase()
    records = []
    for e in entries:
        rec = dict(e.fields)
        rec["ID"] = e.key
        rec["ENTRYTYPE"] = e.entry_type
        records.append(rec)
    db.entries = records

    writer = BibTexWriter()
    writer.indent = "  "
    with open(path, "w", encoding="utf-8") as f:
        f.write(writer.write(db))


def check_bib(path: Path | str) -> dict:
    """Re-resolve every entry in a .bib file by title/doi/arxiv id.

    Returns {"ok": bool, "unresolved": [keys], "resolved": [keys], "details": {...}}.
    """
    entries = load_bib(path)
    resolved_keys: list[str] = []
    unresolved_keys: list[str] = []
    details: dict = {}

    for e in entries:
        score = verify(e)
        details[e.key] = {
            "resolved": e.resolved,
            "match_score": score,
            "resolver": e.resolver,
        }
        (resolved_keys if e.resolved else unresolved_keys).append(e.key)

    return {
        "ok": len(unresolved_keys) == 0,
        "unresolved": unresolved_keys,
        "resolved": resolved_keys,
        "details": details,
    }
