from __future__ import annotations

import hmac
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bid_agent import db
from bid_agent.config import Settings, get_settings
from bid_agent.document_service import (
    cancel_document_parse,
    create_document_upload,
    process_document_by_id,
    queue_reparse_document,
)
from bid_agent.review import ReviewWorkflow
from bid_agent.storage import ensure_project_report_dir, ensure_storage_dirs, write_project_report_artifact
from bid_agent.vector_store import index_project, search_project

COOKIE_NAME = "bid_agent_session"

settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _sign(secret: str, value: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), "sha256").hexdigest()
    return f"{value}.{digest}"


def _verify(secret: str, signed_value: str | None) -> bool:
    if not signed_value or "." not in signed_value:
        return False
    value, digest = signed_value.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), "sha256").hexdigest()
    return hmac.compare_digest(digest, expected) and value == "authenticated"


def is_authenticated(request: Request) -> bool:
    return _verify(settings.session_secret, request.cookies.get(COOKIE_NAME))


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise AuthRedirect()


def require_tool_auth(request: Request) -> None:
    if not settings.agent_tool_token:
        return
    token = request.headers.get("x-agent-tool-token", "")
    if not hmac.compare_digest(token, settings.agent_tool_token):
        raise HTTPException(status_code=403, detail="agent tool token invalid")


class AuthRedirect(Exception):
    pass


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    ensure_storage_dirs(settings.storage_dir)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(settings.database_path)
    with db.db_session(settings.database_path) as conn:
        for project in db.list_projects(conn):
            ensure_project_report_dir(
                settings.reports_dir,
                int(project["id"]),
                str(project["name"]),
            )
    yield


app = FastAPI(title="标书 Hermes Agent 智能评审系统", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.exception_handler(AuthRedirect)
async def auth_redirect_handler(request: Request, exc: AuthRedirect):
    return RedirectResponse(url="/login", status_code=303)


@app.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": ""})


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    if hmac.compare_digest(password, settings.app_password):
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            _sign(settings.session_secret, "authenticated"),
            httponly=True,
            samesite="lax",
        )
        return response
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "密码不正确"},
        status_code=401,
    )


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def project_list(request: Request):
    with db.db_session(settings.database_path) as conn:
        projects = db.list_projects(conn)
        jobs = db.list_review_jobs(conn, limit=8)
    return templates.TemplateResponse(
        request=request,
        name="projects.html",
        context={"projects": projects, "jobs": jobs},
    )


@app.post("/projects", dependencies=[Depends(require_auth)])
def create_project(name: str = Form(...), owner: str = Form("")):
    with db.db_session(settings.database_path) as conn:
        project_id = db.create_project(conn, name=name, owner=owner)
        ensure_project_report_dir(settings.reports_dir, project_id, name)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def project_detail(request: Request, project_id: int):
    with db.db_session(settings.database_path) as conn:
        project = db.get_project(conn, project_id)
        if project is None:
            return PlainTextResponse("project not found", status_code=404)
        documents = db.list_documents(conn, project_id=project_id, limit=200)
        jobs = db.list_review_jobs(conn, project_id=project_id, limit=30)
    return templates.TemplateResponse(
        request=request,
        name="project_detail.html",
        context={
            "project": project,
            "documents": documents,
            "jobs": jobs,
            "categories": DOCUMENT_CATEGORIES,
        },
    )


DOCUMENT_CATEGORIES = [
    ("tender", "招标文件"),
    ("proposal", "投标文件"),
    ("qualification", "资质/证书"),
    ("performance", "业绩"),
    ("credit", "信用/资信"),
    ("commercial", "商务报价"),
    ("other", "其他材料"),
]


