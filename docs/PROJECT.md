# Project architecture

Source of truth: `PLAN.md` (repo root). This document mirrors the architecture, Day 0 decisions, and layout defined there.

## Architecture

```
  git clone --depth 1
        │
        ├─► file filter ──► tree-sitter parse ──┬──► SYMBOL TABLE   (sqlite, exact lookup)
        │                                       │
        │                                       └──► AST CHUNKS
        │                                                │
        │                              ┌─────────────────┴─────────────────┐
        │                              ▼                                   ▼
        │                        BM25 index                         dense vectors
        │                     (code tokenizer)                    (local embeddings)
        │                              └─────────────────┬─────────────────┘
        │                                                ▼
        │                                  reciprocal rank fusion → top 50
        │                                                ▼
        │                                     cross-encoder rerank → top 8
        │                                                ▼
        │                          expand chunk → whole function + imports header
        │                                                ▼
        └──────────────────────────────────►  LLM ──► answer + src/auth/login.py:42-78
```

## Day 0 — locked decisions

| Choice | Decision | Why |
|---|---|---|
| Language | Python 3.11+ | tree-sitter bindings, embeddings, FastAPI all live here |
| Parser | `tree-sitter` direct | the parsing is the part I'm claiming to understand, so I wrote it |
| Embeddings | `BAAI/bge-small-en-v1.5`, local | 384-dim, CPU, no API key, free to re-index while tuning |
| Vector store | Qdrant, embedded mode | real vector DB semantics, zero ops — `QdrantClient(path="./data/qdrant")` |
| Lexical | `rank_bm25` + custom code tokenizer | off-the-shelf tokenizers destroy `getUserById`; mine splits camelCase/snake_case |
| Reranker | `BAAI/bge-reranker-base` cross-encoder | local, free, the second stage a bi-encoder can't do |
| Metadata | SQLite | symbols, chunks, files in one inspectable file |
| Generation | any hosted LLM | swappable behind one function, least interesting part of the system |
| Frameworks | no LangChain, no LlamaIndex | the retrieval core is the evidence; wrapping it in a framework deletes the evidence |
| Frontend | one HTML file | the demo is a GIF, not a product |

**Eval repos:**
- **Repo A** — Harshu's own MERN fitness tracker (already known, cheap to label, gives a JS/TS target)
- **Repo B** — a mid-size Python OSS repo (`psf/requests`, `pallets/flask`, or `encode/httpx`)
- **Repo C** — a repo never seen before, held out, never tuned against, reported separately

## Project layout

```
codebase-assistant/
├─ app/
│  ├─ config.py          # paths, model names, thresholds
│  ├─ ingest.py          # shallow clone + file filtering
│  ├─ parse.py           # tree-sitter → symbols
│  ├─ chunk.py           # AST-boundary splitter
│  ├─ store.py           # sqlite: files, symbols, chunks
│  ├─ lexical.py         # code tokenizer + BM25
│  ├─ dense.py           # embeddings + qdrant
│  ├─ retrieve.py        # symbol / bm25 / dense / hybrid / rerank
│  ├─ expand.py          # chunk → full function + header
│  ├─ answer.py          # prompt, citation parsing + verification
│  ├─ agentic.py         # day 6 baseline
│  └─ api.py             # FastAPI
├─ eval/
│  ├─ golden.jsonl       # the labelled question set
│  ├─ run_eval.py        # metrics + ablation runner
│  └─ results/           # committed csv/markdown output
├─ scripts/build_index.py
├─ web/index.html
├─ requirements.txt
└─ README.md
```

## Known risks

| Risk | Signal | Response |
|---|---|---|
| tree-sitter node types don't match | zero symbols on day 1 | print the raw AST for one file before writing the walker |
| Day 3 overruns | rerank not done by evening | ship bm25+dense+RRF, push rerank to day 5 |
| golden set too easy | every retriever scores >0.9 | add questions whose wording never appears in the code |
| scope creep | "I should add call graphs" | write it in a `FUTURE.md` instead, don't build it |
