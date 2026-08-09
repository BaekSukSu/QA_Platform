import os
from pathlib import Path

import pytest

from qa_platform.extraction.models import (
    DocumentExtractionConfig,
    DocumentExtractionPipelineResult,
)
from qa_platform.pipeline.config import QaPipelineConfig
from qa_platform.pipeline.orchestrator import QaPipelineOrchestrator
from qa_platform.shared.json_io import read_json


RUN_DOCKER_TESTS = os.environ.get("QA_PLATFORM_RUN_DOCKER_TESTS") == "1"

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not RUN_DOCKER_TESTS,
        reason="Set QA_PLATFORM_RUN_DOCKER_TESTS=1 to run Docker QA pipeline tests.",
    ),
]


def fake_extraction_result(tmp_path: Path) -> DocumentExtractionPipelineResult:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_001.txt").write_text(
        "[META]\n"
        "page=1\n"
        "input_source=generated_sample\n"
        "output_source=generated_sample\n"
        "\n"
        "[PACKAGES]\n"
        "\n"
        "[CODE]\n"
        "name = input()\n"
        "print(f'hello {name}')\n"
        "\n"
        "[INPUT]\n"
        "Ada\n"
        "\n"
        "[OUTPUT]\n"
        "hello Ada\n",
        encoding="utf-8",
    )
    return DocumentExtractionPipelineResult(
        source_output_dir=tmp_path / "extract_work",
        imported_output_dir=blocks_dir,
        block_files=[blocks_dir / "block_001.txt"],
        extracted_text_path=tmp_path / "extract_work" / "extracted_text.txt",
        temp_image_dir=tmp_path / "extract_work" / "temp_images",
        stats={"image_blocks": 0, "text_blocks": 1, "imported_blocks": 1},
    )


def make_extractor_config(tmp_path: Path) -> DocumentExtractionConfig:
    input_pdf = tmp_path / "chapter02.pdf"
    input_pdf.write_bytes(b"%PDF")
    return DocumentExtractionConfig(
        input_pdf=input_pdf,
        chapter_number=2,
        book_id="python_junior",
        gemini_api_key="key",
    )


def test_qa_pipeline_orchestrator_runs_docker_chapter(tmp_path) -> None:
    extraction = fake_extraction_result(tmp_path)
    config = QaPipelineConfig(
        extractor=make_extractor_config(tmp_path),
        execution_backend="docker",
        run_root=tmp_path / "run",
    )
    orchestrator = QaPipelineOrchestrator(extract=lambda extractor_config: extraction)

    result = orchestrator.run(config)

    assert result.chapter.total_blocks == 1
    assert result.chapter.passed_blocks == 1
    assert result.chapter.failed_blocks == 0
    summary = read_json(result.summary_path)
    assert summary["execution_backend"] == "docker"
    assert summary["chapter_run"]["passed_blocks"] == 1
