from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bid_agent.config import Settings


@dataclass(frozen=True)
class HermesResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    command_display: str


def _command_parts(command: str) -> list[str]:
    parts = shlex.split(command, posix=os.name != "nt")
    if not parts:
        raise ValueError("HERMES_COMMAND is empty")
    resolved = shutil.which(parts[0]) or parts[0]
    return [resolved, *parts[1:]]


def run_hermes_prompt(
    *,
    settings: Settings,
    prompt: str,
    workdir: Path,
) -> HermesResult:
    parts = [*_command_parts(settings.hermes_command), "-z", prompt]
    env = os.environ.copy()
    if settings.deepseek_api_key:
        env["DEEPSEEK_API_KEY"] = settings.deepseek_api_key
    if settings.deepseek_base_url:
        env["DEEPSEEK_BASE_URL"] = settings.deepseek_base_url
    completed = subprocess.run(
        parts,
        cwd=workdir,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=settings.hermes_timeout_seconds,
        check=False,
    )
    display = " ".join([parts[0], "-z", "<prompt>"])
    return HermesResult(
        ok=completed.returncode == 0 and bool(completed.stdout.strip()),
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
        returncode=completed.returncode,
        command_display=display,
    )


def build_review_prompt(
    *,
    project_name: str,
    documents: list[dict[str, object]],
    evidence: list[dict[str, object]],
) -> str:
    doc_lines = []
    for doc in documents:
        doc_lines.append(
            "- "
            f"id={doc['id']} category={doc['category']} title={doc['title']} "
            f"file={doc['original_filename']} extraction={doc['extraction_status']} "
            f"ocr={doc['ocr_status']}"
        )

    evidence_lines = []
    for index, item in enumerate(evidence[:80], start=1):
        source = item.get("title") or item.get("original_filename")
        page = item.get("page_number") or ""
        sheet = item.get("sheet_name") or ""
        location = f"page={page}" if page else f"sheet={sheet}" if sheet else f"chunk={item.get('chunk_index')}"
        text = str(item.get("text", "")).strip()
        if len(text) > 900:
            text = text[:900].rstrip() + "\n[证据片段已截断，完整原文在资料库文件详情页]"
        evidence_lines.append(
            f"### Evidence {index}\n"
            f"- source: {source}\n"
            f"- category: {item.get('category')}\n"
            f"- location: {location}\n"
            f"- matched_query: {item.get('query', '')}\n"
            f"- text:\n{text}\n"
        )

    return f"""你是一个用于工程投标文件预审的 Hermes Agent 工作流执行者。

项目名称：{project_name}

目标：基于系统提供的文件清单和候选原文证据，输出一份可给人工复核使用的预审报告。

严格要求：
1. 只依据候选证据中的原文，不要用常识补全。
2. 所有结论必须给出来源文件和页码/表格/片段位置。
3. 招标评分规则、资格要求、技术要求、商务要求需要分开说明。
4. 投标文件或资料库中未见证据的项目，得分写 0 或“无法计算”，原因写“当前材料未见证据”。
5. 商务报价评分缺少投标报价、最高投标限价、平均报价、评标基准价、其他投标人报价等参数时，不得编造分数。
6. 技术评分如属于专家主观打分，只能输出“AI 预评估”，并明确不是正式专家评分。
7. 输出必须包含：资格核查、评分项名称、满分、得分、扣分/无法计算原因、引用依据、总分、风险提示、是否建议进入下一轮人工复核。
8. 输出 Markdown。

文件清单：
{chr(10).join(doc_lines) if doc_lines else "无文件"}

候选原文证据：
{chr(10).join(evidence_lines) if evidence_lines else "无候选证据"}
"""
