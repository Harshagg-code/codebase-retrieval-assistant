"""Lexical retrieval: a code-aware tokenizer and a BM25 index over it.

Off-the-shelf tokenizers treat "getUserById" as one opaque token, which
means a query for "user" never matches it. tokenize_code keeps the whole
identifier *and* splits it into its camelCase/snake_case parts, so both
kinds of query work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Splits "getUserById" -> ["get", "User", "By", "Id"]; "XMLParser" -> ["XML", "Parser"].
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+")


def _split_identifier(word: str) -> list[str]:
    parts: list[str] = []
    for segment in word.split("_"):
        if segment:
            parts.extend(m.lower() for m in _CAMEL_RE.findall(segment))
    return parts


def tokenize_code(text: str) -> list[str]:
    tokens: list[str] = []
    for word in _WORD_RE.findall(text):
        lower = word.lower()
        tokens.append(lower)
        parts = _split_identifier(word)
        if len(parts) > 1 or (len(parts) == 1 and parts[0] != lower):
            tokens.extend(parts)
    return tokens


@dataclass
class BM25Index:
    bm25: BM25Okapi
    chunk_ids: list[int]  # chunk_ids[i] is the id of the i-th indexed document


def build_bm25_index(chunk_ids: list[int], texts: list[str]) -> BM25Index:
    tokenized = [tokenize_code(text) for text in texts]
    return BM25Index(bm25=BM25Okapi(tokenized), chunk_ids=chunk_ids)


def bm25_search(index: BM25Index, query: str, top_k: int = 5) -> list[tuple[int, float]]:
    """Returns [(chunk_id, score), ...] sorted by score descending."""
    scores = index.bm25.get_scores(tokenize_code(query))
    ranked = sorted(zip(index.chunk_ids, scores), key=lambda pair: pair[1], reverse=True)
    return ranked[:top_k]
