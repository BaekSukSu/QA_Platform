from pathlib import Path

from qa_platform.extraction.models import (
    DocumentExtractionConfig,
    DocumentExtractionResult,
)


def test_pipeline_writes_text_extracts_blocks_and_imports(monkeypatch, tmp_path) -> None:
    from qa_platform.extraction import pipeline

    input_pdf = tmp_path / "sample.pdf"
    resource_root = tmp_path / "resources"
    input_pdf.write_bytes(b"%PDF")
    config = DocumentExtractionConfig(
        input_pdf=input_pdf,
        chapter_number=2,
        book_id="book",
        gemini_api_key="key",
        work_root=tmp_path / "work",
        output_root=tmp_path / "extracted_blocks",
        keep_temp_images=True,
        session_id="260702_143015",
        resource_root=resource_root,
    )
    captured_resource_root = None

    def fake_resolve_tesseract_runtime(configured_path, resource_root=None):
        nonlocal captured_resource_root
        captured_resource_root = resource_root
        return Path("/usr/bin/tesseract")

    monkeypatch.setattr(
        pipeline,
        "extract_document_content_with_pages",
        lambda config, output_img_dir: DocumentExtractionResult(
            text_data="[page : 1]\nprint('hello')\n",
            image_paths=[],
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "resolve_tesseract_runtime",
        fake_resolve_tesseract_runtime,
    )
    monkeypatch.setattr(
        pipeline,
        "filter_images_locally",
        lambda image_paths, tesseract_path, keep_temp=False: [],
    )
    monkeypatch.setattr(
        pipeline,
        "extract_image_blocks_to_files",
        lambda image_paths, output_dir, start_idx, client, keep_temp=False: 0,
    )
    monkeypatch.setattr(
        pipeline,
        "extract_text_blocks_to_files",
        lambda text_path, output_dir, start_idx, client: (
            (output_dir / "block_1.txt").write_text(
                "[META]\npage : 1\ninput_source : empty\noutput_source : textbook\n\n"
                "[PACKAGES]\nNONE\n\n"
                "[CODE]\nprint('hello')\n\n"
                "[INPUT]\nNONE\n\n"
                "[OUTPUT]\nhello",
                encoding="utf-8",
            )
            or 1
        ),
    )
    monkeypatch.setattr(pipeline, "build_gemini_client", lambda api_key: object())

    result = pipeline.run_document_extraction_pipeline(config)

    assert result.session_id == "260702_143015"
    assert result.extracted_text_path.exists()
    assert result.source_output_dir == tmp_path / "work" / "chap2_260702_143015"
    assert result.imported_output_dir == (
        tmp_path / "extracted_blocks" / "book_ch2_260702_143015"
    )
    assert [path.name for path in result.block_files] == ["block_001.txt"]
    assert captured_resource_root == resource_root
