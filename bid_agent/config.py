from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path | str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_password: str
    session_secret: str
    storage_dir: Path
    reports_dir: Path
    database_url: str
    hermes_command: str
    deepseek_api_key: str | None
    deepseek_base_url: str | None
    ocr_enabled: bool
    ocr_language: str
    hermes_timeout_seconds: int

    @property
    def database_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// DATABASE_URL is supported in v1.")
        raw_path = self.database_url.removeprefix("sqlite:///")
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path


def get_settings() -> Settings:
    load_dotenv()
    storage_dir = Path(os.getenv("STORAGE_DIR", "storage"))
    reports_dir = Path(os.getenv("REPORTS_DIR", "reports"))
    return Settings(
        app_password=os.getenv("APP_PASSWORD", "change-this-before-lan-use"),
        session_secret=os.getenv("SESSION_SECRET", "dev-session-secret-change-me"),
        storage_dir=storage_dir,
        reports_dir=reports_dir,
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{storage_dir / 'app.db'}"),
        hermes_command=os.getenv("HERMES_COMMAND", "hermes"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL") or None,
        ocr_enabled=_bool_env("OCR_ENABLED", True),
        ocr_language=os.getenv("OCR_LANGUAGE", "ch"),
        hermes_timeout_seconds=int(os.getenv("HERMES_TIMEOUT_SECONDS", "900")),
    )
