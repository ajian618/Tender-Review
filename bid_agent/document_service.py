from __future__ import annotations

import mimetypes
import sqlite3
from pathlib import Path
from typing import Any

from bid_agent import db
from bid_agent.config import Settings
from bid_agent.parsers import chunks_to_dicts, parse_document, parse_result_to_json
from bid_agent.storage import store_original, write_json_artifact, write_text_artifact
from bid_agent.vector_store import delete_document_vectors, index_document


ACTIVE_PARSE_STATUSES = {"queued", "running", "cancel_requested"}
REQUESTED_CANCEL_STATUSES = {"cancel_requested", "cancelled"}


class DocumentParseCancelled(RuntimeError):
    """Raised inside the background worker when a user stops a parse job."""


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
    document_id = create_document_upload(
        conn,
        settings=settings,
        file_bytes=file_bytes,
        filename=filename,
        category=category,
        project_id=project_id,
        title=title,
    )
    document = db.get_document(conn, document_id)
    if document is None:
        raise ValueError(f"Document not found after upload: {document_id}")
    _parse_and_index_document(conn, settings=settings, document=document)
    return document_id


def create_document_upload(
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
    db.update_document_parse_progress(
        conn,
        document_id,
        extraction_status="queued",
        parser_engine="",
        parse_strategy=describe_parse_strategy(category, Path(filename).suffix.lower()),
        parse_stage="等待后台解析",
        parse_progress=0,
        parse_current_page=0,
        parse_total_pages=guess_total_pages(stored.path),
        error_message="",
    )
    db.update_document_vector_status(conn, document_id, vector_status="pending", vector_error="")
    if project_id:
        db.touch_project(conn, project_id)
    return document_id


def process_document_by_id(settings: Settings, document_id: int) -> None:
    with db.db_session(settings.database_path) as conn:
        document = db.get_document(conn, document_id)
        if document is None:
            raise ValueError(f"Document not found: {document_id}")
        if str(document["extraction_status"]) in REQUESTED_CANCEL_STATUSES:
            _finalize_document_cancel(conn, settings=settings, document=document)
            return
        _parse_and_index_document(conn, settings=settings, document=document, commit_progress=True)


def _parse_and_index_document(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    document: dict[str, Any],
    commit_progress: bool = False,
) -> None:
    document_id = int(document["id"])
    project_id = int(document["project_id"]) if document["project_id"] else None
    category = str(document["category"])
    filename = str(document["original_filename"])
    title = str(document["title"])
    stored_path = Path(str(document["stored_path"]))

    try:
        _raise_if_cancel_requested(conn, document_id)
        db.update_document_parse_progress(
            conn,
            document_id,
            extraction_status="running",
            parser_engine=settings.document_parser,
            parse_strategy=describe_parse_strategy(category, stored_path.suffix.lower()),
            parse_stage="准备解析文件",
            parse_progress=1,
            error_message="",
        )
        if commit_progress:
            conn.commit()

        def progress_callback(payload: dict[str, Any]) -> None:
            _raise_if_cancel_requested(conn, document_id)
            _write_parse_progress(
                conn,
                document_id=document_id,
                payload=payload,
                commit_progress=commit_progress,
            )
            _raise_if_cancel_requested(conn, document_id)

        result = parse_document(
            stored_path,
            engine=settings.document_parser,
            language=settings.document_language,
            category=category,
            progress_callback=progress_callback,
        )
        _raise_if_cancel_requested(conn, document_id)
        markdown_path = write_text_artifact(
            settings.storage_dir,
            "parsed",
            f"document-{document_id}.md",
            result.markdown,
        )
        json_path = write_json_artifact(
            settings.storage_dir,
            "parse_json",
            f"document-{document_id}.json",
            parse_result_to_json(
                source_filename=filename,
                document_id=document_id,
                result=result,
            ),
        )
        _raise_if_cancel_requested(conn, document_id)
        db.update_document_parse_progress(
            conn,
            document_id,
            extraction_status="running",
            parser_engine=result.engine,
            parse_strategy=describe_parse_strategy(category, stored_path.suffix.lower()),
            parse_stage="写入解析分块",
            parse_progress=92,
        )
        db.replace_document_chunks(
            conn,
            document_id=document_id,
            project_id=project_id,
            category=category,
            title=title,
            chunks=chunks_to_dicts(result.chunks),
        )
        _raise_if_cancel_requested(conn, document_id)
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status=result.status,
            ocr_status="included" if _result_uses_ocr(result) else "not_needed",
            parser_engine=result.engine,
            parsed_markdown_path=str(markdown_path),
            parsed_json_path=str(json_path),
        )
        try:
            db.update_document_parse_progress(
                conn,
                document_id,
                extraction_status=result.status,
                parser_engine=result.engine,
                parse_stage="向量索引中",
                parse_progress=95,
            )
            index_document(
                conn,
                settings=settings,
                document_id=document_id,
                cancel_check=lambda: _raise_if_cancel_requested(conn, document_id),
            )
        except Exception as exc:
            if isinstance(exc, DocumentParseCancelled):
                raise
            db.update_document_vector_status(
                conn,
                document_id,
                vector_status="failed",
                vector_error=str(exc),
            )
        _raise_if_cancel_requested(conn, document_id)
        db.update_document_parse_progress(
            conn,
            document_id,
            extraction_status=result.status,
            parser_engine=result.engine,
            parse_stage="解析和向量索引完成",
            parse_progress=100,
        )
    except DocumentParseCancelled:
        _finalize_document_cancel(conn, settings=settings, document=document)
        if commit_progress:
            conn.commit()
    except Exception as exc:
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status="failed",
            ocr_status="failed",
            parser_engine=settings.document_parser,
            error_message=str(exc),
        )
        db.update_document_parse_progress(
            conn,
            document_id,
            extraction_status="failed",
            parse_stage="解析失败",
            error_message=str(exc),
        )
        if commit_progress:
            conn.commit()
    if project_id:
        db.touch_project(conn, project_id)


