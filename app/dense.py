"""Dense retrieval: BAAI/bge-small-en-v1.5 embeddings in embedded Qdrant.

bge models are trained asymmetrically: queries need an instruction prefix,
documents don't. Applying it to both (or neither) measurably hurts recall,
so QUERY_PREFIX is applied only in dense_search, never in build_dense_index.
"""

from __future__ import annotations

from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer

from app.config import EMBEDDING_MODEL, QDRANT_PATH
from app.store import IndexableChunk

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model_cache: dict[str, SentenceTransformer] = {}


def get_embedding_model(name: str = EMBEDDING_MODEL) -> SentenceTransformer:
    if name not in _model_cache:
        _model_cache[name] = SentenceTransformer(name)
    return _model_cache[name]


_qdrant_cache: dict[str, QdrantClient] = {}


def get_qdrant_client(path: Path = QDRANT_PATH) -> QdrantClient:
    """Cached per path: embedded Qdrant holds an exclusive file lock, so a
    second QdrantClient on the same path (even in the same process) raises
    'already accessed by another instance' -- reuse one client instead.
    """
    key = str(path)
    if key not in _qdrant_cache:
        path.mkdir(parents=True, exist_ok=True)
        _qdrant_cache[key] = QdrantClient(path=key)
    return _qdrant_cache[key]


def collection_name(repo: str) -> str:
    return f"repo_{repo}"


def build_dense_index(
    client: QdrantClient,
    repo: str,
    chunks: list[IndexableChunk],
    model: SentenceTransformer | None = None,
) -> None:
    model = model or get_embedding_model()
    name = collection_name(repo)

    client.recreate_collection(
        collection_name=name,
        vectors_config=qmodels.VectorParams(
            size=model.get_embedding_dimension(),
            distance=qmodels.Distance.COSINE,
        ),
    )

    vectors = model.encode(
        [c.indexed_text for c in chunks],  # no prefix on documents
        show_progress_bar=False,
        normalize_embeddings=True,
    )

    points = [
        qmodels.PointStruct(
            id=c.chunk_id,
            vector=vectors[i].tolist(),
            payload={
                "path": c.path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "symbol_id": c.symbol_id,
            },
        )
        for i, c in enumerate(chunks)
    ]
    client.upsert(collection_name=name, points=points)


def dense_search(
    client: QdrantClient,
    repo: str,
    query: str,
    top_k: int = 5,
    model: SentenceTransformer | None = None,
) -> list[tuple[int, float]]:
    """Returns [(chunk_id, score), ...] sorted by score descending."""
    model = model or get_embedding_model()
    query_vector = model.encode(QUERY_PREFIX + query, normalize_embeddings=True)
    response = client.query_points(
        collection_name=collection_name(repo),
        query=query_vector.tolist(),
        limit=top_k,
    )
    return [(point.id, point.score) for point in response.points]
