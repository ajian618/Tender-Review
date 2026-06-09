from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


@dataclass(frozen=True)
class StoredFile:
    path: Path
    sha256: str
    byte_size: int


def sanitize_filename(filename: str) -> str:
    cleaned = SAFE_NAME_RE.sub("_", filename.strip()).strip("._")
    return cleaned or "uploaded_file"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_storage_dirs(storage_dir: Path) -> None:
    for name in ("originals", "extracted", "ocr", "reports"):
        (storage_dir / name).mkdir(parents=True, exist_ok=True)


def project_report_folder_name(project_id: int, project_name: str) -> str:
    safe_name = sanitize_filename(project_name)
    return f"{project_id:03d}_{safe_name}"


def ensure_project_report_dir(reports_dir: Path, project_id: int, project_name: str) -> Path:
    target = reports_dir / project_report_folder_name(project_id, project_name)
    target.mkdir(parents=True, exist_ok=True)
    return target


def store_original(
    *,
    storage_dir: Path,
    data: bytes,
    original_filename: str,
    project_id: int | None,
) -> StoredFile:
    ensure_storage_dirs(storage_dir)
    digest = sha256_bytes(data)
    safe_name = sanitize_filename(original_filename)
    project_part = f"project-{project_id}" if project_id is not None else "library"
    target_dir = storage_dir / "originals" / project_part
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest[:16]}_{safe_name}"
    target.write_bytes(data)
    return StoredFile(path=target, sha256=digest, byte_size=len(data))


def write_text_artifact(storage_dir: Path, subdir: str, filename: str, text: str) -> Path:
    ensure_storage_dirs(storage_dir)
    target_dir = storage_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / sanitize_filename(filename)
    target.write_text(text, encoding="utf-8")
    return target


def write_project_report_artifact(
    reports_dir: Path,
    *,
    project_id: int,
    project_name: str,
    filename: str,
    text: str,
) -> Path:
    target_dir = ensure_project_report_dir(reports_dir, project_id, project_name)
    target = target_dir / sanitize_filename(filename)
    target.write_text(text, encoding="utf-8")
    return target
