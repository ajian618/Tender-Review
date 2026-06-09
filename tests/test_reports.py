from bid_agent.reports import append_validation_notes, build_fallback_report, missing_report_sections


def test_report_validation_appends_missing_sections():
    report = append_validation_notes("# 报告\n\n## 资格核查\n")
    assert "系统校验补充" in report
    assert "人工复核" in report


def test_fallback_report_keeps_commercial_score_uncomputed():
    report = build_fallback_report(project_name="示例项目", evidence=[], reason="hermes missing")
    assert "商务报价" in report
    assert "无法计算" in report
    assert missing_report_sections(report) == []
