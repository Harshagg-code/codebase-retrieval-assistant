# Decisions log

Architectural decisions made during the build, in the order they were settled. The Day 0 decisions (language, embeddings, vector store, etc.) are recorded in `docs/PROJECT.md` since they were locked before the build started; this log picks up from there.

Entry format:

```
## YYYY-MM-DD — <decision>
**Context:** why this came up
**Decision:** what we chose
**Alternatives considered:** what we didn't pick and why
```

## 2026-09-17 — Eval repo selection

**Context:** Day 0 requires three eval repos spanning a known codebase, a standard OSS target, and a genuinely held-out repo, so retrieval quality can be measured honestly rather than tuned to look good.

**Decision:** Cloned into `data/repos/`:
- **Repo A** — [`Harshagg-code/fitness-tracker`](https://github.com/Harshagg-code/fitness-tracker) — own MERN project, known codebase, cheap to label since the code and intent are already familiar.
- **Repo B** — [`psf/requests`](https://github.com/psf/requests) — standard, well-documented Python target with a clean, idiomatic codebase to test retrieval against.
- **Repo C** — [`Textualize/rich`](https://github.com/Textualize/rich) — held out, never opened or tuned against, reported separately for honest final numbers.

**Alternatives considered:** `pallets/flask` and `encode/httpx` were the other candidates for Repo B; `requests` was picked for its smaller, more contained surface area, which keeps early labeling effort manageable.

## 2026-09-19 — Known limitation: re-chunking a repo with a different `--chunker` wipes the other variant

**Context:** `chunks.chunker` ('ast' vs 'fixed') was added so Day 5's ablation could compare both chunking strategies from one table. But `files` is upserted with `INSERT OR REPLACE` keyed on `(repo, path)`, and `chunks`/`symbols` cascade-delete on that file's id. Re-running `build_index.py` against the *same* repo name with a different `--chunker` replaces the file row, which cascades away **all** of that file's chunks -- including the other chunker's -- not just the ones being replaced.

**Decision:** Accept this as a known limitation for now rather than redesign the cascade to be chunker-scoped. Verified workaround: run each chunker variant under a distinct `--repo-name` (e.g. `requests` for the AST run, `requests-fixed` for the fixed-window run) so both sets of file/symbol/chunk rows coexist under different `repo` values instead of colliding on the same one. This duplicates `files`/`symbols` rows per variant, which is acceptable at this repo scale. We'll apply this workaround when Day 5's ablation actually runs both chunkers side by side; the underlying cascade behavior is not being changed now.

**Alternatives considered:** Scoping the cascade delete to `(file_id, chunker)` instead of `file_id` so both variants could share one repo name and be replaced independently -- deferred as unnecessary complexity until Day 5 shows it's actually needed.

## 2026-09-19 — Golden question set written

**Context:** Day 2 requires a labelled evaluation set spread across question types (symbol / concept / flow / howto) so retrieval strategies can be compared against ground truth rather than eyeballed.

**Decision:** Wrote 32 questions into `eval/golden.jsonl` -- 8 per type (symbol, concept, flow, howto), 19 against Repo B (`requests`) and 13 against Repo A (`fitness-tracker`). Every `gold_file` and `gold_symbol` reference was verified against the real indexed data rather than written from memory, including two genuine same-file name collisions (`adapters.py`'s `BaseAdapter.send`/`HTTPAdapter.send`, `models.py`'s `Request.prepare`/`PreparedRequest.prepare`), which extended the `gold_symbols` format from plain `path:name` to `path:Class.method` where needed. Verification is now a committed script, `eval/check_golden.py`, rather than a one-off check -- it confirms every gold file/symbol resolves in the index and that no entry references repo `rich` (Repo C stays untouched until eval day). Repo C remains completely unindexed and unreferenced.

**Alternatives considered:** Keeping the golden set purely Python (Repo B) for simplicity -- rejected in favor of including Repo A (JS/JSX) so the eval set isn't blind to the language-generalization question the project also cares about.

## 2026-09-20 — Finding: chunk headers can dilute dense retrieval on short functions

**Context:** Day 3 tested dense retrieval on b-002, the concept question specifically designed to have no keyword overlap with its target (`should_strip_auth`). The gold chunk ranked 6th, just outside top-5, despite the function's own docstring closely paraphrasing the question.

**Decision:** Diagnosed rather than patched. Encoding the chunk without its header (file path + ~10 lines of unrelated top-level imports) raises cosine similarity to the query from 0.697 to 0.822 -- enough to move it from rank 6 to rank 1 on its own. Left the header design unchanged, since Day 5's roadmap already plans a "header on vs. off" ablation, and this result is exactly the effect that ablation exists to measure. Patching it now would remove the thing being measured.

**Alternatives considered:** Stripping or shortening the header immediately -- rejected as premature; the header's value (cross-file context, symbol attribution) is a real tradeoff that deserves a proper ablation number rather than an ad hoc fix based on one question.

## 2026-09-20 — Finding: hybrid (RRF) does not uniformly beat its best single input

**Context:** The Day 3 eval harness ran all 32 golden questions through bm25, dense, hybrid, and hybrid+rerank on both repos.

**Decision:** Recorded as an honest result rather than treated as a bug. On `requests`, dense alone beat hybrid at file-level R@1 (47.4% vs. 26.3%) -- reciprocal rank fusion diluted a strong dense signal when BM25 disagreed on ranking. This matches a documented property of RRF in the broader retrieval literature: vanilla RRF assumes its inputs are roughly equally trustworthy, and dilutes a clearly stronger ranker when that assumption doesn't hold. (Not verified: an earlier draft of this entry attributed this specifically to Sourcegraph/Cline's own retrieval work; a web search found no evidence for that specific attribution, so it's been dropped rather than stated as fact.)

**Alternatives considered:** None yet -- this is a measurement to report, not a design decision to make. A weighted or confidence-aware fusion scheme could address it, but that's out of scope unless the Day 5 ablation shows it's worth pursuing.

## 2026-09-20 — Finding: cross-encoder reranking is not uniformly beneficial

**Context:** Same Day 3 eval run. Reranking was expected to be a strict improvement over hybrid, per the architecture's "reciprocal rank fusion → cross-encoder rerank" pipeline.

**Decision:** Recorded honestly. Reranking clearly helped in the case demonstrated during Stage 6 (b-002: fused rank 3 -> reranked rank 1, with a decisive score gap). But on the full eval table for the smaller `fitness-tracker` repo, hybrid+rerank's symbol-level R@1 (23.1%) was worse than plain hybrid (46.2%) -- likely because a repo with far fewer real candidates gives the cross-encoder less genuine signal to re-order against, so it can shuffle a few correct answers out of the top ranks instead of in.

**Alternatives considered:** None yet -- flagged as a real result for the Day 5 ablation writeup, not something to tune away today.

## 2026-09-20 — Finding: symbol-level recall is structurally much lower than file-level recall

**Context:** Same Day 3 eval run, comparing the file-level (primary) and symbol-level (secondary) metrics side by side.

**Decision:** Recorded as an expected consequence of the chunking/linking design, not a retrieval failure. Symbol-level recall requires a retrieved chunk's exact `symbol_id` to match a gold symbol; chunks that merge multiple sibling symbols (Day 2's sibling-merging behavior) or that only partially cover the enclosing class end up with a `symbol_id` that doesn't exactly match what the question asked for, even when the retrieved text is genuinely relevant. File-level recall doesn't have this problem since it only checks the file path. This gap held across every retriever on both repos.

**Alternatives considered:** None -- this is presented as a measurement clarifying what "symbol-level" recall can and can't capture given the chunking design, for whoever reads the Day 5 results later.

## 2026-09-21 — Finding + fix: retrieval-confidence thresholds can't gate abstention; an LLM groundedness check can

**Context:** Day 4's abstention check (a required pass/fail test, not a formality) asked two genuinely unanswerable questions: whether `requests` supports batching GraphQL queries (it has zero GraphQL support or references), and whether `fitness-tracker` syncs with Apple HealthKit (it only talks to its own backend API). Both produced confident, fully-cited, but fabricated answers -- the model took real, topically-adjacent evidence (multi-file upload code; the app's own weight-tracking API calls) and spun it into a plausible-sounding but false claim about the specific thing asked. Every citation in both answers was individually accurate; the claims built on top of them were not. This is exactly the failure mode CLAUDE.md's own conventions warn about: abstaining honestly instead of fabricating.

**Decision:** Two threshold-based fixes were tried and measured before landing on one that works.

- *Attempt 1 -- rerank score threshold.* Measured the top cross-encoder score for both fabrication cases (GraphQL: 0.5655, HealthKit: 0.6746) against all 32 real golden questions' top scores (range 0.007-0.998, median 0.720). 13/32 real questions scored below GraphQL's fabrication score and 15/32 scored below HealthKit's -- including `a-001`, a real question that gets a correct, fully-cited answer, at 0.132. No threshold separates real from fake without blocking 40%+ of legitimate questions. Rejected.
- *Attempt 2 -- BM25 score threshold.* Same test with BM25's top score: GraphQL scored 20.29, HealthKit 17.01, both squarely inside the real question range (10.3-20.2), with real question `b-001` scoring 20.10 -- essentially tied with GraphQL's fabrication. Also rejected. Root cause for both: a retrieval confidence score measures "is this text topically related to the query's other words," not "does this evidence establish the specific claim is true" -- a query can share plenty of vocabulary with genuinely irrelevant evidence (weight-tracking API calls share vocabulary with a HealthKit question; a file-upload example shares vocabulary with a GraphQL-batching question).
- *Fix that worked -- LLM-based groundedness gate.* Added `check_groundedness()` in `app/answer.py`: a separate, cheap LLM call, before generation, given the question and the same retrieved+expanded evidence, forced into a structured `{"grounded": bool, "reason": str}` JSON response via `response_format={"type": "json_object"}`, explicitly instructed to be strict about topical-adjacency-is-not-groundedness. If ungrounded, `answer_question()` returns an abstention message directly and skips generation entirely. Retested: both fabrication cases now correctly abstain with accurate stated reasons, and all 4 retested passing questions (including `a-001`, the lowest-rerank-scoring real question in the whole set) still answer normally and correctly.

**Alternatives considered:** Strengthening the main answer prompt's abstention wording instead of adding a separate gate -- not tried, since the two measured threshold failures showed the problem is about detecting *what the evidence actually establishes*, which needs the model to reason over content, not just a stricter instruction on the same single generation pass. A separate gate call also keeps the main answer prompt's job (cite accurately, order multi-file claims) unentangled from this different job (judge relevance).

## 2026-09-21 — Bug: embedded Qdrant crashes on a second client for the same path

**Context:** Building Day 4's `answer_question()` pipeline, testing the first real end-to-end question threw `RuntimeError: Storage folder data/qdrant is already accessed by another instance of Qdrant client`.

**Decision:** Root cause: `answer_question()` and `retrieve_and_expand()` each independently called `get_qdrant_client()`, and embedded (local file-based) Qdrant holds an exclusive file lock on its storage path -- a second `QdrantClient` instance pointing at the same path, even within the same process, can't open it while the first is alive. Fixed with a per-path client cache in `app/dense.py::get_qdrant_client()`, mirroring the existing embedding-model cache pattern, so repeated calls reuse one client instead of opening a new one. This also protects the FastAPI server (Stage 6) from hitting the same crash across requests or across endpoints that each touch Qdrant.

**Alternatives considered:** Threading a single client through every function's parameters instead of caching -- rejected as more invasive for the same result; the cache fixes it at the source for every current and future caller without changing any function signatures.

## 2026-09-21 — Known gap: flow-question answers under-cite relative to how many claims they make

**Context:** Stage 2's flow-question test (b-003, the `session.get(url)` → `request` → `send` → `resolve_redirects` sequence) produced a correct, well-ordered answer, but on inspection most of its individual factual claims (about `prepare_request`, `resolve_redirects` internals specifically) weren't each backed by their own citation -- only 2 distinct spans were cited across the whole multi-step answer, despite the system prompt's rule that *every* factual claim must end with a citation.

**Decision:** Logged as a known gap, not fixed today. The citation verifier as built only checks that citations *present* are accurate (which they were, in this case) -- it doesn't check citation *coverage*, i.e. whether every claim has one. This is a different quality dimension from what Stage 3 was designed to catch. Worth a look at whether the answer prompt needs a stronger, more specific instruction -- e.g. explicitly requiring one citation per numbered step in a multi-hop explanation, not just somewhere in the overall answer -- rather than relying on the current single general citation rule to naturally produce per-step density.

**Alternatives considered:** None yet -- flagged for whoever picks up prompt refinement next, rather than tuning it blind without a broader sample of multi-hop answers to check against.

## 2026-09-22 — Day 5 ablations: the four-finding story, and what it means for the shipped config

**Context:** Day 5 ran four ablations (retriever type, chunking strategy, header on/off, held-out Repo C) to decide whether the architecture's design choices actually earned their complexity, not just to fill in a results table. Full data in `eval/results/*.md`; this entry is the synthesis.

**Decision:** Ship the current default config unchanged (AST chunker, headers on, `hybrid+rerank`) -- not because every ablation showed it winning outright, but because no ablation showed a clearly better alternative, and each one surfaced a real, specific limitation worth documenting instead of quietly tuning away:

1. **Retriever ablation** — dense alone is the strongest single retriever on both Repo A and B; hybrid (RRF) does *not* uniformly beat it, and reranking doesn't uniformly beat hybrid either. Shipping `hybrid+rerank` anyway because it's the most *consistent* performer across question types and repos, even where it isn't the single best -- dense's advantage is real but narrower (concept/flow questions) than a raw R@1 comparison suggests, per the type breakdown in `retriever_ablation.md`.
2. **Chunking ablation** — the cAST-style AST splitter was worth building, but its value is concentrated entirely in symbol-level recall (which collapses to 0% R@1 under fixed-size chunking on both repos); file-level recall barely cares which chunker is used. This means the AST chunker's real payoff is precise citations, not raw retrieval hit rate.
3. **Header ablation** — the dilution effect found on Day 3 is real and reproduces at scale on `requests`, but it *reverses direction* on `fitness-tracker`, where headers help. No global on/off setting is correct for both repos tested, so headers stay on (the status quo) rather than being flipped off based on a result that doesn't generalize even across two repos.
4. **Repo C, held out** — overall numbers on `rich` land close to `requests`, not a collapse, but concept-type R@1 is 0.0% across every retriever on both concept questions written for it. This is the most important number in the whole ablation set: it's evidence the system's dense/hybrid gains on Repo A/B aren't simply overfit to those two codebases, while also honestly surfacing that concept-level understanding is the weakest link on genuinely new code.

The throughline across all four: **every "which config wins" question turned out to be repo-dependent or question-type-dependent, not universal.** That's the honest finding this project was designed to produce, per PLAN.md's original framing -- "a measured comparison of retrieval strategies... with the results reported honestly" -- rather than a single number claiming one architecture is simply better.

**Alternatives considered:** Picking a different default per-repo based on these results (e.g. fixed-size + no header for `requests`, AST + header for `fitness-tracker`) -- rejected as overfitting the shipped config to the exact two repos it was measured on, which is precisely the failure mode Repo C's held-out step exists to guard against.
