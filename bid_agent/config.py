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
    document_parser: str
    document_language: str
    vector_enabled: bool
    vector_store_dir: Path
    vector_collection: str
    embedding_model: str
    embedding_dim: int

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
    vector_store_dir = Path(os.getenv("VECTOR_STORE_DIR", str(storage_dir / "qdrant")))
    return Settings(
        app_password=os.getenv("APP_PASSWORD", "change-this-before-lan-use"),
        session_secret=os.getenv("SESSION_SECRET", "dev-session-secret-change-me"),
        storage_dir=storage_dir,
        reports_dir=reports_dir,
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{storage_dir / 'app.db'}"),
        document_parser=os.getenv("DOCUMENT_PARSER", "paddle_structure"),
        document_language=os.getenv("DOCUMENT_LANGUAGE", "ch"),
        vector_enabled=_bool_env("VECTOR_ENABLED", True),
        vector_store_dir=vector_store_dir,
        vector_collection=os.getenv("VECTOR_COLLECTION", "bid_documents"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "512")),
    )
