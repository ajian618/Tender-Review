from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from bid_agent import db
from bid_agent.config import Settings


@lru_cache(maxsize=4)
def _embedding_model(model_name: str):
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name)


@lru_cache(maxsize=4)
def _qdrant_client(path: str) -> QdrantClient:
    return QdrantClient(path=path)


def get_client(settings: Settings) -> QdrantClient:
    settings.vector_store_dir.mkdir(parents=True, exist_ok=True)
    return _qdrant_client(str(settings.vector_store_dir.resolve()))


def ensure_collection(settings: Settings) -> None:
    client = get_client(settings)
    if client.collection_exists(settings.vector_collection):
        return
    client.create_collection(
        collection_name=settings.vector_collection,
        vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
    )


def embed_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    model = _embedding_model(settings.embedding_model)
    return [vector.tolist() for vector in model.embed(texts)]


def _check_cancel(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check is not None:
        cancel_check()


def delete_document_vectors(*, settings: Settings, document_id: int) -> None:
    if not settings.vector_enabled:
        return
    client = get_client(settings)
    if not client.collection_exists(settings.vector_collection):
        return
    client.delete(
        collection_name=settings.vector_collection,
        points_selector=FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            )
        ),
    )


def index_document(
    conn,
    *,
    settings: Settings,
    document_id: int,
    cancel_check: Callable[[], None] | None = None,
) -> int:
    _check_cancel(cancel_check)
    if not settings.vector_enabled:
        db.update_document_vector_status(conn, document_id, vector_status="disabled")
        return 0
    document = db.get_document(conn, document_id)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")
    chunks = db.list_document_chunks(conn, document_id, limit=100000)
    if not chunks:
        db.update_document_vector_status(conn, document_id, vector_status="empty")
        return 0

    db.update_document_vector_status(conn, document_id, vector_status="running")
    ensure_collection(settings)
    delete_document_vectors(settings=settings, document_id=document_id)
    _check_cancel(cancel_check)

    texts = [str(chunk["text"]) for chunk in chunks]
    vectors = embed_texts(settings, texts)
    _check_cancel(cancel_check)
    points = []
    for chunk, vector in zip(chunks, vectors):
        points.append(
            PointStruct(
                id=int(chunk["id"]),
                vector=vector,
                payload={
                    "chunk_id": int(chunk["id"]),
                    "document_id": int(document_id),
                    "project_id": int(document["project_id"]) if document["project_id"] else None,
                    "category": str(document["category"]),
                    "title": str(document["title"]),
                    "original_filename": str(document["original_filename"]),
                    "page_number": chunk.get("page_number"),
                    "sheet_name": chunk.get("sheet_name") or "",
                    "block_type": chunk.get("block_type") or "markdown",
                    "chunk_index": int(chunk["chunk_index"]),
                    "text": str(chunk["text"]),
                },
            )
        )
    _check_cancel(cancel_check)
    client = get_client(settings)
    client.upsert(collection_name=settings.vector_collection, points=points)
    _check_cancel(cancel_check)
    db.update_document_vector_status(conn, document_id, vector_status="completed")
    return len(points)


def search_project(
    *,
    settings: Settings,
    project_id: int,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    ensure_collection(settings)
    client = get_client(settings)
    vector = embed_texts(settings, [query])[0]
    query_filter = Filter(
        must=[
            FieldCondition(
                key="project_id",
                match=MatchValue(value=project_id),
            )
        ]
    )
    if hasattr(client, "query_points"):
        result = client.query_points(
            collection_name=settings.vector_collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        points = result.points
    else:
        points = client.search(
            collection_name=settings.vector_collection,
            query_vector=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
    rows: list[dict[str, Any]] = []
    for point in points:
        payload = dict(point.payload or {})
        payload["score"] = float(point.score)
        rows.append(payload)
    return rows


def index_project(conn, *, settings: Settings, project_id: int) -> int:
    total = 0
    for document in db.list_documents(conn, project_id=project_id, limit=10000):
        try:
            total += index_document(conn, settings=settings, document_id=int(document["id"]))
        except Exception as exc:
            db.update_document_vector_status(
                conn,
                int(document["id"]),
                vector_status="failed",
                vector_error=str(exc),
            )
    return total
