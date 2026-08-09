from __future__ import annotations

from pathlib import Path
import platform

from qa_platform.extraction.models import (
    DocumentExtractionConfig,
    DocumentExtractionResult,
)
from qa_platform.extraction.pdf_engine import extract_pdf_content_with_pages
from qa_platform.extraction.windows_hwp_com_engine import (
    extract_hwp_content_with_pages,
)


def extract_document_content_with_pages(
    config: DocumentExtractionConfig,
    output_img_dir: Path,
) -> DocumentExtractionResult:
    engine = config.extractor_engine
    if engine == "auto":
        engine = "windows_com" if platform.system() == "Windows" else "pdf"

    if engine == "pdf":
        return extract_pdf_content_with_pages(config, output_img_dir)

    if engine == "windows_com":
        if config.input_hwp is None:
            raise FileNotFoundError(
                "Windows HWP COM extraction requires paths.input_hwp."
            )
        return extract_hwp_content_with_pages(
            config.input_hwp,
            output_img_dir,
            security_module_name=config.security_module_name,
        )

    raise ValueError(f"Unsupported extractor_engine: {engine}")
