from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DocumentExtractionConfig:
    chapter_number: int
    book_id: str
    gemini_api_key: str
    input_hwp: Path | None = None
    input_pdf: Path | None = None
    extractor_engine: str = "auto"
    tesseract_cmd: str = ""
    keep_temp_images: bool = False
    session_id: str | None = None
    resource_root: Path | None = None
    output_root: Path = Path("extracted_blocks")
    work_root: Path = Path("run/document_extraction")
    security_module_name: str = "SecurityModule"


@dataclass(frozen=True)
class DocumentExtractionResult:
    text_data: str
    image_paths: list[Path]


@dataclass(frozen=True)
class DocumentExtractionPipelineResult:
    source_output_dir: Path
    imported_output_dir: Path
    block_files: list[Path]
    extracted_text_path: Path
    temp_image_dir: Path
    session_id: str = ""
    stats: dict[str, int] = field(default_factory=dict)
