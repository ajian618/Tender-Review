from __future__ import annotations

import traceback
from threading import Event, Thread
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep

from bid_agent import db
from bid_agent.config import Settings
from bid_agent.hermes import build_agent_review_task, run_hermes_agent_task
from bid_agent.reports import append_validation_notes, build_fallback_report
from bid_agent.storage import write_project_report_artifact


class ReviewWorkflow:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, job_id: int) -> None:
        with db.db_session(self.settings.database_path) as conn:
            job = db.get_review_job(conn, job_id)
            if job is None:
                raise ValueError(f"Review job not found: {job_id}")
            project = db.get_project(conn, int(job["project_id"]))
            if project is None:
                raise ValueError(f"Project not found: {job['project_id']}")
            db.update_review_job(
                conn,
                job_id,
                status="running",
                stage="启动技术标评审",
                progress=5,
                started_at=db.utc_now(),
                log_text="Hermes Agent 技术标评审任务已启动。\n",
            )

        try:
            self._run_inner(job_id)
        except Exception as exc:
            with db.db_session(self.settings.database_path) as conn:
                current = db.get_review_job(conn, job_id)
                log_text = (current or {}).get("log_text", "")
                db.update_review_job(
                    conn,
                    job_id,
                    status="failed",
                    stage="系统异常",
                    progress=100,
                    error_message=str(exc),
                    finished_at=db.utc_now(),
                    log_text=log_text + "\n系统异常：\n" + traceback.format_exc(),
                )

    def _run_inner(self, job_id: int) -> None:
        with db.db_session(self.settings.database_path) as conn:
            job = db.get_review_job(conn, job_id)
            if job is None:
                raise ValueError(f"Review job not found: {job_id}")
            project_id = int(job["project_id"])
            review_no = int(job.get("review_no") or 1)
            project = db.get_project(conn, project_id)
            if project is None:
                raise ValueError(f"Project not found: {project_id}")
            project_name = str(project["name"])
            generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            file_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            log = [
                "读取项目状态完成。",
                f"评审次数：第 {review_no} 次",
                f"生成时间：{generated_at}",
                "评审范围：仅技术标，满分 25 分；资信、资格、商务报价等暂按理想状态处理。",
                "正在调用 Hermes Agent；技术评分办法识别、证据选择和拟定打分由 Hermes 通过 MCP 工具完成。",
            ]
            task = build_agent_review_task(
                project_id=project_id,
                project_name=project_name,
                job_id=job_id,
            )
            db.update_review_job(
                conn,
                job_id,
                stage="准备调用 Hermes 技术标评审 Agent",
                progress=15,
                log_text="\n".join(log) + "\n",
            )

        hermes_error = ""
        try:
            stop_heartbeat = Event()
            heartbeat = Thread(
                target=self._heartbeat_progress,
                args=(job_id, stop_heartbeat),
                daemon=True,
            )
            heartbeat.start()
            result = run_hermes_agent_task(
                settings=self.settings,
                task=task,
                workdir=Path.cwd(),
            )
            stop_heartbeat.set()
            heartbeat.join(timeout=2)
            self._set_progress(
                job_id,
                stage="Hermes 已返回结果，正在整理技术标报告",
                progress=88,
            )
            log.append(f"Hermes 命令：{result.command_display}")
            log.append(f"Hermes returncode：{result.returncode}")
            if result.stderr:
                log.append("Hermes stderr：")
                log.append(result.stderr[-4000:])
            if result.ok:
                report = result.stdout
                final_status = "completed"
            else:
                hermes_error = result.stderr or result.stdout or "Hermes 未返回有效报告"
                report = build_fallback_report(
                    project_name=project_name,
                    evidence=[],
                    reason=hermes_error[:1000],
                )
                final_status = "failed"
        except Exception as exc:
            try:
                stop_heartbeat.set()
            except UnboundLocalError:
                pass
            hermes_error = str(exc)
            report = build_fallback_report(
                project_name=project_name,
                evidence=[],
                reason=hermes_error,
            )
            final_status = "failed"

        with db.db_session(self.settings.database_path) as conn:
            existing_report_artifacts = [
                artifact
                for artifact in db.list_review_artifacts(conn, job_id)
                if artifact["artifact_type"] == "report"
            ]
            if not existing_report_artifacts:
                report = append_validation_notes(report)
                report_with_meta = (
                    f"# 第 {review_no} 次智能预审报告\n\n"
                    f"- 项目：{project_name}\n"
                    f"- 任务 ID：{job_id}\n"
                    f"- 生成时间：{generated_at}\n\n"
                    "---\n\n"
                    f"{report}"
                )
                report_path = write_project_report_artifact(
                    self.settings.reports_dir,
                    project_id=project_id,
                    project_name=project_name,
                    filename=f"第{review_no:03d}次_{file_stamp}_agent_report.md",
                    text=report_with_meta,
                )
                db.create_review_artifact(
                    conn,
                    job_id=job_id,
                    artifact_type="report",
                    title=f"第 {review_no} 次 Hermes 智能预审报告（{generated_at}）",
                    stored_path=str(report_path),
                )
                log.append(f"报告已生成：{report_path}")
            else:
                log.append(f"Hermes 已通过工具保存报告：{existing_report_artifacts[-1]['stored_path']}")
            db.update_review_job(
                conn,
                job_id,
                status=final_status,
                stage="技术标报告生成完成" if final_status == "completed" else "技术标报告生成失败",
                progress=100,
                error_message=hermes_error,
                finished_at=db.utc_now(),
                log_text="\n".join(log) + "\n",
            )

    def _heartbeat_progress(self, job_id: int, stop_event: Event) -> None:
        started = monotonic()
        last_bucket = -1
        while not stop_event.wait(5):
            elapsed = int(monotonic() - started)
            bucket = elapsed // 15
            if bucket == last_bucket:
                continue
            last_bucket = bucket
            progress = min(82, 25 + bucket * 6)
            stage = f"Hermes 正在检索技术标证据并拟定 25 分制评分，已运行 {elapsed} 秒"
            self._set_progress(job_id, stage=stage, progress=progress)

    def _set_progress(self, job_id: int, *, stage: str, progress: int) -> None:
        with db.db_session(self.settings.database_path) as conn:
            job = db.get_review_job(conn, job_id)
            if job is None or job["status"] not in {"queued", "running"}:
                return
            db.update_review_job(
                conn,
                job_id,
                status="running",
                stage=stage,
                progress=progress,
            )
