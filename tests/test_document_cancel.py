from pathlib import Path

from bid_agent import db
from bid_agent.config import Settings
from bid_agent.document_service import (
    cancel_document_parse,
    create_document_upload,
    process_document_by_id,
    queue_reparse_document,
)
from bid_agent.storage import write_json_artifact, write_text_artifact


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_password="pw",
        session_secret="secret",
        storage_dir=tmp_path / "storage",
        reports_dir=tmp_path / "reports",
        database_url=f"sqlite:///{tmp_path / 'storage' / 'app.db'}",
        document_parser="paddle_structure",
        document_language="ch",
        vector_enabled=False,
        vector_store_dir=tmp_path / "storage" / "qdrant",
        vector_collection="bid_documents",
        embedding_model="BAAI/bge-small-zh-v1.5",
        embedding_dim=512,
    )


def test_cancel_document_parse_clears_chunks_artifacts_and_vector_state(tmp_path: Path):
    settings = _settings(tmp_path)
    db.init_db(settings.database_path)
    with db.db_session(settings.database_path) as conn:
        project_id = db.create_project(conn, "示例项目")
        document_id = db.create_document(
            conn,
            project_id=project_id,
            title="投标文件",
            category="proposal",
            original_filename="proposal.txt",
            stored_path="proposal.txt",
            sha256="abc",
            byte_size=12,
            mime_type="text/plain",
        )
        markdown_path = write_text_artifact(settings.storage_dir, "parsed", "document-1.md", "old")
        json_path = write_json_artifact(settings.storage_dir, "parse_json", "document-1.json", {"old": True})
        db.replace_document_chunks(
            conn,
            document_id=document_id,
            project_id=project_id,
            category="proposal",
            title="投标文件",
            chunks=[{"text": "错误类型产生的旧证据"}],
        )
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status="completed",
            ocr_status="included",
            parser_engine="paddle_structure_pages",
            parsed_markdown_path=str(markdown_path),
            parsed_json_path=str(json_path),
        )
        db.update_document_vector_status(conn, document_id, vector_status="completed")

        cancel_document_parse(conn, settings=settings, document_id=document_id)

        document = db.get_document(conn, document_id)
        chunks = db.list_document_chunks(conn, document_id)

    assert document["extraction_status"] == "cancelled"
    assert document["ocr_status"] == "cancelled"
    assert document["vector_status"] == "cleared"
    assert document["parsed_markdown_path"] == ""
    assert document["parsed_json_path"] == ""
    assert chunks == []
    assert not markdown_path.exists()
    assert not json_path.exists()


def test_cancelled_queued_document_does_not_parse_later(tmp_path: Path):
    settings = _settings(tmp_path)
    db.init_db(settings.database_path)
    with db.db_session(settings.database_path) as conn:
        project_id = db.create_project(conn, "示例项目")
        document_id = create_document_upload(
            conn,
            settings=settings,
            file_bytes="本来会被解析的文本".encode("utf-8"),
            filename="proposal.txt",
            category="proposal",
            project_id=project_id,
        )
        cancel_document_parse(conn, settings=settings, document_id=document_id)

    process_document_by_id(settings, document_id)

    with db.db_session(settings.database_path) as conn:
        document = db.get_document(conn, document_id)
        chunks = db.list_document_chunks(conn, document_id)

    assert document["extraction_status"] == "cancelled"
    assert document["vector_status"] == "cleared"
    assert chunks == []


def test_queue_reparse_clears_previous_parse_outputs(tmp_path: Path):
    settings = _settings(tmp_path)
    db.init_db(settings.database_path)
    with db.db_session(settings.database_path) as conn:
        project_id = db.create_project(conn, "示例项目")
        document_id = db.create_document(
            conn,
            project_id=project_id,
            title="投标文件",
            category="proposal",
            original_filename="proposal.txt",
            stored_path="proposal.txt",
            sha256="abc",
            byte_size=12,
            mime_type="text/plain",
        )
        markdown_path = write_text_artifact(settings.storage_dir, "parsed", "document-1.md", "old")
        db.replace_document_chunks(
            conn,
            document_id=document_id,
            project_id=project_id,
            category="proposal",
            title="投标文件",
            chunks=[{"text": "旧证据"}],
        )
        db.update_document_extraction(
            conn,
            document_id,
            extraction_status="completed",
            ocr_status="included",
            parser_engine="paddle_structure_pages",
            parsed_markdown_path=str(markdown_path),
        )

        queue_reparse_document(conn, settings=settings, document_id=document_id)

        document = db.get_document(conn, document_id)
        chunks = db.list_document_chunks(conn, document_id)

    assert document["extraction_status"] == "queued"
    assert document["vector_status"] == "pending"
    assert document["parsed_markdown_path"] == ""
    assert chunks == []
    assert not markdown_path.exists()
