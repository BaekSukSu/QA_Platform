from dataclasses import replace
from pathlib import Path

from qa_platform.chapter.models import ChapterRunResult
from qa_platform.execution.docker import DockerBlockExecutor
from qa_platform.execution.docker_runtime import DockerExecutorConfig
from qa_platform.extraction.models import (
    DocumentExtractionConfig,
    DocumentExtractionPipelineResult,
)
from qa_platform.pipeline.config import QaPipelineConfig
from qa_platform.pipeline.orchestrator import (
    QaPipelineOrchestrator,
    build_qa_pipeline_executor,
)
from qa_platform.shared.json_io import read_json


def make_extraction_result(
    tmp_path: Path,
    session_id: str,
) -> DocumentExtractionPipelineResult:
    blocks_dir = tmp_path / "extracted_blocks" / f"python_junior_ch2_{session_id}"
    blocks_dir.mkdir(parents=True)
    (blocks_dir / "block_001.txt").write_text(
        "[META]\n"
        "page=1\n"
        "input_source=generated_sample\n"
        "output_source=generated_sample\n"
        "\n"
        "[PACKAGES]\n"
        "\n"
        "[CODE]\n"
        "print('hello')\n"
        "\n"
        "[INPUT]\n"
        "\n"
        "[OUTPUT]\n"
        "hello\n",
        encoding="utf-8",
    )
    return DocumentExtractionPipelineResult(
        source_output_dir=tmp_path / "extract_work" / f"chap2_{session_id}",
        imported_output_dir=blocks_dir,
        block_files=[blocks_dir / "block_001.txt"],
        extracted_text_path=(
            tmp_path / "extract_work" / f"chap2_{session_id}" / "extracted_text.txt"
        ),
        temp_image_dir=(
            tmp_path / "extract_work" / f"chap2_{session_id}" / "temp_images"
        ),
        session_id=session_id,
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


def test_build_qa_pipeline_executor_always_selects_docker(tmp_path) -> None:
    config = QaPipelineConfig(
        extractor=make_extractor_config(tmp_path),
        execution_backend="docker",
        run_root=tmp_path / "run",
    )

    executor = build_qa_pipeline_executor(config)

    assert executor.__class__.__name__ == "DockerBlockExecutor"


def test_orchestrator_extracts_then_runs_chapter_with_injected_runner(
    tmp_path,
) -> None:
    session_id = "260702_143015"
    extractor_config = make_extractor_config(tmp_path)
    extraction_result = make_extraction_result(tmp_path, session_id)
    calls = []

    def fake_extract(extractor_config):
        calls.append(("extract", extractor_config))
        return extraction_result

    class RecordingRunner:
        def run(self, blocks_dir, run_root, session_id=None):
            calls.append(("run", blocks_dir, run_root, session_id))
            run_dir = run_root / session_id
            run_dir.mkdir(parents=True)
            return ChapterRunResult(
                run_id=session_id,
                run_dir=run_dir,
                total_blocks=1,
                passed_blocks=1,
                failed_blocks=0,
                skipped_blocks=0,
                report_json_path=run_dir / "chapter_error_report.json",
                report_markdown_path=run_dir / "chapter_error_report.md",
            )

    config = QaPipelineConfig(
        extractor=extractor_config,
        run_root=tmp_path / "qa_pipeline_runs",
    )
    orchestrator = QaPipelineOrchestrator(
        extract=fake_extract,
        runner_factory=lambda config: RecordingRunner(),
        session_id_factory=lambda: session_id,
    )

    result = orchestrator.run(config)

    assert calls[0][0] == "extract"
    assert calls[0][1].session_id == session_id
    assert calls[1] == (
        "run",
        extraction_result.imported_output_dir,
        tmp_path / "qa_pipeline_runs",
        session_id,
    )
    assert isinstance(result.chapter, ChapterRunResult)
    assert result.chapter.run_id == session_id
    assert result.chapter.run_dir == tmp_path / "qa_pipeline_runs" / session_id

    summary = read_json(result.summary_path)
    assert summary["schema_version"] == 1
    assert summary["pipeline"] == "qa_pipeline"
    assert summary["execution_backend"] == "docker"
    assert summary["extractor"]["session_id"] == session_id
    assert summary["extractor"]["imported_output_dir"] == str(
        extraction_result.imported_output_dir
    )
    assert summary["extractor"]["source_output_dir"] == str(
        extraction_result.source_output_dir
    )
    assert summary["extractor"]["block_files"] == [
        str(path) for path in extraction_result.block_files
    ]
    assert summary["extractor"]["extracted_text_path"] == str(
        extraction_result.extracted_text_path
    )
    assert summary["extractor"]["temp_image_dir"] == str(
        extraction_result.temp_image_dir
    )
    assert summary["extractor"]["stats"] == {
        "image_blocks": 0,
        "text_blocks": 1,
        "imported_blocks": 1,
    }
    assert summary["chapter_run"]["run_id"] == session_id
    assert summary["chapter_run"]["run_dir"] == str(result.chapter.run_dir)
    assert summary["chapter_run"]["total_blocks"] == 1
    assert summary["chapter_run"]["passed_blocks"] == 1
    assert summary["chapter_run"]["failed_blocks"] == 0
    assert summary["chapter_run"]["skipped_blocks"] == 0
    assert summary["chapter_run"]["report_json_path"] == str(
        result.chapter.report_json_path
    )
    assert summary["chapter_run"]["report_markdown_path"] == str(
        result.chapter.report_markdown_path
    )


def test_orchestrator_summary_uses_runner_docker_config_after_chapter_run(
    tmp_path,
) -> None:
    session_id = "260702_143015"
    extraction_result = make_extraction_result(tmp_path, session_id)

    def fake_extract(extractor_config):
        return extraction_result

    class DependencyRunner:
        def __init__(self) -> None:
            self.executor = DockerBlockExecutor(config=DockerExecutorConfig())

        def run(self, blocks_dir, run_root, session_id=None):
            self.executor.config = replace(
                self.executor.config,
                image="",
                install_requirements=("numpy",),
            )
            run_dir = run_root / session_id
            run_dir.mkdir(parents=True)
            return ChapterRunResult(
                run_id=session_id,
                run_dir=run_dir,
                total_blocks=1,
                passed_blocks=1,
                failed_blocks=0,
                skipped_blocks=0,
                report_json_path=run_dir / "chapter_error_report.json",
                report_markdown_path=run_dir / "chapter_error_report.md",
            )

    config = QaPipelineConfig(
        extractor=make_extractor_config(tmp_path),
        run_root=tmp_path / "qa_pipeline_runs",
    )
    orchestrator = QaPipelineOrchestrator(
        extract=fake_extract,
        runner_factory=lambda config: DependencyRunner(),
        session_id_factory=lambda: session_id,
    )

    result = orchestrator.run(config)

    summary = read_json(result.summary_path)
    assert summary["docker"]["image"].startswith(
        "qa-platform-python:3.11-deps-"
    )
    assert summary["docker"]["python_version"] == "3.11"
    assert summary["docker"]["install_requirements"] == ["numpy"]


def test_orchestrator_summary_ignores_non_docker_executor_config(
    tmp_path,
) -> None:
    session_id = "260702_143015"
    extraction_result = make_extraction_result(tmp_path, session_id)

    def fake_extract(extractor_config):
        return extraction_result

    class NonDockerExecutorConfig:
        image = "custom-executor:latest"
        python_version = "9.99"
        install_requirements = ("not-a-docker-requirement",)

    class CustomExecutor:
        config = NonDockerExecutorConfig()

    class CustomRunner:
        executor = CustomExecutor()

        def run(self, blocks_dir, run_root, session_id=None):
            run_dir = run_root / session_id
            run_dir.mkdir(parents=True)
            return ChapterRunResult(
                run_id=session_id,
                run_dir=run_dir,
                total_blocks=1,
                passed_blocks=1,
                failed_blocks=0,
                skipped_blocks=0,
                report_json_path=run_dir / "chapter_error_report.json",
                report_markdown_path=run_dir / "chapter_error_report.md",
            )

    config = QaPipelineConfig(
        extractor=make_extractor_config(tmp_path),
        run_root=tmp_path / "qa_pipeline_runs",
        docker=DockerExecutorConfig(python_version="3.12"),
    )
    orchestrator = QaPipelineOrchestrator(
        extract=fake_extract,
        runner_factory=lambda config: CustomRunner(),
        session_id_factory=lambda: session_id,
    )

    result = orchestrator.run(config)

    summary = read_json(result.summary_path)
    assert summary["docker"] == {
        "image": "qa-platform-python-stdlib:3.12",
        "python_version": "3.12",
        "install_requirements": [],
    }
