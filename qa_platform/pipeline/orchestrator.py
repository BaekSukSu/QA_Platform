from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from qa_platform.chapter.models import ChapterRunResult
from qa_platform.chapter.runner import ChapterRunner
from qa_platform.execution.base import BlockExecutor
from qa_platform.execution.docker import DockerBlockExecutor
from qa_platform.execution.docker_runtime import DockerExecutorConfig
from qa_platform.extraction.models import (
    DocumentExtractionConfig,
    DocumentExtractionPipelineResult,
)
from qa_platform.extraction.pipeline import run_document_extraction_pipeline
from qa_platform.pipeline.config import QaPipelineConfig
from qa_platform.shared.json_io import write_json
from qa_platform.shared.session import build_session_id


ExtractFunction = Callable[
    [DocumentExtractionConfig],
    DocumentExtractionPipelineResult,
]


@dataclass(frozen=True)
class QaPipelineResult:
    extraction: DocumentExtractionPipelineResult
    chapter: ChapterRunResult
    summary_path: Path


class QaPipelineOrchestrator:
    def __init__(
        self,
        *,
        extract: ExtractFunction = run_document_extraction_pipeline,
        runner_factory: Callable[[QaPipelineConfig], ChapterRunner] | None = None,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.extract = extract
        self.runner_factory = runner_factory or _default_runner_factory
        self.session_id_factory = session_id_factory or build_session_id

    def run(self, config: QaPipelineConfig) -> QaPipelineResult:
        session_id = config.extractor.session_id or self.session_id_factory()
        extractor_config = replace(config.extractor, session_id=session_id)
        extraction = self.extract(extractor_config)
        runner = self.runner_factory(config)
        chapter = runner.run(
            extraction.imported_output_dir,
            config.run_root,
            session_id=session_id,
        )
        summary_path = chapter.run_dir / "qa_pipeline.json"
        write_json(
            summary_path,
            _build_summary(
                config=config,
                docker=_docker_summary_from_runner(runner, config.docker),
                extraction=extraction,
                chapter=chapter,
            ),
        )
        return QaPipelineResult(
            extraction=extraction,
            chapter=chapter,
            summary_path=summary_path,
        )


def run_qa_pipeline(config: QaPipelineConfig) -> QaPipelineResult:
    return QaPipelineOrchestrator().run(config)


def build_qa_pipeline_executor(config: QaPipelineConfig) -> BlockExecutor:
    return DockerBlockExecutor(config=config.docker)


def _default_runner_factory(config: QaPipelineConfig) -> ChapterRunner:
    return ChapterRunner(executor=build_qa_pipeline_executor(config))


def _build_summary(
    *,
    config: QaPipelineConfig,
    docker: dict[str, object],
    extraction: DocumentExtractionPipelineResult,
    chapter: ChapterRunResult,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "pipeline": "qa_pipeline",
        "execution_backend": config.execution_backend,
        "docker": docker,
        "extractor": {
            "session_id": extraction.session_id or chapter.run_id,
            "source_output_dir": str(extraction.source_output_dir),
            "imported_output_dir": str(extraction.imported_output_dir),
            "block_files": [str(path) for path in extraction.block_files],
            "extracted_text_path": str(extraction.extracted_text_path),
            "temp_image_dir": str(extraction.temp_image_dir),
            "stats": extraction.stats,
        },
        "chapter_run": {
            "run_id": chapter.run_id,
            "run_dir": str(chapter.run_dir),
            "total_blocks": chapter.total_blocks,
            "passed_blocks": chapter.passed_blocks,
            "failed_blocks": chapter.failed_blocks,
            "skipped_blocks": chapter.skipped_blocks,
            "report_json_path": str(chapter.report_json_path),
            "report_markdown_path": str(chapter.report_markdown_path),
        },
    }


def _docker_summary_from_runner(
    runner: ChapterRunner,
    fallback: DockerExecutorConfig,
) -> dict[str, object]:
    executor = getattr(runner, "executor", None)
    executor_config = getattr(executor, "config", None)
    docker_config = (
        executor_config
        if isinstance(executor_config, DockerExecutorConfig)
        else fallback
    )
    return {
        "image": docker_config.image,
        "python_version": docker_config.python_version,
        "install_requirements": list(docker_config.install_requirements),
    }
