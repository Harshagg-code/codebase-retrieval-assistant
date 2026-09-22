# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

This is a RAG system that indexes a GitHub repository and answers natural-language questions about it, grounded in citations (`path/to/file.py:42-78`). The point of the project is not "a chatbot over code" — it's a measured comparison of retrieval strategies (lexical, dense, hybrid, reranked, and an agentic grep-based baseline) against a hand-labeled evaluation set, with results reported honestly, including on a held-out repo never tuned against.

## Tech stack

| Choice | Decision | Why |
|---|---|---|
| Language | Python 3.11+ | tree-sitter bindings, embeddings, FastAPI all live here |
| Parser | `tree-sitter` direct | the parsing is the part being claimed to understand, so it's hand-written |
| Embeddings | `BAAI/bge-small-en-v1.5`, local | 384-dim, CPU, no API key, free to re-index while tuning |
| Vector store | Qdrant, embedded mode | real vector DB semantics, zero ops — `QdrantClient(path="./data/qdrant")` |
| Lexical | `rank_bm25` + custom code tokenizer | off-the-shelf tokenizers destroy `getUserById`; the custom one splits camelCase/snake_case |
| Reranker | `BAAI/bge-reranker-base` cross-encoder | local, free, the second stage a bi-encoder can't do |
| Metadata | SQLite | symbols, chunks, files in one inspectable file |
| Generation | any hosted LLM | swappable behind one function, least interesting part of the system |
| Frameworks | no LangChain, no LlamaIndex | the retrieval core is the evidence; wrapping it in a framework deletes the evidence |
| Frontend | one HTML file | the demo is a GIF, not a product |

Full architecture diagram and project layout: [docs/PROJECT.md](docs/PROJECT.md).

## Running things

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# ingest + index a repo
python scripts/build_index.py <repo-url>

# run the eval harness across retrievers
python eval/run_eval.py --retriever bm25,dense,hybrid,hybrid+rerank

# serve the API
uvicorn app.api:app --reload
```

These commands describe the intended shape of the CLI/API per `docs/ROADMAP.md`; check that the corresponding module exists before assuming a command works.

## Coding conventions

- No LangChain/LlamaIndex or similar retrieval frameworks — the retrieval logic itself is the deliverable, so it stays hand-written and inspectable.
- Generation is isolated behind a single function so the LLM provider can be swapped without touching retrieval code.
- Citations are always `path:start-end` and are verified against the actual file before being returned — never trust an unverified citation.
- The system must be able to abstain honestly when a repo doesn't contain the answer, rather than fabricate one.
- Ablations (retriever type, chunking strategy, header on/off) should be runnable independently via flags, not hardcoded branches.
- Keep `eval/golden.jsonl` and `eval/results/` as the source of truth for claims about retrieval quality — don't report numbers that aren't reproducible from these.

## Current status

See [docs/ROADMAP.md](docs/ROADMAP.md) for the day-by-day checklist and current progress — don't restate status here.

## Decisions log

Architectural choices made after Day 0 are recorded in [docs/DECISIONS.md](docs/DECISIONS.md). Propose an entry there whenever a real architectural choice is settled during the build.
