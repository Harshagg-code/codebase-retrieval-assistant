# AI Codebase Assistant — architecture & build plan

> Source document. Claude Code: read this in full, then use it to generate
> CLAUDE.md, docs/PROJECT.md, docs/ROADMAP.md, and docs/DECISIONS.md as
> instructed at the bottom of this file. Do not start writing application
> code yet.

## What this is

A RAG system that indexes a GitHub repository and answers natural-language
questions about it, grounded in citations (`path/to/file.py:42-78`). The
point of the project is not "a chatbot over code" — it's a measured
comparison of retrieval strategies (lexical, dense, hybrid, reranked, and
an agentic grep-based baseline) against a hand-labeled evaluation set, with
the results reported honestly, including on a held-out repo never tuned
against.

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

## Day-by-day roadmap

### Day 0 — setup
- [ ] venv + requirements installed, embedding model pre-downloaded
- [ ] repo skeleton pushed to GitHub
- [ ] three eval repos chosen and cloned
- [ ] `.env` with LLM key, gitignored

### Day 1 — ingestion & parsing
- [ ] `ingest.py`: shallow clone, handle already-cloned repos
- [ ] file filter with logged reasons (skip dirs, extensions, size caps)
- [ ] `store.py`: SQLite schema (files, symbols, chunks tables)
- [ ] `parse.py`: tree-sitter parsers for Python, TS/JS, one more
- [ ] walk AST, extract every definition with line range + parent
- [ ] CLI prints an ingestion report (files indexed, symbols found, skip breakdown)
- **Done when:** `python scripts/build_index.py <url>` prints real counts and `sqlite3` shows real symbols with plausible line ranges.

### Day 2 — chunking & the golden set
- [ ] `chunk.py`: recursive AST splitter with sibling merging (cAST-style)
- [ ] character-window fallback for unsupported languages
- [ ] header prepended to every chunk (file path, imports, enclosing class/symbol) before indexing
- [ ] fixed-size chunker too — needed as the day-5 ablation baseline
- [ ] write 30+ questions into `eval/golden.jsonl` with gold files/symbols, spread across types: symbol / concept / flow / howto
- [ ] sanity script: assert every gold file exists in the index
- **Done when:** golden set has 30+ entries across 3 repos, sanity check passes, chunker works in both AST and fixed-size modes.

### Day 3 — retrieval & eval harness (heaviest day)
- [ ] code tokenizer (splits camelCase/snake_case) + BM25 index
- [ ] dense index: embed all chunks into embedded Qdrant
- [ ] symbol retriever: exact + case-insensitive lookup
- [ ] hybrid retriever: reciprocal rank fusion (RRF) over BM25 + dense
- [ ] cross-encoder rerank of fused top 50 → top 8
- [ ] `run_eval.py`: recall@k, MRR, per-question-type breakdown
- [ ] run it, record the first numbers
- **Done when:** `run_eval.py --retriever bm25,dense,hybrid,hybrid+rerank` prints a full metrics table.

### Day 4 — answers, citations, API
- [ ] `expand.py`: chunk → enclosing symbol's full source + import header
- [ ] answer prompt with forced citations + explicit permission to abstain
- [ ] citation verifier: parse `path:start-end`, check it actually exists
- [ ] FastAPI: `POST /ingest`, `POST /ask`, `GET /symbols?q=`
- [ ] query rewriting for follow-ups (last 2 turns)
- [ ] minimal `web/index.html`
- **Done when:** `/ask` returns grounded, citation-verified answers, and abstains honestly when the repo doesn't contain the answer.

### Day 5 — ablations, README, ship (MVP)
- [ ] ablation: retriever type (bm25 / dense / hybrid / hybrid+rerank)
- [ ] ablation: chunking (fixed-size vs AST)
- [ ] ablation: header on vs off
- [ ] report held-out Repo C separately
- [ ] commit `eval/results/*.md`
- [ ] README: architecture diagram, results table, limitations, how to run
- [ ] 30-second demo GIF
- [ ] push, add resume bullets with real numbers, **resume applying**
- **Done when:** repo is public, README leads with GIF + results table. Everything after this is optional.

### Day 6 — agentic baseline
- [ ] tools: `list_files`, `grep`, `read_file`, hard cap 10 calls
- [ ] record files read, tokens, latency per question
- [ ] score against the same golden set with the same recall function
- [ ] add row to results table with cost/latency column
- **Done when:** README has an `agentic (grep + read)` row alongside the four retrievers, with an honest tradeoff writeup.

### Day 7 — polish (optional, stop whenever)
- [ ] query router: identifier-shaped queries → symbol table, else → hybrid
- [ ] grow golden set to 50 questions
- [ ] embedding ablation (swap in a code-specific model)
- [ ] repo map: rank files by inbound symbol references
- [ ] Dockerfile
- [ ] tests for chunker + tokenizer
- **Do not start:** knowledge graphs, Neo4j, multi-repo support, auth, React frontend.

## Known risks

| Risk | Signal | Response |
|---|---|---|
| tree-sitter node types don't match | zero symbols on day 1 | print the raw AST for one file before writing the walker |
| Day 3 overruns | rerank not done by evening | ship bm25+dense+RRF, push rerank to day 5 |
| golden set too easy | every retriever scores >0.9 | add questions whose wording never appears in the code |
| scope creep | "I should add call graphs" | write it in a `FUTURE.md` instead, don't build it |

---

## Instructions for Claude Code

Using everything above, generate these four files. Show them to me for
review before writing any application code:

1. **`CLAUDE.md`** (repo root) — project description in one paragraph, tech
   stack with one-line justifications, how to run things (venv, ingest,
   eval), coding conventions, and a pointer to `docs/ROADMAP.md` for
   current status rather than restating it.

2. **`docs/PROJECT.md`** — the architecture diagram, the Day 0 decisions
   table, and the project layout, verbatim from above.

3. **`docs/ROADMAP.md`** — the day-by-day checklist above, as real markdown
   checkboxes you'll update as we complete tasks.

4. **`docs/DECISIONS.md`** — start empty except for a header and this
   format, ready to append to as we build:

   ```
   ## YYYY-MM-DD — <decision>
   **Context:** why this came up
   **Decision:** what we chose
   **Alternatives considered:** what we didn't pick and why
   ```

   Propose an entry here whenever we settle a real architectural choice
   during the build — don't wait to be asked.
