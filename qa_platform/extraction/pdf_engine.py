from __future__ import annotations

from io import BytesIO
from pathlib import Path

from qa_platform.extraction.models import (
    DocumentExtractionConfig,
    DocumentExtractionResult,
)

try:
    from PIL import Image
except ImportError:

    class _MissingImage:
        def open(self, image_bytes):
            raise RuntimeError("Pillow is required. Install it with: pip install pillow")

    Image = _MissingImage()


class _FitzProxy:
    def open(self, path):
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError(
                "PyMuPDF is required. Install it with: pip install pymupdf"
            ) from exc
        return fitz.open(path)


fitz = _FitzProxy()


def extract_pdf_text_with_pages(pdf_path: Path) -> str:
    document = fitz.open(str(pdf_path))
    try:
        chunks = []
        for page_index, page in enumerate(document, start=1):
            page_text = page.get_text("text").strip()
            chunks.append(f"[page : {page_index}]\n{page_text}\n")
        return "\n".join(chunks)
    finally:
        document.close()


def extract_pdf_images_with_pages(pdf_path: Path, output_img_dir: Path) -> list[Path]:
    output_img_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(str(pdf_path))
    image_paths: list[Path] = []
    global_image_index = 1
    try:
        for page_number, page in enumerate(document, start=1):
            for image_info in page.get_images(full=True):
                xref = image_info[0]
                image_data = document.extract_image(xref)
                image_path = output_img_dir / f"{global_image_index}_{page_number}.bmp"
                image = Image.open(BytesIO(image_data["image"]))
                image.convert("RGB").save(image_path, "BMP")
                image_paths.append(image_path)
                global_image_index += 1
    finally:
        document.close()
    return image_paths


def resolve_input_pdf(config: DocumentExtractionConfig) -> Path:
    if config.input_pdf is None:
        raise FileNotFoundError(
            "PDF extraction requires paths.input_pdf. "
            "On macOS, provide a pre-converted PDF file instead of HWP."
        )
    if not config.input_pdf.exists():
        raise FileNotFoundError(f"PDF input does not exist: {config.input_pdf}")
    return config.input_pdf


def extract_pdf_content_with_pages(
    config: DocumentExtractionConfig,
    output_img_dir: Path,
) -> DocumentExtractionResult:
    pdf_path = resolve_input_pdf(config)
    output_img_dir.mkdir(parents=True, exist_ok=True)
    return DocumentExtractionResult(
        text_data=extract_pdf_text_with_pages(pdf_path),
        image_paths=extract_pdf_images_with_pages(pdf_path, output_img_dir),
    )
