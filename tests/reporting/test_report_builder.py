from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from qa_platform.chapter.models import (
    ChapterRunManifest,
    ChapterRunWarning,
    ResultIndexEntry,
)
from qa_platform.contract.models import (
    BlockSpec,
    ExecutionResult,
    PackageSpec,
    ParseError,
    ParseResult,
)
from qa_platform.shared.json_io import (
    read_json,
    write_json,
)
from qa_platform.reporting.report_builder import ReportBuilder, ReportInputError


FIXED_REPORT_TIME = datetime(2026, 6, 21, 6, 30, 14, tzinfo=timezone.utc)


def write_manifest(
    run_dir: Path,
    *,
    total_blocks: int,
    passed_blocks: int,
    failed_blocks: int,
    warnings: list[ChapterRunWarning] | None = None,
) -> None:
    manifest = ChapterRunManifest(
        schema_version=1,
        run_id="260621_153012",
        source_blocks_dir="/tmp/source_blocks",
        started_at="2026-06-21T15:30:12+09:00",
        completed_at="2026-06-21T15:30:13+09:00",
        status="completed",
        total_blocks=total_blocks,
        processed_blocks=total_blocks,
        passed_blocks=passed_blocks,
        failed_blocks=failed_blocks,
        warnings=warnings or [],
        run_error=None,
    )
    write_json(run_dir / "run_manifest.json", manifest.to_dict())


def write_results_index(
    run_dir: Path,
    entries: list[ResultIndexEntry],
) -> None:
    content = "".join(
        json.dumps(entry.to_dict(), ensure_ascii=False, separators=(",", ":"))
        + "\n"
        for entry in entries
    )
    (run_dir / "results.jsonl").write_text(content, encoding="utf-8")


def write_block_files(
    run_dir: Path,
    *,
    block_id: str,
    result: ExecutionResult,
    parse_result: ParseResult | None,
    source_block_text: str,
) -> None:
    block_dir = run_dir / "blocks" / block_id
    block_dir.mkdir(parents=True)
    (block_dir / "block.txt").write_text(source_block_text, encoding="utf-8")
    write_json(block_dir / "result.json", result.to_dict())

    if parse_result is None:
        return

    write_json(block_dir / "block.json", parse_result.to_dict())
    if parse_result.parse_success and parse_result.spec is not None:
        (block_dir / "normalized.py").write_text(
            parse_result.spec.code,
            encoding="utf-8",
        )
        (block_dir / "stdin.txt").write_text(
            parse_result.spec.stdin,
            encoding="utf-8",
        )


def result_entry(result: ExecutionResult) -> ResultIndexEntry:
    return ResultIndexEntry(
        block_id=result.block_id,
        status=result.status,
        category=result.category,
        result_path=f"blocks/{result.block_id}/result.json",
    )


def build_single_failed_run(
    tmp_path: Path,
    *,
    category: str = "name_error",
) -> tuple[Path, ExecutionResult]:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category=category,
        exit_code=1,
        duration_ms=10,
        stdout="",
        stderr="NameError: name 'missing' is not defined\n",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="NameError",
        error_message="name 'missing' is not defined",
        expected_output="",
        output_matched=None,
        meta={},
    )
    spec = BlockSpec(
        code="print(missing)\n",
        stdin="",
        expected_output="",
        meta={},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=spec,
        ),
        source_block_text="[CODE]\nprint(missing)\n",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])
    return run_dir, result


