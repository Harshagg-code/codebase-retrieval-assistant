# Roadmap

Day-by-day build plan. Check items off as they're completed; this is the current-status source of truth referenced from `CLAUDE.md`.

## Day 0 — setup
- [ ] venv + requirements installed, embedding model pre-downloaded
- [ ] repo skeleton pushed to GitHub
- [ ] three eval repos chosen and cloned
- [ ] `.env` with LLM key, gitignored

## Day 1 — ingestion & parsing
- [x] `ingest.py`: shallow clone, handle already-cloned repos
- [x] file filter with logged reasons (skip dirs, extensions, size caps)
- [x] `store.py`: SQLite schema (files, symbols, chunks tables)
- [ ] `parse.py`: tree-sitter parsers for Python, TS/JS, one more — Python + JS/TS/TSX done; third language deferred to Day 7, none of the three eval repos need it
- [x] walk AST, extract every definition with line range + parent
- [x] CLI prints an ingestion report (files indexed, symbols found, skip breakdown)

**Done when:** `python scripts/build_index.py <url>` prints real counts and `sqlite3` shows real symbols with plausible line ranges.

## Day 2 — chunking & the golden set
- [x] `chunk.py`: recursive AST splitter with sibling merging (cAST-style)
- [x] character-window fallback for unsupported languages
- [ ] header prepended to every chunk (file path, imports, enclosing class/symbol) before indexing — deferred to Day 3; only needed when text is actually handed to the embedder/BM25 indexer, not stored
- [x] fixed-size chunker too — needed as the day-5 ablation baseline
- [x] write 30+ questions into `eval/golden.jsonl` with gold files/symbols, spread across types: symbol / concept / flow / howto
- [x] sanity script: assert every gold file exists in the index

**Done when:** golden set has 30+ entries across 3 repos, sanity check passes, chunker works in both AST and fixed-size modes.

## Day 3 — retrieval & eval harness (heaviest day)
- [x] code tokenizer (splits camelCase/snake_case) + BM25 index
- [x] dense index: embed all chunks into embedded Qdrant
- [x] symbol retriever: exact + case-insensitive lookup
- [x] hybrid retriever: reciprocal rank fusion (RRF) over BM25 + dense
- [x] cross-encoder rerank of fused top 50 → top 8
- [x] `run_eval.py`: recall@k, MRR, per-question-type breakdown
- [x] run it, record the first numbers

**Done when:** `run_eval.py --retriever bm25,dense,hybrid,hybrid+rerank` prints a full metrics table.

## Day 4 — answers, citations, API
- [x] `expand.py`: chunk → enclosing symbol's full source + import header
- [x] answer prompt with forced citations + explicit permission to abstain
- [x] citation verifier: parse `path:start-end`, check it actually exists
- [x] FastAPI: `POST /ingest`, `POST /ask`, `GET /symbols?q=`
- [x] query rewriting for follow-ups (last 2 turns)
- [x] minimal `web/index.html`

**Done when:** `/ask` returns grounded, citation-verified answers, and abstains honestly when the repo doesn't contain the answer.

## Day 5 — ablations, README, ship (MVP)
- [x] ablation: retriever type (bm25 / dense / hybrid / hybrid+rerank)
- [x] ablation: chunking (fixed-size vs AST)
- [x] ablation: header on vs off
- [x] report held-out Repo C separately
- [x] commit `eval/results/*.md`
- [x] README: architecture diagram, results table, limitations, how to run
- [ ] 30-second demo GIF — `scripts/demo.py` and `demo.tape` are committed and tested; the actual render (`vhs demo.tape`) failed silently in-session (headless Chrome step, likely a macOS permission issue) and is deferred to be run locally
- [x] push
- [ ] add resume bullets with real numbers, **resume applying** — personal task, not part of the engineering work

**Done when:** repo is public, README leads with GIF + results table. Everything after this is optional. (Repo is public with real results; GIF is the one open item, script-ready.)

## Day 6 — agentic baseline
- [ ] tools: `list_files`, `grep`, `read_file`, hard cap 10 calls
- [ ] record files read, tokens, latency per question
- [ ] score against the same golden set with the same recall function
- [ ] add row to results table with cost/latency column

**Done when:** README has an `agentic (grep + read)` row alongside the four retrievers, with an honest tradeoff writeup.

## Day 7 — polish (optional, stop whenever)
- [ ] query router: identifier-shaped queries → symbol table, else → hybrid
- [ ] grow golden set to 50 questions
- [ ] embedding ablation (swap in a code-specific model)
- [ ] repo map: rank files by inbound symbol references
- [ ] Dockerfile
- [ ] tests for chunker + tokenizer

**Do not start:** knowledge graphs, Neo4j, multi-repo support, auth, React frontend.
