from bid_agent.reports import append_validation_notes, build_fallback_report, missing_report_sections


def test_report_validation_appends_missing_sections():
    report = append_validation_notes("# 报告\n\n## 技术标预评审结论\n")
    assert "系统校验补充" in report
    assert "人工复核" in report


def test_fallback_report_uses_technical_score_scope():
    report = build_fallback_report(project_name="示例项目", evidence=[], reason="hermes missing")
    assert "技术标拟定得分" in report
    assert "25" in report
    assert "本次仅评价技术标" in report
    assert missing_report_sections(report) == []
