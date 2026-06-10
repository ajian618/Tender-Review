from pathlib import Path
from types import SimpleNamespace

from bid_agent.config import Settings
from bid_agent.hermes import run_hermes_agent_task


def test_run_hermes_agent_task_uses_hermes_cli_config_by_default(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_run(parts, **kwargs):
        captured["parts"] = parts
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("bid_agent.hermes.shutil.which", lambda command: command)
    monkeypatch.setattr("bid_agent.hermes.subprocess.run", fake_run)

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

    result = run_hermes_agent_task(settings=settings, task="hello", workdir=tmp_path)

    assert captured["parts"] == [
        "hermes",
        "-z",
        "hello",
    ]
    assert result.ok is True
    assert result.command_display == "hermes -z <agent-task>"
