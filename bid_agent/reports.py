from __future__ import annotations

REQUIRED_REPORT_SECTIONS = [
    "资格核查",
    "评分项",
    "得分",
    "无法计算",
    "扣分",
    "引用",
    "风险提示",
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
        f"# {project_name} 预审报告",
        "",
        "## Hermes 运行状态",
        "",
        f"Hermes Agent 未完成正式评审：{reason}",
        "",
        "## 资格核查",
        "",
        "当前仅能根据已入库文本片段列出待核查事项，不能给出正式通过结论。",
        "",
        "| 核查项 | 状态 | 引用 |",
        "|---|---|---|",
        "| 企业资质、营业执照、安全生产许可证 | 需人工复核 | 见下方候选证据 |",
        "| 资质动态核查结果 | 需人工复核 | 见下方候选证据 |",
        "| 项目负责人、人员证书、社保 | 需人工复核 | 见下方候选证据 |",
        "",
        "## 评分项",
        "",
        "Hermes 未完成评分项抽取，得分暂记为无法计算。",
        "",
        "| 评分项 | 满分 | 得分 | 扣分/无法计算原因 | 引用 |",
        "|---|---:|---:|---|---|",
        "| 技术评分 | 待抽取 | 无法计算 | Hermes 未完成正式评审，需人工复核评分标准和技术响应 | 见候选证据 |",
        "| 商务报价 | 待抽取 | 无法计算 | 缺少或未识别报价、评标基准价、平均报价等必要参数时不得编造分数 | 见候选证据 |",
        "| 资信/信用 | 待抽取 | 无法计算 | 需核对信用等级、资质证书、业绩和人员材料 | 见候选证据 |",
        "",
        "## 候选引用证据",
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
            "## 风险提示",
            "",
            "- 本报告不是正式定分结果，只能作为人工预审辅助。",
            "- 扫描件、表格和证书真伪需要人工或外部系统核验。",
            "- 商务报价缺少必要参数时必须保持“无法计算”。",
            "",
            "## 是否建议进入下一轮人工复核",
            "",
            "建议进入人工复核，但需先补齐 Hermes 运行失败原因并复核完整资格文件、商务报价和信用/资质材料。",
            "",
        ]
    )
    return "\n".join(lines)
