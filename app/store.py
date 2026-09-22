"""SQLite metadata store: files, symbols, and (from Day 2) chunks -- one inspectable file."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.chunk import Chunk, build_header
from app.config import SQLITE_PATH
from app.parse import Symbol, extract_imports, parse_file

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    repo TEXT NOT NULL,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    UNIQUE(repo, path)
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    parent TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    chunker TEXT NOT NULL DEFAULT 'ast'  -- 'ast' or 'fixed'; lets Day 5 compare both from one table
);

CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
"""


def connect(db_path: Path = SQLITE_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def upsert_file(conn: sqlite3.Connection, repo: str, path: str, language: str, size_bytes: int) -> int:
    """Insert a file, replacing any prior row for the same (repo, path).

    ON DELETE CASCADE means re-ingesting a changed file drops its stale
    symbols/chunks automatically instead of leaving duplicates behind.
    """
    cur = conn.execute(
        "INSERT OR REPLACE INTO files (repo, path, language, size_bytes) VALUES (?, ?, ?, ?)",
        (repo, path, language, size_bytes),
    )
    conn.commit()
    return cur.lastrowid


def insert_symbols(conn: sqlite3.Connection, file_id: int, symbols: list[Symbol]) -> list[int]:
    """Insert symbols one at a time (not executemany) so each row's id can be
    returned -- callers need these to link chunks back to their symbol.
    """
    ids = []
    for s in symbols:
        cur = conn.execute(
            """
            INSERT INTO symbols (file_id, name, kind, start_line, end_line, parent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, s.name, s.kind, s.start_line, s.end_line, s.parent),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def insert_chunks(conn: sqlite3.Connection, file_id: int, chunks: list[Chunk], chunker: str) -> None:
    conn.executemany(
        """
        INSERT INTO chunks (file_id, symbol_id, start_line, end_line, text, chunker)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(file_id, c.symbol_id, c.start_line, c.end_line, c.text, chunker) for c in chunks],
    )
    conn.commit()


@dataclass
class IndexableChunk:
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    symbol_id: int | None
    chunker: str
    text: str
    indexed_text: str  # header + text -- what actually gets tokenized/embedded


def get_indexable_chunks(
    conn: sqlite3.Connection, repo: str, repo_root: Path, include_header: bool = True
) -> list[IndexableChunk]:
    """Every chunk for `repo`, paired with its on-demand header (file path +
    imports + enclosing symbol, from Day 2's deferred design). Imports are
    computed once per file, not once per chunk, by re-parsing files with a
    known grammar; files with none (language='text') just get no imports line.

    include_header=False skips header-building entirely and indexes the raw
    chunk text only -- used by Day 5's header ablation to measure the
    dilution effect found in Day 3 (docs/DECISIONS.md, 2026-09-20).
    """
    result: list[IndexableChunk] = []

    for file_id, path, language in conn.execute(
        "SELECT id, path, language FROM files WHERE repo = ?", (repo,)
    ).fetchall():
        symbols = {}
        file_imports = ""
        if include_header:
            symbols = {
                row[0]: Symbol(
                    name=row[1], kind=row[2], path=path,
                    start_line=row[3], end_line=row[4], parent=row[5], id=row[0],
                )
                for row in conn.execute(
                    "SELECT id, name, kind, start_line, end_line, parent FROM symbols WHERE file_id = ?",
                    (file_id,),
                ).fetchall()
            }
            if language and language != "text":
                full_path = repo_root / path
                root = parse_file(full_path, language)
                file_imports = extract_imports(root, full_path.read_bytes(), language)

        for chunk_id, start_line, end_line, text, symbol_id, chunker in conn.execute(
            "SELECT id, start_line, end_line, text, symbol_id, chunker FROM chunks WHERE file_id = ?",
            (file_id,),
        ).fetchall():
            if include_header:
                chunk = Chunk(path=path, start_line=start_line, end_line=end_line, text=text, symbol_id=symbol_id)
                header = build_header(chunk, file_imports, symbols)
                indexed_text = f"{header}\n{text}"
            else:
                indexed_text = text

            result.append(IndexableChunk(
                chunk_id=chunk_id,
                path=path,
                start_line=start_line,
                end_line=end_line,
                symbol_id=symbol_id,
                chunker=chunker,
                text=text,
                indexed_text=indexed_text,
            ))

    return result
