from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import pytest

from qa_platform.execution.base import BlockExecutor
from qa_platform.chapter.models import (
    ChapterErrorReport,
    ChapterReportSummary,
)
from qa_platform.chapter.runner import (
    ChapterInputError,
    ChapterRunner,
    _discover_block_files,
)
from qa_platform.contract.models import (
    BlockSpec,
    ExecutionResult,
    ParseResult,
)
from qa_platform.contract.parser import BlockSpecParser
from qa_platform.shared.json_io import (
    read_json,
    write_json,
)


FIXED_RUN_TIME = datetime(2026, 6, 21, 15, 30, 12, tzinfo=timezone.utc)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeExecutor:
    def execute(self, block_dir: Path) -> ExecutionResult:
        raise NotImplementedError


class RecordingParser:
    def __init__(self, calls: list[tuple[str, str]]) -> None:
        self.calls = calls

    def parse_block_dir(self, block_dir: Path) -> ParseResult:
        self.calls.append(("parse", block_dir.name))
        spec = BlockSpec(
            code=f"print('{block_dir.name}')\n",
            stdin="",
            expected_output=f"{block_dir.name}\n",
            meta={"page": block_dir.name[-3:]},
        )
        parse_result = ParseResult(
            parse_success=True,
            block_id=block_dir.name,
            spec=spec,
        )
        write_json(block_dir / "block.json", parse_result.to_dict())
        (block_dir / "normalized.py").write_text(spec.code, encoding="utf-8")
        (block_dir / "stdin.txt").write_text("", encoding="utf-8")
        return parse_result


class RecordingExecutor:
    def __init__(
        self,
        calls: list[tuple[str, str]],
        *,
        failing_block_id: str | None = None,
    ) -> None:
        self.calls = calls
        self.failing_block_id = failing_block_id

    def execute(self, block_dir: Path) -> ExecutionResult:
        self.calls.append(("execute", block_dir.name))
        if block_dir.name == self.failing_block_id:
            raise PermissionError("permission denied")
        result = ExecutionResult(
            block_id=block_dir.name,
            status="passed",
            category=None,
            exit_code=0,
            duration_ms=10,
            stdout=f"{block_dir.name}\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            error_type=None,
            error_message=None,
            expected_output=f"{block_dir.name}\n",
            output_matched=True,
            meta={"page": block_dir.name[-3:]},
        )
        write_json(block_dir / "result.json", result.to_dict())
        return result


class PreparingExecutor(RecordingExecutor):
    def prepare_chapter(self, parse_results: list[ParseResult]) -> None:
        for parse_result in parse_results:
            self.calls.append(("prepare", parse_result.block_id))


class AcceptedEofExecutor:
    def execute(self, block_dir: Path) -> ExecutionResult:
        result = ExecutionResult(
            block_id=block_dir.name,
            status="passed",
            category=None,
            exit_code=1,
            duration_ms=10,
            stdout="one\ntwo\n",
            stderr=(
                "Traceback (most recent call last):\n"
                "EOFError: EOF when reading a line\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            error_type="EOFError",
            error_message="EOF when reading a line",
            expected_output="finished\n",
            output_matched=None,
            meta={"stdin_exhaustion": "accept"},
        )
        write_json(block_dir / "result.json", result.to_dict())
        return result


class RecordingReportBuilder:
    def __init__(
        self,
        calls: list[tuple[str, str]],
        *,
        error: Exception | None = None,
    ) -> None:
        self.calls = calls
        self.error = error

    def build(self, run_dir: Path) -> ChapterErrorReport:
        self.calls.append(("report", run_dir.name))
        if self.error is not None:
            raise self.error
        (run_dir / "chapter_error_report.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (run_dir / "chapter_error_report.md").write_text(
            "# report\n",
            encoding="utf-8",
        )
        return ChapterErrorReport(
            schema_version=1,
            run_id=run_dir.name,
            source_blocks_dir="/tmp/blocks",
            generated_at=FIXED_RUN_TIME.isoformat(),
            summary=ChapterReportSummary(
                total_blocks=0,
                passed_blocks=0,
                failed_blocks=0,
                category_counts={},
            ),
            warnings=[],
            errors=[],
        )


def make_runner() -> ChapterRunner:
    return ChapterRunner(
        executor=FakeExecutor(),
        clock=lambda: FIXED_RUN_TIME,
    )


@pytest.mark.parametrize("input_kind", ["missing", "file", "empty"])
def test_prepare_run_rejects_invalid_input_without_creating_run_root(
    tmp_path,
    input_kind: str,
) -> None:
    blocks_dir = tmp_path / "blocks"
    if input_kind == "file":
        blocks_dir.write_text("not a directory", encoding="utf-8")
    elif input_kind == "empty":
        blocks_dir.mkdir()

    run_root = tmp_path / "run"

    with pytest.raises(ChapterInputError):
        make_runner()._prepare_run(blocks_dir, run_root)

    assert not run_root.exists()


def test_discover_ignores_unrelated_files_and_sorts_valid_blocks(
    tmp_path,
) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "notes.md").write_text("memo", encoding="utf-8")
    (blocks_dir / "block_010.txt").write_text("ten", encoding="utf-8")
    (blocks_dir / "block_002.txt").write_text("two", encoding="utf-8")
    (blocks_dir / "nested").mkdir()

    block_files, warnings = _discover_block_files(blocks_dir)

    assert [path.name for path in block_files] == [
        "block_002.txt",
        "block_010.txt",
    ]
    assert len(warnings) == 1
    assert warnings[0].warning_type == "missing_block_numbers"


