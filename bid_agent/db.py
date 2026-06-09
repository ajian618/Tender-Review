from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_session(database_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(database_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def init_db(database_path: Path) -> None:
    with db_session(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                mime_type TEXT DEFAULT '',
                extraction_status TEXT NOT NULL DEFAULT 'pending',
                ocr_status TEXT NOT NULL DEFAULT 'not_needed',
                error_message TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                category TEXT NOT NULL,
                page_number INTEGER,
                sheet_name TEXT DEFAULT '',
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
                chunk_text,
                document_id UNINDEXED,
                chunk_id UNINDEXED,
                project_id UNINDEXED,
                category UNINDEXED,
                title UNINDEXED,
                tokenize='unicode61'
            );

            CREATE TABLE IF NOT EXISTS review_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                review_no INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                log_text TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS review_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES review_jobs(id) ON DELETE CASCADE,
                artifact_type TEXT NOT NULL,
                title TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        ensure_column(
            conn,
            "review_jobs",
            "review_no",
            "INTEGER NOT NULL DEFAULT 1",
        )
        normalize_review_numbers(conn)


def ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def normalize_review_numbers(conn: sqlite3.Connection) -> None:
    project_ids = [
        int(row["project_id"])
        for row in conn.execute("SELECT DISTINCT project_id FROM review_jobs").fetchall()
    ]
    for project_id in project_ids:
        rows = conn.execute(
            """
            SELECT id
            FROM review_jobs
            WHERE project_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            conn.execute(
                "UPDATE review_jobs SET review_no = ? WHERE id = ?",
                (index, int(row["id"])),
            )


def create_project(conn: sqlite3.Connection, name: str, owner: str = "") -> int:
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO projects (name, owner, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (name.strip(), owner.strip(), now, now),
    )
    return int(cur.lastrowid)


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.*,
               COUNT(DISTINCT d.id) AS document_count,
               COUNT(DISTINCT j.id) AS job_count
        FROM projects p
        LEFT JOIN documents d ON d.project_id = p.id
        LEFT JOIN review_jobs j ON j.project_id = p.id
        GROUP BY p.id
        ORDER BY p.updated_at DESC, p.id DESC
        """
    ).fetchall()
    return rows_to_dicts(rows)


def get_project(conn: sqlite3.Connection, project_id: int) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())


def touch_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (utc_now(), project_id))


def create_document(
    conn: sqlite3.Connection,
    *,
    project_id: int | None,
    title: str,
    category: str,
    original_filename: str,
    stored_path: str,
    sha256: str,
    byte_size: int,
    mime_type: str,
) -> int:
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO documents (
            project_id, title, category, original_filename, stored_path, sha256,
            byte_size, mime_type, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            title,
            category,
            original_filename,
            stored_path,
            sha256,
            byte_size,
            mime_type,
            now,
            now,
        ),
    )
    if project_id:
        touch_project(conn, project_id)
    return int(cur.lastrowid)


def update_document_extraction(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    extraction_status: str,
    ocr_status: str,
    error_message: str = "",
) -> None:
    conn.execute(
        """
        UPDATE documents
        SET extraction_status = ?, ocr_status = ?, error_message = ?, updated_at = ?
        WHERE id = ?
        """,
        (extraction_status, ocr_status, error_message, utc_now(), document_id),
    )


def list_documents(
    conn: sqlite3.Connection,
    *,
    project_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    params: tuple[Any, ...]
    where = ""
    if project_id is not None:
        where = "WHERE d.project_id = ?"
        params = (project_id, limit)
    else:
        params = (limit,)
    rows = conn.execute(
        f"""
        SELECT d.*, p.name AS project_name, COUNT(c.id) AS chunk_count
        FROM documents d
        LEFT JOIN projects p ON p.id = d.project_id
        LEFT JOIN document_chunks c ON c.document_id = d.id
        {where}
        GROUP BY d.id
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return rows_to_dicts(rows)


def get_document(conn: sqlite3.Connection, document_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT d.*, p.name AS project_name
            FROM documents d
            LEFT JOIN projects p ON p.id = d.project_id
            WHERE d.id = ?
            """,
            (document_id,),
        ).fetchone()
    )


def replace_document_chunks(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    project_id: int | None,
    category: str,
    title: str,
    chunks: list[dict[str, Any]],
) -> None:
    conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM document_fts WHERE document_id = ?", (str(document_id),))
    now = utc_now()
    for index, chunk in enumerate(chunks):
        text = str(chunk["text"]).strip()
        if not text:
            continue
        cur = conn.execute(
            """
            INSERT INTO document_chunks (
                document_id, project_id, category, page_number, sheet_name,
                chunk_index, text, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                project_id,
                category,
                chunk.get("page_number"),
                chunk.get("sheet_name", ""),
                index,
                text,
                now,
            ),
        )
        chunk_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO document_fts (
                chunk_text, document_id, chunk_id, project_id, category, title
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (text, str(document_id), str(chunk_id), str(project_id or ""), category, title),
        )


def list_document_chunks(
    conn: sqlite3.Connection,
    document_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM document_chunks
        WHERE document_id = ?
        ORDER BY chunk_index ASC
        LIMIT ?
        """,
        (document_id, limit),
    ).fetchall()
    return rows_to_dicts(rows)


