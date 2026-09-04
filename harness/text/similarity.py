"""Cheap local similarity for ideas, lemmas and evolved programs (Round-2 Y8).

No embeddings API: TF-IDF over a math-aware tokenizer with cosine similarity
(numpy), plus an AST-normalized hash for code. Used by ``harness ideas dedup``
(near-duplicate attack routes), the lemma bank (near-duplicate lemma statements)
and the evolutionary search (novelty rejection before spending evaluation
budget — cf. ShinkaEvolve's ``code_embed_sim_threshold`` / ``max_novelty_attempts``).

Threshold guidance: 0.8 cosine for near-duplicate *ideas/statements*, 0.95 for
*code*; with fewer than three documents TF-IDF is degenerate, so
:func:`near_duplicates` falls back to ``difflib`` ratios there. The AI
co-scientist's "proximity agent" (arXiv 2502.18864) plays the same role for
hypotheses; its metric is unspecified, so nothing here claims to reproduce it.
"""
from __future__ import annotations

import ast
import difflib
import math
import re
from collections import Counter

from harness.verify.exact import sha256_text

_TOKEN_RE = re.compile(r"[a-z]+|\d+|[^\w\s]", re.UNICODE)
_STOP = {"the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "is", "be", "that", "this", "with", "by", "as",
         "we", "it", "at", "from", "then", "if", "so", "are", "all", "any", "every", "each", "let"}


def tokenize(text: str) -> list[str]:
    """Lowercase word/number/symbol tokens; math symbols (``≤ ^ ∑ | +``) survive as their own tokens."""
    toks = _TOKEN_RE.findall((text or "").lower())
    return [t for t in toks if t not in _STOP and t not in {",", ".", ";", ":"}]


def normalize_code(src: str) -> str:
    """AST round-trip with docstrings removed (falls back to whitespace-normalized text)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return " ".join(src.split())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    try:
        return ast.unparse(tree)
    except Exception:  # pragma: no cover - unparse failures are exotic
        return " ".join(src.split())


def code_hash(src: str) -> str:
    return sha256_text(normalize_code(src))


def _vectors(docs: list[list[str]]) -> tuple[list[dict[str, float]], dict[str, float]]:
    n = len(docs)
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
    vecs: list[dict[str, float]] = []
    for d in docs:
        tf = Counter(d)
        v = {t: (1.0 + math.log(c)) * idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})
    return vecs, idf


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def cosine_matrix(items: list[str], tokenizer=tokenize) -> list[list[float]]:
    """Pairwise TF-IDF cosine similarities (symmetric, diagonal 1)."""
    vecs, _ = _vectors([tokenizer(s) for s in items])
    n = len(items)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        mat[i][i] = 1.0
        for j in range(i + 1, n):
            mat[i][j] = mat[j][i] = cosine(vecs[i], vecs[j])
    return mat


def near_duplicates(items: list[str], threshold: float = 0.8, tokenizer=tokenize) -> list[tuple[int, int, float]]:
    """Index pairs whose similarity is at least ``threshold`` (difflib ratio when n < 3)."""
    n = len(items)
    out: list[tuple[int, int, float]] = []
    if n < 2:
        return out
    if n < 3:
        r = difflib.SequenceMatcher(None, " ".join(tokenizer(items[0])), " ".join(tokenizer(items[1]))).ratio()
        return [(0, 1, r)] if r >= threshold else []
    mat = cosine_matrix(items, tokenizer)
    for i in range(n):
        for j in range(i + 1, n):
            if mat[i][j] >= threshold:
                out.append((i, j, round(mat[i][j], 4)))
    out.sort(key=lambda t: -t[2])
    return out


def most_similar(query: str, items: list[str], k: int = 5, tokenizer=tokenize) -> list[tuple[int, float]]:
    """Top-``k`` ``(index, score)`` of ``items`` for ``query``."""
    if not items:
        return []
    vecs, _ = _vectors([tokenizer(s) for s in [query] + items])
    q = vecs[0]
    scored = [(i, round(cosine(q, v), 4)) for i, v in enumerate(vecs[1:])]
    scored.sort(key=lambda t: (-t[1], t[0]))
    return scored[:k]


def proximity_graph(items: list[str], threshold: float = 0.5, tokenizer=tokenize) -> dict:
    """``{"nodes": n, "edges": [(i, j, w)], "clusters": [[i, ...], ...]}`` (union-find over edges ≥ threshold)."""
    n = len(items)
    edges: list[tuple[int, int, float]] = []
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    if n >= 2:
        mat = cosine_matrix(items, tokenizer) if n >= 3 else None
        for i in range(n):
            for j in range(i + 1, n):
                w = mat[i][j] if mat is not None else difflib.SequenceMatcher(None, items[i], items[j]).ratio()
                if w >= threshold:
                    edges.append((i, j, round(w, 4)))
                    parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    clusters = sorted(groups.values(), key=lambda g: (-len(g), g[0]))
    return {"nodes": n, "edges": edges, "clusters": clusters}
