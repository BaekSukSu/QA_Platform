from pathlib import Path

import pytest

from qa_platform.extraction.config import (
    DocumentExtractionConfig,
    load_document_extraction_config,
)


def test_load_document_extraction_config_maps_pdf_input_dict(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_document_extraction_config(
        {
            "project": {
                "extractor_engine": "pdf",
                "chapter_number": 2,
                "book_id": "python_junior",
                "keep_temp_images": True,
            },
            "paths": {
                "input_pdf": str(input_pdf),
                "tesseract_cmd": "",
            },
            "api": {},
        }
    )

    assert isinstance(config, DocumentExtractionConfig)
    assert config.extractor_engine == "pdf"
    assert config.chapter_number == 2
    assert config.book_id == "python_junior"
    assert config.input_hwp is None
    assert config.input_pdf == input_pdf
    assert config.keep_temp_images is True
    assert config.gemini_api_key == "env-key"


def test_load_document_extraction_config_defaults_output_root_to_extracted_blocks(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_document_extraction_config(
        {
            "project": {
                "extractor_engine": "pdf",
                "chapter_number": 2,
                "book_id": "python_junior",
            },
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "sample.pdf",
            },
            "api": {},
        }
    )

    assert config.output_root == workspace_root / "extracted_blocks"


def test_load_document_extraction_config_stores_configured_resource_root(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    resource_root = tmp_path / "resources"
    workspace_root.mkdir()
    resource_root.mkdir()

    config = load_document_extraction_config(
        {
            "project": {"chapter_number": 2},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "sample.pdf",
                "resource_root": str(resource_root),
            },
        }
    )

    assert config.resource_root == resource_root.resolve()


def test_load_document_extraction_config_keeps_blank_resource_root_none(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    config = load_document_extraction_config(
        {
            "project": {"chapter_number": 2},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "sample.pdf",
                "resource_root": "",
            },
        }
    )

    assert config.resource_root is None


def test_load_document_extraction_config_keeps_missing_resource_root_none(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    config = load_document_extraction_config(
        {
            "project": {"chapter_number": 2},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "sample.pdf",
            },
        }
    )

    assert config.resource_root is None


def test_load_document_extraction_config_resolves_paths_from_workspace_root(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    input_hwp = workspace_root / "textbook" / "chapter02.hwp"
    input_hwp.parent.mkdir()
    input_hwp.write_bytes(b"hwp")

    config = load_document_extraction_config(
        {
            "project": {
                "chapter_number": 2,
                "book_id": "python_junior",
            },
            "paths": {
                "workspace_root": str(workspace_root),
                "input_hwp": "textbook/chapter02.hwp",
                "input_pdf": "debug/chapter02.pdf",
                "output_root": "extracted_blocks",
                "work_root": "run/document_extraction",
            },
            "api": {},
        }
    )

    assert config.input_hwp == workspace_root / "textbook" / "chapter02.hwp"
    assert config.input_pdf == workspace_root / "debug" / "chapter02.pdf"
    assert config.output_root == workspace_root / "extracted_blocks"
    assert config.work_root == workspace_root / "run" / "document_extraction"


def test_load_document_extraction_config_rejects_missing_api_key(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        load_document_extraction_config(
            {
                "project": {"chapter_number": 2},
                "paths": {
                    "workspace_root": str(workspace_root),
                    "input_pdf": "sample.pdf",
                },
                "api": {},
            }
        )


def test_load_document_extraction_config_ignores_config_api_key(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        load_document_extraction_config(
            {
                "project": {"chapter_number": 2},
                "paths": {
                    "workspace_root": str(workspace_root),
                    "input_pdf": "sample.pdf",
                },
                "api": {"gemini_api_key": "config-key"},
            }
        )


def test_load_document_extraction_config_reads_gemini_key_from_dotenv(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / ".env").write_text(
        "# local secrets\n"
        "GEMINI_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_document_extraction_config(
        {
            "project": {"chapter_number": 2, "extractor_engine": "pdf"},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "sample.pdf",
            },
            "api": {},
        }
    )

    assert config.gemini_api_key == "dotenv-key"


def test_load_document_extraction_config_reads_default_workspace_dotenv(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / ".env").write_text(
        "GEMINI_API_KEY=from-workspace\n",
        encoding="utf-8",
    )

    config = load_document_extraction_config(
        {
            "project": {"book_id": "book", "chapter_number": 1},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "input/book.pdf",
            },
        }
    )

    assert config.gemini_api_key == "from-workspace"


def test_load_document_extraction_config_reads_configured_env_file(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "secrets.env").write_text(
        "GEMINI_API_KEY=from-configured\n",
        encoding="utf-8",
    )

    config = load_document_extraction_config(
        {
            "project": {"book_id": "book", "chapter_number": 1},
            "paths": {
                "workspace_root": str(workspace_root),
                "env_file": "secrets.env",
                "input_pdf": "input/book.pdf",
            },
        }
    )

    assert config.gemini_api_key == "from-configured"


def test_load_document_extraction_config_prefers_dotenv_over_config_api_key(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / ".env").write_text(
        "GEMINI_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_document_extraction_config(
        {
            "project": {"chapter_number": 2, "extractor_engine": "pdf"},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "sample.pdf",
            },
            "api": {"gemini_api_key": "config-key"},
        }
    )

    assert config.gemini_api_key == "dotenv-key"


def test_load_document_extraction_config_keeps_existing_env_over_dotenv(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "shell-key")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / ".env").write_text(
        "GEMINI_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_document_extraction_config(
        {
            "project": {"chapter_number": 2, "extractor_engine": "pdf"},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "sample.pdf",
            },
            "api": {},
        }
    )

    assert config.gemini_api_key == "shell-key"


def test_load_document_extraction_config_replaces_empty_env_from_dotenv(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / ".env").write_text(
        "GEMINI_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_document_extraction_config(
        {
            "project": {"chapter_number": 2, "extractor_engine": "pdf"},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "sample.pdf",
            },
        }
    )

    assert config.gemini_api_key == "dotenv-key"
