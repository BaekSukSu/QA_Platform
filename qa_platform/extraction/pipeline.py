from __future__ import annotations

from google import genai

from qa_platform.extraction.block_importer import (
    import_extracted_chapter_blocks,
)
from qa_platform.extraction.document_engine import (
    extract_document_content_with_pages,
)
from qa_platform.extraction.image_block_extractor import (
    extract_image_blocks_to_files,
)
from qa_platform.extraction.models import (
    DocumentExtractionConfig,
    DocumentExtractionPipelineResult,
)
from qa_platform.extraction.block_postprocessor import (
    postprocess_extracted_blocks,
)
from qa_platform.extraction.tesseract_filter import (
    filter_images_locally,
    resolve_tesseract_runtime,
)
from qa_platform.extraction.text_block_extractor import (
    extract_text_blocks_to_files,
)
from qa_platform.shared.session import build_session_id


def build_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)


def run_document_extraction_pipeline(
    config: DocumentExtractionConfig,
) -> DocumentExtractionPipelineResult:
    session_id = config.session_id or build_session_id()
    source_output_dir = config.work_root / f"chap{config.chapter_number}_{session_id}"
    temp_image_dir = source_output_dir / "temp_images"
    source_output_dir.mkdir(parents=True, exist_ok=True)
    temp_image_dir.mkdir(parents=True, exist_ok=True)

    document_result = extract_document_content_with_pages(config, temp_image_dir)
    extracted_text_path = source_output_dir / "extracted_text.txt"
    extracted_text_path.write_text(document_result.text_data, encoding="utf-8")

    tesseract_runtime = resolve_tesseract_runtime(
        config.tesseract_cmd,
        resource_root=config.resource_root,
    )
    filtered_image_paths = filter_images_locally(
        document_result.image_paths,
        tesseract_runtime,
        keep_temp=config.keep_temp_images,
    )

    client = build_gemini_client(config.gemini_api_key)
    image_block_count = extract_image_blocks_to_files(
        filtered_image_paths,
        source_output_dir,
        start_idx=1,
        client=client,
        keep_temp=config.keep_temp_images,
    )
    text_block_count = extract_text_blocks_to_files(
        extracted_text_path,
        source_output_dir,
        start_idx=image_block_count + 1,
        client=client,
    )

    postprocess_extracted_blocks(source_output_dir, client=client)

    imported = import_extracted_chapter_blocks(
        source_output_dir,
        output_root=config.output_root,
        book_id=config.book_id,
        chapter_number=config.chapter_number,
        session_id=session_id,
    )
    return DocumentExtractionPipelineResult(
        source_output_dir=source_output_dir,
        imported_output_dir=imported.output_dir,
        block_files=imported.block_files,
        extracted_text_path=extracted_text_path,
        temp_image_dir=temp_image_dir,
        session_id=session_id,
        stats={
            "image_blocks": image_block_count,
            "text_blocks": text_block_count,
            "imported_blocks": len(imported.block_files),
        },
    )