def reparse_document(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    document_id: int,
) -> None:
    document = db.get_document(conn, document_id)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")
    if str(document["extraction_status"]) in ACTIVE_PARSE_STATUSES:
        raise ValueError("Document is already parsing. Stop and clear it before reparsing.")
    _clear_document_outputs(conn, settings=settings, document=document)
    db.update_document_extraction(
        conn,
        document_id,
        extraction_status="running",
        ocr_status="running",
        parser_engine=settings.document_parser,
        error_message="",
    )
    db.update_document_parse_progress(
        conn,
        document_id,
        extraction_status="running",
        parser_engine=settings.document_parser,
        parse_strategy=describe_parse_strategy(str(document["category"]), Path(str(document["stored_path"])).suffix.lower()),
        parse_stage="准备重新解析",
        parse_progress=1,
        parse_current_page=0,
        parse_total_pages=guess_total_pages(Path(str(document["stored_path"]))),
        error_message="",
    )
    db.update_document_vector_status(conn, document_id, vector_status="pending", vector_error="")
    try:
        _parse_and_index_document(conn, settings=settings, document=document)
    except Exception as exc:
        db.replace_document_chunks(
            conn,
            document_id=document_id,
            project_id=document["project_id"],
            category=str(document["category"]),
            title=str(document["title"]),
            chunks=[],
        )
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status="failed",
            ocr_status="failed",
            parser_engine=settings.document_parser,
            error_message=str(exc),
        )
        raise
    if document["project_id"]:
        db.touch_project(conn, int(document["project_id"]))


def queue_reparse_document(conn: sqlite3.Connection, *, settings: Settings, document_id: int) -> None:
    document = db.get_document(conn, document_id)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")
    if str(document["extraction_status"]) in ACTIVE_PARSE_STATUSES:
        raise ValueError("Document is already parsing. Stop and clear it before reparsing.")
    _clear_document_outputs(conn, settings=settings, document=document)
    path = Path(str(document["stored_path"]))
    db.update_document_parse_progress(
        conn,
        document_id,
        extraction_status="queued",
        parser_engine="",
        parse_strategy=describe_parse_strategy(str(document["category"]), path.suffix.lower()),
        parse_stage="等待后台重新解析",
        parse_progress=0,
        parse_current_page=0,
        parse_total_pages=guess_total_pages(path),
        error_message="",
    )
    db.update_document_vector_status(conn, document_id, vector_status="pending", vector_error="")


