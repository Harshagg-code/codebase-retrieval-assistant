"""FastAPI app: POST /ingest, POST /ask, GET /symbols."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.answer import answer_question, rewrite_query, verify
from app.config import REPOS_DIR, SQLITE_PATH
from app.ingest import clone_repo
from app.store import connect
from scripts.build_index import _looks_like_url, build_index

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Codebase Assistant")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


def get_conn() -> sqlite3.Connection:
    return connect(SQLITE_PATH)


# ---- POST /ingest -------------------------------------------------------------

class IngestRequest(BaseModel):
    repo: str  # local path or a git URL
    repo_name: str | None = None
    chunker: str = "ast"


class IngestResponse(BaseModel):
    repo_name: str
    files_scanned: int
    files_kept: int
    files_skipped: int
    symbols_found: int
    chunks_created: int
    parse_errors: int


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    if _looks_like_url(req.repo):
        repo_path = clone_repo(req.repo)
    else:
        repo_path = Path(req.repo)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail=f"not a directory: {repo_path}")

    if req.chunker not in ("ast", "fixed"):
        raise HTTPException(status_code=400, detail="chunker must be 'ast' or 'fixed'")

    repo_name = req.repo_name or repo_path.name
    stats = build_index(repo_path, repo_name, SQLITE_PATH, req.chunker)

    return IngestResponse(
        repo_name=stats.repo_name,
        files_scanned=stats.files_scanned,
        files_kept=stats.files_kept,
        files_skipped=stats.files_skipped,
        symbols_found=stats.symbols_found,
        chunks_created=stats.chunks_created,
        parse_errors=stats.parse_errors,
    )


# ---- POST /ask ------------------------------------------------------------

class Turn(BaseModel):
    question: str
    answer: str


class AskRequest(BaseModel):
    repo: str
    question: str
    history: list[Turn] = []


class CitationOut(BaseModel):
    path: str
    start_line: int
    end_line: int
    verified: bool


class AskResponse(BaseModel):
    question: str
    rewritten_question: str | None
    answer: str
    grounded: bool
    groundedness_reason: str | None
    citations: list[CitationOut]
    evidence_spans: list[str]


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    conn = get_conn()
    try:
        row = conn.execute("SELECT 1 FROM files WHERE repo = ? LIMIT 1", (req.repo,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"repo not ingested: {req.repo!r}")

        rewritten = None
        question = req.question
        if req.history:
            history_pairs = [(t.question, t.answer) for t in req.history]
            rewritten = rewrite_query(history_pairs, req.question)
            question = rewritten

        result = answer_question(conn, req.repo, question, repo_root=REPOS_DIR / req.repo)

        v = verify(result.answer, result.evidence)
        citations = [
            CitationOut(path=c.path, start_line=c.start_line, end_line=c.end_line, verified=c.verified)
            for c in v.citations
        ]

        return AskResponse(
            question=req.question,
            rewritten_question=rewritten,
            answer=result.answer,
            grounded=result.grounded,
            groundedness_reason=result.groundedness_reason,
            citations=citations,
            evidence_spans=[f"{e.path}:{e.start_line}-{e.end_line}" for e in result.evidence],
        )
    finally:
        conn.close()


# ---- GET /symbols -----------------------------------------------------------

class SymbolOut(BaseModel):
    id: int
    name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    parent: str | None


@app.get("/symbols", response_model=list[SymbolOut])
def symbols(
    repo: str = Query(...),
    q: str = Query(..., min_length=1),
    limit: int = Query(20, le=100),
) -> list[SymbolOut]:
    conn = get_conn()
    try:
        exact = conn.execute(
            """
            SELECT s.id, s.name, s.kind, f.path, s.start_line, s.end_line, s.parent
            FROM symbols s JOIN files f ON f.id = s.file_id
            WHERE f.repo = ? AND LOWER(s.name) = LOWER(?)
            LIMIT ?
            """,
            (repo, q, limit),
        ).fetchall()

        rows = exact
        if not rows:
            rows = conn.execute(
                """
                SELECT s.id, s.name, s.kind, f.path, s.start_line, s.end_line, s.parent
                FROM symbols s JOIN files f ON f.id = s.file_id
                WHERE f.repo = ? AND LOWER(s.name) LIKE LOWER(?)
                LIMIT ?
                """,
                (repo, f"%{q}%", limit),
            ).fetchall()

        return [
            SymbolOut(id=r[0], name=r[1], kind=r[2], path=r[3], start_line=r[4], end_line=r[5], parent=r[6])
            for r in rows
        ]
    finally:
        conn.close()
