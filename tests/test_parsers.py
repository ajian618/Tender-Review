from pathlib import Path

from bid_agent import parsers
from bid_agent.parsers import chunk_markdown, parse_document


def test_chunk_markdown_splits_long_text():
    text = "资格要求。" * 500
    chunks = chunk_markdown(text, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)


def test_parse_text_document(tmp_path: Path):
    path = tmp_path / "fake.txt"
    path.write_text("投标人应具备水利水电工程施工总承包二级资质。", encoding="utf-8")
    result = parse_document(path, engine="paddle_structure", language="ch")
    assert result.engine == "plain_markdown"
    assert result.status == "completed"
    assert "二级资质" in result.chunks[0].text


def test_parse_digital_pdf_uses_fast_text_route(tmp_path: Path):
    import fitz

    path = tmp_path / "digital.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Qualification requirements: bidder must provide evidence. " * 40,
    )
    doc.save(path)
    doc.close()

    result = parse_document(path, engine="paddle_structure", language="ch")

    assert result.engine == "pymupdf_pdf_text"
    assert result.status == "completed"
    assert result.metadata["page_count"] == 1
    assert "Qualification requirements" in result.markdown


def test_parse_mixed_pdf_keeps_pages_together(tmp_path: Path, monkeypatch):
    import fitz

    path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Digital tender page with qualification and scoring rules. " * 40,
    )
    doc.new_page()
    doc.save(path)
    doc.close()

    def fake_structure_page_parse(
        path_arg,
        *,
        page_numbers,
        language,
        progress_callback=None,
        progress_start=20,
        progress_end=85,
    ):
        assert page_numbers == [2]
        return {
            2: {
                "markdown": "OCR page: scanned certificate table.",
                "raw": [{"parser": "fake"}],
            }
        }

    monkeypatch.setattr(
        parsers,
        "_parse_low_text_pdf_pages_with_structure",
        fake_structure_page_parse,
    )

    result = parse_document(path, engine="paddle_structure", language="ch")

    assert result.engine == "hybrid_pdf"
    assert result.metadata["page_count"] == 2
    assert result.metadata["low_text_pages"] == [2]
    assert result.metadata["structure_page_numbers"] == [2]
    assert "Digital tender page" in result.markdown
    assert "OCR page: scanned certificate table." in result.markdown
    assert {chunk.page_number for chunk in result.chunks} == {1, 2}


def test_proposal_pdf_uses_structure_first_strategy(tmp_path: Path, monkeypatch):
    import fitz

    path = tmp_path / "proposal.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Proposal slide page with embedded evidence.")
    doc.save(path)
    doc.close()

    def fake_structure_page_parse(
        path_arg,
        *,
        page_numbers,
        language,
        progress_callback=None,
        progress_start=20,
        progress_end=85,
    ):
        assert page_numbers == [1]
        if progress_callback:
            progress_callback(
                {
                    "stage": "fake structure",
                    "progress": 50,
                    "current_page": 1,
                    "total_pages": 1,
                    "strategy": "paddle_structure_pages",
                }
            )
        return {1: {"markdown": "Structured proposal evidence.", "raw": []}}

    events = []
    monkeypatch.setattr(
        parsers,
        "_parse_low_text_pdf_pages_with_structure",
        fake_structure_page_parse,
    )

    result = parse_document(
        path,
        engine="paddle_structure",
        language="ch",
        category="proposal",
        progress_callback=events.append,
    )

    assert result.engine == "paddle_structure_pages"
    assert result.metadata["structure_page_count"] == 1
    assert result.chunks[0].block_type == "pdf_ocr_page"
    assert "Structured proposal evidence." in result.markdown
    assert any(event.get("strategy") == "paddle_structure_pages" for event in events)
