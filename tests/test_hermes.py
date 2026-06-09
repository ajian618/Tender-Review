from pathlib import Path
from types import SimpleNamespace

from bid_agent.config import Settings
from bid_agent.hermes import run_hermes_prompt


def test_run_hermes_prompt_uses_hermes_cli_config_by_default(tmp_path: Path, monkeypatch):
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
        ocr_enabled=False,
        ocr_language="ch",
        hermes_timeout_seconds=5,
    )

    result = run_hermes_prompt(settings=settings, prompt="hello", workdir=tmp_path)

    assert captured["parts"] == [
        "hermes",
        "-z",
        "hello",
    ]
    assert result.ok is True
    assert result.command_display == "hermes -z <prompt>"
