from pathlib import Path

from bid_agent import db
from bid_agent.search import collect_review_evidence


def _add_doc(conn, project_id: int, title: str, category: str, text: str) -> int:
    document_id = db.create_document(
        conn,
        project_id=project_id,
        title=title,
        category=category,
        original_filename=f"{title}.txt",
        stored_path=f"{title}.txt",
        sha256=title,
        byte_size=len(text),
        mime_type="text/plain",
    )
    db.replace_document_chunks(
        conn,
        document_id=document_id,
        project_id=project_id,
        category=category,
        title=title,
        chunks=[{"text": text}],
    )
    return document_id


def test_collect_review_evidence_seeds_tender_and_proposal(tmp_path: Path):
    db_path = tmp_path / "app.db"
    db.init_db(db_path)
    with db.db_session(db_path) as conn:
        project_id = db.create_project(conn, "示例项目")
        _add_doc(conn, project_id, "招标", "tender", "资格要求：二级资质。")
        _add_doc(conn, project_id, "投标", "proposal", "施工组织设计和项目管理人员配置。")
        evidence = collect_review_evidence(conn, project_id=project_id)

    categories = {item["category"] for item in evidence}
    assert "tender" in categories
    assert "proposal" in categories
