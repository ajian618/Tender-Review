from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".xlsm",
    ".pptx",
    ".txt",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
}

OFFICE_EXTENSIONS = {".docx", ".xlsx", ".xlsm", ".pptx"}
STRUCTURE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
TEXT_EXTENSIONS = {".txt", ".md"}
_STRUCTURE_PARSERS: dict[str, Any] = {}
PDF_TEXT_LOW_PAGE_CHARS = 40
STRUCTURE_FIRST_CATEGORIES = {"proposal", "qualification", "performance", "credit", "commercial"}
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ParsedChunk:
    text: str
    page_number: int | None = None
    sheet_name: str = ""
    block_type: str = "markdown"


@dataclass(frozen=True)
class ParseResult:
    engine: str
    markdown: str
    chunks: list[ParsedChunk]
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_json: list[Any] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "completed" if self.chunks else "empty"


@dataclass(frozen=True)
class PdfTextPage:
    page_number: int
    text: str
    text_chars: int


def chunk_markdown(text: str, max_chars: int = 2200, overlap: int = 220) -> list[str]:
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        window = normalized[start:end]
        split_at = max(
            window.rfind("\n## "),
            window.rfind("\n# "),
            window.rfind("\n\n"),
            window.rfind("\n"),
        )
        if split_at > max_chars * 0.45 and end < len(normalized):
            end = start + split_at + 1
        part = normalized[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def _as_chunks(
    markdown: str,
    *,
    page_number: int | None = None,
    sheet_name: str = "",
    block_type: str = "markdown",
) -> list[ParsedChunk]:
    return [
        ParsedChunk(
            text=part,
            page_number=page_number,
            sheet_name=sheet_name,
            block_type=block_type,
        )
        for part in chunk_markdown(markdown)
    ]


def parse_document(
    path: Path,
    *,
    engine: str,
    language: str,
    category: str = "other",
    progress_callback: ProgressCallback | None = None,
) -> ParseResult:
    suffix = path.suffix.lower()
    _emit_progress(progress_callback, stage="选择解析策略", strategy="")
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type for local enhanced parsing: {suffix}")
    if suffix in TEXT_EXTENSIONS:
        _emit_progress(progress_callback, stage="读取文本文件", progress=20)
        return _parse_text(path)
    if suffix in OFFICE_EXTENSIONS:
        _emit_progress(
            progress_callback,
            stage="Office/PPT 文档转 Markdown",
            progress=20,
            strategy="paddle_doc2md",
        )
        return _parse_office_with_paddle_doc2md(path)
    if engine != "paddle_structure":
        raise ValueError(f"Unsupported parser engine: {engine}")
    if suffix == ".pdf":
        if category in STRUCTURE_FIRST_CATEGORIES:
            return _parse_pdf_with_structure_first(
                path,
                language=language,
                progress_callback=progress_callback,
            )
        return _parse_pdf_with_text_or_structure(
            path,
            language=language,
            progress_callback=progress_callback,
        )
    if suffix in STRUCTURE_EXTENSIONS:
        return _parse_with_paddle_structure(
            path,
            language=language,
            progress_callback=progress_callback,
        )
    raise ValueError(f"No parser route for file type: {suffix}")


def _emit_progress(
    progress_callback: ProgressCallback | None,
    *,
    stage: str,
    progress: int | None = None,
    current_page: int | None = None,
    total_pages: int | None = None,
    strategy: str | None = None,
) -> None:
    if progress_callback is None:
        return
    payload: dict[str, Any] = {"stage": stage}
    if progress is not None:
        payload["progress"] = max(0, min(100, int(progress)))
    if current_page is not None:
        payload["current_page"] = int(current_page)
    if total_pages is not None:
        payload["total_pages"] = int(total_pages)
    if strategy is not None:
        payload["strategy"] = strategy
    progress_callback(payload)


def _parse_text(path: Path) -> ParseResult:
    markdown = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    chunks = _as_chunks(markdown, block_type="text")
    return ParseResult(
        engine="plain_markdown",
        markdown=markdown,
        chunks=chunks,
        metadata={"source_type": "text", "suffix": path.suffix.lower()},
        raw_json=[],
    )


def _parse_office_with_paddle_doc2md(path: Path) -> ParseResult:
    from paddleocr._doc2md.core import convert

    converted = convert(path)
    markdown = converted.markdown.strip()
    chunks = _as_chunks(markdown, block_type="office_markdown")
    return ParseResult(
        engine="paddle_doc2md",
        markdown=markdown,
        chunks=chunks,
        metadata={
            "source_type": "office",
            "suffix": path.suffix.lower(),
            "title": converted.title,
            "metadata": converted.metadata,
            "image_count": len(converted.images),
        },
        raw_json=[
            {
                "title": converted.title,
                "metadata": converted.metadata,
                "images": sorted(converted.images.keys()),
            }
        ],
    )


def _parse_pdf_with_text_or_structure(
    path: Path,
    *,
    language: str,
    progress_callback: ProgressCallback | None = None,
) -> ParseResult:
    _emit_progress(
        progress_callback,
        stage="招标/通用 PDF：先读取文字层，再补扫低文字页",
        progress=5,
        strategy="hybrid_pdf",
    )
    pages, page_count = _extract_pdf_text_pages(path)
    _emit_progress(
        progress_callback,
        stage="文字层读取完成",
        progress=20,
        current_page=page_count,
        total_pages=page_count,
        strategy="hybrid_pdf",
    )
    low_text_pages = [
        page.page_number for page in pages if page.text_chars < PDF_TEXT_LOW_PAGE_CHARS
    ]
    structure_pages = (
        _parse_low_text_pdf_pages_with_structure(
            path,
            page_numbers=low_text_pages,
            language=language,
            progress_callback=progress_callback,
            progress_start=25,
            progress_end=85,
        )
        if low_text_pages
        else {}
    )

    page_markdowns: list[str] = []
    chunks: list[ParsedChunk] = []
    raw_json: list[dict[str, Any]] = []
    structure_page_numbers: list[int] = []

    for page in pages:
        structure_page = structure_pages.get(page.page_number)
        if structure_page and structure_page.get("markdown"):
            markdown = str(structure_page["markdown"]).strip()
            parser_source = "paddle_structure_page"
            block_type = "pdf_ocr_page"
            structure_page_numbers.append(page.page_number)
        else:
            markdown = page.text.strip()
            parser_source = "pymupdf_text"
            block_type = "pdf_text"
        if markdown:
            page_markdowns.append(f"\n\n<!-- page:{page.page_number} source:{parser_source} -->\n\n{markdown}")
            chunks.extend(
                _as_chunks(
                    markdown,
                    page_number=page.page_number,
                    block_type=block_type,
                )
            )
        raw_json.append(
            {
                "page_number": page.page_number,
                "parser_source": parser_source,
                "text_chars": page.text_chars,
                "is_low_text": page.page_number in low_text_pages,
                "structure_raw": (structure_page or {}).get("raw", []),
            }
        )

    markdown = "\n".join(page_markdowns).strip()
    _emit_progress(
        progress_callback,
        stage="合并 Markdown/JSON 分块",
        progress=90,
        current_page=page_count,
        total_pages=page_count,
        strategy="hybrid_pdf" if structure_pages else "pymupdf_pdf_text",
    )
    return ParseResult(
        engine="hybrid_pdf" if structure_pages else "pymupdf_pdf_text",
        markdown=markdown,
        chunks=chunks,
        metadata={
            "source_type": "pdf_hybrid" if structure_pages else "pdf_text",
            "suffix": path.suffix.lower(),
            "page_count": page_count,
            "total_text_chars": sum(page.text_chars for page in pages),
            "low_text_pages": low_text_pages[:200],
            "low_text_page_count": len(low_text_pages),
            "structure_page_numbers": structure_page_numbers[:200],
            "structure_page_count": len(structure_page_numbers),
        },
        raw_json=raw_json,
    )


def _parse_pdf_with_structure_first(
    path: Path,
    *,
    language: str,
    progress_callback: ProgressCallback | None = None,
) -> ParseResult:
    _emit_progress(
        progress_callback,
        stage="标书/证据材料：逐页 PPStructureV3 精细解析",
        progress=5,
        strategy="paddle_structure_pages",
    )
    pages, page_count = _extract_pdf_text_pages(path)
    page_numbers = [page.page_number for page in pages]
    structure_pages = _parse_low_text_pdf_pages_with_structure(
        path,
        page_numbers=page_numbers,
        language=language,
        progress_callback=progress_callback,
        progress_start=10,
        progress_end=88,
    )

    page_markdowns: list[str] = []
    chunks: list[ParsedChunk] = []
    raw_json: list[dict[str, Any]] = []
    fallback_text_pages: list[int] = []

    for page in pages:
        structure_page = structure_pages.get(page.page_number, {})
        markdown = str(structure_page.get("markdown") or "").strip()
        parser_source = "paddle_structure_page"
        block_type = "pdf_ocr_page"
        if not markdown and page.text.strip():
            markdown = page.text.strip()
            parser_source = "pymupdf_text_fallback"
            block_type = "pdf_text_fallback"
            fallback_text_pages.append(page.page_number)
        if markdown:
            page_markdowns.append(
                f"\n\n<!-- page:{page.page_number} source:{parser_source} -->\n\n{markdown}"
            )
            chunks.extend(
                _as_chunks(
                    markdown,
                    page_number=page.page_number,
                    block_type=block_type,
                )
            )
        raw_json.append(
            {
                "page_number": page.page_number,
                "parser_source": parser_source,
                "text_chars": page.text_chars,
                "structure_raw": structure_page.get("raw", []),
            }
        )

    markdown = "\n".join(page_markdowns).strip()
    _emit_progress(
        progress_callback,
        stage="合并精细解析结果",
        progress=90,
        current_page=page_count,
        total_pages=page_count,
        strategy="paddle_structure_pages",
    )
    return ParseResult(
        engine="paddle_structure_pages",
        markdown=markdown,
        chunks=chunks,
        metadata={
            "source_type": "pdf_structure_first",
            "suffix": path.suffix.lower(),
            "page_count": page_count,
            "total_text_chars": sum(page.text_chars for page in pages),
            "structure_page_numbers": page_numbers[:200],
            "structure_page_count": len(page_numbers),
            "fallback_text_pages": fallback_text_pages[:200],
            "fallback_text_page_count": len(fallback_text_pages),
        },
        raw_json=raw_json,
    )


def _parse_pdf_text(path: Path) -> ParseResult:
    pages, page_count = _extract_pdf_text_pages(path)
    page_markdowns = []
    chunks: list[ParsedChunk] = []
    low_text_pages = []
    for page in pages:
        if page.text_chars < PDF_TEXT_LOW_PAGE_CHARS:
            low_text_pages.append(page.page_number)
        if page.text:
            page_markdowns.append(f"\n\n<!-- page:{page.page_number} -->\n\n{page.text}")
            chunks.extend(_as_chunks(page.text, page_number=page.page_number, block_type="pdf_text"))

    markdown = "\n".join(page_markdowns).strip()
    return ParseResult(
        engine="pymupdf_pdf_text",
        markdown=markdown,
        chunks=chunks,
        metadata={
            "source_type": "pdf_text",
            "suffix": path.suffix.lower(),
            "page_count": page_count,
            "total_text_chars": sum(page.text_chars for page in pages),
            "low_text_pages": low_text_pages[:200],
            "low_text_page_count": len(low_text_pages),
        },
        raw_json=[
            {
                "page_number": page.page_number,
                "text_chars": page.text_chars,
                "is_low_text": page.text_chars < PDF_TEXT_LOW_PAGE_CHARS,
            }
            for page in pages
        ],
    )


def _extract_pdf_text_pages(path: Path) -> tuple[list[PdfTextPage], int]:
    import fitz

    pages: list[PdfTextPage] = []
    with fitz.open(path) as doc:
        for page_index in range(doc.page_count):
            page_number = page_index + 1
            page = doc.load_page(page_index)
            text = page.get_text("text", sort=True).strip()
            pages.append(
                PdfTextPage(
                    page_number=page_number,
                    text=text,
                    text_chars=len(text),
                )
            )
        return pages, doc.page_count


def _parse_low_text_pdf_pages_with_structure(
    path: Path,
    *,
    page_numbers: list[int],
    language: str,
    progress_callback: ProgressCallback | None = None,
    progress_start: int = 20,
    progress_end: int = 85,
) -> dict[int, dict[str, Any]]:
    if not page_numbers:
        return {}
    import fitz

    _emit_progress(
        progress_callback,
        stage="加载 PPStructureV3 模型",
        progress=progress_start,
        current_page=0,
        total_pages=len(page_numbers),
        strategy="paddle_structure_pages",
    )
    parser = _get_paddle_structure_parser(language)
    parsed_pages: dict[int, dict[str, Any]] = {}
    with fitz.open(path) as doc, TemporaryDirectory(prefix="bid_pdf_pages_") as temp_dir:
        temp_path = Path(temp_dir)
        total = len(page_numbers)
        span = max(1, progress_end - progress_start)
        for index, page_number in enumerate(page_numbers, start=1):
            _emit_progress(
                progress_callback,
                stage=f"PPStructureV3 正在解析第 {page_number} 页",
                progress=progress_start + int((index - 1) * span / total),
                current_page=index,
                total_pages=total,
                strategy="paddle_structure_pages",
            )
            page = doc.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image_path = temp_path / f"page-{page_number:04d}.png"
            pixmap.save(image_path)
            results = list(parser.predict(str(image_path), format_block_content=True))
            markdown_parts = [
                markdown
                for result in results
                if (markdown := _extract_markdown(result).strip())
            ]
            parsed_pages[page_number] = {
                "markdown": "\n\n".join(markdown_parts).strip(),
                "raw": [_json_safe(_extract_json(result)) for result in results],
            }
        _emit_progress(
            progress_callback,
            stage="PPStructureV3 页解析完成",
            progress=progress_end,
            current_page=total,
            total_pages=total,
            strategy="paddle_structure_pages",
        )
    return parsed_pages


def _parse_with_paddle_structure(
    path: Path,
    *,
    language: str,
    progress_callback: ProgressCallback | None = None,
) -> ParseResult:
    _emit_progress(
        progress_callback,
        stage="加载 PPStructureV3 模型",
        progress=20,
        strategy="paddle_structure",
    )
    parser = _get_paddle_structure_parser(language)
    results = list(parser.predict(str(path), format_block_content=True))
    page_markdowns: list[str] = []
    raw_json: list[Any] = []
    chunks: list[ParsedChunk] = []
    for index, result in enumerate(results, start=1):
        markdown = _extract_markdown(result).strip()
        if markdown:
            page_markdowns.append(f"\n\n<!-- page:{index} -->\n\n{markdown}")
            chunks.extend(_as_chunks(markdown, page_number=index, block_type="page_markdown"))
        raw_json.append(_json_safe(_extract_json(result)))

    markdown = "\n".join(page_markdowns).strip()
    _emit_progress(
        progress_callback,
        stage="结构化解析完成",
        progress=90,
        total_pages=len(results),
        strategy="paddle_structure",
    )
    return ParseResult(
        engine="paddle_structure",
        markdown=markdown,
        chunks=chunks,
        metadata={
            "source_type": "layout",
            "suffix": path.suffix.lower(),
            "page_count": len(results),
            "language": language,
        },
        raw_json=raw_json,
    )


def _get_paddle_structure_parser(language: str):
    parser = _STRUCTURE_PARSERS.get(language)
    if parser is not None:
        return parser
    from paddleocr import PPStructureV3

    parser = PPStructureV3(
        lang=language,
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
        use_textline_orientation=True,
        use_table_recognition=True,
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_seal_recognition=False,
    )
    _STRUCTURE_PARSERS[language] = parser
    return parser


def _extract_markdown(result: Any) -> str:
    if hasattr(result, "markdown"):
        value = getattr(result, "markdown")
        return str(value() if callable(value) else value)
    if isinstance(result, dict):
        layout = result.get("layout_parsing_result")
        if layout is not None:
            return _extract_markdown(layout)
        markdown = result.get("markdown")
        if markdown is not None:
            return str(markdown)
        for value in result.values():
            nested = _extract_markdown(value)
            if nested:
                return nested
    if isinstance(result, (list, tuple)):
        return "\n\n".join(part for item in result if (part := _extract_markdown(item)))
    return ""


def _extract_json(result: Any) -> Any:
    if isinstance(result, dict):
        return result
    json_value = getattr(result, "json", None)
    if json_value is not None:
        return json_value() if callable(json_value) else json_value
    to_dict = getattr(result, "to_dict", None)
    if to_dict is not None:
        return to_dict()
    return {"repr": repr(result)}


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    return value


def parse_result_to_json(
    *,
    source_filename: str,
    document_id: int,
    result: ParseResult,
) -> dict[str, Any]:
    return {
        "version": 1,
        "document_id": document_id,
        "source_filename": source_filename,
        "engine": result.engine,
        "status": result.status,
        "metadata": result.metadata,
        "markdown_chars": len(result.markdown),
        "chunks": [
            {
                "index": index,
                "page_number": chunk.page_number,
                "sheet_name": chunk.sheet_name,
                "block_type": chunk.block_type,
                "text": chunk.text,
            }
            for index, chunk in enumerate(result.chunks)
        ],
        "raw": result.raw_json,
    }


def chunks_to_dicts(chunks: list[ParsedChunk]) -> list[dict[str, object]]:
    return [
        {
            "text": chunk.text,
            "page_number": chunk.page_number,
            "sheet_name": chunk.sheet_name,
            "block_type": chunk.block_type,
        }
        for chunk in chunks
        if chunk.text.strip()
    ]
