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
        document_parser="paddle_structure",
        document_language="ch",
        vector_enabled=False,
        vector_store_dir=tmp_path / "storage" / "qdrant",
        vector_collection="bid_documents",
        embedding_model="BAAI/bge-small-zh-v1.5",
        embedding_dim=512,
        agent_tool_token="",
        app_base_url="http://127.0.0.1:8000",
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

    def fake_run_hermes_agent_task(**kwargs):
        assert "bid_get_project" in kwargs["task"]
        assert "bid_search_evidence" in kwargs["task"]
        assert "bid_save_review_report" in kwargs["task"]
        return HermesResult(
            ok=True,
            stdout=(
                "# 技术标预评审结论\n\n"
                "技术标拟定得分：22/25\n\n"
                "## 技术评分表\n\n"
                "| 评审项 | 满分 | 拟得分 | 扣分 | 证据/依据 |\n"
                "|---|---:|---:|---|---|\n"
                "| 技术响应 | 25 | 22 | 部分措施不够细 | fake.txt chunk 0 引用 |\n\n"
                "## 主要扣分依据\nfake.txt chunk 0 引用。\n\n"
                "## 需人工复核\n复核技术措施。\n\n"
                "## 本次评审假设\n本次仅评价技术标；资信、资格、商务报价、信用等非技术标因素暂按理想状态处理。"
            ),
            stderr="",
            returncode=0,
            command_display="hermes -z <agent-task>",
        )

    monkeypatch.setattr("bid_agent.review.run_hermes_agent_task", fake_run_hermes_agent_task)
    ReviewWorkflow(settings).run(job_id)

    with db.db_session(settings.database_path) as conn:
        job = db.get_review_job(conn, job_id)
        artifacts = db.list_review_artifacts(conn, job_id)

    assert job["status"] == "completed"
    assert job["review_no"] == 1
    assert {artifact["artifact_type"] for artifact in artifacts} == {"report"}
    assert all(str(tmp_path / "reports") in artifact["stored_path"] for artifact in artifacts)
    assert all("_agent_report.md" in artifact["stored_path"] for artifact in artifacts)
