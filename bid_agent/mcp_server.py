from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from bid_agent import db
from bid_agent.config import Settings, get_settings
from bid_agent.storage import ensure_project_report_dir, ensure_storage_dirs, write_project_report_artifact
from bid_agent.vector_store import index_project, search_project


mcp = FastMCP(
    "bid-review",
    instructions=(
        "Direct tools for the local bid-review workstation. Hermes is the active "
        "agent: use these tools to read SQLite project/document/chunk state, query "
        "the local Qdrant vector store, manage review jobs, save reports, and "
        "persist reusable review lessons. The FastAPI web app is only a data "
        "management surface for upload, parsing, cleanup, and human browsing."
    ),
)


def _settings() -> Settings:
    settings = get_settings()
    ensure_storage_dirs(settings.storage_dir)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(settings.database_path)
    return settings


def _require_project(conn, project_id: int) -> dict[str, Any]:
    project = db.get_project(conn, project_id)
    if project is None:
        raise ValueError(f"project not found: {project_id}")
    return project


@mcp.tool()
def bid_list_projects() -> dict[str, Any]:
    """List bid-review projects from the local SQLite database."""
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        return {"projects": db.list_projects(conn), "database_path": str(settings.database_path)}


@mcp.tool()
def bid_get_project(project_id: int) -> dict[str, Any]:
    """Get one project with parsed documents, vector state, and review jobs."""
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        project = _require_project(conn, project_id)
        documents = db.list_documents(conn, project_id=project_id, limit=500)
        jobs = db.list_review_jobs(conn, project_id=project_id, limit=50)
        return {"project": project, "documents": documents, "jobs": jobs}


@mcp.tool()
def bid_get_document_chunks(document_id: int, limit: int = 80) -> dict[str, Any]:
    """Read parsed Markdown chunks for one document directly from SQLite."""
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        document = db.get_document(conn, document_id)
        if document is None:
            raise ValueError(f"document not found: {document_id}")
        return {"document": document, "chunks": db.list_document_chunks(conn, document_id, limit=limit)}


@mcp.tool()
def bid_search_evidence(project_id: int, query: str, limit: int = 10) -> dict[str, Any]:
    """
    Search project evidence through local Qdrant, with SQLite FTS/LIKE fallback.

    Hermes decides which queries to ask and which returned evidence belongs in
    the report. This tool only retrieves candidate chunks with traceable metadata.
    """
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        _require_project(conn, project_id)

    vector_error = ""
    results: list[dict[str, Any]] = []
    source = "qdrant"
    try:
        results = search_project(settings=settings, project_id=project_id, query=query, limit=limit)
    except Exception as exc:
        vector_error = str(exc)

    if not results:
        with db.db_session(settings.database_path) as conn:
            results = db.search_chunks(conn, query, project_id=project_id, limit=limit)
        source = "sqlite_fts"

    return {
        "source": source,
        "query": query,
        "project_id": project_id,
        "vector_error": vector_error,
        "results": results,
    }


@mcp.tool()
def bid_rebuild_vector_index(project_id: int) -> dict[str, Any]:
    """Rebuild the local Qdrant vector index for a project from SQLite chunks."""
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        _require_project(conn, project_id)
        indexed = index_project(conn, settings=settings, project_id=project_id)
        return {"project_id": project_id, "indexed_chunks": indexed}


@mcp.tool()
def bid_create_review_job(project_id: int, title: str = "Hermes Agent 评审任务") -> dict[str, Any]:
    """Create a review job that Hermes can manage from CLI, desktop, or Feishu."""
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        _require_project(conn, project_id)
        job_id = db.create_review_job(conn, project_id, title)
        return {"job": db.get_review_job(conn, job_id)}


@mcp.tool()
def bid_get_review_job(job_id: int) -> dict[str, Any]:
    """Read one review job and its saved artifacts."""
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        job = db.get_review_job(conn, job_id)
        if job is None:
            raise ValueError(f"review job not found: {job_id}")
        artifacts = db.list_review_artifacts(conn, job_id)
        return {"job": job, "artifacts": artifacts}


@mcp.tool()
def bid_update_review_job(
    job_id: int,
    status: str | None = None,
    stage: str | None = None,
    progress: int | None = None,
    append_log: str = "",
    error_message: str | None = None,
) -> dict[str, Any]:
    """Update a Hermes-managed review job status, stage, progress, and log."""
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        current = db.get_review_job(conn, job_id)
        if current is None:
            raise ValueError(f"review job not found: {job_id}")
        log_text = current.get("log_text", "")
        if append_log.strip():
            log_text = f"{log_text.rstrip()}\n{append_log.strip()}\n"
        db.update_review_job(
            conn,
            job_id,
            status=status,
            stage=stage,
            progress=progress,
            log_text=log_text,
            error_message=error_message,
        )
        return {"job": db.get_review_job(conn, job_id)}


@mcp.tool()
def bid_save_review_report(
    project_id: int,
    markdown: str,
    title: str = "Hermes报告",
    job_id: int | None = None,
) -> dict[str, Any]:
    """Save the final Markdown review report into the project's report folder."""
    markdown = markdown.strip()
    if not markdown:
        raise ValueError("markdown is required")

    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        project = _require_project(conn, project_id)
        ensure_project_report_dir(settings.reports_dir, project_id, str(project["name"]))
        report_path = write_project_report_artifact(
            settings.reports_dir,
            project_id=project_id,
            project_name=str(project["name"]),
            filename=f"agent_report_{db.utc_now().replace(':', '').replace('-', '')}.md",
            text=markdown,
        )
        artifact_id = None
        if job_id is not None:
            job = db.get_review_job(conn, int(job_id))
            if job is None:
                raise ValueError(f"review job not found: {job_id}")
            artifact_id = db.create_review_artifact(
                conn,
                job_id=int(job_id),
                artifact_type="report",
                title=title,
                stored_path=str(report_path),
            )
        return {"stored_path": str(report_path), "artifact_id": artifact_id}


@mcp.tool()
def bid_search_agent_lessons(
    query: str = "",
    scope: str = "",
    project_id: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Search reusable Hermes review lessons and company-specific technical notes.

    Use this before scoring or planning so every entry point shares the same
    accumulated experience.
    """
    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        lessons = db.search_agent_lessons(
            conn,
            query=query,
            scope=scope,
            project_id=project_id,
            limit=limit,
        )
        return {"query": query, "scope": scope, "project_id": project_id, "lessons": lessons}


@mcp.tool()
def bid_save_agent_lesson(
    title: str,
    lesson: str,
    scope: str = "technical_review",
    tags: str = "",
    source: str = "hermes",
    project_id: int | None = None,
    document_id: int | None = None,
) -> dict[str, Any]:
    """
    Persist a reusable lesson from Hermes, desktop, CLI, or Feishu conversations.

    Save durable lessons only: review criteria, scene-specific risks, correction
    patterns, evidence requirements, and company scoring preferences.
    """
    if not lesson.strip():
        raise ValueError("lesson is required")

    settings = _settings()
    with db.db_session(settings.database_path) as conn:
        if project_id is not None:
            _require_project(conn, project_id)
        if document_id is not None and db.get_document(conn, document_id) is None:
            raise ValueError(f"document not found: {document_id}")
        lesson_id = db.create_agent_lesson(
            conn,
            title=title,
            lesson=lesson,
            scope=scope,
            tags=tags,
            source=source,
            project_id=project_id,
            document_id=document_id,
        )
        return {"lesson": db.get_agent_lesson(conn, lesson_id)}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
