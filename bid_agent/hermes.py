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


def run_hermes_agent_task(*, settings: Settings, task: str, workdir: Path) -> HermesResult:
    parts = [*_command_parts(settings.hermes_command), "-z", task]
    env = os.environ.copy()
    env.setdefault("BID_AGENT_BASE_URL", settings.app_base_url)
    if settings.agent_tool_token:
        env.setdefault("AGENT_TOOL_TOKEN", settings.agent_tool_token)
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
    return HermesResult(
        ok=completed.returncode == 0 and bool(completed.stdout.strip()),
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
        returncode=completed.returncode,
        command_display=" ".join([parts[0], "-z", "<agent-task>"]),
    )


def build_agent_review_task(*, project_id: int, project_name: str, job_id: int) -> str:
    return f"""你是运行在公司电脑上的 Hermes 技术标评审专家。

当前系统只做技术标预评审。技术标满分固定为 25 分。资信、资格、商务报价、信用、业绩真实性和外部核验暂时全部假设为理想状态，不展开评价，不写长篇说明。

你必须作为智能体工作：不要要求用户把资料贴给你，也不要等待人工给你证据。你要主动调用本地 bid-review MCP 工具检索资料库和向量库，找出招标文件中的技术评分办法，并对投标文件中的技术响应进行拟定打分。

项目：
- project_id: {project_id}
- project_name: {project_name}
- review_job_id: {job_id}

必须执行的工作流：
1. 调用 bid_get_project 了解项目、文件分类、解析状态和向量状态。
2. 如发现向量库未建好或证据检索为空，调用 bid_rebuild_vector_index。
3. 必须多次调用 bid_search_evidence，不要只读文件清单后直接写报告。
4. 优先检索并识别招标文件中的技术标评分办法、技术方案要求、施工组织设计要求、质量/安全/进度/资源配置/重难点措施等技术评审项。
5. 围绕每个技术评审项检索投标文件响应，形成“评分项 -> 投标响应 -> 证据引用 -> 拟扣分”的证据链。
6. 必须给出技术标拟定总分，格式为 `技术标拟定得分：X/25`。除非完全没有技术标材料，否则不得只写“无法计算”。
7. 如果招标文件中明确列出技术评分分项，按原分项表打分；如果分项权重不完整，将识别到的技术要求归并为 25 分制分项，并说明这是预评分归并口径。
8. 每个扣分点都必须引用工具返回的文件名、页码/块号/片段位置；没有证据就写“当前材料未见证据”，并在该项谨慎扣分。
9. 资信、资格、商务报价、信用、业绩真实性、证书真伪、社保和外部平台核验只在“本次评审假设”中用一句话说明为理想状态/暂不评价，不得展开成章节。
10. 生成最终 Markdown 报告后，调用 bid_save_review_report 保存报告，job_id 使用 {job_id}。

报告必须简洁，避免套话。只包含以下章节：
1. `# 技术标预评审结论`
   - 第一行必须写：`技术标拟定得分：X/25`
   - 一句话说明主要扣分原因。
2. `## 技术评分表`
   - 表格列：`评审项 | 满分 | 拟得分 | 扣分 | 证据/依据`
   - 总分必须汇总为 25 分。
3. `## 主要扣分依据`
   - 只列有实际扣分或证据不足的项，逐条引用文件名和页码/块号。
4. `## 需人工复核`
   - 只列技术方案里 OCR/图表/关键承诺不清楚的内容。
5. `## 本次评审假设`
   - 固定写：`本次仅评价技术标；资信、资格、商务报价、信用等非技术标因素暂按理想状态处理。`

最终回答只输出保存后的报告摘要和报告路径，不要输出内部思考过程。
"""
