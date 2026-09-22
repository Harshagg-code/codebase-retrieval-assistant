"""CLI entrypoint: filter -> parse -> extract symbols -> chunk -> store, for one repo.

Usage: python scripts/build_index.py <repo_path_or_git_url> [--repo-name NAME] [--chunker ast|fixed]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.chunk import Chunk, chunk_ast, chunk_fixed
from app.config import LANGUAGE_BY_EXTENSION, SQLITE_PATH
from app.ingest import SKIP_REASONS, clone_repo, filter_files
from app.parse import Symbol, extract_symbols, parse_file
from app.store import connect, insert_chunks, insert_symbols, upsert_file

_SSH_URL_RE = re.compile(r"^[\w.\-]+@[\w.\-]+:.+")


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://") or bool(
        _SSH_URL_RE.match(value)
    )


def _link_symbol_ids(chunks: list[Chunk], symbol_rows: list[tuple[int, Symbol]]) -> None:
    """For each chunk, set symbol_id to the smallest symbol range that fully
    contains it (innermost enclosing symbol), or leave None if no symbol's
    range fully contains the chunk (e.g. it merges several sibling symbols).
    """
    for chunk in chunks:
        best_id = None
        best_span = None
        for symbol_id, symbol in symbol_rows:
            if symbol.start_line <= chunk.start_line and chunk.end_line <= symbol.end_line:
                span = symbol.end_line - symbol.start_line
                if best_span is None or span < best_span:
                    best_id = symbol_id
                    best_span = span
        chunk.symbol_id = best_id


@dataclass
class IngestStats:
    repo_name: str
    files_scanned: int
    files_kept: int
    files_skipped: int
    skipped_by_reason: dict[str, int]
    files_with_symbols: int
    files_chunked_only: int
    parse_errors: int
    parse_error_details: list[str]
    symbols_found: int
    symbols_by_language: dict[str, int] = field(default_factory=dict)
    symbols_by_kind: dict[str, int] = field(default_factory=dict)
    chunks_created: int = 0
    chunks_by_chunker: dict[str, int] = field(default_factory=dict)
    chunks_linked_to_symbol: int = 0


def build_index(repo_path: Path, repo_name: str, db_path: Path, chunker: str) -> IngestStats:
    filter_result = filter_files(repo_path)

    conn = connect(db_path)
    symbols_by_language: Counter[str] = Counter()
    symbols_by_kind: Counter[str] = Counter()
    chunks_by_chunker: Counter[str] = Counter()
    chunks_linked_to_symbol = 0
    files_with_symbols = 0
    files_chunked_only = 0
    parse_errors: list[tuple[Path, Exception]] = []

    for rel in filter_result.kept:
        full_path = repo_path / rel
        source = full_path.read_bytes()
        language = LANGUAGE_BY_EXTENSION.get(rel.suffix.lower())

        symbols: list[Symbol] = []
        root = None
        if language is not None:
            try:
                root = parse_file(full_path, language)
                symbols = extract_symbols(root, source, str(rel), language)
            except Exception as exc:  # tree-sitter grammar issues, unreadable files, etc.
                parse_errors.append((rel, exc))
                continue

        file_id = upsert_file(
            conn, repo=repo_name, path=str(rel), language=language or "text", size_bytes=len(source)
        )

        symbol_ids = insert_symbols(conn, file_id, symbols) if symbols else []
        symbol_rows = list(zip(symbol_ids, symbols))

        if root is not None and chunker == "ast":
            chunks = chunk_ast(root, source, str(rel))
            chunker_used = "ast"
        else:
            text = source.decode("utf-8", errors="replace")
            chunks = chunk_fixed(text, str(rel))
            chunker_used = "fixed"

        _link_symbol_ids(chunks, symbol_rows)
        insert_chunks(conn, file_id, chunks, chunker_used)

        chunks_by_chunker[chunker_used] += len(chunks)
        chunks_linked_to_symbol += sum(1 for c in chunks if c.symbol_id is not None)

        if language is not None:
            files_with_symbols += 1
            symbols_by_language[language] += len(symbols)
            for symbol in symbols:
                symbols_by_kind[symbol.kind] += 1
        else:
            files_chunked_only += 1

    conn.close()

    total_skipped = sum(len(paths) for paths in filter_result.skipped.values())
    total_scanned = len(filter_result.kept) + total_skipped

    return IngestStats(
        repo_name=repo_name,
        files_scanned=total_scanned,
        files_kept=len(filter_result.kept),
        files_skipped=total_skipped,
        skipped_by_reason={r: len(filter_result.skipped[r]) for r in SKIP_REASONS if filter_result.skipped[r]},
        files_with_symbols=files_with_symbols,
        files_chunked_only=files_chunked_only,
        parse_errors=len(parse_errors),
        parse_error_details=[f"{rel}: {exc}" for rel, exc in parse_errors[:10]],
        symbols_found=sum(symbols_by_language.values()),
        symbols_by_language=dict(symbols_by_language),
        symbols_by_kind=dict(symbols_by_kind),
        chunks_created=sum(chunks_by_chunker.values()),
        chunks_by_chunker=dict(chunks_by_chunker),
        chunks_linked_to_symbol=chunks_linked_to_symbol,
    )


def print_report(stats: IngestStats, db_path: Path) -> None:
    print(f"=== Ingestion report: {stats.repo_name} ===")
    print(f"scanned {stats.files_scanned} files: {stats.files_kept} kept, {stats.files_skipped} skipped")
    for reason, count in stats.skipped_by_reason.items():
        print(f"  {count} by {reason}")

    print(
        f"parsed {stats.files_with_symbols} files for symbols "
        f"({stats.files_chunked_only} kept files have no language mapping -- chunked as plain text)"
    )
    if stats.parse_errors:
        print(f"  {stats.parse_errors} files failed to parse and were skipped entirely:")
        for detail in stats.parse_error_details:
            print(f"    {detail}")

    print(f"symbols found: {stats.symbols_found}")
    if stats.symbols_by_language:
        print("  by language:")
        for language, count in stats.symbols_by_language.items():
            print(f"    {language}: {count}")
    if stats.symbols_by_kind:
        print("  by kind:")
        for kind, count in stats.symbols_by_kind.items():
            print(f"    {kind}: {count}")

    print(f"chunks created: {stats.chunks_created}")
    for name, count in stats.chunks_by_chunker.items():
        print(f"    {name}: {count}")
    if stats.chunks_created:
        print(f"  linked to an enclosing symbol: {stats.chunks_linked_to_symbol}/{stats.chunks_created}")

    print(f"sqlite: {db_path} (repo={stats.repo_name!r})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="local directory path, or a git URL to clone")
    parser.add_argument("--repo-name", default=None, help="defaults to the repo directory name")
    parser.add_argument("--db", type=Path, default=SQLITE_PATH)
    parser.add_argument(
        "--chunker", choices=["ast", "fixed"], default="ast",
        help="chunking strategy for parseable files (Day 5 ablation); unparseable files always use 'fixed'",
    )
    args = parser.parse_args()

    if _looks_like_url(args.repo):
        repo_path = clone_repo(args.repo)
    else:
        repo_path = Path(args.repo)
        if not repo_path.is_dir():
            print(f"error: not a directory: {repo_path}", file=sys.stderr)
            sys.exit(1)

    repo_name = args.repo_name or repo_path.name
    stats = build_index(repo_path, repo_name, args.db, args.chunker)
    print_report(stats, args.db)


if __name__ == "__main__":
    main()
