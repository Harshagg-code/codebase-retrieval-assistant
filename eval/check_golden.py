"""Sanity check for eval/golden.jsonl: every gold_file and gold_symbol must
actually exist in the indexed sqlite database.

Through Day 4, this also hard-failed any entry referencing repo 'rich',
since Repo C was meant to stay untouched until eval day -- that guard
existed to prevent Repo A/B questions from being unconsciously tuned
against held-out data. Day 5 Stage 4 is that eval day: Repo C's own
golden questions were written blind (from source, before any retrieval
was run against it) and are now checked like any other repo's.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import SQLITE_PATH

GOLDEN_PATH = Path(__file__).resolve().parent / "golden.jsonl"


def load_golden(path: Path = GOLDEN_PATH) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _file_exists(conn: sqlite3.Connection, repo: str, path: str) -> bool:
    cur = conn.execute("SELECT 1 FROM files WHERE repo = ? AND path = ?", (repo, path))
    return cur.fetchone() is not None


def _symbol_exists(conn: sqlite3.Connection, repo: str, gold_symbol: str) -> bool:
    """gold_symbol is 'path:name' or, where a file has two same-named symbols
    in different classes, the disambiguated 'path:Class.method'.
    """
    path, _, name_spec = gold_symbol.rpartition(":")
    if "." in name_spec:
        parent, _, name = name_spec.partition(".")
    else:
        parent, name = None, name_spec

    query = """
        SELECT 1 FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE f.repo = ? AND f.path = ? AND s.name = ?
    """
    params = [repo, path, name]
    if parent is not None:
        query += " AND s.parent = ?"
        params.append(parent)

    cur = conn.execute(query, params)
    return cur.fetchone() is not None


def check(entries: list[dict], db_path: Path = SQLITE_PATH) -> list[str]:
    conn = sqlite3.connect(db_path)
    failures: list[str] = []

    for entry in entries:
        entry_id = entry.get("id", "<missing id>")
        repo = entry.get("repo")

        for gold_file in entry.get("gold_files", []):
            if not _file_exists(conn, repo, gold_file):
                failures.append(f"{entry_id}: gold_file not found in index: {repo}/{gold_file}")

        for gold_symbol in entry.get("gold_symbols", []):
            if not _symbol_exists(conn, repo, gold_symbol):
                failures.append(f"{entry_id}: gold_symbol not found in index: {repo}/{gold_symbol}")

    conn.close()
    return failures


def main() -> None:
    entries = load_golden()
    failures = check(entries)

    print(f"checked {len(entries)} golden questions against {SQLITE_PATH}")
    if failures:
        print(f"FAIL: {len(failures)} problem(s) found")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)

    print("PASS: every gold_file and gold_symbol resolves")


if __name__ == "__main__":
    main()
