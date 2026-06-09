from pathlib import Path

from bid_agent import db


def test_create_review_job_increments_review_no_per_project(tmp_path: Path):
    db_path = tmp_path / "app.db"
    db.init_db(db_path)
    with db.db_session(db_path) as conn:
        first_project = db.create_project(conn, "项目一")
        second_project = db.create_project(conn, "项目二")
        first_job = db.create_review_job(conn, first_project, "预审")
        second_job = db.create_review_job(conn, first_project, "复审")
        other_job = db.create_review_job(conn, second_project, "预审")

        first = db.get_review_job(conn, first_job)
        second = db.get_review_job(conn, second_job)
        other = db.get_review_job(conn, other_job)

    assert first["review_no"] == 1
    assert second["review_no"] == 2
    assert other["review_no"] == 1