def cancel_document_parse(conn: sqlite3.Connection, *, settings: Settings, document_id: int) -> None:
    document = db.get_document(conn, document_id)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")

    _clear_document_outputs(conn, settings=settings, document=document)
    current_status = str(document["extraction_status"])
    if current_status == "running":
        db.update_document_parse_progress(
            conn,
            document_id,
            extraction_status="cancel_requested",
            parse_stage="已请求停止，正在等待当前解析步骤结束",
            error_message="用户停止解析并清空结果",
        )
    else:
        _finalize_document_cancel(conn, settings=settings, document=document)

    if document["project_id"]:
        db.touch_project(conn, int(document["project_id"]))


def _write_parse_progress(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    payload: dict[str, Any],
    commit_progress: bool,
) -> None:
    db.update_document_parse_progress(
        conn,
        document_id,
        extraction_status="running",
        parse_strategy=payload.get("strategy"),
        parse_stage=str(payload.get("stage") or ""),
        parse_progress=payload.get("progress"),
        parse_current_page=payload.get("current_page"),
        parse_total_pages=payload.get("total_pages"),
    )
    if commit_progress:
        conn.commit()


def _raise_if_cancel_requested(conn: sqlite3.Connection, document_id: int) -> None:
    row = conn.execute(
        "SELECT extraction_status FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if row is not None and str(row["extraction_status"]) in REQUESTED_CANCEL_STATUSES:
        raise DocumentParseCancelled(f"Document parse cancelled: {document_id}")


def _finalize_document_cancel(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    document: dict[str, Any],
) -> None:
    _clear_document_outputs(conn, settings=settings, document=document)
    db.mark_document_cancelled(conn, int(document["id"]))


def _clear_document_outputs(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    document: dict[str, Any],
) -> None:
    document_id = int(document["id"])
    _delete_parse_artifact(settings, str(document.get("parsed_markdown_path") or ""))
    _delete_parse_artifact(settings, str(document.get("parsed_json_path") or ""))
    vector_error = ""
    try:
        delete_document_vectors(settings=settings, document_id=document_id)
    except Exception as exc:
        vector_error = str(exc)
    db.clear_document_parsed_content(
        conn,
        document_id,
        vector_status="failed" if vector_error else "cleared",
        vector_error=vector_error,
    )


def _delete_parse_artifact(settings: Settings, raw_path: str) -> None:
    if not raw_path.strip():
        return
    try:
        path = Path(raw_path)
        resolved = path.resolve()
        storage_root = settings.storage_dir.resolve()
    except OSError:
        return
    if resolved == storage_root or storage_root not in resolved.parents:
        return
    if resolved.exists() and resolved.is_file():
        resolved.unlink()


def describe_parse_strategy(category: str, suffix: str) -> str:
    suffix = suffix.lower()
    if suffix == ".pdf":
        if category in {"proposal", "qualification", "performance", "credit", "commercial"}:
            return "逐页 PPStructureV3 精细解析"
        return "文字层快速提取 + 低文字页 PPStructureV3"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "图片 PPStructureV3"
    if suffix in {".docx", ".xlsx", ".xlsm", ".pptx"}:
        return "PaddleOCR doc2md"
    return "文本直接入库"


def guess_total_pages(path: Path) -> int:
    if path.suffix.lower() != ".pdf":
        return 0
    try:
        import fitz

        with fitz.open(path) as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def _result_uses_ocr(result) -> bool:
    if result.engine in {"paddle_structure", "paddle_structure_pages", "hybrid_pdf"}:
        return True
    return int(result.metadata.get("structure_page_count") or 0) > 0
