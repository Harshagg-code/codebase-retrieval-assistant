# Retriever ablation: bm25 / dense / hybrid / hybrid+rerank

Reproduce with:

```bash
python eval/run_eval.py requests
python eval/run_eval.py fitness-tracker
```

32 golden questions (19 on `requests`, 13 on `fitness-tracker`), 8 per type (symbol/concept/flow/howto). File-level recall is primary (does the retrieved chunk come from the right file); symbol-level is secondary (does it carry the exact gold `symbol_id`) — see `docs/DECISIONS.md` for why symbol-level recall runs structurally lower. `hybrid+rerank` returns at most 8 results, so its recall@10 is capped at recall@8.

## requests (Repo B)

### File-level (primary)

| retriever | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| bm25 | all | 19 | 21.1% | 52.6% | 73.7% | 0.361 |
| bm25 | symbol | 5 | 20.0% | 100.0% | 100.0% | 0.507 |
| bm25 | concept | 5 | 20.0% | 40.0% | 80.0% | 0.300 |
| bm25 | flow | 5 | 20.0% | 40.0% | 40.0% | 0.296 |
| bm25 | howto | 4 | 25.0% | 25.0% | 75.0% | 0.338 |
| dense | all | 19 | **47.4%** | **94.7%** | 100.0% | **0.652** |
| dense | symbol | 5 | 80.0% | 100.0% | 100.0% | 0.900 |
| dense | concept | 5 | 20.0% | 100.0% | 100.0% | 0.457 |
| dense | flow | 5 | 60.0% | 100.0% | 100.0% | 0.750 |
| dense | howto | 4 | 25.0% | 75.0% | 100.0% | 0.463 |
| hybrid | all | 19 | 26.3% | 84.2% | 94.7% | 0.505 |
| hybrid | symbol | 5 | 40.0% | 100.0% | 100.0% | 0.650 |
| hybrid | concept | 5 | 0.0% | 80.0% | 100.0% | 0.335 |
| hybrid | flow | 5 | 40.0% | 80.0% | 80.0% | 0.565 |
| hybrid | howto | 4 | 25.0% | 75.0% | 100.0% | 0.461 |
| hybrid+rerank | all | 19 | 42.1% | 84.2% | 94.7% | 0.586 |
| hybrid+rerank | symbol | 5 | 80.0% | 100.0% | 100.0% | 0.840 |
| hybrid+rerank | concept | 5 | 40.0% | 80.0% | 80.0% | 0.550 |
| hybrid+rerank | flow | 5 | 40.0% | 100.0% | 100.0% | 0.633 |
| hybrid+rerank | howto | 4 | 0.0% | 50.0% | 100.0% | 0.252 |

### Symbol-level (secondary)

| retriever | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| bm25 | all | 19 | 0.0% | 26.3% | 26.3% | 0.077 |
| bm25 | symbol | 5 | 0.0% | 40.0% | 40.0% | 0.107 |
| bm25 | concept | 5 | 0.0% | 40.0% | 40.0% | 0.108 |
| bm25 | flow | 5 | 0.0% | 20.0% | 20.0% | 0.077 |
| bm25 | howto | 4 | 0.0% | 0.0% | 0.0% | 0.000 |
| dense | all | 19 | 15.8% | 36.8% | 57.9% | 0.264 |
| dense | symbol | 5 | 20.0% | 20.0% | 40.0% | 0.222 |
| dense | concept | 5 | 0.0% | 40.0% | 80.0% | 0.233 |
| dense | flow | 5 | 40.0% | 80.0% | 80.0% | 0.528 |
| dense | howto | 4 | 0.0% | 0.0% | 25.0% | 0.025 |
| hybrid | all | 19 | 5.3% | 31.6% | 36.8% | 0.158 |
| hybrid | symbol | 5 | 0.0% | 40.0% | 40.0% | 0.150 |
| hybrid | concept | 5 | 0.0% | 60.0% | 60.0% | 0.182 |
| hybrid | flow | 5 | 20.0% | 20.0% | 40.0% | 0.261 |
| hybrid | howto | 4 | 0.0% | 0.0% | 0.0% | 0.011 |
| hybrid+rerank | all | 19 | 15.8% | 36.8% | 42.1% | 0.239 |
| hybrid+rerank | symbol | 5 | 20.0% | 40.0% | 40.0% | 0.240 |
| hybrid+rerank | concept | 5 | 20.0% | 20.0% | 20.0% | 0.200 |
| hybrid+rerank | flow | 5 | 20.0% | 80.0% | 80.0% | 0.433 |
| hybrid+rerank | howto | 4 | 0.0% | 0.0% | 25.0% | 0.042 |

## fitness-tracker (Repo A)

### File-level (primary)

