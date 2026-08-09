from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path
import re
import shutil

from qa_platform.execution.base import BlockExecutor
from qa_platform.contract.parser import BlockSpecParser
from qa_platform.chapter.models import (
    ChapterRunManifest,
    ChapterRunResult,
    ChapterRunWarning,
    ResultIndexEntry,
)
from qa_platform.contract.constants import (
    CATEGORY_RUNNER_ERROR,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
)
from qa_platform.contract.models import (
    ExecutionResult,
    ParseResult,
)
from qa_platform.shared.json_io import (
    read_json,
    write_json,
)
from qa_platform.reporting.report_builder import ReportBuilder
from qa_platform.shared.session import build_session_id


BLOCK_FILE_PATTERN = re.compile(r"^block_(?P<number>[0-9]{3})\.txt$")


class ChapterInputError(ValueError):
    """챕터 입력 디렉터리 또는 block 파일 구성이 유효하지 않음."""


@dataclass(frozen=True)
class _PreparedRun:
    run_id: str
    run_dir: Path
    block_files: list[Path]
    manifest: ChapterRunManifest


@dataclass(frozen=True)
class _PreparedBlock:
    block_dir: Path
    parse_result: ParseResult | None
    runner_error_result: ExecutionResult | None


class ChapterRunner:
    def __init__(
        self,
        executor: BlockExecutor,
        parser: BlockSpecParser | None = None,
        report_builder: ReportBuilder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.executor = executor
        self.parser = parser or BlockSpecParser()
        self.report_builder = report_builder or ReportBuilder()
        self.clock = clock or (lambda: datetime.now().astimezone())

    def run(
        self,
        blocks_dir: Path,
        run_root: Path = Path("run"),
        session_id: str | None = None,
    ) -> ChapterRunResult:
        prepared = self._prepare_run(blocks_dir, run_root, session_id=session_id)
        manifest = prepared.manifest
        results_path = prepared.run_dir / "results.jsonl"

        try:
            prepared_blocks: list[_PreparedBlock] = []
            parse_results: list[ParseResult] = []
            for source_path in prepared.block_files:
                block_id = source_path.stem
                block_dir = prepared.run_dir / "blocks" / block_id
                block_dir.mkdir()
                shutil.copyfile(source_path, block_dir / "block.txt")

                try:
                    parse_result = self.parser.parse_block_dir(block_dir)
                except Exception as exc:
                    prepared_blocks.append(
                        _PreparedBlock(
                            block_dir=block_dir,
                            parse_result=None,
                            runner_error_result=_build_runner_error_result(
                                block_dir=block_dir,
                                block_id=block_id,
                                exc=exc,
                            ),
                        )
                    )
                    continue

                parse_results.append(parse_result)
                prepared_blocks.append(
                    _PreparedBlock(
                        block_dir=block_dir,
                        parse_result=parse_result,
                        runner_error_result=None,
                    )
                )

            prepare_chapter = getattr(self.executor, "prepare_chapter", None)
            if callable(prepare_chapter):
                prepare_chapter(parse_results)

            for prepared_block in prepared_blocks:
                block_dir = prepared_block.block_dir
                block_id = block_dir.name
                result = prepared_block.runner_error_result
                if result is None:
                    try:
                        result = self.executor.execute(block_dir)
                    except Exception as exc:
                        result = _build_runner_error_result(
                            block_dir=block_dir,
                            block_id=block_id,
                            exc=exc,
                        )
                        write_json(
                            block_dir / "result.json",
                            result.to_dict(),
                        )

                if prepared_block.runner_error_result is not None:
                    write_json(block_dir / "result.json", result.to_dict())

                _append_result_index(results_path, result)
                manifest = replace(
                    manifest,
                    processed_blocks=manifest.processed_blocks + 1,
                    passed_blocks=(
                        manifest.passed_blocks
                        + int(result.status == STATUS_PASSED)
                    ),
                    failed_blocks=(
                        manifest.failed_blocks
                        + int(result.status == STATUS_FAILED)
                    ),
                    skipped_blocks=(
                        manifest.skipped_blocks
                        + int(result.status == STATUS_SKIPPED)
                    ),
                )
                _write_manifest(prepared.run_dir, manifest)

            self.report_builder.build(prepared.run_dir)
            manifest = replace(
                manifest,
                completed_at=self.clock().isoformat(),
                status="completed",
            )
            _write_manifest(prepared.run_dir, manifest)
        except Exception as exc:
            failed_manifest = replace(
                manifest,
                completed_at=self.clock().isoformat(),
                status="failed",
                run_error=f"{exc.__class__.__name__}: {exc}",
            )
            try:
                _write_manifest(prepared.run_dir, failed_manifest)
            except Exception:
                pass
            raise

        return ChapterRunResult(
            run_id=prepared.run_id,
            run_dir=prepared.run_dir,
            total_blocks=manifest.total_blocks,
            passed_blocks=manifest.passed_blocks,
            failed_blocks=manifest.failed_blocks,
            skipped_blocks=manifest.skipped_blocks,
            report_json_path=(
                prepared.run_dir / "chapter_error_report.json"
            ),
            report_markdown_path=(
                prepared.run_dir / "chapter_error_report.md"
            ),
        )

    def _prepare_run(
        self,
        blocks_dir: Path,
        run_root: Path,
        session_id: str | None = None,
    ) -> _PreparedRun:
        block_files, warnings = _discover_block_files(blocks_dir)
        started_at = self.clock()
        run_id = session_id or build_session_id(lambda: started_at)
        run_dir = run_root / run_id

        run_root.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir()
        (run_dir / "blocks").mkdir()

        manifest = ChapterRunManifest(
            schema_version=1,
            run_id=run_id,
            source_blocks_dir=str(blocks_dir.resolve()),
            started_at=started_at.isoformat(),
            completed_at=None,
            status="running",
            total_blocks=len(block_files),
            processed_blocks=0,
            passed_blocks=0,
            failed_blocks=0,
            skipped_blocks=0,
            warnings=warnings,
            run_error=None,
        )
        write_json(run_dir / "run_manifest.json", manifest.to_dict())
        return _PreparedRun(
            run_id=run_id,
            run_dir=run_dir,
            block_files=block_files,
            manifest=manifest,
        )


def _discover_block_files(
    blocks_dir: Path,
) -> tuple[list[Path], list[ChapterRunWarning]]:
    if not blocks_dir.exists():
        raise ChapterInputError(f"Blocks directory does not exist: {blocks_dir}")
    if not blocks_dir.is_dir():
        raise ChapterInputError(f"Blocks path is not a directory: {blocks_dir}")

    block_files: list[Path] = []
    block_numbers: set[int] = set()
    for path in blocks_dir.iterdir():
        if not path.is_file():
            continue
        match = BLOCK_FILE_PATTERN.fullmatch(path.name)
        if match is not None:
            block_files.append(path)
            block_numbers.add(int(match.group("number")))
            continue
        if path.name.startswith("block_") and path.suffix == ".txt":
            raise ChapterInputError(f"Invalid block file name: {path.name}")

    if not block_files:
        raise ChapterInputError(
            f"No valid block_###.txt files found in {blocks_dir}."
        )

    block_files.sort(key=lambda path: path.name)
    warnings = _build_missing_number_warnings(block_numbers)
    return block_files, warnings


def _build_missing_number_warnings(
    block_numbers: set[int],
) -> list[ChapterRunWarning]:
    largest_number = max(block_numbers)
    missing_numbers = [
        number
        for number in range(1, largest_number + 1)
        if number not in block_numbers
    ]
    if not missing_numbers:
        return []

    return [
        ChapterRunWarning(
            warning_type="missing_block_numbers",
            message=(
                "Block numbers are missing between "
                f"001 and {largest_number:03d}."
            ),
            block_ids=[
                f"block_{number:03d}" for number in missing_numbers
            ],
        )
    ]


def _append_result_index(
    results_path: Path,
    result: ExecutionResult,
) -> None:
    entry = ResultIndexEntry(
        block_id=result.block_id,
        status=result.status,
        category=result.category,
        result_path=f"blocks/{result.block_id}/result.json",
    )
    with results_path.open("a", encoding="utf-8") as results_file:
        results_file.write(
            json.dumps(
                entry.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )


def _build_runner_error_result(
    block_dir: Path,
    block_id: str,
    exc: Exception,
) -> ExecutionResult:
    expected_output: str | None = None
    meta: dict[str, str] = {}
    try:
        parse_result = ParseResult.from_dict(
            read_json(block_dir / "block.json")
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        parse_result = None

    if (
        parse_result is not None
        and parse_result.parse_success
        and parse_result.spec is not None
    ):
        expected_output = parse_result.spec.expected_output
        meta = parse_result.spec.meta

    return ExecutionResult(
        block_id=block_id,
        status=STATUS_FAILED,
        category=CATEGORY_RUNNER_ERROR,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=exc.__class__.__name__,
        error_message=str(exc),
        expected_output=expected_output,
        output_matched=None,
        meta=meta,
    )


def _write_manifest(
    run_dir: Path,
    manifest: ChapterRunManifest,
) -> None:
    write_json(run_dir / "run_manifest.json", manifest.to_dict())
