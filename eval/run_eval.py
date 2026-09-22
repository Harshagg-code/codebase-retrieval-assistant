"""Day 3 eval harness: run every golden question for a repo through each
retriever (bm25 / dense / hybrid / hybrid+rerank), compute recall@1/5/10
and MRR at file level (primary) and symbol level (secondary), broken down
by question type, and print a results table.

Usage: python eval/run_eval.py <repo> [--retriever bm25,dense,hybrid,hybrid+rerank]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import REPOS_DIR, SQLITE_PATH
from app.dense import build_dense_index, dense_search, get_qdrant_client
from app.lexical import build_bm25_index, bm25_search
from app.retrieve import rerank, rrf
from app.store import get_indexable_chunks

GOLDEN_PATH = Path(__file__).resolve().parent / "golden.jsonl"
RETRIEVERS = ("bm25", "dense", "hybrid", "hybrid+rerank")
QUESTION_TYPES = ("symbol", "concept", "flow", "howto")
CANDIDATE_POOL = 50  # depth for bm25/dense/hybrid before slicing to recall@1/5/10
RERANK_TOP_K = 8      # hybrid+rerank's final list is capped here, so its
                       # recall@10 is structurally bounded by recall@8


def load_golden(repo: str) -> list[dict]:
    entries = [json.loads(line) for line in open(GOLDEN_PATH) if line.strip()]
    return [e for e in entries if e["repo"] == repo]


def resolve_gold_symbol_ids(conn: sqlite3.Connection, repo: str, gold_symbols: list[str]) -> set[int]:
    """Same 'path:name' / 'path:Class.method' resolution as check_golden.py."""
    ids: set[int] = set()
    for gold_symbol in gold_symbols:
        path, _, name_spec = gold_symbol.rpartition(":")
        if "." in name_spec:
            parent, _, name = name_spec.partition(".")
        else:
            parent, name = None, name_spec

        query = """
            SELECT s.id FROM symbols s JOIN files f ON f.id = s.file_id
            WHERE f.repo = ? AND f.path = ? AND s.name = ?
        """
        params = [repo, path, name]
        if parent is not None:
            query += " AND s.parent = ?"
            params.append(parent)

        ids.update(row[0] for row in conn.execute(query, params).fetchall())
    return ids


def compute_metrics(ranked: list[tuple[int, float]], by_id: dict, relevant: set[int] | set[str], key: str) -> dict:
    """relevant is either a set of gold_files (key='path') or gold symbol ids (key='symbol_id')."""
    hits = [1 if getattr(by_id[cid], key) in relevant else 0 for cid, _ in ranked]
    mrr = 0.0
    for i, hit in enumerate(hits, 1):
        if hit:
            mrr = 1.0 / i
            break
    return {
        "recall@1": 1 if any(hits[:1]) else 0,
        "recall@5": 1 if any(hits[:5]) else 0,
        "recall@10": 1 if any(hits[:10]) else 0,
        "mrr": mrr,
    }


def evaluate_repo(
    repo: str,
    db_path: Path = SQLITE_PATH,
    index_repo_name: str | None = None,
    include_header: bool = True,
) -> dict:
    """repo selects which golden questions to run (eval/golden.jsonl's `repo`
    field). index_repo_name, when different, selects which `files.repo` rows
    to actually build indexes from -- e.g. a 'requests-fixed' variant
    ingested separately with --chunker fixed (see docs/DECISIONS.md,
    2026-09-19, for why a distinct repo name is needed rather than
    overwriting `repo`'s own index).
    """
    index_repo = index_repo_name or repo
    repo_root = REPOS_DIR / repo
    conn = sqlite3.connect(db_path)

    chunks = get_indexable_chunks(conn, index_repo, repo_root, include_header=include_header)
    by_id = {c.chunk_id: c for c in chunks}
    bm25_index = build_bm25_index([c.chunk_id for c in chunks], [c.indexed_text for c in chunks])
    qdrant = get_qdrant_client()
    build_dense_index(qdrant, index_repo, chunks)

    questions = load_golden(repo)
    # results[retriever][level][type-or-"all"] -> list of per-question metric dicts
    results: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for q in questions:
        gold_files = set(q["gold_files"])
        gold_symbol_ids = resolve_gold_symbol_ids(conn, index_repo, q["gold_symbols"])

        bm25_r = bm25_search(bm25_index, q["question"], top_k=CANDIDATE_POOL)
        dense_r = dense_search(qdrant, index_repo, q["question"], top_k=CANDIDATE_POOL)
        fused_r = rrf([bm25_r, dense_r], top_k=CANDIDATE_POOL)
        candidates = [(cid, by_id[cid].indexed_text) for cid, _ in fused_r]
        reranked_r = rerank(q["question"], candidates, top_k=RERANK_TOP_K)

        rankings = {"bm25": bm25_r, "dense": dense_r, "hybrid": fused_r, "hybrid+rerank": reranked_r}

        for retriever, ranked in rankings.items():
            file_metrics = compute_metrics(ranked, by_id, gold_files, "path")
            symbol_metrics = compute_metrics(ranked, by_id, gold_symbol_ids, "symbol_id")
            for level, metrics in (("file", file_metrics), ("symbol", symbol_metrics)):
                results[retriever][level][q["type"]].append(metrics)
                results[retriever][level]["all"].append(metrics)

    conn.close()
    return results


def aggregate(metric_lists: list[dict]) -> dict | None:
    if not metric_lists:
        return None
    n = len(metric_lists)
    agg = {k: sum(m[k] for m in metric_lists) / n for k in ("recall@1", "recall@5", "recall@10", "mrr")}
    agg["n"] = n
    return agg


def print_table(repo: str, results: dict, retrievers: list[str]) -> None:
    print(f"=== Retrieval eval: {repo} ===")
    for level, label in (("file", "FILE-level (primary)"), ("symbol", "SYMBOL-level (secondary)")):
        print(f"\n-- {label} --")
        print(f"{'retriever':<15}{'type':<10}{'n':>4}{'R@1':>8}{'R@5':>8}{'R@10':>8}{'MRR':>8}")
        for retriever in retrievers:
            for qtype in ("all",) + QUESTION_TYPES:
                agg = aggregate(results[retriever][level][qtype])
                if agg is None:
                    continue
                print(
                    f"{retriever:<15}{qtype:<10}{agg['n']:>4}"
                    f"{agg['recall@1']*100:>7.1f}%{agg['recall@5']*100:>7.1f}%"
                    f"{agg['recall@10']*100:>7.1f}%{agg['mrr']:>8.3f}"
                )
    print(
        f"\nNote: hybrid+rerank returns at most {RERANK_TOP_K} results, "
        f"so its recall@10 is structurally capped at its recall@{RERANK_TOP_K} (== recall@10 here since 8 < 10)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="which golden question set to run (eval/golden.jsonl's repo field)")
    parser.add_argument("--retriever", default=",".join(RETRIEVERS))
    parser.add_argument(
        "--index-repo-name", default=None,
        help="build indexes from a differently-named files.repo (e.g. a --chunker fixed "
             "variant ingested under 'requests-fixed'); defaults to `repo`",
    )
    parser.add_argument(
        "--no-header", action="store_true",
        help="index raw chunk text only, skipping Day 2's header (file/imports/symbol) -- for the header ablation",
    )
    args = parser.parse_args()

    retrievers = [r.strip() for r in args.retriever.split(",")]
    for r in retrievers:
        if r not in RETRIEVERS:
            print(f"error: unknown retriever {r!r}, choose from {RETRIEVERS}", file=sys.stderr)
            sys.exit(1)

    results = evaluate_repo(
        args.repo, index_repo_name=args.index_repo_name, include_header=not args.no_header,
    )
    print_table(args.repo, results, retrievers)


if __name__ == "__main__":
    main()
