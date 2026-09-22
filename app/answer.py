"""answer.py: retrieve -> expand -> prompt -> generate, behind one function.

Generation is isolated to generate_answer() so the LLM provider can be
swapped without touching retrieval -- per PLAN.md, it's the least
interesting part of the system. Everything upstream (retrieval, fusion,
rerank, expansion) is what's actually being measured.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from app.config import GENERATION_MODEL, REPOS_DIR
from app.dense import build_dense_index, dense_search, get_qdrant_client
from app.expand import ExpandedContext, expand
from app.lexical import BM25Index, build_bm25_index, bm25_search
from app.retrieve import rerank, rrf
from app.store import IndexableChunk, get_indexable_chunks

CANDIDATE_POOL = 50
RERANK_TOP_K = 8

SYSTEM_PROMPT = """You are a code assistant answering questions about one specific GitHub repository. You must answer strictly from the evidence given to you below -- never from general knowledge of what similar code usually does.

Rules, follow them exactly:
1. Every factual claim about the code must end with a citation in the exact format `path:start-end` (e.g. `src/requests/sessions.py:154-184`), referencing one of the evidence spans given to you. Never invent a citation or cite a line range you were not given.
2. If the evidence does not contain enough information to answer the question, say so plainly -- for example: "I don't have enough evidence in this repository to answer that." Do not guess or produce a confident-sounding answer you cannot back with a citation.
3. If the answer involves more than one file or function, explain the actual order things happen in (what calls what, what runs first), not just an unordered list of facts.
4. Be concise and technical. Explain what the evidence means; don't just restate it verbatim."""


ABSTENTION_PREFIX = "I don't have enough evidence in this repository to answer that."

GROUNDEDNESS_SYSTEM_PROMPT = """You are a strict fact-checking gate for a code question-answering system. You will be given a user's question about a specific repository and a list of evidence snippets retrieved from it. Decide one thing only: does this evidence actually establish a real, specific answer to THIS question -- not just whether it's topically related.

Be strict. Evidence that is merely about a similar or adjacent topic does NOT count as grounded, even if it shares vocabulary with the question. For example: evidence about the app's own weight-tracking API does not ground a question about syncing with a third-party service (like Apple HealthKit) that is never mentioned in the evidence. Evidence about uploading multiple files does not ground a question about a completely different protocol (like GraphQL) that is never mentioned in the evidence. The evidence must describe or implement the *specific* thing asked about, not something merely nearby.

Respond with a JSON object with exactly two keys:
{"grounded": true or false, "reason": "one sentence explaining why"}"""


@dataclass
class GroundednessCheck:
    grounded: bool
    reason: str


def check_groundedness(
    question: str,
    evidence: list[ExpandedContext],
    client: OpenAI | None = None,
    model: str = GENERATION_MODEL,
) -> GroundednessCheck:
    client = client or OpenAI()
    evidence_text = "\n\n".join(
        f"### {e.path}:{e.start_line}-{e.end_line}\n```\n{e.text}\n```" for e in evidence
    )
    prompt = f"Question: {question}\n\nEvidence:\n\n{evidence_text}"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": GROUNDEDNESS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)
    return GroundednessCheck(grounded=bool(data.get("grounded", False)), reason=str(data.get("reason", "")))


# ---- Query rewriting for follow-ups ------------------------------------------
# Retrieval only ever sees the string handed to it -- "where's the token
# validated?" carries no retrievable signal on its own. Rewriting folds the
# last 1-2 turns' context into a standalone question before retrieval runs.

REWRITE_SYSTEM_PROMPT = """Given recent conversation history and a new follow-up question, rewrite the follow-up into a fully standalone question that could be understood and answered with no knowledge of the conversation history. Preserve the user's intent exactly -- do not broaden, narrow, or answer it. Respond with only the rewritten question, no extra text or quotes."""


def rewrite_query(
    history: list[tuple[str, str]],
    follow_up: str,
    client: OpenAI | None = None,
    model: str = GENERATION_MODEL,
) -> str:
    """history: [(question, answer), ...], most recent last. Only the last 2 turns are used."""
    if not history:
        return follow_up

    client = client or OpenAI()
    history_text = "\n\n".join(f"Q: {q}\nA: {a}" for q, a in history[-2:])
    prompt = f"Conversation history:\n\n{history_text}\n\nFollow-up question: {follow_up}\n\nRewritten standalone question:"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return response.choices[0].message.content.strip()


