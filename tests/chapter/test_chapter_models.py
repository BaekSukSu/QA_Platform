from pathlib import Path

from qa_platform.chapter.models import (
    ChapterErrorReport,
    ChapterReportError,
    ChapterReportSummary,
    ChapterRunManifest,
    ChapterRunResult,
    ChapterRunWarning,
    ResultIndexEntry,
)
from qa_platform.contract.models import PackageSpec


def test_chapter_run_warning_round_trips_to_json_dict() -> None:
    warning = ChapterRunWarning(
        warning_type="missing_block_numbers",
        message="Block numbers are missing between 001 and 003.",
        block_ids=["block_002"],
    )

    data = warning.to_dict()

    assert data == {
        "warning_type": "missing_block_numbers",
        "message": "Block numbers are missing between 001 and 003.",
        "block_ids": ["block_002"],
    }
    assert ChapterRunWarning.from_dict(data) == warning


def test_result_index_entry_round_trips_to_json_dict() -> None:
    entry = ResultIndexEntry(
        block_id="block_002",
        status="failed",
        category="name_error",
        result_path="blocks/block_002/result.json",
    )

    data = entry.to_dict()

    assert data == {
        "block_id": "block_002",
        "status": "failed",
        "category": "name_error",
        "result_path": "blocks/block_002/result.json",
    }
    assert ResultIndexEntry.from_dict(data) == entry


def test_chapter_run_manifest_round_trips_with_warnings() -> None:
    manifest = ChapterRunManifest(
        schema_version=1,
        run_id="260621_153012",
        source_blocks_dir="/tmp/blocks",
        started_at="2026-06-21T15:30:12+09:00",
        completed_at=None,
        status="running",
        total_blocks=3,
        processed_blocks=1,
        passed_blocks=1,
        failed_blocks=0,
        warnings=[
            ChapterRunWarning(
                warning_type="missing_block_numbers",
                message="Block numbers are missing between 001 and 003.",
                block_ids=["block_002"],
            )
        ],
        run_error=None,
    )

    data = manifest.to_dict()

    assert data["warnings"] == [
        {
            "warning_type": "missing_block_numbers",
            "message": "Block numbers are missing between 001 and 003.",
            "block_ids": ["block_002"],
        }
    ]
    assert ChapterRunManifest.from_dict(data) == manifest


def test_chapter_report_summary_serializes_sorted_category_counts() -> None:
    summary = ChapterReportSummary(
        total_blocks=3,
        passed_blocks=1,
        failed_blocks=2,
        category_counts={"output_mismatch": 1, "name_error": 1},
    )

    assert list(summary.to_dict()["category_counts"]) == [
        "name_error",
        "output_mismatch",
    ]


def test_chapter_report_error_serializes_packages() -> None:
    error = ChapterReportError(
        block_id="block_002",
        page="12",
        status="failed",
        category="module_not_found",
        review_reason="패키지를 확인해야 합니다.",
        error_type="ModuleNotFoundError",
        error_message="No module named 'numpy'",
        exit_code=1,
        duration_ms=42,
        code="import numpy\n",
        source_block_text="[CODE]\nimport numpy\n",
        stdin="",
        packages=[PackageSpec(name="numpy", specifier="", raw="numpy")],
        expected_output=None,
        stdout="",
        stderr="ModuleNotFoundError: No module named 'numpy'\n",
        output_matched=None,
        stdout_truncated=False,
        stderr_truncated=False,
        meta={"page": "12"},
        result_path="blocks/block_002/result.json",
    )

    data = error.to_dict()

    assert data["packages"] == [
        {"name": "numpy", "specifier": "", "raw": "numpy"}
    ]
    assert data["page"] == "12"
    assert data["meta"] == {"page": "12"}


def test_chapter_error_report_serializes_nested_models() -> None:
    report_error = ChapterReportError(
        block_id="block_002",
        page=None,
        status="failed",
        category="name_error",
        review_reason="이름을 확인해야 합니다.",
        error_type="NameError",
        error_message="name 'missing' is not defined",
        exit_code=1,
        duration_ms=10,
        code="print(missing)\n",
        source_block_text="[CODE]\nprint(missing)\n",
        stdin="",
        packages=[],
        expected_output="",
        stdout="",
        stderr="NameError: name 'missing' is not defined\n",
        output_matched=None,
        stdout_truncated=False,
        stderr_truncated=False,
        meta={},
        result_path="blocks/block_002/result.json",
    )
    report = ChapterErrorReport(
        schema_version=1,
        run_id="260621_153012",
        source_blocks_dir="/tmp/blocks",
        generated_at="2026-06-21T15:30:14+09:00",
        summary=ChapterReportSummary(
            total_blocks=2,
            passed_blocks=1,
            failed_blocks=1,
            category_counts={"name_error": 1},
        ),
        warnings=[],
        errors=[report_error],
    )

    data = report.to_dict()

    assert data["summary"]["failed_blocks"] == 1
    assert data["errors"][0]["block_id"] == "block_002"
    assert data["errors"][0]["packages"] == []


def test_chapter_run_result_keeps_paths_as_path_objects(tmp_path) -> None:
    run_dir = tmp_path / "run" / "260621_153012"
    result = ChapterRunResult(
        run_id="260621_153012",
        run_dir=run_dir,
        total_blocks=8,
        passed_blocks=8,
        failed_blocks=0,
        report_json_path=run_dir / "chapter_error_report.json",
        report_markdown_path=run_dir / "chapter_error_report.md",
    )

    assert result.run_dir == Path(run_dir)
    assert isinstance(result.report_json_path, Path)
    assert isinstance(result.report_markdown_path, Path)
