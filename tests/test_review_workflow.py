from pathlib import Path

from bid_agent import db
from bid_agent.config import Settings
from bid_agent.document_service import ingest_document
from bid_agent.hermes import HermesResult
from bid_agent.review import ReviewWorkflow


def test_review_workflow_creates_report_with_mocked_hermes(tmp_path: Path, monkeypatch):
    settings = Settings(
        app_password="pw",
        session_secret="secret",
        storage_dir=tmp_path / "storage",
        reports_dir=tmp_path / "reports",
        database_url=f"sqlite:///{tmp_path / 'storage' / 'app.db'}",
        hermes_command="hermes",
        deepseek_api_key=None,
        deepseek_base_url=None,
        ocr_enabled=False,
        ocr_language="ch",
        hermes_timeout_seconds=5,
    )
    db.init_db(settings.database_path)
    with db.db_session(settings.database_path) as conn:
        project_id = db.create_project(conn, "示例项目")
        ingest_document(
            conn,
            settings=settings,
            file_bytes="资格要求：投标人应具备二级资质。商务报价缺少参数。".encode("utf-8"),
            filename="fake.txt",
            category="tender",
            project_id=project_id,
        )
        job_id = db.create_review_job(conn, project_id, "示例项目预审")

    def fake_run_hermes_prompt(**kwargs):
        return HermesResult(
            ok=True,
            stdout=(
                "# 预审报告\n\n"
                "## 资格核查\n有资质要求引用。\n\n"
                "## 评分项名称\n商务报价。\n\n"
                "满分 70，得分 无法计算，扣分/无法计算原因：缺少报价参数。\n\n"
                "引用依据：fake.txt。\n\n"
                "总分：无法计算。\n\n"
                "## 风险提示\n需复核。\n\n"
                "## 是否建议进入下一轮人工复核\n建议。"
            ),
            stderr="",
            returncode=0,
            command_display="hermes -z <prompt>",
        )

    monkeypatch.setattr("bid_agent.review.run_hermes_prompt", fake_run_hermes_prompt)
    ReviewWorkflow(settings).run(job_id)

    with db.db_session(settings.database_path) as conn:
        job = db.get_review_job(conn, job_id)
        artifacts = db.list_review_artifacts(conn, job_id)

    assert job["status"] == "completed"
    assert job["review_no"] == 1
    assert {artifact["artifact_type"] for artifact in artifacts} == {"prompt", "report"}
    assert all(str(tmp_path / "reports") in artifact["stored_path"] for artifact in artifacts)
    assert all("第001次" in artifact["stored_path"] for artifact in artifacts)
