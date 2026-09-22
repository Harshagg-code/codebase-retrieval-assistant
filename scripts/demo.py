"""Demo script: one real cited answer, one real abstention. Drives the README's demo GIF."""

from __future__ import annotations

import sqlite3
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.answer import answer_question
from app.config import SQLITE_PATH


def show(repo: str, question: str, conn: sqlite3.Connection, max_chars: int = 420) -> None:
    print(f"\n$ ask {repo!r}: {question}\n")
    result = answer_question(conn, repo, question)
    if not result.grounded:
        print(textwrap.fill(f"[ABSTAINED] {result.answer}", width=88))
        return
    text = result.answer
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(".", 1)[0] + ". [...]"
    print(textwrap.fill(text, width=88))


def main() -> None:
    conn = sqlite3.connect(SQLITE_PATH)
    show("requests", "What does the dispatch_hook function do?", conn)
    show("requests", "How does requests support batching multiple GraphQL queries into a single HTTP request?", conn)
    conn.close()


if __name__ == "__main__":
    main()
