# Chunking ablation: AST (cAST-style) vs. fixed-size

Reproduce with:

```bash
# index a fixed-size variant under a distinct repo name (see docs/DECISIONS.md,
# 2026-09-19, for why the same repo name can't hold both chunker variants)
python scripts/build_index.py data/repos/requests --repo-name requests-fixed --chunker fixed
python scripts/build_index.py data/repos/fitness-tracker --repo-name fitness-tracker-fixed --chunker fixed

# evaluate the fixed variant using the original repo's golden questions
python eval/run_eval.py requests --index-repo-name requests-fixed --retriever hybrid+rerank
python eval/run_eval.py fitness-tracker --index-repo-name fitness-tracker-fixed --retriever hybrid+rerank
```

`hybrid+rerank` only (our default/best retriever), same 32 golden questions, same indexing pipeline otherwise -- only the chunk boundaries differ. AST results are `hybrid+rerank` rows from `retriever_ablation.md`.

## requests (Repo B)

### File-level (primary)

| chunker | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| AST | all | 19 | 42.1% | 84.2% | 94.7% | 0.586 |
| fixed | all | 19 | 42.1% | 78.9% | 94.7% | 0.591 |

### Symbol-level (secondary)

| chunker | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| AST | all | 19 | **15.8%** | **36.8%** | **42.1%** | **0.239** |
| fixed | all | 19 | 0.0% | 5.3% | 15.8% | 0.033 |

## fitness-tracker (Repo A)

### File-level (primary)

| chunker | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| AST | all | 13 | 69.2% | 92.3% | 100.0% | 0.796 |
| fixed | all | 13 | 69.2% | 92.3% | 100.0% | 0.778 |

### Symbol-level (secondary)

| chunker | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| AST | all | 13 | **23.1%** | 38.5% | 38.5% | **0.282** |
| fixed | all | 13 | 0.0% | 30.8% | 38.5% | 0.131 |

## Takeaway

**File-level recall is nearly identical between AST and fixed-size chunking on both repos** (within 0-5 points of each other, no consistent winner) -- at the "which file is this in" granularity, chunk boundaries barely matter, because the retriever and reranker can still recognize relevant content wherever the cut happens to fall.

**Symbol-level recall is where AST chunking earns its keep.** R@1 drops to exactly 0.0% under fixed-size chunking on *both* repos (from 15.8% and 23.1% under AST), and MRR drops by roughly 2-7x. This is the expected, direct consequence of what fixed-size chunking does: it cuts through function/class bodies at arbitrary character boundaries, so a chunk's line range rarely aligns cleanly with one symbol's full range -- `symbol_id` linking success dropped from 290/658 chunks (AST, `requests`) to 195/617 (fixed, `requests-fixed`), and even linked chunks are less likely to land inside the *specific* symbol a question asks about.

**Conclusion: the cAST-style splitter was worth building**, but its value is concentrated in symbol-precise retrieval, not file-level retrieval. A system that only needed "which file has the answer" wouldn't need it; one that needs "which specific function" does.