| retriever | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| bm25 | all | 13 | 38.5% | 69.2% | 84.6% | 0.520 |
| bm25 | symbol | 3 | 33.3% | 66.7% | 100.0% | 0.542 |
| bm25 | concept | 3 | 66.7% | 100.0% | 100.0% | 0.733 |
| bm25 | flow | 3 | 33.3% | 66.7% | 66.7% | 0.457 |
| bm25 | howto | 4 | 25.0% | 50.0% | 75.0% | 0.391 |
| dense | all | 13 | **76.9%** | 92.3% | 92.3% | **0.837** |
| dense | symbol | 3 | 100.0% | 100.0% | 100.0% | 1.000 |
| dense | concept | 3 | 66.7% | 100.0% | 100.0% | 0.778 |
| dense | flow | 3 | 100.0% | 100.0% | 100.0% | 1.000 |
| dense | howto | 4 | 50.0% | 75.0% | 75.0% | 0.637 |
| hybrid | all | 13 | 76.9% | 92.3% | 100.0% | 0.815 |
| hybrid | symbol | 3 | 100.0% | 100.0% | 100.0% | 1.000 |
| hybrid | concept | 3 | 66.7% | 100.0% | 100.0% | 0.750 |
| hybrid | flow | 3 | 66.7% | 100.0% | 100.0% | 0.733 |
| hybrid | howto | 4 | 75.0% | 75.0% | 100.0% | 0.786 |
| hybrid+rerank | all | 13 | 69.2% | 92.3% | 100.0% | 0.796 |
| hybrid+rerank | symbol | 3 | 100.0% | 100.0% | 100.0% | 1.000 |
| hybrid+rerank | concept | 3 | 66.7% | 66.7% | 100.0% | 0.714 |
| hybrid+rerank | flow | 3 | 66.7% | 100.0% | 100.0% | 0.833 |
| hybrid+rerank | howto | 4 | 50.0% | 100.0% | 100.0% | 0.675 |

### Symbol-level (secondary)

| retriever | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| bm25 | all | 13 | 23.1% | 46.2% | 46.2% | 0.328 |
| bm25 | symbol | 3 | 0.0% | 33.3% | 33.3% | 0.167 |
| bm25 | concept | 3 | 66.7% | 66.7% | 66.7% | 0.667 |
| bm25 | flow | 3 | 0.0% | 33.3% | 33.3% | 0.141 |
| bm25 | howto | 4 | 25.0% | 50.0% | 50.0% | 0.333 |
| dense | all | 13 | 53.8% | 53.8% | 53.8% | 0.538 |
| dense | symbol | 3 | 33.3% | 33.3% | 33.3% | 0.333 |
| dense | concept | 3 | 66.7% | 66.7% | 66.7% | 0.667 |
| dense | flow | 3 | 66.7% | 66.7% | 66.7% | 0.667 |
| dense | howto | 4 | 50.0% | 50.0% | 50.0% | 0.500 |
| hybrid | all | 13 | 46.2% | 53.8% | 53.8% | 0.487 |
| hybrid | symbol | 3 | 33.3% | 33.3% | 33.3% | 0.333 |
| hybrid | concept | 3 | 66.7% | 66.7% | 66.7% | 0.667 |
| hybrid | flow | 3 | 33.3% | 66.7% | 66.7% | 0.444 |
| hybrid | howto | 4 | 50.0% | 50.0% | 50.0% | 0.500 |
| hybrid+rerank | all | 13 | 23.1% | 38.5% | 38.5% | 0.282 |
| hybrid+rerank | symbol | 3 | 33.3% | 33.3% | 33.3% | 0.333 |
| hybrid+rerank | concept | 3 | 33.3% | 33.3% | 33.3% | 0.333 |
| hybrid+rerank | flow | 3 | 0.0% | 33.3% | 33.3% | 0.111 |
| hybrid+rerank | howto | 4 | 25.0% | 50.0% | 50.0% | 0.333 |

## Takeaways

- **Dense is the strongest single retriever on both repos** at file-level R@1 (47.4% / 76.9%), well ahead of BM25 (21.1% / 38.5%) — expected, since several golden questions were deliberately written with no keyword overlap with their target.
- **Hybrid does not uniformly beat its best single input.** On `requests`, dense alone beats hybrid at R@1 (47.4% vs. 26.3%) — RRF fusion dilutes a strong dense signal when BM25 disagrees on ranking. See `docs/DECISIONS.md` (2026-09-20) for the full root-cause writeup.
- **Reranking is not uniformly beneficial either.** It recovers some of hybrid's R@1 loss on `requests` (26.3% → 42.1%), but on the smaller `fitness-tracker` repo it *hurts* symbol-level R@1 relative to plain hybrid (23.1% vs. 46.2%) — likely too few real candidates for the cross-encoder to meaningfully re-order.
- **Symbol-level recall runs well below file-level recall for every retriever on both repos** — an expected consequence of the chunking design (sibling-merged chunks don't always carry one exact `symbol_id`), not a retrieval failure.