def test_build_json_report_aggregates_failures_in_result_order(tmp_path) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)

    passed_result = ExecutionResult(
        block_id="block_001",
        status="passed",
        category=None,
        exit_code=0,
        duration_ms=10,
        stdout="ok\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=None,
        error_message=None,
        expected_output="ok\n",
        output_matched=True,
        meta={"page": "10"},
    )
    name_error_result = ExecutionResult(
        block_id="block_002",
        status="failed",
        category="name_error",
        exit_code=1,
        duration_ms=20,
        stdout="",
        stderr="NameError: name 'missing' is not defined\n",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="NameError",
        error_message="name 'missing' is not defined",
        expected_output="hello\n",
        output_matched=None,
        meta={"page": "12"},
    )
    mismatch_result = ExecutionResult(
        block_id="block_003",
        status="failed",
        category="output_mismatch",
        exit_code=0,
        duration_ms=30,
        stdout="actual\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=None,
        error_message=None,
        expected_output="expected\n",
        output_matched=False,
        meta={},
    )
    parse_error_result = ExecutionResult(
        block_id="block_004",
        status="failed",
        category="parse_error",
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="missing_section",
        error_message="Missing [CODE] section.",
        expected_output=None,
        output_matched=None,
        meta={},
    )

    success_specs = {
        "block_001": BlockSpec(
            code="print('ok')\n",
            stdin="",
            expected_output="ok\n",
            meta={"page": "10"},
        ),
        "block_002": BlockSpec(
            code="print(missing)\n",
            stdin="",
            packages=[
                PackageSpec(name="sample", specifier=">=1", raw="sample>=1")
            ],
            expected_output="hello\n",
            meta={"page": "12"},
        ),
        "block_003": BlockSpec(
            code="print('actual')\n",
            stdin="",
            expected_output="expected\n",
            meta={},
        ),
    }

    for result in (passed_result, name_error_result, mismatch_result):
        spec = success_specs[result.block_id]
        write_block_files(
            run_dir,
            block_id=result.block_id,
            result=result,
            parse_result=ParseResult(
                parse_success=True,
                block_id=result.block_id,
                spec=spec,
            ),
            source_block_text=f"[CODE]\n{spec.code}",
        )

    write_block_files(
        run_dir,
        block_id="block_004",
        result=parse_error_result,
        parse_result=ParseResult(
            parse_success=False,
            block_id="block_004",
            error=ParseError(
                error_type="missing_section",
                message="Missing [CODE] section.",
            ),
        ),
        source_block_text="[INPUT]\nvalue\n",
    )
    entries = [
        result_entry(passed_result),
        result_entry(name_error_result),
        result_entry(mismatch_result),
        result_entry(parse_error_result),
    ]
    write_manifest(
        run_dir,
        total_blocks=4,
        passed_blocks=1,
        failed_blocks=3,
    )
    write_results_index(run_dir, entries)

    report = ReportBuilder(clock=lambda: FIXED_REPORT_TIME).build(run_dir)

    assert report.generated_at == "2026-06-21 Time 06:30:14"
    assert report.summary.to_dict() == {
        "total_blocks": 4,
        "passed_blocks": 1,
        "failed_blocks": 3,
        "skipped_blocks": 0,
        "category_counts": {
            "name_error": 1,
            "output_mismatch": 1,
            "parse_error": 1,
        },
    }
    assert [error.block_id for error in report.errors] == [
        "block_002",
        "block_003",
        "block_004",
    ]
    assert report.errors[0].page == "12"
    assert report.errors[0].packages == [
        PackageSpec(name="sample", specifier=">=1", raw="sample>=1")
    ]
    assert report.errors[0].review_reason
    assert report.errors[1].page is None
    assert report.errors[2].code == ""
    assert report.errors[2].source_block_text == "[INPUT]\nvalue\n"
    assert read_json(run_dir / "chapter_error_report.json") == report.to_dict()


def test_build_rejects_missing_manifest(tmp_path) -> None:
    run_dir, _ = build_single_failed_run(tmp_path)
    (run_dir / "run_manifest.json").unlink()

    with pytest.raises(ReportInputError, match="run_manifest"):
        ReportBuilder().build(run_dir)


def test_build_rejects_missing_results_index(tmp_path) -> None:
    run_dir, _ = build_single_failed_run(tmp_path)
    (run_dir / "results.jsonl").unlink()

    with pytest.raises(ReportInputError, match="results.jsonl"):
        ReportBuilder().build(run_dir)


@pytest.mark.parametrize(
    "content",
    [
        "\n",
        "{not-json}\n",
        '{"block_id":"block_001"}\n',
    ],
)
def test_build_rejects_invalid_results_index_lines(
    tmp_path,
    content: str,
) -> None:
    run_dir, _ = build_single_failed_run(tmp_path)
    (run_dir / "results.jsonl").write_text(content, encoding="utf-8")

    with pytest.raises(ReportInputError, match="results.jsonl"):
        ReportBuilder().build(run_dir)


def test_build_rejects_duplicate_block_ids(tmp_path) -> None:
    run_dir, result = build_single_failed_run(tmp_path)
    entry = result_entry(result)
    write_results_index(run_dir, [entry, entry])

    with pytest.raises(ReportInputError, match="Duplicate block_id"):
        ReportBuilder().build(run_dir)


