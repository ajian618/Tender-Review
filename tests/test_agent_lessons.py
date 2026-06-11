from pathlib import Path

from bid_agent import db


def test_agent_lessons_can_be_saved_and_searched(tmp_path: Path):
    db_path = tmp_path / "app.db"
    db.init_db(db_path)

    with db.db_session(db_path) as conn:
        project_id = db.create_project(conn, "排涝调蓄工程")
        lesson_id = db.create_agent_lesson(
            conn,
            title="排涝项目度汛措施",
            lesson="排涝调蓄项目技术标应重点核对度汛、围堰、导流和防渗措施。",
            scope="technical_review",
            tags="排涝,度汛,围堰",
            source="manual",
            project_id=project_id,
        )
        lesson = db.get_agent_lesson(conn, lesson_id)
        results = db.search_agent_lessons(conn, "度汛 围堰", project_id=project_id)

    assert lesson is not None
    assert lesson["title"] == "排涝项目度汛措施"
    assert results
    assert results[0]["lesson"] == "排涝调蓄项目技术标应重点核对度汛、围堰、导流和防渗措施。"


def test_agent_lessons_include_global_lessons_for_project_search(tmp_path: Path):
    db_path = tmp_path / "app.db"
    db.init_db(db_path)

    with db.db_session(db_path) as conn:
        project_id = db.create_project(conn, "水库除险加固")
        db.create_agent_lesson(
            conn,
            title="通用质量安全检查",
            lesson="质量、安全、进度、资源配置是技术标通用核查维度。",
            scope="technical_review",
            tags="质量,安全,进度",
            source="hermes",
        )
        results = db.search_agent_lessons(conn, "质量 安全", project_id=project_id)

    assert results
    assert results[0]["project_id"] is None
