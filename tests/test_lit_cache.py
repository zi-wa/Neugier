"""Offline tests for harness.lit.cache — excerpt provenance verification (rule R5a)."""
from __future__ import annotations

from pathlib import Path

import harness
from harness.lit import cache


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


SOURCE = (
    "Theorem 2.1 (Cauchy–Davenport for the integers). For every finite set S of integers with at least "
    "two elements we have |S+S| ≥ 2|S| − 1, with equality if and only if S is an arithmetic pro-\n"
    "gression. The proof uses the “compression” technique of Section 3."
)


# -------------------------------------------------------------- safe names --

def test_safe_name_variants():
    assert cache.safe_name("arxiv:2401.01234v2") == "2401.01234"
    assert cache.safe_name("2401.01234") == "2401.01234"
    assert cache.safe_name("math/0601001") == "math_0601001"
    assert cache.safe_name("doi:10.1000/ab c") == "doi_10.1000_ab_c"
    assert cache.safe_name("oeis:a000045") == "oeis_A000045"
    assert cache.safe_name("mo:12345") == "mo_12345"
    u1 = cache.safe_name("https://example.org/x.pdf")
    assert u1.startswith("url_") and len(u1) == 20
    assert cache.safe_name("url:https://example.org/x.pdf") == u1
    assert cache.safe_name("Smith & Jones 2020") == "Smith_Jones_2020"
    assert cache.kind_of("arxiv:2401.01234") == "arxiv" and cache.kind_of("smith2020") == "other"


def test_find_cached_text_prefers_campaign_cache_and_accepts_layouts(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CACHE", tmp_path / "dotcache")
    camp = tmp_path / "camp"
    assert cache.find_cached_text("smith2020", camp) is None
    proj = _write(tmp_path / "dotcache" / "lit" / "fulltext" / "smith2020.txt", "project copy")
    assert cache.find_cached_text("smith2020", camp) == proj
    local = _write(camp / "cache" / "smith2020" / "smith2020.txt", "campaign copy")
    assert cache.find_cached_text("smith2020", camp) == local
    _write(camp / "cache" / "2401.01234.txt", "arxiv text")
    assert cache.find_cached_text("arXiv:2401.01234v3", camp) == camp / "cache" / "2401.01234.txt"


def test_active_campaign_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CAMPAIGNS", tmp_path / "campaigns")
    assert cache.active_campaign_dir() is None
    _write(tmp_path / "campaigns" / "ACTIVE", "demo\n")
    assert cache.active_campaign_dir() == tmp_path / "campaigns" / "demo"


# ------------------------------------------------------------- normalizing --

def test_normalize_for_match_handles_pdf_artifacts():
    n = cache.normalize_for_match("arithmetic pro-\ngression  “compression”  ﬁnite­")
    assert n == "arithmetic progression compression finite"
    assert cache.normalize_for_match("|S+S| ≥ 2|S| − 1") == "|s+s| >= 2|s| - 1"


def test_excerpt_hash_is_stable_under_normalization():
    a = cache.excerpt_hash("For every finite set S")
    b = cache.excerpt_hash("  for EVERY   finite set S ")
    assert a == b and len(a) == 12


# ------------------------------------------------------------ verification --

def test_verify_exact_normalized_chunks_and_failures(tmp_path):
    camp = tmp_path / "camp"
    src = _write(camp / "cache" / "smith2020.txt", SOURCE)

    exact = cache.verify_excerpt("For every finite set S of integers with at least two elements", "smith2020", camp)
    assert exact.verified is True and exact.method == "exact" and exact.source_path == "cache/smith2020.txt"
    assert exact.source_sha256 and len(exact.excerpt_hash) == 12

    norm = cache.verify_excerpt('S is an arithmetic progression. The proof uses the "compression" technique', "smith2020", camp)
    assert norm.verified is True and norm.method == "normalized"

    chunky = cache.verify_excerpt(
        "For every finite set S of integers with at least two elements we have |S+S| >= 2|S| - 1 (typo here), "
        "with equality if and only if S is an arithmetic progression. The proof uses the compression technique of Section 3.",
        "smith2020", camp,
    )
    assert chunky.verified is True and chunky.method == "chunks"

    bad = cache.verify_excerpt("The Riemann hypothesis holds for all zeros in the critical strip of the zeta function.", "smith2020", camp)
    assert bad.verified is False and bad.method == "not-found"

    nosrc = cache.verify_excerpt("For every finite set S of integers with at least two elements", "unknown2020", camp)
    assert nosrc.verified is None and nosrc.method == "no-source"

    short = cache.verify_excerpt("too short", "smith2020", camp)
    assert short.verified is False and short.method == "too-short"

    direct = cache.verify_excerpt("compression", "whatever", None, source_path=src, min_chars=5)
    assert direct.verified is True


def test_fetch_to_cache_unknown_kind_returns_none(tmp_path):
    assert cache.fetch_to_cache("mo:12345", tmp_path) is None
    assert cache.fetch_to_cache("plainbibkey", tmp_path) is None