def test_build_rejects_absolute_result_path(tmp_path) -> None:
    run_dir, result = build_single_failed_run(tmp_path)
    absolute_path = (run_dir / "blocks" / "block_001" / "result.json").resolve()
    entry = ResultIndexEntry(
        block_id=result.block_id,
        status=result.status,
        category=result.category,
        result_path=str(absolute_path),
    )
    write_results_index(run_dir, [entry])

    with pytest.raises(ReportInputError, match="result_path"):
        ReportBuilder().build(run_dir)


def test_build_rejects_result_path_outside_run_directory(tmp_path) -> None:
    run_dir, result = build_single_failed_run(tmp_path)
    outside_dir = run_dir.parent / "outside"
    outside_dir.mkdir()
    write_json(outside_dir / "result.json", result.to_dict())
    entry = ResultIndexEntry(
        block_id=result.block_id,
        status=result.status,
        category=result.category,
        result_path="../outside/result.json",
    )
    write_results_index(run_dir, [entry])

    with pytest.raises(ReportInputError, match="result_path"):
        ReportBuilder().build(run_dir)


def test_build_rejects_missing_result_json(tmp_path) -> None:
    run_dir, _ = build_single_failed_run(tmp_path)
    (run_dir / "blocks" / "block_001" / "result.json").unlink()

    with pytest.raises(ReportInputError, match="block_001"):
        ReportBuilder().build(run_dir)


def test_build_rejects_index_and_result_mismatch(tmp_path) -> None:
    run_dir, result = build_single_failed_run(tmp_path)
    write_results_index(
        run_dir,
        [
            ResultIndexEntry(
                block_id=result.block_id,
                status="passed",
                category=None,
                result_path="blocks/block_001/result.json",
            )
        ],
    )

    with pytest.raises(ReportInputError, match="does not match"):
        ReportBuilder().build(run_dir)


def test_build_rejects_unknown_failure_category(tmp_path) -> None:
    run_dir, _ = build_single_failed_run(tmp_path, category="unknown_category")

    with pytest.raises(ReportInputError, match="category"):
        ReportBuilder().build(run_dir)


def test_build_rejects_unknown_result_status(tmp_path) -> None:
    run_dir, result = build_single_failed_run(tmp_path)
    invalid_result = ExecutionResult(
        **{
            **result.__dict__,
            "status": "ignored",
        }
    )
    write_json(
        run_dir / "blocks" / "block_001" / "result.json",
        invalid_result.to_dict(),
    )
    write_results_index(run_dir, [result_entry(invalid_result)])

    with pytest.raises(ReportInputError, match="status"):
        ReportBuilder().build(run_dir)


def test_build_rejects_passed_result_with_failure_category(tmp_path) -> None:
    run_dir, result = build_single_failed_run(tmp_path)
    invalid_result = ExecutionResult(
        **{
            **result.__dict__,
            "status": "passed",
            "category": "name_error",
        }
    )
    write_json(
        run_dir / "blocks" / "block_001" / "result.json",
        invalid_result.to_dict(),
    )
    write_results_index(run_dir, [result_entry(invalid_result)])

    with pytest.raises(ReportInputError, match="category"):
        ReportBuilder().build(run_dir)


def test_build_uses_source_fallback_for_runner_error(tmp_path) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="runner_error",
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="PermissionError",
        error_message="permission denied",
        expected_output=None,
        output_matched=None,
        meta={},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=None,
        source_block_text="[CODE]\nprint('hello')\n",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])

    report = ReportBuilder().build(run_dir)

    assert report.errors[0].code == ""
    assert report.errors[0].stdin == ""
    assert report.errors[0].packages == []
    assert report.errors[0].source_block_text == "[CODE]\nprint('hello')\n"


def test_build_writes_markdown_with_summary_warning_and_failure_detail(
    tmp_path,
) -> None:
    run_dir, _ = build_single_failed_run(tmp_path)
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
        warnings=[
            ChapterRunWarning(
                warning_type="missing_block_numbers",
                message="Block numbers are missing between 001 and 003.",
                block_ids=["block_002"],
            )
        ],
    )

    report = ReportBuilder(clock=lambda: FIXED_REPORT_TIME).build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert "# 챕터 오류 리포트" in markdown
    assert report.run_id in markdown
    assert "| 전체 block | 1 |" in markdown
    assert "| 실패 block | 1 |" in markdown
    assert "| `name_error` | 1 |" in markdown
    assert "Block numbers are missing between 001 and 003." in markdown
    assert "### `block_001`" in markdown
    assert "페이지 정보 없음" in markdown
    assert "변수나 함수 이름의 오탈자" in markdown
    assert "print(missing)" in markdown
    assert "NameError: name 'missing' is not defined" in markdown