@app.post("/projects/{project_id}/documents", dependencies=[Depends(require_auth)])
async def upload_project_document(
    project_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    category: str = Form("other"),
    title: str = Form(""),
):
    file_bytes = await file.read()
    with db.db_session(settings.database_path) as conn:
        project = db.get_project(conn, project_id)
        if project is None:
            return PlainTextResponse("project not found", status_code=404)
        document_id = create_document_upload(
            conn,
            settings=settings,
            file_bytes=file_bytes,
            filename=file.filename or "uploaded_file",
            category=category,
            project_id=project_id,
            title=title,
        )
    background_tasks.add_task(process_document_by_id, settings, document_id)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.get("/documents", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def document_library(request: Request, q: str = ""):
    with db.db_session(settings.database_path) as conn:
        documents = db.list_documents(conn, limit=300)
        results = db.search_chunks(conn, q, limit=30) if q.strip() else []
    return templates.TemplateResponse(
        request=request,
        name="documents.html",
        context={"documents": documents, "results": results, "q": q},
    )


@app.get("/documents/{document_id}", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def document_detail(request: Request, document_id: int):
    with db.db_session(settings.database_path) as conn:
        document = db.get_document(conn, document_id)
        if document is None:
            return PlainTextResponse("document not found", status_code=404)
        chunks = db.list_document_chunks(conn, document_id, limit=200)
    return templates.TemplateResponse(
        request=request,
        name="document_detail.html",
        context={"document": document, "chunks": chunks, "categories": DOCUMENT_CATEGORIES},
    )


@app.get("/api/agent/projects", dependencies=[Depends(require_tool_auth)])
def agent_list_projects():
    with db.db_session(settings.database_path) as conn:
        return {"projects": db.list_projects(conn)}


@app.get("/api/agent/projects/{project_id}", dependencies=[Depends(require_tool_auth)])
def agent_get_project(project_id: int):
    with db.db_session(settings.database_path) as conn:
        project = db.get_project(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        documents = db.list_documents(conn, project_id=project_id, limit=500)
        jobs = db.list_review_jobs(conn, project_id=project_id, limit=50)
        return {"project": project, "documents": documents, "jobs": jobs}


@app.get("/api/projects/{project_id}/documents/status", dependencies=[Depends(require_auth)])
def project_document_status(project_id: int):
    with db.db_session(settings.database_path) as conn:
        project = db.get_project(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        documents = db.list_documents(conn, project_id=project_id, limit=500)
        return {"documents": [_document_status_payload(document) for document in documents]}


@app.get("/api/documents/{document_id}/status", dependencies=[Depends(require_auth)])
def document_status(document_id: int):
    with db.db_session(settings.database_path) as conn:
        document = db.get_document(conn, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        return {"document": _document_status_payload(document)}


@app.get("/api/agent/documents/{document_id}/chunks", dependencies=[Depends(require_tool_auth)])
def agent_get_document_chunks(document_id: int, limit: int = 80):
    with db.db_session(settings.database_path) as conn:
        document = db.get_document(conn, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        return {"document": document, "chunks": db.list_document_chunks(conn, document_id, limit=limit)}


@app.get("/api/agent/projects/{project_id}/search", dependencies=[Depends(require_tool_auth)])
def agent_search_project(project_id: int, q: str, limit: int = 10):
    try:
        results = search_project(settings=settings, project_id=project_id, query=q, limit=limit)
        source = "qdrant"
    except Exception:
        with db.db_session(settings.database_path) as conn:
            results = db.search_chunks(conn, q, project_id=project_id, limit=limit)
        source = "sqlite_fts"
    return {"source": source, "query": q, "results": results}


@app.post("/api/agent/projects/{project_id}/vector-index", dependencies=[Depends(require_tool_auth)])
def agent_index_project(project_id: int):
    with db.db_session(settings.database_path) as conn:
        project = db.get_project(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        indexed = index_project(conn, settings=settings, project_id=project_id)
        return {"project_id": project_id, "indexed_chunks": indexed}


@app.post("/api/agent/projects/{project_id}/reports", dependencies=[Depends(require_tool_auth)])
def agent_save_project_report(project_id: int, payload: dict = Body(...)):
    title = str(payload.get("title") or "Hermes智能预审报告")
    markdown = str(payload.get("markdown") or "").strip()
    job_id = payload.get("job_id")
    if not markdown:
        raise HTTPException(status_code=400, detail="markdown is required")
    with db.db_session(settings.database_path) as conn:
        project = db.get_project(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        report_path = write_project_report_artifact(
            settings.reports_dir,
            project_id=project_id,
            project_name=str(project["name"]),
            filename=f"agent_report_{db.utc_now().replace(':', '').replace('-', '')}.md",
            text=markdown,
        )
        artifact_id = None
        if job_id:
            artifact_id = db.create_review_artifact(
                conn,
                job_id=int(job_id),
                artifact_type="report",
                title=title,
                stored_path=str(report_path),
            )
        return {"stored_path": str(report_path), "artifact_id": artifact_id}


@app.post("/documents/{document_id}/reparse", dependencies=[Depends(require_auth)])
def reparse_document_route(
    document_id: int,
    background_tasks: BackgroundTasks,
    category: str | None = Form(None),
):
    with db.db_session(settings.database_path) as conn:
        document = db.get_document(conn, document_id)
        if document is None:
            return PlainTextResponse("document not found", status_code=404)
        if str(document["extraction_status"]) in {"queued", "running", "cancel_requested"}:
            return PlainTextResponse(
                "document is already parsing; stop and clear it before reparsing",
                status_code=400,
            )
        if category:
            if category not in {value for value, _label in DOCUMENT_CATEGORIES}:
                return PlainTextResponse("invalid document category", status_code=400)
            db.update_document_category(conn, document_id, category)
        try:
            queue_reparse_document(conn, settings=settings, document_id=document_id)
        except ValueError as exc:
            return PlainTextResponse(str(exc), status_code=400)
        project_id = document["project_id"]
    background_tasks.add_task(process_document_by_id, settings, document_id)
    if project_id:
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    return RedirectResponse(url=f"/documents/{document_id}", status_code=303)


@app.post("/documents/{document_id}/cancel-parse", dependencies=[Depends(require_auth)])
def cancel_document_parse_route(document_id: int):
    with db.db_session(settings.database_path) as conn:
        document = db.get_document(conn, document_id)
        if document is None:
            return PlainTextResponse("document not found", status_code=404)
        cancel_document_parse(conn, settings=settings, document_id=document_id)
        project_id = document["project_id"]
    if project_id:
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    return RedirectResponse(url=f"/documents/{document_id}", status_code=303)


@app.post("/projects/{project_id}/review", dependencies=[Depends(require_auth)])
def create_review(project_id: int, background_tasks: BackgroundTasks):
    with db.db_session(settings.database_path) as conn:
        project = db.get_project(conn, project_id)
        if project is None:
            return PlainTextResponse("project not found", status_code=404)
        job_id = db.create_review_job(conn, project_id, f"{project['name']} 技术标智能预审")
    background_tasks.add_task(ReviewWorkflow(settings).run, job_id)
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/projects/{project_id}/vector-index", dependencies=[Depends(require_auth)])
def rebuild_project_vector_index(project_id: int):
    with db.db_session(settings.database_path) as conn:
        project = db.get_project(conn, project_id)
        if project is None:
            return PlainTextResponse("project not found", status_code=404)
        index_project(conn, settings=settings, project_id=project_id)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def job_detail(request: Request, job_id: int):
    with db.db_session(settings.database_path) as conn:
        job = db.get_review_job(conn, job_id)
        if job is None:
            return PlainTextResponse("job not found", status_code=404)
        artifacts = db.list_review_artifacts(conn, job_id)
    report_text = ""
    report_dir = ""
    for artifact in artifacts:
        path = Path(str(artifact["stored_path"]))
        if not path.exists():
            continue
        if artifact["artifact_type"] == "report":
            report_text = path.read_text(encoding="utf-8", errors="replace")
            report_dir = str(path.parent)
    return templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            "job": job,
            "artifacts": artifacts,
            "report_text": report_text,
            "report_dir": report_dir,
        },
    )


@app.get("/api/jobs/{job_id}/status", dependencies=[Depends(require_auth)])
def job_status(job_id: int):
    with db.db_session(settings.database_path) as conn:
        job = db.get_review_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        artifacts = db.list_review_artifacts(conn, job_id)
    report_text = ""
    report_dir = ""
    for artifact in artifacts:
        path = Path(str(artifact["stored_path"]))
        if artifact["artifact_type"] == "report" and path.exists():
            report_text = path.read_text(encoding="utf-8", errors="replace")
            report_dir = str(path.parent)
            break
    return {
        "job": _job_status_payload(job),
        "artifacts": artifacts,
        "report_text": report_text,
        "report_dir": report_dir,
    }


@app.post("/jobs/{job_id}/open-report-folder", dependencies=[Depends(require_auth)])
def open_report_folder(job_id: int):
    with db.db_session(settings.database_path) as conn:
        job = db.get_review_job(conn, job_id)
        if job is None:
            return PlainTextResponse("job not found", status_code=404)
        artifacts = db.list_review_artifacts(conn, job_id)

    report_path: Path | None = None
    for artifact in artifacts:
        path = Path(str(artifact["stored_path"]))
        if artifact["artifact_type"] == "report" and path.exists():
            report_path = path
            break
    if report_path is None:
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    resolved_report = report_path.resolve()
    allowed_roots = [
        settings.reports_dir.resolve(),
        (settings.storage_dir / "reports").resolve(),
    ]
    if not any(root == resolved_report.parent or root in resolved_report.parents for root in allowed_roots):
        return PlainTextResponse("report path is outside reports directory", status_code=400)

    folder = resolved_report.parent
    if os.name == "nt":
        subprocess.Popen(["explorer", str(folder)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


def main() -> None:
    import uvicorn

    host = __import__("os").getenv("APP_HOST", "0.0.0.0")
    port = int(__import__("os").getenv("APP_PORT", "8000"))
    uvicorn.run("bid_agent.app:app", host=host, port=port, reload=False)


def _document_status_payload(document: dict) -> dict:
    return {
        "id": document["id"],
        "title": document["title"],
        "category": document["category"],
        "extraction_status": document["extraction_status"],
        "ocr_status": document["ocr_status"],
        "parser_engine": document["parser_engine"],
        "parse_strategy": document.get("parse_strategy") or "",
        "parse_stage": document.get("parse_stage") or "",
        "parse_progress": int(document.get("parse_progress") or 0),
        "parse_current_page": int(document.get("parse_current_page") or 0),
        "parse_total_pages": int(document.get("parse_total_pages") or 0),
        "vector_status": document["vector_status"],
        "vector_error": document["vector_error"],
        "error_message": document.get("error_message") or "",
        "updated_at": document["updated_at"],
        "chunk_count": int(document.get("chunk_count") or 0),
    }


def _job_status_payload(job: dict) -> dict:
    return {
        "id": job["id"],
        "project_id": job["project_id"],
        "project_name": job["project_name"],
        "review_no": job["review_no"],
        "title": job["title"],
        "status": job["status"],
        "stage": job.get("stage") or "",
        "progress": int(job.get("progress") or 0),
        "log_text": job.get("log_text") or "",
        "error_message": job.get("error_message") or "",
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "updated_at": job.get("updated_at"),
    }


if __name__ == "__main__":
    main()
