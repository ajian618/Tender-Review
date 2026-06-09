from pathlib import Path

from bid_agent.extractors import chunk_text, extract_document


def test_chunk_text_splits_long_text():
    text = "资格要求。" * 500
    chunks = chunk_text(text, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)


def test_extract_text_document(tmp_path: Path):
    path = tmp_path / "fake.txt"
    path.write_text("投标人应具备水利水电工程施工总承包二级资质。", encoding="utf-8")
    chunks, ocr_status = extract_document(path, ocr_enabled=False, ocr_language="ch")
    assert ocr_status == "not_needed"
    assert "二级资质" in chunks[0]["text"]
