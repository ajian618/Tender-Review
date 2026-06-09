from pathlib import Path

from bid_agent import db


def test_db_fts_search_finds_document_chunk(tmp_path: Path):
    db_path = tmp_path / "app.db"
    db.init_db(db_path)
    with db.db_session(db_path) as conn:
        project_id = db.create_project(conn, "示例项目")
        document_id = db.create_document(
            conn,
            project_id=project_id,
            title="招标文件",
            category="tender",
            original_filename="fake.txt",
            stored_path="fake.txt",
            sha256="abc",
            byte_size=10,
            mime_type="text/plain",
        )
        db.replace_document_chunks(
            conn,
            document_id=document_id,
            project_id=project_id,
            category="tender",
            title="招标文件",
            chunks=[{"text": "投标人应具备水利水电工程施工总承包二级资质。"}],
        )
        results = db.search_chunks(conn, "资质", project_id=project_id)
    assert results
    assert results[0]["title"] == "招标文件"
