from __future__ import annotations

import mimetypes
import sqlite3
from pathlib import Path

from bid_agent import db
from bid_agent.config import Settings
from bid_agent.extractors import extract_document
from bid_agent.storage import store_original, write_text_artifact


def ingest_document(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    file_bytes: bytes,
    filename: str,
    category: str,
    project_id: int | None,
    title: str | None = None,
) -> int:
    stored = store_original(
        storage_dir=settings.storage_dir,
        data=file_bytes,
        original_filename=filename,
        project_id=project_id,
    )
    doc_title = title.strip() if title and title.strip() else Path(filename).stem
    mime_type = mimetypes.guess_type(filename)[0] or ""
    document_id = db.create_document(
        conn,
        project_id=project_id,
        title=doc_title,
        category=category,
        original_filename=filename,
        stored_path=str(stored.path),
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        mime_type=mime_type,
    )

    try:
        chunks, ocr_status = extract_document(
            stored.path,
            ocr_enabled=settings.ocr_enabled,
            ocr_language=settings.ocr_language,
        )
        db.replace_document_chunks(
            conn,
            document_id=document_id,
            project_id=project_id,
            category=category,
            title=doc_title,
            chunks=chunks,
        )
        extracted_text = "\n\n".join(str(chunk["text"]) for chunk in chunks)
        write_text_artifact(
            settings.storage_dir,
            "extracted",
            f"document-{document_id}.txt",
            extracted_text,
        )
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status="completed" if chunks else "empty",
            ocr_status=ocr_status,
        )
    except Exception as exc:
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status="failed",
            ocr_status="failed",
            error_message=str(exc),
        )
    if project_id:
        db.touch_project(conn, project_id)
    return document_id


def reextract_document(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    document_id: int,
) -> None:
    document = db.get_document(conn, document_id)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")
    db.update_document_extraction(
        conn,
        document_id,
        extraction_status="running",
        ocr_status="running",
        error_message="",
    )
    path = Path(str(document["stored_path"]))
    try:
        chunks, ocr_status = extract_document(
            path,
            ocr_enabled=settings.ocr_enabled,
            ocr_language=settings.ocr_language,
        )
        db.replace_document_chunks(
            conn,
            document_id=document_id,
            project_id=document["project_id"],
            category=str(document["category"]),
            title=str(document["title"]),
            chunks=chunks,
        )
        extracted_text = "\n\n".join(str(chunk["text"]) for chunk in chunks)
        write_text_artifact(
            settings.storage_dir,
            "extracted",
            f"document-{document_id}.txt",
            extracted_text,
        )
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status="completed" if chunks else "empty",
            ocr_status=ocr_status,
        )
    except Exception as exc:
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status="failed",
            ocr_status="failed",
            error_message=str(exc),
        )
        raise
    if document["project_id"]:
        db.touch_project(conn, int(document["project_id"]))
