"""Pydantic data models shared across the literature layer.

All literature clients (arxiv, openalex, zbmath, oeis, mathoverflow) normalize
their results into :class:`Paper` where reasonable. Bibliography entries used
by :mod:`harness.lit.bib` are :class:`BibEntry`.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Paper(BaseModel):
    """A normalized literature record.

    ``id`` is engine-prefixed, e.g. ``"arxiv:2607.29042"``, ``"openalex:W123"``,
    ``"zbmath:1234.56789"``.
    """

    id: str
    source: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    categories: list[str] = Field(default_factory=list)
    cited_by_count: int | None = None
    extra: dict = Field(default_factory=dict)


class BibEntry(BaseModel):
    """A single bibliography entry, possibly resolved against a literature source."""

    key: str
    entry_type: str = "article"
    fields: dict = Field(default_factory=dict)
    resolved: bool = False
    resolver: str | None = None
    match_score: float | None = None


class FullText(BaseModel):
    """Extracted full text of an arXiv paper, plus provenance metadata."""

    arxiv_id: str
    kind: str  # "tex" | "html" | "pdf"
    text: str
    main_file: str | None = None
    files: list[str] = Field(default_factory=list)
    char_count: int = 0
