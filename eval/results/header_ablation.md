# Header ablation: headers ON (file + imports + enclosing symbol) vs. OFF (raw chunk text only)

Reproduce with:

```bash
python eval/run_eval.py requests                 # headers ON (default)
python eval/run_eval.py requests --no-header      # headers OFF

python eval/run_eval.py fitness-tracker
python eval/run_eval.py fitness-tracker --no-header
```

Day 3 found that a chunk's header (`docs/DECISIONS.md`, 2026-09-20) can dilute embedding similarity enough to push a correct answer out of top-5 -- the `b-002` case, concept question, no keyword overlap with its target, ranked 6th with headers on; stripping the header raised its cosine similarity from 0.697 to 0.822. This ablation measures whether that's a net loss across the whole eval set, or a local effect confined to specific cases.

**Result: it's not a net loss or gain either way -- it's repo-dependent, and the direction flips.**

## requests (Repo B) -- removing the header mostly *helps*

### File-level, all question types

| header | retriever | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|
| ON | bm25 | 21.1% | 52.6% | 73.7% | 0.361 |
| OFF | bm25 | 21.1% | 52.6% | 84.6% | 0.364 |
| ON | dense | 47.4% | 94.7% | 100.0% | 0.652 |
| OFF | dense | **52.6%** | 89.5% | 100.0% | **0.702** |
| ON | hybrid | 26.3% | 84.2% | 94.7% | 0.505 |
| OFF | hybrid | **42.1%** | 78.9% | 94.7% | **0.601** |
| ON | hybrid+rerank | 42.1% | 84.2% | 94.7% | 0.586 |
| OFF | hybrid+rerank | 42.1% | 84.2% | 94.7% | 0.602 |

### File-level, concept-type only (n=5) -- where Day 3's effect was found

| header | retriever | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|
| ON | dense | 20.0% | 100.0% | 100.0% | 0.457 |
| OFF | dense | **60.0%** | 80.0% | 100.0% | **0.733** |
| ON | hybrid | 0.0% | 80.0% | 100.0% | 0.335 |
| OFF | hybrid | **40.0%** | 80.0% | 100.0% | **0.579** |
| ON | hybrid+rerank | 40.0% | 80.0% | 80.0% | 0.550 |
| OFF | hybrid+rerank | 20.0% | 80.0% | 100.0% | 0.458 |

Confirms Day 3's finding at scale on dense and hybrid: concept-type R@1 more than doubles or triples with headers off. Note `hybrid+rerank` is the one exception even here -- it does *worse* without the header on this slice (40% -> 20% R@1), because the cross-encoder rerank step can use the header's file/symbol context to disambiguate in a way the bi-encoder embedding couldn't.

## fitness-tracker (Repo A) -- removing the header mostly *hurts*

### File-level, all question types

| header | retriever | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|
| ON | bm25 | 38.5% | 69.2% | 84.6% | 0.520 |
| OFF | bm25 | 38.5% | 69.2% | 84.6% | 0.501 |
| ON | dense | **76.9%** | 92.3% | 92.3% | **0.837** |
| OFF | dense | 69.2% | 84.6% | 92.3% | 0.774 |
| ON | hybrid | **76.9%** | 92.3% | 100.0% | **0.815** |
| OFF | hybrid | 61.5% | 92.3% | 92.3% | 0.724 |
| ON | hybrid+rerank | **69.2%** | 92.3% | 100.0% | **0.796** |
| OFF | hybrid+rerank | 46.2% | 84.6% | 84.6% | 0.608 |

Here headers ON win on every retriever except BM25 (roughly flat either way), sometimes by a wide margin (`hybrid+rerank` R@1 drops 23 points without the header).

## Why the direction flips: a hypothesis, not proven

`requests` files (`sessions.py`, `utils.py`) are large, with long, often barely-relevant import blocks (10+ lines) relative to a single chunked function -- exactly the dilution scenario Day 3 found. `fitness-tracker` files are small (controllers are 50-80 lines total), so their import blocks are short and directly relevant (e.g. importing the one model a function actually uses), and the header's `# in: function calculateCalories` line adds real disambiguating signal without much dilution cost, since there's little irrelevant text to dilute with. This wasn't tested directly (would need per-file header-length-vs-chunk-length correlation to confirm) -- flagged as a hypothesis for follow-up, not a conclusion.

## Takeaway

**Headers are not a uniform net win or net loss.** The effect is real (confirmed at scale on `requests`, reversed on `fitness-tracker`), and appears to depend on how much of a file's header content is actually relevant to the chunk it's attached to -- likely correlated with file size and import-block length relative to chunk size, though that correlation isn't verified here. This is not a case for simply flipping a global on/off switch; it's a case for a smarter, possibly per-file or per-chunk-size-aware header policy, which is out of scope for today.
