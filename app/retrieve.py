"""Retrieval strategies: exact symbol lookup, hybrid fusion (RRF), and reranking.

BM25 (lexical.py) and dense (dense.py) each already know how to search their
own index; this module is where those get combined, plus the exact-match
path that doesn't need either.
"""

from __future__ import annotations

import re
import sqlite3

from sentence_transformers import CrossEncoder

from app.config import RERANKER_MODEL

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MIN_IDENTIFIER_LEN = 3  # skip trivial words like "do"/"is" that could false-match a short symbol name


def symbol_lookup(conn: sqlite3.Connection, repo: str, query: str, top_k: int = 5) -> list[tuple[int, float]]:
    """Exact, case-insensitive lookup of any identifier-shaped word in the
    query against the symbols table. This is a lookup, not a ranked
    similarity search -- every hit scores 1.0.
    """
    seen: dict[int, float] = {}
    for word in _IDENTIFIER_RE.findall(query):
        if len(word) < _MIN_IDENTIFIER_LEN:
            continue
        for (symbol_id,) in conn.execute(
            """
            SELECT s.id FROM symbols s JOIN files f ON f.id = s.file_id
            WHERE f.repo = ? AND LOWER(s.name) = LOWER(?)
            """,
            (repo, word),
        ).fetchall():
            seen[symbol_id] = 1.0

    ranked = sorted(seen.items(), key=lambda pair: pair[1], reverse=True)
    return ranked[:top_k]


def rrf(rankings: list[list[tuple[int, float]]], k: int = 60, top_k: int = 5) -> list[tuple[int, float]]:
    """Reciprocal rank fusion: combine several ranked lists by *rank*, not
    raw score, so BM25's unbounded scores and dense's 0-1 cosine scores
    never need to be normalized against each other.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, (item_id, _score) in enumerate(ranking, start=1):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + rank)

    ranked = sorted(fused.items(), key=lambda pair: pair[1], reverse=True)
    return ranked[:top_k]


_reranker_cache: dict[str, CrossEncoder] = {}


def get_reranker(name: str = RERANKER_MODEL) -> CrossEncoder:
    if name not in _reranker_cache:
        _reranker_cache[name] = CrossEncoder(name)
    return _reranker_cache[name]


def rerank(
    query: str,
    candidates: list[tuple[int, str]],
    top_k: int = 8,
    model: CrossEncoder | None = None,
) -> list[tuple[int, float]]:
    """candidates: [(chunk_id, indexed_text), ...], typically the fused top-50.
    A cross-encoder scores query and candidate jointly (unlike bi-encoder
    dense retrieval, which embeds them independently), which is more
    accurate but too slow to run over a whole corpus -- hence reranking a
    short list rather than searching with it directly.
    """
    model = model or get_reranker()
    pairs = [(query, text) for _, text in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip((cid for cid, _ in candidates), scores), key=lambda pair: pair[1], reverse=True)
    return ranked[:top_k]
