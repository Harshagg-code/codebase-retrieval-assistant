"""expand.py: retrieved chunk -> full function/method source for the LLM.

This header (imports + whole symbol) is generation-time context, built
after retrieval on the already-fused/reranked top results -- distinct
from Day 3's embedding-time header (app/chunk.py:build_header), which we
know can dilute similarity scores. Never conflate the two: this one never
touches the index, so retrieval dilution doesn't apply here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.config import LANGUAGE_BY_EXTENSION
from app.parse import Symbol, extract_imports, parse_file

MAX_EXPAND_LINES = 200


@dataclass
class ExpandedContext:
    path: str
    start_line: int
    end_line: int
    text: str
    imports: str
    expanded: bool  # True: whole enclosing symbol pulled. False: fell back to the chunk's own span.


def _get_symbol(conn: sqlite3.Connection, symbol_id: int, path: str) -> Symbol | None:
    row = conn.execute(
        "SELECT name, kind, start_line, end_line, parent FROM symbols WHERE id = ?", (symbol_id,)
    ).fetchone()
    if row is None:
        return None
    return Symbol(name=row[0], kind=row[1], path=path, start_line=row[2], end_line=row[3], parent=row[4], id=symbol_id)


def expand(
    chunk,
    conn: sqlite3.Connection,
    repo_root: Path,
    max_lines: int = MAX_EXPAND_LINES,
) -> ExpandedContext:
    """chunk needs .path, .start_line, .end_line, .text, .symbol_id (an
    IndexableChunk or Chunk works)."""
    symbol = _get_symbol(conn, chunk.symbol_id, chunk.path) if chunk.symbol_id is not None else None

    if symbol is not None and (symbol.end_line - symbol.start_line) <= max_lines:
        full_path = repo_root / chunk.path
        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
        text = "\n".join(lines[symbol.start_line - 1 : symbol.end_line])

        imports = ""
        language = LANGUAGE_BY_EXTENSION.get(full_path.suffix.lower())
        if language is not None:
            root = parse_file(full_path, language)
            imports = extract_imports(root, full_path.read_bytes(), language)

        return ExpandedContext(
            path=chunk.path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            text=text,
            imports=imports,
            expanded=True,
        )

    # no enclosing symbol, or it's too large -- just the chunk's own span
    return ExpandedContext(
        path=chunk.path,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        text=chunk.text,
        imports="",
        expanded=False,
    )