def test_markdown_splits_failed_and_skipped_category_counts(tmp_path) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    failed_result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="name_error",
        exit_code=1,
        duration_ms=10,
        stdout="",
        stderr="NameError: name 'missing' is not defined\n",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="NameError",
        error_message="name 'missing' is not defined",
        expected_output="",
        output_matched=None,
        meta={},
    )
    skipped_result = ExecutionResult(
        block_id="block_002",
        status="skipped",
        category="incomplete_snippet",
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="SkippedByCodeType",
        error_message="Block execution skipped because code_type=INCOMPLETE_SNIPPET.",
        expected_output="",
        output_matched=None,
        meta={"code_type": "INCOMPLETE_SNIPPET"},
    )
    for result in (failed_result, skipped_result):
        write_block_files(
            run_dir,
            block_id=result.block_id,
            result=result,
            parse_result=ParseResult(
                parse_success=True,
                block_id=result.block_id,
                spec=BlockSpec(
                    code="print('sample')\n",
                    stdin="",
                    expected_output="",
                    meta=result.meta,
                ),
            ),
            source_block_text="[CODE]\nprint('sample')\n",
        )
    write_manifest(
        run_dir,
        total_blocks=2,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(
        run_dir,
        [result_entry(failed_result), result_entry(skipped_result)],
    )

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    category_section = markdown[
        markdown.index("## Category별 검토 수") : markdown.index(
            "## 검토 우선순위"
        )
    ]
    failed_section = category_section[
        category_section.index("### 실패 block") : category_section.index(
            "### 건너뜀 block"
        )
    ]
    skipped_section = category_section[
        category_section.index("### 건너뜀 block") :
    ]
    assert "| `name_error` | 1 |" in failed_section
    assert "| `incomplete_snippet` |" not in failed_section
    assert "| `incomplete_snippet` | 1 |" in skipped_section
    assert "| `name_error` |" not in skipped_section


def test_markdown_includes_review_priority_table(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    failed_result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="name_error",
        exit_code=1,
        duration_ms=10,
        stdout="",
        stderr="NameError: missing\n",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="NameError",
        error_message="missing | name\nsecond line",
        expected_output="",
        output_matched=None,
        meta={"page": "12"},
    )
    skipped_result = ExecutionResult(
        block_id="block_002",
        status="skipped",
        category="incomplete_snippet",
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="SkippedByCodeType",
        error_message="code_type=INCOMPLETE_SNIPPET",
        expected_output="",
        output_matched=None,
        meta={"code_type": "INCOMPLETE_SNIPPET"},
    )
    for result in (failed_result, skipped_result):
        write_block_files(
            run_dir,
            block_id=result.block_id,
            result=result,
            parse_result=ParseResult(
                parse_success=True,
                block_id=result.block_id,
                spec=BlockSpec(
                    code="print('sample')\n",
                    stdin="",
                    expected_output="",
                    meta=result.meta,
                ),
            ),
            source_block_text="[CODE]\nprint('sample')\n",
        )
    write_manifest(
        run_dir,
        total_blocks=2,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(
        run_dir,
        [result_entry(failed_result), result_entry(skipped_result)],
    )

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    priority_section = markdown[
        markdown.index("## 검토 우선순위") : markdown.index("## 입력 경고")
    ]
    assert "### 실패 block" in priority_section
    assert "### 건너뜀 block" in priority_section
    assert (
        "| block | 페이지 | Category | 실패 타입 | 실패 메시지 | 결과 파일 |"
        in priority_section
    )
    assert (
        "| `block_001` | 12 | `name_error` | NameError | "
        "missing \\| name | `blocks/block_001/result.json` |"
    ) in priority_section
    assert (
        "| block | 페이지 | Category | 스킵 타입 | 스킵 사유 | 주요 근거 | 결과 파일 |"
        in priority_section
    )
    assert (
        "| `block_002` | 페이지 정보 없음 | `incomplete_snippet` | "
        "SkippedByCodeType | code_type=INCOMPLETE_SNIPPET | "
        "code_type=INCOMPLETE_SNIPPET | "
        "`blocks/block_002/result.json` |"
    ) in priority_section
    assert "second line" not in priority_section


def test_markdown_splits_failed_and_skipped_detail_sections(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    failed_result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="name_error",
        exit_code=1,
        duration_ms=10,
        stdout="",
        stderr="NameError: name 'missing' is not defined\n",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="NameError",
        error_message="name 'missing' is not defined",
        expected_output="",
        output_matched=None,
        meta={},
    )
    skipped_result = ExecutionResult(
        block_id="block_002",
        status="skipped",
        category="incomplete_snippet",
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="SkippedByCodeType",
        error_message="Block execution skipped because code_type=INCOMPLETE_SNIPPET.",
        expected_output="",
        output_matched=None,
        meta={"code_type": "INCOMPLETE_SNIPPET"},
    )
    for result in (failed_result, skipped_result):
        write_block_files(
            run_dir,
            block_id=result.block_id,
            result=result,
            parse_result=ParseResult(
                parse_success=True,
                block_id=result.block_id,
                spec=BlockSpec(
                    code="print('sample')\n",
                    stdin="",
                    expected_output="",
                    meta=result.meta,
                ),
            ),
            source_block_text="[CODE]\nprint('sample')\n",
        )
    write_manifest(
        run_dir,
        total_blocks=2,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(
        run_dir,
        [result_entry(failed_result), result_entry(skipped_result)],
    )

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    failed_detail_section = markdown[
        markdown.index("## 실패 block 상세") : markdown.index(
            "## 건너뜀 block 상세"
        )
    ]
    skipped_detail_section = markdown[
        markdown.index("## 건너뜀 block 상세") :
    ]
    assert "## 검토 block 상세" not in markdown
    assert "### `block_001`" in failed_detail_section
    assert "### `block_002`" not in failed_detail_section
    assert "### `block_002`" in skipped_detail_section
    assert "### `block_001`" not in skipped_detail_section


def test_markdown_includes_output_diff_for_output_mismatch(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="output_mismatch",
        exit_code=0,
        duration_ms=10,
        stdout="actual\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=None,
        error_message=None,
        expected_output="expected\n",
        output_matched=False,
        meta={},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=BlockSpec(
                code="print('actual')\n",
                stdin="",
                expected_output="expected\n",
                meta={},
            ),
        ),
        source_block_text="[CODE]\nprint('actual')\n",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert "#### 출력 diff" in markdown
    assert "```diff" in markdown
    assert "--- expected" in markdown
    assert "+++ stdout" in markdown
    assert "-expected" in markdown
    assert "+actual" in markdown


def test_markdown_output_diff_preserves_final_newline_difference(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="output_mismatch",
        exit_code=0,
        duration_ms=10,
        stdout="expected",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=None,
        error_message=None,
        expected_output="expected\n",
        output_matched=False,
        meta={},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=BlockSpec(
                code="print('expected', end='')\n",
                stdin="",
                expected_output="expected\n",
                meta={},
            ),
        ),
        source_block_text="[CODE]\nprint('expected', end='')\n",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert "#### 출력 diff" in markdown
    assert "출력 차이가 없습니다." not in markdown
    assert "-expected" in markdown
    assert "+expected" in markdown
    assert "+expected\n\\ No newline at end of file" in markdown


def test_markdown_output_diff_marks_missing_expected_final_newline(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="output_mismatch",
        exit_code=0,
        duration_ms=10,
        stdout="expected\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=None,
        error_message=None,
        expected_output="expected",
        output_matched=False,
        meta={},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=BlockSpec(
                code="print('expected')\n",
                stdin="",
                expected_output="expected",
                meta={},
            ),
        ),
        source_block_text="[CODE]\nprint('expected')\n",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert "#### 출력 diff" in markdown
    assert "출력 차이가 없습니다." not in markdown
    assert "-expected\n\\ No newline at end of file\n+expected" in markdown


@pytest.mark.parametrize(
    ("expected_output", "stdout", "marker"),
    [
        ("++same\n", "++same", "+++same\n\\ No newline at end of file"),
        ("--same", "--same\n", "---same\n\\ No newline at end of file"),
    ],
)
def test_markdown_output_diff_marks_body_lines_that_look_like_headers(
    tmp_path,
    expected_output: str,
    stdout: str,
    marker: str,
) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="output_mismatch",
        exit_code=0,
        duration_ms=10,
        stdout=stdout,
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=None,
        error_message=None,
        expected_output=expected_output,
        output_matched=False,
        meta={},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=BlockSpec(
                code="print('same')\n",
                stdin="",
                expected_output=expected_output,
                meta={},
            ),
        ),
        source_block_text="[CODE]\nprint('same')\n",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert "#### 출력 diff" in markdown
    assert marker in markdown


def test_markdown_detail_includes_result_path_and_meta(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_019",
        status="failed",
        category="name_error",
        exit_code=1,
        duration_ms=1,
        stdout="",
        stderr="NameError: name 'greet' is not defined\n",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="NameError",
        error_message="name 'greet' is not defined",
        expected_output="",
        output_matched=None,
        meta={"page": "15", "context_symbols": "greet"},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=BlockSpec(
                code='greet("영희")\n',
                stdin="",
                expected_output="",
                meta={"page": "15", "context_symbols": "greet"},
            ),
        ),
        source_block_text='[CODE]\ngreet("영희")\n',
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert "| 상태 | `failed` |" in markdown
    assert "| 결과 파일 | `blocks/block_019/result.json` |" in markdown
    assert "| 실패 타입 | NameError |" in markdown
    assert "| 실패 메시지 | name 'greet' is not defined |" in markdown
    assert "#### Meta" in markdown
    assert "| Key | Value |" in markdown
    assert "| `context_symbols` | greet |" in markdown
    assert "| `page` | 15 |" in markdown


def test_markdown_skipped_detail_uses_skip_labels_and_evidence(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_018",
        status="skipped",
        category="missing_required_file",
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="MissingRequiredFileSkipped",
        error_message=(
            "Block execution skipped because it reads external files "
            "not provided by QA fixtures: age.csv."
        ),
        expected_output="",
        output_matched=None,
        meta={
            "page": "45",
            "run_skip_reason": "missing_required_file",
            "missing_required_files": "age.csv",
        },
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=BlockSpec(
                code="import pandas as pd\ndf = pd.read_csv('age.csv')\n",
                stdin="",
                expected_output="",
                meta=result.meta,
            ),
        ),
        source_block_text=(
            "[CODE]\nimport pandas as pd\ndf = pd.read_csv('age.csv')\n"
        ),
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=0,
    )
    write_results_index(run_dir, [result_entry(result)])

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    skipped_detail_section = markdown[
        markdown.index("## 건너뜀 block 상세") :
    ]
    assert "| 상태 | `skipped` |" in skipped_detail_section
    assert "| Category | `missing_required_file` |" in skipped_detail_section
    assert (
        "| 스킵 타입 | MissingRequiredFileSkipped |"
        in skipped_detail_section
    )
    assert (
        "| 스킵 사유 | Block execution skipped because it reads external "
        "files not provided by QA fixtures: age.csv. |"
    ) in skipped_detail_section
    assert (
        "| 주요 근거 | missing_required_files=age.csv |"
        in skipped_detail_section
    )
    assert "| 오류 타입 |" not in skipped_detail_section
    assert "| 오류 메시지 |" not in skipped_detail_section


def test_report_generated_at_uses_readable_clock_time_without_offset(
    tmp_path,
) -> None:
    run_dir, _ = build_single_failed_run(tmp_path)
    report_time = datetime(
        2026,
        7,
        7,
        13,
        25,
        30,
        331784,
        tzinfo=timezone(timedelta(hours=9)),
    )

    report = ReportBuilder(clock=lambda: report_time).build(run_dir)

    assert report.generated_at == "2026-07-07 Time 13:25:30"
    assert read_json(run_dir / "chapter_error_report.json")["generated_at"] == (
        "2026-07-07 Time 13:25:30"
    )
    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert "2026-07-07 Time 13:25:30" in markdown
    assert ".331784" not in markdown
    assert "+09:00" not in markdown
    assert "2026-07-07T13:25:30" not in markdown


def test_report_includes_setup_code_for_contextual_blocks(tmp_path) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_019",
        status="failed",
        category="name_error",
        exit_code=1,
        duration_ms=1,
        stdout="",
        stderr="NameError: name 'greet' is not defined\n",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="NameError",
        error_message="name 'greet' is not defined",
        expected_output=(
            "TypeError: greet() missing 1 required positional argument: 'msg'\n"
        ),
        output_matched=None,
        meta={"page": "15", "context_symbols": "greet"},
    )
    spec = BlockSpec(
        setup_code="def greet(name, msg):\n    print(name, msg)\n",
        code='greet("영희")\n',
        stdin="",
        expected_output=(
            "TypeError: greet() missing 1 required positional argument: 'msg'\n"
        ),
        meta={"page": "15", "context_symbols": "greet"},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=spec,
        ),
        source_block_text=(
            "[META]\npage=15\ncontext_symbols=greet\n\n"
            "[PACKAGES]\n\n"
            "[SETUP]\ndef greet(name, msg):\n    print(name, msg)\n\n"
            "[CODE]\ngreet(\"영희\")\n\n"
            "[INPUT]\n\n"
            "[OUTPUT]\nTypeError: greet() missing 1 required positional argument: 'msg'\n"
        ),
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])

    ReportBuilder().build(run_dir)

    report = (run_dir / "chapter_error_report.md").read_text(encoding="utf-8")
    assert "#### Setup 코드" in report
    assert "def greet(name, msg):" in report
    assert "context_symbols" in report