def list_project_chunks(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    category: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: list[Any] = [project_id]
    where = "c.project_id = ?"
    if category is not None:
        where += " AND c.category = ?"
        params.append(category)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            c.id AS chunk_id,
            c.document_id,
            c.project_id,
            c.category,
            c.page_number,
            c.sheet_name,
            c.chunk_index,
            c.text,
            d.title,
            d.original_filename,
            0.0 AS rank
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE {where}
        ORDER BY d.id ASC, c.chunk_index ASC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return rows_to_dicts(rows)


def search_chunks(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    cleaned = " ".join(part.strip() for part in query.split() if part.strip())
    if not cleaned:
        return []
    where = "document_fts MATCH ?"
    params: list[Any] = [cleaned]
    if project_id is not None:
        where += " AND document_fts.project_id = ?"
        params.append(str(project_id))
    params.append(limit)
    try:
        rows = conn.execute(
            f"""
            SELECT
                c.id AS chunk_id,
                c.document_id,
                c.project_id,
                c.category,
                c.page_number,
                c.sheet_name,
                c.chunk_index,
                c.text,
                d.title,
                d.original_filename,
                bm25(document_fts) AS rank
            FROM document_fts
            JOIN document_chunks c ON c.id = CAST(document_fts.chunk_id AS INTEGER)
            JOIN documents d ON d.id = c.document_id
            WHERE {where}
            ORDER BY rank ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    results = rows_to_dicts(rows)
    if results:
        return results
    return like_search_chunks(conn, cleaned, project_id=project_id, limit=limit)


def like_search_chunks(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    terms = [term.strip() for term in query.split() if term.strip()] or [query.strip()]
    where_parts = ["(" + " OR ".join("c.text LIKE ?" for _ in terms) + ")"]
    params: list[Any] = [f"%{term}%" for term in terms]
    if project_id is not None:
        where_parts.append("c.project_id = ?")
        params.append(project_id)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            c.id AS chunk_id,
            c.document_id,
            c.project_id,
            c.category,
            c.page_number,
            c.sheet_name,
            c.chunk_index,
            c.text,
            d.title,
            d.original_filename,
            0.0 AS rank
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE {' AND '.join(where_parts)}
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return rows_to_dicts(rows)


def create_review_job(conn: sqlite3.Connection, project_id: int, title: str) -> int:
    now = utc_now()
    row = conn.execute(
        "SELECT COALESCE(MAX(review_no), 0) + 1 AS next_no FROM review_jobs WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    review_no = int(row["next_no"] if row else 1)
    cur = conn.execute(
        """
        INSERT INTO review_jobs (project_id, review_no, status, title, created_at, updated_at)
        VALUES (?, ?, 'queued', ?, ?, ?)
        """,
        (project_id, review_no, title, now, now),
    )
    touch_project(conn, project_id)
    return int(cur.lastrowid)


def get_review_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT j.*, p.name AS project_name
            FROM review_jobs j
            JOIN projects p ON p.id = j.project_id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    )


def list_review_jobs(
    conn: sqlite3.Connection,
    *,
    project_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: tuple[Any, ...]
    where = ""
    if project_id is not None:
        where = "WHERE j.project_id = ?"
        params = (project_id, limit)
    else:
        params = (limit,)
    rows = conn.execute(
        f"""
        SELECT j.*, p.name AS project_name
        FROM review_jobs j
        JOIN projects p ON p.id = j.project_id
        {where}
        ORDER BY j.created_at DESC, j.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return rows_to_dicts(rows)


def update_review_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: str | None = None,
    log_text: str | None = None,
    error_message: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> None:
    current = get_review_job(conn, job_id)
    if current is None:
        raise ValueError(f"Review job not found: {job_id}")
    conn.execute(
        """
        UPDATE review_jobs
        SET status = ?,
            log_text = ?,
            error_message = ?,
            started_at = COALESCE(?, started_at),
            finished_at = COALESCE(?, finished_at),
            updated_at = ?
        WHERE id = ?
        """,
        (
            status or current["status"],
            log_text if log_text is not None else current["log_text"],
            error_message if error_message is not None else current["error_message"],
            started_at,
            finished_at,
            utc_now(),
            job_id,
        ),
    )


def create_review_artifact(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    artifact_type: str,
    title: str,
    stored_path: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO review_artifacts (job_id, artifact_type, title, stored_path, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_id, artifact_type, title, stored_path, utc_now()),
    )
    return int(cur.lastrowid)


def list_review_artifacts(conn: sqlite3.Connection, job_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM review_artifacts
        WHERE job_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (job_id,),
    ).fetchall()
    return rows_to_dicts(rows)