@pytest.mark.parametrize(
    "invalid_name",
    ["block_01.txt", "block_0001.txt", "block_abc.txt"],
)
def test_discover_rejects_invalid_block_file_names(
    tmp_path,
    invalid_name: str,
) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_001.txt").write_text("valid", encoding="utf-8")
    (blocks_dir / invalid_name).write_text("invalid", encoding="utf-8")

    with pytest.raises(ChapterInputError, match=invalid_name):
        _discover_block_files(blocks_dir)


def test_discover_allows_missing_numbers_and_records_warning(tmp_path) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_001.txt").write_text("one", encoding="utf-8")
    (blocks_dir / "block_003.txt").write_text("three", encoding="utf-8")

    _, warnings = _discover_block_files(blocks_dir)

    assert [warning.to_dict() for warning in warnings] == [
        {
            "warning_type": "missing_block_numbers",
            "message": "Block numbers are missing between 001 and 003.",
            "block_ids": ["block_002"],
        }
    ]


def test_prepare_run_creates_timestamped_workspace_and_manifest(
    tmp_path,
) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_001.txt").write_text("one", encoding="utf-8")
    run_root = tmp_path / "run"
    executor = FakeExecutor()
    assert isinstance(executor, BlockExecutor)
    runner = ChapterRunner(
        executor=executor,
        clock=lambda: FIXED_RUN_TIME,
    )

    prepared = runner._prepare_run(blocks_dir, run_root)

    assert runner.executor is executor
    assert prepared.run_dir == run_root / "260621_153012"
    assert prepared.block_files == [blocks_dir / "block_001.txt"]
    assert (prepared.run_dir / "blocks").is_dir()
    manifest = read_json(prepared.run_dir / "run_manifest.json")
    assert manifest == {
        "schema_version": 1,
        "run_id": "260621_153012",
        "source_blocks_dir": str(blocks_dir.resolve()),
        "started_at": "2026-06-21T15:30:12+00:00",
        "completed_at": None,
        "status": "running",
        "total_blocks": 1,
        "processed_blocks": 0,
        "passed_blocks": 0,
        "failed_blocks": 0,
        "skipped_blocks": 0,
        "warnings": [],
        "run_error": None,
    }


def test_prepare_run_rejects_existing_run_id_without_modifying_it(
    tmp_path,
) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_001.txt").write_text("one", encoding="utf-8")
    existing_run_dir = tmp_path / "run" / "260621_153012"
    existing_run_dir.mkdir(parents=True)
    sentinel = existing_run_dir / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        make_runner()._prepare_run(blocks_dir, tmp_path / "run")

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in existing_run_dir.iterdir()) == [
        "sentinel.txt"
    ]


def test_run_calls_parser_and_executor_in_block_order_and_writes_index(
    tmp_path,
) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_002.txt").write_text("two", encoding="utf-8")
    (blocks_dir / "block_001.txt").write_text("one", encoding="utf-8")
    calls: list[tuple[str, str]] = []
    runner = ChapterRunner(
        executor=RecordingExecutor(calls),
        parser=RecordingParser(calls),
        report_builder=RecordingReportBuilder(calls),
        clock=lambda: FIXED_RUN_TIME,
    )

    result = runner.run(blocks_dir, tmp_path / "run")

    assert calls == [
        ("parse", "block_001"),
        ("parse", "block_002"),
        ("execute", "block_001"),
        ("execute", "block_002"),
        ("report", "260621_153012"),
    ]
    assert result.total_blocks == 2
    assert result.passed_blocks == 2
    assert result.failed_blocks == 0
    assert result.report_json_path.exists()
    assert result.report_markdown_path.exists()

    for block_id, source_text in (
        ("block_001", "one"),
        ("block_002", "two"),
    ):
        block_dir = result.run_dir / "blocks" / block_id
        assert (block_dir / "block.txt").read_text(encoding="utf-8") == (
            source_text
        )
        assert (block_dir / "result.json").exists()

    index_lines = (result.run_dir / "results.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert [json.loads(line) for line in index_lines] == [
        {
            "block_id": "block_001",
            "status": "passed",
            "category": None,
            "result_path": "blocks/block_001/result.json",
        },
        {
            "block_id": "block_002",
            "status": "passed",
            "category": None,
            "result_path": "blocks/block_002/result.json",
        },
    ]
    assert (result.run_dir / "results.jsonl").read_text(
        encoding="utf-8"
    ).endswith("\n")
    manifest = read_json(result.run_dir / "run_manifest.json")
    assert manifest["status"] == "completed"
    assert manifest["processed_blocks"] == 2
    assert manifest["passed_blocks"] == 2
    assert manifest["failed_blocks"] == 0
    assert manifest["completed_at"] == FIXED_RUN_TIME.isoformat()