def test_build_markdown_says_when_no_blocks_failed(tmp_path) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_001",
        status="passed",
        category=None,
        exit_code=0,
        duration_ms=10,
        stdout="ok\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=None,
        error_message=None,
        expected_output="ok\n",
        output_matched=True,
        meta={},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=BlockSpec(
                code="print('ok')\n",
                stdin="",
                expected_output="ok\n",
                meta={},
            ),
        ),
        source_block_text="[CODE]\nprint('ok')\n",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=1,
        failed_blocks=0,
    )
    write_results_index(run_dir, [result_entry(result)])

    report = ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert report.errors == []
    assert "실패 block이 없습니다." in markdown
    assert "건너뜀 block이 없습니다." in markdown


def test_build_treats_accepted_eof_result_as_passed(tmp_path) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    result = ExecutionResult(
        block_id="block_001",
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
    spec = BlockSpec(
        code="while input() != 'stop':\n    pass\n",
        stdin="one\ntwo\n",
        expected_output="finished\n",
        meta={"stdin_exhaustion": "accept"},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=spec,
        ),
        source_block_text="[CODE]\nwhile input() != 'stop':\n    pass\n",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=1,
        failed_blocks=0,
    )
    write_results_index(run_dir, [result_entry(result)])

    report = ReportBuilder().build(run_dir)

    assert report.summary.passed_blocks == 1
    assert report.summary.failed_blocks == 0
    assert report.summary.category_counts == {}
    assert report.errors == []


