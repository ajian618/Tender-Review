from __future__ import annotations

REQUIRED_REPORT_SECTIONS = [
    "技术标",
    "25",
    "拟定得分",
    "扣分",
    "引用",
    "人工复核",
]


def missing_report_sections(report: str) -> list[str]:
    normalized = report.replace(" ", "")
    return [section for section in REQUIRED_REPORT_SECTIONS if section not in normalized]


def append_validation_notes(report: str) -> str:
    missing = missing_report_sections(report)
    if not missing:
        return report
    notes = [
        "",
        "## 系统校验补充",
        "",
        "以下报告要素在 Hermes 原始输出中不够明确，已标记给人工复核：",
        "",
    ]
    for item in missing:
        notes.append(f"- {item}")
    notes.extend(
        [
            "",
            "人工复核时应回到原始文件、抽取文本和引用页码确认结论。",
            "",
        ]
    )
    return report.rstrip() + "\n" + "\n".join(notes)


def build_fallback_report(
    *,
    project_name: str,
    evidence: list[dict[str, object]],
    reason: str,
) -> str:
    lines = [
        f"# {project_name} 技术标预评审报告",
        "",
        "## Hermes 运行状态",
        "",
        f"Hermes Agent 未完成正式评审：{reason}",
        "",
        "## 技术标预评审结论",
        "",
        "技术标拟定得分：待人工复核/25",
        "",
        "Hermes 未完成技术标评分，不能可靠给出 25 分制拟定分数。",
        "",
        "## 技术评分表",
        "",
        "| 评审项 | 满分 | 拟得分 | 扣分 | 证据/依据 |",
        "|---|---:|---:|---|---|",
        "| 技术标整体响应 | 25 | 待复核 | Hermes 未完成技术标评审 | 见候选证据 |",
        "",
        "## 主要扣分依据",
        "",
        "Hermes 未完成扣分依据生成，以下仅列候选技术证据供人工复核。",
        "",
        "## 候选技术证据引用",
        "",
    ]
    if not evidence:
        lines.append("未检索到候选证据。")
    for index, item in enumerate(evidence[:20], start=1):
        source = item.get("title") or item.get("original_filename") or f"document {item.get('document_id')}"
        page = item.get("page_number")
        location = f"PDF page {page}" if page else f"chunk {item.get('chunk_index')}"
        text = str(item.get("text", "")).strip().replace("\n", " ")
        lines.append(f"{index}. `{source}` {location}: {text[:500]}")
    lines.extend(
        [
            "",
            "## 需人工复核",
            "",
            "- 回到招标文件确认技术标评分办法和满分构成。",
            "- 回到投标文件确认施工组织设计、质量、安全、进度、资源配置和重难点措施是否完整。",
            "- 对 OCR 不清楚的表格、图片和流程图进行人工核对。",
            "",
            "## 本次评审假设",
            "",
            "本次仅评价技术标；资信、资格、商务报价、信用等非技术标因素暂按理想状态处理。",
            "",
        ]
    )
    return "\n".join(lines)