@dataclass
class AnswerResult:
    question: str
    answer: str
    evidence: list[ExpandedContext]
    grounded: bool = True
    groundedness_reason: str | None = None


def build_prompt(question: str, evidence: list[ExpandedContext]) -> str:
    blocks = []
    for e in evidence:
        imports_part = f"{e.imports}\n\n" if e.imports else ""
        blocks.append(f"### {e.path}:{e.start_line}-{e.end_line}\n```\n{imports_part}{e.text}\n```")
    evidence_text = "\n\n".join(blocks)
    return f"Question: {question}\n\nEvidence:\n\n{evidence_text}"


def generate_answer(
    question: str,
    evidence: list[ExpandedContext],
    client: OpenAI | None = None,
    model: str = GENERATION_MODEL,
) -> str:
    client = client or OpenAI()
    prompt = build_prompt(question, evidence)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


def retrieve_and_expand(
    conn: sqlite3.Connection,
    repo: str,
    question: str,
    chunks: list[IndexableChunk],
    bm25_index: BM25Index,
    repo_root: Path,
    top_k: int = RERANK_TOP_K,
) -> list[ExpandedContext]:
    """hybrid+rerank retrieval -- our strongest all-around retriever per Day 3 -- then expand()."""
    by_id = {c.chunk_id: c for c in chunks}
    qdrant = get_qdrant_client()

    bm25_r = bm25_search(bm25_index, question, top_k=CANDIDATE_POOL)
    dense_r = dense_search(qdrant, repo, question, top_k=CANDIDATE_POOL)
    fused = rrf([bm25_r, dense_r], top_k=CANDIDATE_POOL)
    candidates = [(cid, by_id[cid].indexed_text) for cid, _ in fused]
    reranked = rerank(question, candidates, top_k=top_k)

    return [expand(by_id[cid], conn, repo_root) for cid, _ in reranked]


def answer_question(
    conn: sqlite3.Connection,
    repo: str,
    question: str,
    repo_root: Path | None = None,
    client: OpenAI | None = None,
    model: str = GENERATION_MODEL,
) -> AnswerResult:
    repo_root = repo_root or (REPOS_DIR / repo)
    chunks = get_indexable_chunks(conn, repo, repo_root)
    bm25_index = build_bm25_index([c.chunk_id for c in chunks], [c.indexed_text for c in chunks])

    qdrant = get_qdrant_client()
    build_dense_index(qdrant, repo, chunks)

    evidence = retrieve_and_expand(conn, repo, question, chunks, bm25_index, repo_root)

    check = check_groundedness(question, evidence, client=client, model=model)
    if not check.grounded:
        abstention = f"{ABSTENTION_PREFIX} {check.reason}"
        return AnswerResult(
            question=question, answer=abstention, evidence=evidence,
            grounded=False, groundedness_reason=check.reason,
        )

    answer = generate_answer(question, evidence, client=client, model=model)
    return AnswerResult(
        question=question, answer=answer, evidence=evidence,
        grounded=True, groundedness_reason=check.reason,
    )


# ---- Citation verification ---------------------------------------------------
# Every `path:start-end` the model writes must correspond to a real span it
# was actually shown. A small line tolerance allows the model to cite a
# narrower, more specific sub-range within the evidence it was given (e.g.
# citing just a function's lines within a whole-file evidence block) without
# that counting as a fabrication.

_CITATION_RE = re.compile(r"([^\s`(),\[\]]+):(\d+)-(\d+)")


@dataclass
class Citation:
    raw: str
    path: str
    start_line: int
    end_line: int
    verified: bool


@dataclass
class VerificationResult:
    citations: list[Citation]

    @property
    def total(self) -> int:
        return len(self.citations)

    @property
    def verified_count(self) -> int:
        return sum(1 for c in self.citations if c.verified)

    @property
    def failed(self) -> list[Citation]:
        return [c for c in self.citations if not c.verified]


def extract_citations(answer: str) -> list[tuple[str, int, int]]:
    return [(path, int(start), int(end)) for path, start, end in _CITATION_RE.findall(answer)]


def verify(answer: str, retrieved: list[ExpandedContext], tolerance: int = 5) -> VerificationResult:
    citations = []
    for path, start, end in extract_citations(answer):
        ok = any(
            e.path == path and start >= e.start_line - tolerance and end <= e.end_line + tolerance
            for e in retrieved
        )
        citations.append(Citation(raw=f"{path}:{start}-{end}", path=path, start_line=start, end_line=end, verified=ok))
    return VerificationResult(citations=citations)
