from pathlib import Path

from qa_platform.extraction.models import DocumentExtractionConfig
from qa_platform.extraction.pdf_engine import extract_pdf_content_with_pages


def test_extract_pdf_content_returns_page_text_and_images(monkeypatch, tmp_path) -> None:
    from qa_platform.extraction import pdf_engine

    class FakeImage:
        def convert(self, mode):
            assert mode == "RGB"
            return self

        def save(self, path, image_format):
            assert image_format == "BMP"
            Path(path).write_bytes(b"bmp")

    class FakeImageModule:
        @staticmethod
        def open(image_bytes):
            assert image_bytes.read() == b"raw"
            return FakeImage()

    class FakePage:
        def __init__(self, text):
            self.text = text

        def get_text(self, mode):
            assert mode == "text"
            return self.text

        def get_images(self, full=True):
            assert full is True
            return [(7,)]

    class FakeDocument:
        def __iter__(self):
            return iter([FakePage("one"), FakePage("two")])

        def extract_image(self, xref):
            assert xref == 7
            return {"image": b"raw"}

        def close(self):
            pass

    monkeypatch.setattr(pdf_engine.fitz, "open", lambda path: FakeDocument())
    monkeypatch.setattr(pdf_engine, "Image", FakeImageModule)

    input_pdf = tmp_path / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")
    config = DocumentExtractionConfig(
        input_pdf=input_pdf,
        chapter_number=2,
        book_id="book",
        gemini_api_key="key",
    )

    result = extract_pdf_content_with_pages(config, tmp_path / "images")

    assert result.text_data == "[page : 1]\none\n\n[page : 2]\ntwo\n"
    assert [path.name for path in result.image_paths] == [
        "1_1.bmp",
        "2_2.bmp",
    ]


def test_extract_pdf_content_requires_input_pdf(tmp_path) -> None:
    config = DocumentExtractionConfig(
        chapter_number=2,
        book_id="book",
        gemini_api_key="key",
    )

    try:
        extract_pdf_content_with_pages(config, tmp_path / "images")
    except FileNotFoundError as exc:
        assert "paths.input_pdf" in str(exc)
    else:
        raise AssertionError("PDF extraction should require paths.input_pdf")


def test_extract_pdf_content_rejects_missing_input_pdf_file(tmp_path) -> None:
    missing_pdf = tmp_path / "missing.pdf"
    image_dir = tmp_path / "images"
    config = DocumentExtractionConfig(
        input_pdf=missing_pdf,
        chapter_number=2,
        book_id="book",
        gemini_api_key="key",
    )

    try:
        extract_pdf_content_with_pages(config, image_dir)
    except FileNotFoundError as exc:
        assert str(missing_pdf) in str(exc)
        assert not image_dir.exists()
    else:
        raise AssertionError("PDF extraction should reject a missing PDF file")
