import platform

import pytest

from qa_platform.extraction.models import (
    DocumentExtractionConfig,
    DocumentExtractionResult,
)


def make_hwp_config(tmp_path, engine: str) -> DocumentExtractionConfig:
    input_hwp = tmp_path / "sample.hwp"
    input_hwp.write_bytes(b"hwp")
    return DocumentExtractionConfig(
        input_hwp=input_hwp,
        extractor_engine=engine,
        chapter_number=2,
        book_id="book",
        gemini_api_key="key",
    )


def make_pdf_config(tmp_path, engine: str) -> DocumentExtractionConfig:
    input_pdf = tmp_path / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")
    return DocumentExtractionConfig(
        input_pdf=input_pdf,
        extractor_engine=engine,
        chapter_number=2,
        book_id="book",
        gemini_api_key="key",
    )


def test_document_engine_selects_pdf(monkeypatch, tmp_path) -> None:
    from qa_platform.extraction import document_engine

    calls = []

    def fake_pdf(config, output_img_dir):
        calls.append((config, output_img_dir))
        return DocumentExtractionResult("text", [])

    monkeypatch.setattr(document_engine, "extract_pdf_content_with_pages", fake_pdf)

    result = document_engine.extract_document_content_with_pages(
        make_pdf_config(tmp_path, "pdf"),
        tmp_path / "images",
    )

    assert result.text_data == "text"
    assert calls[0][1] == tmp_path / "images"


def test_document_engine_auto_selects_windows_on_windows(monkeypatch, tmp_path) -> None:
    from qa_platform.extraction import document_engine

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        document_engine,
        "extract_hwp_content_with_pages",
        lambda hwp_path, output_img_dir, security_module_name="SecurityModule": (
            DocumentExtractionResult("windows", [])
        ),
    )

    result = document_engine.extract_document_content_with_pages(
        make_hwp_config(tmp_path, "auto"),
        tmp_path / "images",
    )

    assert result.text_data == "windows"


def test_document_engine_windows_com_requires_input_hwp(tmp_path) -> None:
    from qa_platform.extraction.document_engine import (
        extract_document_content_with_pages,
    )

    config = DocumentExtractionConfig(
        input_pdf=tmp_path / "sample.pdf",
        extractor_engine="windows_com",
        chapter_number=2,
        book_id="book",
        gemini_api_key="key",
    )

    with pytest.raises(FileNotFoundError, match="paths.input_hwp"):
        extract_document_content_with_pages(config, tmp_path / "images")


def test_document_engine_auto_selects_pdf_on_macos(monkeypatch, tmp_path) -> None:
    from qa_platform.extraction import document_engine

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        document_engine,
        "extract_pdf_content_with_pages",
        lambda config, output_img_dir: DocumentExtractionResult("mac-pdf", []),
    )

    result = document_engine.extract_document_content_with_pages(
        make_pdf_config(tmp_path, "auto"),
        tmp_path / "images",
    )

    assert result.text_data == "mac-pdf"


def test_document_engine_rejects_unknown_engine(tmp_path) -> None:
    from qa_platform.extraction.document_engine import (
        extract_document_content_with_pages,
    )

    with pytest.raises(ValueError, match="Unsupported extractor_engine"):
        extract_document_content_with_pages(
            make_hwp_config(tmp_path, "unknown"),
            tmp_path / "images",
        )
