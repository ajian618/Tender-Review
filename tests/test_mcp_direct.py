from pathlib import Path

from bid_agent import db


def _configure_env(monkeypatch, tmp_path: Path) -> Path:
    storage_dir = tmp_path / "storage"
    reports_dir = tmp_path / "reports"
    db_path = storage_dir / "app.db"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("REPORTS_DIR", str(reports_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("VECTOR_STORE_DIR", str(storage_dir / "qdrant"))
    return db_path


def _add_doc(conn, project_id: int, title: str, category: str, text: str) -> int:
    document_id = db.create_document(
        conn,
        project_id=project_id,
        title=title,
        category=category,
        original_filename=f"{title}.txt",
        stored_path=f"{title}.txt",
        sha256=title,
        byte_size=len(text.encode("utf-8")),
        mime_type="text/plain",
    )
    db.replace_document_chunks(
        conn,
        document_id=document_id,
        project_id=project_id,
        category=category,
        title=title,
        chunks=[{"text": text, "page_number": 3}],
    )
    return document_id


def test_mcp_reads_sqlite_without_fastapi(monkeypatch, tmp_path: Path):
    db_path = _configure_env(monkeypatch, tmp_path)

    db.init_db(db_path)
    with db.db_session(db_path) as conn:
        project_id = db.create_project(conn, "示例水利项目")
        _add_doc(conn, project_id, "招标文件", "tender", "技术评分办法：施工组织设计满分 25 分。")

    from bid_agent import mcp_server

    projects = mcp_server.bid_list_projects()
    project = mcp_server.bid_get_project(project_id)

    assert projects["projects"][0]["name"] == "示例水利项目"
    assert project["documents"][0]["title"] == "招标文件"
    assert "database_path" in projects


def test_mcp_search_falls_back_to_sqlite_when_vector_search_fails(monkeypatch, tmp_path: Path):
    db_path = _configure_env(monkeypatch, tmp_path)

    db.init_db(db_path)
    with db.db_session(db_path) as conn:
        project_id = db.create_project(conn, "示例水利项目")
        _add_doc(conn, project_id, "投标文件", "proposal", "本工程设置围堰、导流和度汛专项措施。")

    from bid_agent import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "search_project",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("vector unavailable")),
    )

    result = mcp_server.bid_search_evidence(project_id, "围堰 度汛", limit=5)

    assert result["source"] == "sqlite_fts"
    assert "vector unavailable" in result["vector_error"]
    assert result["results"]
    assert result["results"][0]["original_filename"] == "投标文件.txt"


def test_mcp_saves_and_searches_agent_lessons(monkeypatch, tmp_path: Path):
    db_path = _configure_env(monkeypatch, tmp_path)

    db.init_db(db_path)
    with db.db_session(db_path) as conn:
        project_id = db.create_project(conn, "排涝工程")

    from bid_agent import mcp_server

    saved = mcp_server.bid_save_agent_lesson(
        title="排涝工程检查口径",
        lesson="排涝工程应重点检索泵站、调蓄、度汛、围堰和排水组织措施。",
        scope="technical_review",
        tags="排涝,泵站,度汛",
        project_id=project_id,
    )
    searched = mcp_server.bid_search_agent_lessons("泵站 度汛", project_id=project_id)

    assert saved["lesson"]["title"] == "排涝工程检查口径"
    assert searched["lessons"]
    assert searched["lessons"][0]["lesson"] == "排涝工程应重点检索泵站、调蓄、度汛、围堰和排水组织措施。"
