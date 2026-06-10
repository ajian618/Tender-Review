from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


BASE_URL = os.getenv("BID_AGENT_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOOL_TOKEN = os.getenv("AGENT_TOOL_TOKEN", "")

mcp = FastMCP(
    "bid-review",
    instructions=(
        "Tools for the local bid-review workstation. Use them to inspect projects, "
        "search parsed tender/proposal evidence, rebuild the local Qdrant index, "
        "and save final review reports. Do not invent evidence; cite returned chunks."
    ),
)


def _headers() -> dict[str, str]:
    if not TOOL_TOKEN:
        return {}
    return {"x-agent-tool-token": TOOL_TOKEN}


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=120) as client:
        response = client.get(f"{BASE_URL}{path}", params=params, headers=_headers())
        response.raise_for_status()
        return response.json()


def _post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=300) as client:
        response = client.post(f"{BASE_URL}{path}", json=payload or {}, headers=_headers())
        response.raise_for_status()
        return response.json()


@mcp.tool()
def bid_list_projects() -> dict[str, Any]:
    """List bid-review projects available in the local workstation."""
    return _get("/api/agent/projects")


@mcp.tool()
def bid_get_project(project_id: int) -> dict[str, Any]:
    """Get one project with its parsed documents and review jobs."""
    return _get(f"/api/agent/projects/{project_id}")


@mcp.tool()
def bid_get_document_chunks(document_id: int, limit: int = 80) -> dict[str, Any]:
    """Read parsed Markdown chunks for one document."""
    return _get(f"/api/agent/documents/{document_id}/chunks", {"limit": limit})


@mcp.tool()
def bid_search_evidence(project_id: int, query: str, limit: int = 10) -> dict[str, Any]:
    """Search project evidence through local Qdrant semantic search with SQLite fallback."""
    return _get(f"/api/agent/projects/{project_id}/search", {"q": query, "limit": limit})


@mcp.tool()
def bid_rebuild_vector_index(project_id: int) -> dict[str, Any]:
    """Rebuild the local Qdrant vector index for a project."""
    return _post(f"/api/agent/projects/{project_id}/vector-index")


@mcp.tool()
def bid_save_review_report(
    project_id: int,
    markdown: str,
    title: str = "Hermes智能预审报告",
    job_id: int | None = None,
) -> dict[str, Any]:
    """Save the final Markdown review report into the project's report folder."""
    return _post(
        f"/api/agent/projects/{project_id}/reports",
        {"markdown": markdown, "title": title, "job_id": job_id},
    )


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