def test_markdown_escapes_tables_and_uses_longer_code_fences(tmp_path) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    run_dir.mkdir(parents=True)
    code = "print('```')\n"
    result = ExecutionResult(
        block_id="block_001",
        status="failed",
        category="runtime_error",
        exit_code=1,
        duration_ms=10,
        stdout="first\nsecond\n",
        stderr="RuntimeError: bad | value\n",
        stdout_truncated=False,
        stderr_truncated=True,
        error_type="RuntimeError",
        error_message="bad | value",
        expected_output="expected\n",
        output_matched=None,
        meta={"page": "1|2"},
    )
    write_block_files(
        run_dir,
        block_id=result.block_id,
        result=result,
        parse_result=ParseResult(
            parse_success=True,
            block_id=result.block_id,
            spec=BlockSpec(
                code=code,
                stdin="one\ntwo\n",
                expected_output="expected\n",
                meta={"page": "1|2"},
            ),
        ),
        source_block_text=f"[CODE]\n{code}",
    )
    write_manifest(
        run_dir,
        total_blocks=1,
        passed_blocks=0,
        failed_blocks=1,
    )
    write_results_index(run_dir, [result_entry(result)])

    ReportBuilder().build(run_dir)

    markdown = (run_dir / "chapter_error_report.md").read_text(
        encoding="utf-8"
    )
    assert "````python\nprint('```')\n````" in markdown
    assert "1\\|2" in markdown
    assert "bad \\| value" in markdown
    assert "stderr 잘림 | 예 |" in markdown
