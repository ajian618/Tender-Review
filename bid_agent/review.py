from __future__ import annotations

import traceback
from datetime import datetime

from bid_agent import db
from bid_agent.config import Settings
from bid_agent.hermes import build_review_prompt, run_hermes_prompt
from bid_agent.reports import append_validation_notes, build_fallback_report
from bid_agent.search import collect_review_evidence
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
                started_at=db.utc_now(),
                log_text="评审任务已启动。\n",
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
            documents = db.list_documents(conn, project_id=project_id, limit=500)
            evidence = collect_review_evidence(conn, project_id=project_id)
            generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            file_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            log = [
                "读取项目和文件完成。",
                f"评审次数：第 {review_no} 次",
                f"生成时间：{generated_at}",
                f"文件数量：{len(documents)}",
                f"候选证据片段：{len(evidence)}",
            ]
            prompt = build_review_prompt(
                project_name=project_name,
                documents=documents,
                evidence=evidence,
            )
            prompt_with_meta = (
                f"# 第 {review_no} 次评审 Prompt\n\n"
                f"- 项目：{project_name}\n"
                f"- 任务 ID：{job_id}\n"
                f"- 生成时间：{generated_at}\n\n"
                "---\n\n"
                f"{prompt}"
            )
            prompt_path = write_project_report_artifact(
                self.settings.reports_dir,
                project_id=project_id,
                project_name=project_name,
                filename=f"第{review_no:03d}次_{file_stamp}_prompt.md",
                text=prompt_with_meta,
            )
            db.create_review_artifact(
                conn,
                job_id=job_id,
                artifact_type="prompt",
                title=f"第 {review_no} 次 Hermes 任务提示词（{generated_at}）",
                stored_path=str(prompt_path),
            )
            db.update_review_job(conn, job_id, log_text="\n".join(log) + "\n正在调用 Hermes Agent...\n")

        hermes_error = ""
        hermes_instruction = (
            "请读取下面这个 UTF-8 Markdown 文件，并严格执行文件中的投标预审任务要求。"
            "最终只输出预审报告 Markdown，不要输出读取过程。\n\n"
            f"Prompt 文件路径：{prompt_path.resolve()}"
        )
        try:
            result = run_hermes_prompt(
                settings=self.settings,
                prompt=hermes_instruction,
                workdir=prompt_path.parent,
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
                    evidence=evidence,
                    reason=hermes_error[:1000],
                )
                final_status = "failed"
        except Exception as exc:
            hermes_error = str(exc)
            report = build_fallback_report(
                project_name=project_name,
                evidence=evidence,
                reason=hermes_error,
            )
            final_status = "failed"

        report = append_validation_notes(report)
        report_with_meta = (
            f"# 第 {review_no} 次评审报告\n\n"
            f"- 项目：{project_name}\n"
            f"- 任务 ID：{job_id}\n"
            f"- 生成时间：{generated_at}\n"
            f"- 报告目录：{prompt_path.parent}\n\n"
            "---\n\n"
            f"{report}"
        )
        report_path = write_project_report_artifact(
            self.settings.reports_dir,
            project_id=project_id,
            project_name=project_name,
            filename=f"第{review_no:03d}次_{file_stamp}_report.md",
            text=report_with_meta,
        )

        with db.db_session(self.settings.database_path) as conn:
            db.create_review_artifact(
                conn,
                job_id=job_id,
                artifact_type="report",
                title=f"第 {review_no} 次预审报告（{generated_at}）",
                stored_path=str(report_path),
            )
            log.append(f"报告已生成：{report_path}")
            db.update_review_job(
                conn,
                job_id,
                status=final_status,
                error_message=hermes_error,
                finished_at=db.utc_now(),
                log_text="\n".join(log) + "\n",
            )
