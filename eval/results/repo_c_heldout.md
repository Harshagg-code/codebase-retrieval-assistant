# Repo C (Textualize/rich) — held-out results

**These results are reported separately and are never blended into Repo A/B's averages.** Repo C was never opened, indexed, or evaluated until Day 5 Stage 4. Its 8 golden questions were written blind — from reading `rich`'s source directly, before running any retrieval against it — using the same methodology and difficulty spread as the other 32 (see `docs/DECISIONS.md`, 2026-09-19, and the entries below for how each question was chosen). This is the number that answers whether the system generalizes, or was just tuned to look good on the two repos it was iterated against.

Reproduce with:

```bash
python scripts/build_index.py data/repos/rich
python eval/check_golden.py             # confirms all 40 questions (32 + 8) resolve
python eval/run_eval.py rich
```

Config: AST chunker, headers on — the shipped default, per Stages 1-3 (fixed-size chunking showed no file-level benefit and a clear symbol-level cost; headers showed no consistent win/loss direction across repos, so there's no principled reason to deviate from default here).

**Caveat: n=2 per question type.** Each question swings its type's recall rate by 50 percentage points, so per-type numbers below are noisy signals, not precise estimates — read them as directional, not exact.

## File-level (primary)

| retriever | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| bm25 | all | 8 | 12.5% | 12.5% | 37.5% | 0.182 |
| bm25 | symbol | 2 | 0.0% | 0.0% | 0.0% | 0.057 |
| bm25 | concept | 2 | 0.0% | 0.0% | 50.0% | 0.056 |
| bm25 | flow | 2 | 50.0% | 50.0% | 50.0% | 0.520 |
| bm25 | howto | 2 | 0.0% | 0.0% | 50.0% | 0.094 |
| dense | all | 8 | 37.5% | 75.0% | 100.0% | 0.568 |
| dense | symbol | 2 | 100.0% | 100.0% | 100.0% | 1.000 |
| dense | concept | 2 | 0.0% | 50.0% | 100.0% | 0.208 |
| dense | flow | 2 | 0.0% | 100.0% | 100.0% | 0.500 |
| dense | howto | 2 | 50.0% | 50.0% | 100.0% | 0.562 |
| hybrid | all | 8 | 25.0% | 62.5% | 87.5% | 0.445 |
| hybrid | symbol | 2 | 50.0% | 100.0% | 100.0% | 0.625 |
| hybrid | concept | 2 | 0.0% | 50.0% | 50.0% | 0.276 |
| hybrid | flow | 2 | 0.0% | 50.0% | 100.0% | 0.321 |
| hybrid | howto | 2 | 50.0% | 50.0% | 100.0% | 0.556 |
| hybrid+rerank | all | 8 | 37.5% | 62.5% | 87.5% | 0.542 |
| hybrid+rerank | symbol | 2 | 100.0% | 100.0% | 100.0% | 1.000 |
| hybrid+rerank | concept | 2 | 0.0% | 50.0% | 50.0% | 0.250 |
| hybrid+rerank | flow | 2 | 0.0% | 50.0% | 100.0% | 0.333 |
| hybrid+rerank | howto | 2 | 50.0% | 50.0% | 100.0% | 0.583 |

## Symbol-level (secondary)

| retriever | type | n | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| bm25 | all | 8 | 0.0% | 12.5% | 12.5% | 0.045 |
| dense | all | 8 | 12.5% | 25.0% | 50.0% | 0.197 |
| hybrid | all | 8 | 12.5% | 25.0% | 50.0% | 0.190 |
| hybrid+rerank | all | 8 | 25.0% | 25.0% | 37.5% | 0.271 |

(per-type symbol-level rows omitted here for space -- see raw `run_eval.py rich` output; same n=2 noise caveat applies even more sharply at this stricter granularity.)

## Comparison to Repo A/B (shipped config, `hybrid+rerank`, file-level, all types)

| repo | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|
| requests (Repo B) | 42.1% | 84.2% | 94.7% | 0.586 |
| fitness-tracker (Repo A) | 69.2% | 92.3% | 100.0% | 0.796 |
| **rich (Repo C, held-out)** | **37.5%** | **62.5%** | **87.5%** | **0.542** |

## Honest read

Repo C's overall R@1 (37.5%) and MRR (0.542) land close to `requests`' numbers and noticeably below `fitness-tracker`'s -- not a collapse, but not the ceiling either. The more telling signal is per-type: **concept-type R@1 is 0.0% for every single retriever, including the shipped `hybrid+rerank`** -- both concept questions (`c-003` on `Color.parse`'s format-detection logic, `c-004` on `Style.__str__`'s bitflag-to-string conversion) failed to rank their gold file first with any retriever, though 50% did land it in the top 5. Flow-type R@1 is also 0.0% for every retriever except BM25 (50%). Symbol and howto held up better, largely matching Repo A/B's pattern of "easy, keyword-adjacent questions retrieve well; questions requiring genuine conceptual understanding are harder."

Given n=2 per type, this shouldn't be read as "the system fails at concept questions on new repos" -- it's two data points. But it's also not being smoothed over: the shipped default genuinely didn't get either concept question's file ranked first on a repo it was never tuned against, and that's exactly the kind of result this held-out step exists to surface rather than hide.
