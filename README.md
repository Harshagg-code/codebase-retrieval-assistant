# Codebase Assistant

A RAG system that indexes a GitHub repository and answers natural-language questions about it, grounded in citations (`path/to/file.py:42-78`). The point isn't "a chatbot over code" — it's a measured comparison of retrieval strategies (lexical, dense, hybrid, reranked) against a hand-labeled evaluation set, with results reported honestly, including on a held-out repo (`Textualize/rich`) never tuned against. Everything below — the architecture, the numbers, the limitations — is real output from this repo, not aspirational.

<!--
Demo GIF: scripts/demo.py and demo.tape are ready to generate one --
run `vhs demo.tape` locally (needs `brew install vhs`) to produce
web/demo.gif, then embed it here with:
![demo](web/demo.gif)
-->

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
        │                              LLM groundedness gate → abstain, or:
        │                                                ▼
        └──────────────────────────────────►  LLM ──► answer + src/auth/login.py:42-78
```

| Choice | Decision | Why |
|---|---|---|
| Language | Python 3.13 | tree-sitter bindings, embeddings, FastAPI all live here |
| Parser | `tree-sitter` direct | the parsing is the part being claimed to understand, so it's hand-written |
| Embeddings | `BAAI/bge-small-en-v1.5`, local | 384-dim, CPU, no API key, free to re-index while tuning |
| Vector store | Qdrant, embedded mode | real vector DB semantics, zero ops — `QdrantClient(path="./data/qdrant")` |
| Lexical | `rank_bm25` + custom code tokenizer | off-the-shelf tokenizers destroy `getUserById`; the tokenizer here splits camelCase/snake_case |
| Reranker | `BAAI/bge-reranker-base` cross-encoder | local, free, the second stage a bi-encoder can't do |
| Metadata | SQLite | symbols, chunks, files in one inspectable file |
| Generation | OpenAI (`gpt-4o-mini`), swappable | isolated behind one function — the least interesting part of the system |
| Frameworks | no LangChain, no LlamaIndex | the retrieval core is the evidence; wrapping it in a framework deletes the evidence |
| Frontend | one HTML file | the demo is a walkthrough, not a product |

Full decision history: [docs/DECISIONS.md](docs/DECISIONS.md). Day-by-day build log: [docs/ROADMAP.md](docs/ROADMAP.md).

## Results

Full tables, methodology, and reproduction commands: [eval/results/](eval/results/). Summary below.

### Retriever comparison (file-level R@1 / R@5 / MRR, all question types)

| repo | bm25 | dense | hybrid | hybrid+rerank |
|---|---|---|---|---|
| requests (Repo B) | 21.1% / 52.6% / 0.361 | 47.4% / 94.7% / 0.652 | 26.3% / 84.2% / 0.505 | 42.1% / 84.2% / 0.586 |
| fitness-tracker (Repo A) | 38.5% / 69.2% / 0.520 | 76.9% / 92.3% / 0.837 | 76.9% / 92.3% / 0.815 | 69.2% / 92.3% / 0.796 |

**Dense is the strongest single retriever on both repos.** Hybrid (RRF) does *not* uniformly beat it — on `requests` it underperforms dense at R@1 by 21 points, because reciprocal rank fusion dilutes a strong dense signal when BM25 disagrees. Reranking partially recovers that loss but isn't uniformly beneficial either (see [Limitations](#limitations)). Full breakdown by question type: [`retriever_ablation.md`](eval/results/retriever_ablation.md).

### Chunking ablation: AST (cAST-style) vs. fixed-size, `hybrid+rerank`

| repo | metric | AST | fixed |
|---|---|---|---|
| requests | symbol-level R@1 / MRR | 15.8% / 0.239 | 0.0% / 0.033 |
| fitness-tracker | symbol-level R@1 / MRR | 23.1% / 0.282 | 0.0% / 0.131 |

File-level recall is nearly identical between the two chunkers on both repos. Symbol-level recall — does the retrieved chunk carry the *exact* right function/method — collapses to 0% R@1 under fixed-size chunking on both repos. Details: [`chunking_ablation.md`](eval/results/chunking_ablation.md).

### Header ablation: on (file + imports + symbol) vs. off (raw text only)

Mixed, repo-dependent result — not a clean win or loss either way. On `requests`, removing the header roughly doubles concept-type dense R@1 (20% → 60%), confirming a real embedding-dilution effect from long, often-irrelevant import blocks. On `fitness-tracker`, removing the header *hurts* almost every retriever (`hybrid+rerank` R@1 drops 23 points), likely because its files are small enough that the header's import block is short and actually relevant. Full numbers and a labeled hypothesis for the divergence: [`header_ablation.md`](eval/results/header_ablation.md).

### Held-out Repo C (`Textualize/rich`) — never opened until this step

| repo | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|
| requests | 42.1% | 84.2% | 94.7% | 0.586 |
| fitness-tracker | 69.2% | 92.3% | 100.0% | 0.796 |
| **rich (held-out)** | **37.5%** | **62.5%** | **87.5%** | **0.542** |

Overall numbers land close to `requests`, not a collapse. The honest finding: **concept-type R@1 is 0.0% for every retriever, including the shipped default**, on both concept questions written for this repo (n=2, so read directionally, not precisely). Symbol and howto questions held up better. This is reported separately from Repo A/B on purpose — see [`repo_c_heldout.md`](eval/results/repo_c_heldout.md) for the full writeup and how the 8 questions were written blind before any retrieval was run.

## Limitations

Reported the same way the results are: honestly, not smoothed over.

- **Chunk headers can dilute dense retrieval similarity**, sometimes badly (one case moved a correct answer from rank 1 to rank 6 by prepending unrelated import lines), and the effect *reverses direction* between repos — there's no global on/off setting that's correct everywhere. A per-file or per-chunk-size-aware header policy would likely help; not built.
- **Hybrid (RRF) fusion does not uniformly beat its best single input.** When dense is clearly the stronger retriever, naive rank-based fusion with a weaker BM25 signal can dilute it rather than help. A confidence-aware fusion scheme could address this; not implemented.
- **Symbol-level recall runs well below file-level recall for every retriever**, an expected consequence of AST sibling-merging (a chunk can span several symbols, or only part of a large one) rather than a retrieval failure — but it means "cites the right file" is a much easier bar to clear than "cites the exact right function."
- **The groundedness gate adds a full extra LLM call to every question**, before the answer-generation call. It was necessary — retrieval-confidence thresholds (rerank score, BM25 score) were tried first and measurably failed to separate real questions from fabrication-inducing ones — but it roughly doubles latency and generation cost per question.
- **The index is static.** There's no incremental re-indexing: a changed file means re-running `build_index.py` for the whole repo. Fine for a demo/eval tool: not fine for a repo that changes hourly.
- **Only Python and JavaScript/TypeScript/TSX are fully supported** (symbol extraction, AST chunking). A third language was deliberately deferred (see `docs/ROADMAP.md`, Day 7) since neither eval repo needed it. Unsupported languages still get indexed via the fixed-size fallback chunker, just without symbol-aware citations.

## Running it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# .env with a real key:
echo "OPENAI_API_KEY=sk-..." > .env

# ingest a repo (local path or a git URL)
python scripts/build_index.py <repo-path-or-url>

# ask a question end to end (retrieve -> expand -> groundedness gate -> answer)
python scripts/demo.py

# run the eval harness
python eval/run_eval.py <repo-name>

# serve the API + web UI
uvicorn app.api:app --reload
# then open http://127.0.0.1:8000
```

`POST /ingest`, `POST /ask` (repo + question, optional conversation history), `GET /symbols?q=` — see [app/api.py](app/api.py).