def test_run_prepares_chapter_after_parsing_and_before_execution(
    tmp_path,
) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_001.txt").write_text("one", encoding="utf-8")
    (blocks_dir / "block_002.txt").write_text("two", encoding="utf-8")
    calls: list[tuple[str, str]] = []
    runner = ChapterRunner(
        executor=PreparingExecutor(calls),
        parser=RecordingParser(calls),
        report_builder=RecordingReportBuilder(calls),
        clock=lambda: FIXED_RUN_TIME,
    )

    runner.run(blocks_dir, tmp_path / "run")

    assert calls == [
        ("parse", "block_001"),
        ("parse", "block_002"),
        ("prepare", "block_001"),
        ("prepare", "block_002"),
        ("execute", "block_001"),
        ("execute", "block_002"),
        ("report", "260621_153012"),
    ]


def test_run_counts_accepted_eof_result_as_passed(tmp_path) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_001.txt").write_text("one", encoding="utf-8")
    calls: list[tuple[str, str]] = []
    runner = ChapterRunner(
        executor=AcceptedEofExecutor(),
        parser=RecordingParser(calls),
        report_builder=RecordingReportBuilder(calls),
        clock=lambda: FIXED_RUN_TIME,
    )

    result = runner.run(blocks_dir, tmp_path / "run")

    index_entry = json.loads(
        (result.run_dir / "results.jsonl").read_text(encoding="utf-8")
    )
    manifest = read_json(result.run_dir / "run_manifest.json")
    saved_result = read_json(
        result.run_dir / "blocks" / "block_001" / "result.json"
    )
    assert index_entry["status"] == "passed"
    assert index_entry["category"] is None
    assert manifest["passed_blocks"] == 1
    assert manifest["failed_blocks"] == 0
    assert saved_result["exit_code"] == 1
    assert saved_result["error_type"] == "EOFError"
    assert result.passed_blocks == 1
    assert result.failed_blocks == 0


def test_parser_preserves_chapter6_context_fixture(tmp_path) -> None:
    source = PROJECT_ROOT / "tests" / "fixtures" / "chapter6_context_blocks"
    blocks_dir = tmp_path / "blocks"
    shutil.copytree(source, blocks_dir)
    block_dir = tmp_path / "run" / "block_001"
    block_dir.mkdir(parents=True)
    shutil.copyfile(blocks_dir / "block_001.txt", block_dir / "block.txt")

    result = BlockSpecParser().parse_block_dir(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert "def greet(name, msg):" in result.spec.setup_code
    assert (block_dir / "normalized.py").read_text(encoding="utf-8").startswith(
        "def greet(name, msg):"
    )


def test_run_records_runner_error_and_continues_with_later_blocks(
    tmp_path,
) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    for number in range(1, 4):
        (blocks_dir / f"block_{number:03d}.txt").write_text(
            str(number),
            encoding="utf-8",
        )
    calls: list[tuple[str, str]] = []
    runner = ChapterRunner(
        executor=RecordingExecutor(
            calls,
            failing_block_id="block_002",
        ),
        parser=RecordingParser(calls),
        report_builder=RecordingReportBuilder(calls),
        clock=lambda: FIXED_RUN_TIME,
    )

    run_result = runner.run(blocks_dir, tmp_path / "run")

    assert ("execute", "block_003") in calls
    failed_result = read_json(
        run_result.run_dir / "blocks" / "block_002" / "result.json"
    )
    assert failed_result["status"] == "failed"
    assert failed_result["category"] == "runner_error"
    assert failed_result["error_type"] == "PermissionError"
    assert failed_result["error_message"] == "permission denied"
    assert failed_result["expected_output"] == "block_002\n"
    assert failed_result["meta"] == {"page": "002"}
    assert run_result.total_blocks == 3
    assert run_result.passed_blocks == 2
    assert run_result.failed_blocks == 1
    manifest = read_json(run_result.run_dir / "run_manifest.json")
    assert manifest["status"] == "completed"
    assert manifest["processed_blocks"] == 3
    assert manifest["failed_blocks"] == 1


def test_run_marks_manifest_failed_when_report_builder_raises(
    tmp_path,
) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "block_001.txt").write_text("one", encoding="utf-8")
    calls: list[tuple[str, str]] = []
    runner = ChapterRunner(
        executor=RecordingExecutor(calls),
        parser=RecordingParser(calls),
        report_builder=RecordingReportBuilder(
            calls,
            error=RuntimeError("report failed"),
        ),
        clock=lambda: FIXED_RUN_TIME,
    )

    with pytest.raises(RuntimeError, match="report failed"):
        runner.run(blocks_dir, tmp_path / "run")

    manifest = read_json(
        tmp_path / "run" / "260621_153012" / "run_manifest.json"
    )
    assert manifest["status"] == "failed"
    assert manifest["run_error"] == "RuntimeError: report failed"
    assert manifest["processed_blocks"] == 1
