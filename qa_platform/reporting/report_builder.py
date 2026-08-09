from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
import difflib
import json
from pathlib import Path
import re

from qa_platform.chapter.models import (
    ChapterErrorReport,
    ChapterReportError,
    ChapterReportSummary,
    ChapterRunManifest,
    ResultIndexEntry,
)
from qa_platform.contract.constants import (
    RESULT_CATEGORIES,
    RESULT_STATUSES,
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


REPORT_GENERATED_AT_FORMAT = "%Y-%m-%d Time %H:%M:%S"

REVIEW_REASONS = {
    "parse_error": "block의 필수 섹션, 섹션 순서와 [META] 형식을 확인해야 합니다.",
    "syntax_error": "Python 문법 오류와 들여쓰기를 확인해야 합니다.",
    "name_error": "변수나 함수 이름의 오탈자, 정의 누락 또는 정의 순서를 확인해야 합니다.",
    "module_not_found": "필요한 패키지가 선언되어 있는지와 실행 환경에 설치되어 있는지 확인해야 합니다.",
    "missing_required_file": "코드가 참조하는 외부 파일의 경로와 제공 여부를 확인해야 합니다.",
    "input_required_or_invalid": "코드가 요구하는 입력 개수와 입력값 형식을 확인해야 합니다.",
    "timeout": "무한 반복 또는 지나치게 오래 걸리는 연산이 있는지 확인해야 합니다.",
    "output_mismatch": "교재 예상 출력과 실제 출력의 값, 공백 및 줄 구성을 비교해야 합니다.",
    "runtime_error": "traceback의 마지막 예외와 해당 코드의 실행 조건을 확인해야 합니다.",
    "unsupported_package": "요청 패키지가 QA_Platform의 지원 패키지 정책에 포함되는지 확인해야 합니다.",
    "environment_dependent": "GUI, 운영체제 경로 또는 시스템 환경에 의존하는 코드인지 확인해야 합니다.",
    "executor_input_error": "Parser 산출물이 누락되거나 손상되었는지 확인해야 합니다.",
    "incomplete_snippet": "독립 실행용 코드가 아닌 개념 설명용 파편으로 분류되어 실행을 건너뛰었습니다.",
    "error_finding": "오류 찾기 또는 수정 문제로 분류되어 실행을 건너뛰었습니다.",
    "runner_error": "block 작업 파일과 ChapterRunner 내부 처리 중 발생한 예외를 확인해야 합니다.",
}


class ReportInputError(ValueError):
    """저장된 run 산출물이 리포트 입력 계약을 만족하지 않음."""


class ReportBuilder:
    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.clock = clock or (lambda: datetime.now().astimezone())

    def build(self, run_dir: Path) -> ChapterErrorReport:
        manifest = _read_manifest(run_dir)
        entries = _read_result_entries(run_dir)
        results = [
            (entry, _read_indexed_result(run_dir, entry))
            for entry in entries
        ]

        category_counts = Counter(
            result.category
            for _, result in results
            if result.status != STATUS_PASSED and result.category is not None
        )
        summary = ChapterReportSummary(
            total_blocks=len(results),
            passed_blocks=sum(
                result.status == STATUS_PASSED for _, result in results
            ),
            failed_blocks=sum(
                result.status == STATUS_FAILED for _, result in results
            ),
            skipped_blocks=sum(
                result.status == STATUS_SKIPPED for _, result in results
            ),
            category_counts=dict(category_counts),
        )
        errors = [
            _build_report_error(run_dir, entry, result)
            for entry, result in results
            if result.status != STATUS_PASSED
        ]
        report = ChapterErrorReport(
            schema_version=1,
            run_id=manifest.run_id,
            source_blocks_dir=manifest.source_blocks_dir,
            generated_at=_format_report_generated_at(self.clock()),
            summary=summary,
            warnings=manifest.warnings,
            errors=errors,
        )
        write_json(
            run_dir / "chapter_error_report.json",
            report.to_dict(),
        )
        (run_dir / "chapter_error_report.md").write_text(
            _render_markdown(report),
            encoding="utf-8",
        )
        return report


def _format_report_generated_at(report_time: datetime) -> str:
    return report_time.strftime(REPORT_GENERATED_AT_FORMAT)


def _read_manifest(run_dir: Path) -> ChapterRunManifest:
    try:
        return ChapterRunManifest.from_dict(
            read_json(run_dir / "run_manifest.json")
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ReportInputError("Invalid run_manifest.json.") from exc


def _read_result_entries(run_dir: Path) -> list[ResultIndexEntry]:
    results_path = run_dir / "results.jsonl"
    try:
        lines = results_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReportInputError("Missing or unreadable results.jsonl.") from exc

    entries: list[ResultIndexEntry] = []
    seen_block_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        try:
            entry = ResultIndexEntry.from_dict(json.loads(line))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ReportInputError(
                f"Invalid results.jsonl line {line_number}."
            ) from exc
        if entry.block_id in seen_block_ids:
            raise ReportInputError(f"Duplicate block_id: {entry.block_id}.")
        _validate_result_path(run_dir, entry.result_path)
        seen_block_ids.add(entry.block_id)
        entries.append(entry)
    return entries


def _validate_result_path(run_dir: Path, result_path: str) -> None:
    relative_path = Path(result_path)
    if relative_path.is_absolute():
        raise ReportInputError("result_path must be relative to the run directory.")

    run_root = run_dir.resolve()
    resolved_path = (run_dir / relative_path).resolve()
    if not resolved_path.is_relative_to(run_root):
        raise ReportInputError("result_path must stay inside the run directory.")


def _read_indexed_result(
    run_dir: Path,
    entry: ResultIndexEntry,
) -> ExecutionResult:
    result_path = run_dir / entry.result_path
    try:
        result = ExecutionResult.from_dict(read_json(result_path))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ReportInputError(
            f"Missing or invalid result for {entry.block_id}."
        ) from exc

    if (
        result.block_id != entry.block_id
        or result.status != entry.status
        or result.category != entry.category
    ):
        raise ReportInputError(
            f"Result index does not match result.json for {entry.block_id}."
        )
    _validate_result_contract(result)
    return result


def _validate_result_contract(result: ExecutionResult) -> None:
    if result.status not in RESULT_STATUSES:
        raise ReportInputError(
            f"Invalid result status for {result.block_id}: {result.status}."
        )
    if result.status == STATUS_PASSED and result.category is not None:
        raise ReportInputError(
            f"Passed result category must be null for {result.block_id}."
        )
    if result.status == STATUS_FAILED and (
        result.category is None or result.category not in RESULT_CATEGORIES
    ):
        raise ReportInputError(
            f"Invalid failure category for {result.block_id}."
        )
    if result.status == STATUS_SKIPPED and (
        result.category is None or result.category not in RESULT_CATEGORIES
    ):
        raise ReportInputError(
            f"Invalid skipped category for {result.block_id}."
        )


def _build_report_error(
    run_dir: Path,
    entry: ResultIndexEntry,
    result: ExecutionResult,
) -> ChapterReportError:
    category = result.category
    if category is None or category not in RESULT_CATEGORIES:
        raise ReportInputError(
            f"Invalid failure category for {result.block_id}."
        )

    block_dir = (run_dir / entry.result_path).parent
    parse_result = _read_optional_parse_result(block_dir / "block.json")
    spec = (
        parse_result.spec
        if parse_result is not None and parse_result.parse_success
        else None
    )

    return ChapterReportError(
        block_id=result.block_id,
        page=result.meta.get("page"),
        status=result.status,
        category=category,
        review_reason=REVIEW_REASONS[category],
        error_type=result.error_type,
        error_message=result.error_message,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        code=_read_optional_text(block_dir / "normalized.py")
        or (spec.code if spec is not None else ""),
        source_block_text=_read_optional_text(block_dir / "block.txt"),
        stdin=_read_optional_text(block_dir / "stdin.txt")
        or (spec.stdin if spec is not None else ""),
        packages=spec.packages if spec is not None else [],
        expected_output=result.expected_output,
        stdout=result.stdout,
        stderr=result.stderr,
        output_matched=result.output_matched,
        stdout_truncated=result.stdout_truncated,
        stderr_truncated=result.stderr_truncated,
        meta=result.meta,
        result_path=entry.result_path,
    )


def _read_optional_parse_result(path: Path) -> ParseResult | None:
    if not path.exists():
        return None
    try:
        return ParseResult.from_dict(read_json(path))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _read_optional_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _render_markdown(report: ChapterErrorReport) -> str:
    failed_errors, skipped_errors = _partition_errors_by_status(report.errors)
    lines = [
        "# 챕터 오류 리포트",
        "",
        "## 실행 정보",
        "",
        f"- Run ID: `{report.run_id}`",
        f"- 원본 block 디렉터리: `{report.source_blocks_dir}`",
        f"- 리포트 생성 시각: `{report.generated_at}`",
        "",
        "## 실행 요약",
        "",
        "| 항목 | 수 |",
        "| --- | ---: |",
        f"| 전체 block | {report.summary.total_blocks} |",
        f"| 통과 block | {report.summary.passed_blocks} |",
        f"| 실패 block | {report.summary.failed_blocks} |",
        f"| 건너뜀 block | {report.summary.skipped_blocks} |",
        "",
        "## Category별 검토 수",
        "",
    ]

    if report.summary.category_counts:
        failed_counts = _count_error_categories(failed_errors)
        skipped_counts = _count_error_categories(skipped_errors)
        lines.extend(["### 실패 block", ""])
        _append_category_count_table(
            lines,
            failed_counts,
            empty_message="실패 block category가 없습니다.",
        )
        lines.extend(["", "### 건너뜀 block", ""])
        _append_category_count_table(
            lines,
            skipped_counts,
            empty_message="건너뜀 block category가 없습니다.",
        )
    else:
        lines.append("검토 category가 없습니다.")

    lines.extend(["", "## 검토 우선순위", ""])
    _append_review_priority_table(lines, failed_errors, skipped_errors)

    lines.extend(["", "## 입력 경고", ""])
    if report.warnings:
        for warning in report.warnings:
            block_ids = ", ".join(warning.block_ids)
            suffix = f" ({block_ids})" if block_ids else ""
            lines.append(f"- {warning.message}{suffix}")
    else:
        lines.append("입력 경고가 없습니다.")

    lines.extend(["", "## 실패 block 상세", ""])
    _append_error_details(
        lines,
        failed_errors,
        empty_message="실패 block이 없습니다.",
    )
    lines.extend(["", "## 건너뜀 block 상세", ""])
    _append_error_details(
        lines,
        skipped_errors,
        empty_message="건너뜀 block이 없습니다.",
    )

    return "\n".join(lines).rstrip() + "\n"


def _partition_errors_by_status(
    errors: list[ChapterReportError],
) -> tuple[list[ChapterReportError], list[ChapterReportError]]:
    failed_errors = [
        error for error in errors if error.status == STATUS_FAILED
    ]
    skipped_errors = [
        error for error in errors if error.status == STATUS_SKIPPED
    ]
    return failed_errors, skipped_errors


def _count_error_categories(
    errors: list[ChapterReportError],
) -> dict[str, int]:
    return dict(
        Counter(error.category for error in errors)
    )


def _append_category_count_table(
    lines: list[str],
    category_counts: dict[str, int],
    *,
    empty_message: str,
) -> None:
    if not category_counts:
        lines.append(empty_message)
        return

    lines.extend(
        [
            "| Category | 수 |",
            "| --- | ---: |",
            *[
                f"| `{category}` | {count} |"
                for category, count in sorted(category_counts.items())
            ],
        ]
    )


def _append_review_priority_table(
    lines: list[str],
    failed_errors: list[ChapterReportError],
    skipped_errors: list[ChapterReportError],
) -> None:
    lines.extend(["### 실패 block", ""])
    _append_priority_rows(
        lines,
        failed_errors,
        header="| block | 페이지 | Category | 실패 타입 | 실패 메시지 | 결과 파일 |",
        separator="| --- | --- | --- | --- | --- | --- |",
        render_row=_render_failed_priority_row,
        empty_message="실패 block이 없습니다.",
    )
    lines.extend(["", "### 건너뜀 block", ""])
    _append_priority_rows(
        lines,
        skipped_errors,
        header=(
            "| block | 페이지 | Category | 스킵 타입 | 스킵 사유 | "
            "주요 근거 | 결과 파일 |"
        ),
        separator="| --- | --- | --- | --- | --- | --- | --- |",
        render_row=_render_skipped_priority_row,
        empty_message="건너뜀 block이 없습니다.",
    )


def _append_priority_rows(
    lines: list[str],
    errors: list[ChapterReportError],
    *,
    header: str,
    separator: str,
    render_row: Callable[[ChapterReportError], str],
    empty_message: str,
) -> None:
    if not errors:
        lines.append(empty_message)
        return

    lines.extend([header, separator])
    lines.extend(render_row(error) for error in errors)


def _append_error_details(
    lines: list[str],
    errors: list[ChapterReportError],
    *,
    empty_message: str,
) -> None:
    if not errors:
        lines.append(empty_message)
        return

    for error in errors:
        lines.extend(_render_error_markdown(error))


def _render_failed_priority_row(error: ChapterReportError) -> str:
    page = error.page if error.page is not None else "페이지 정보 없음"
    error_type = error.error_type or "정보 없음"
    error_message = _first_non_empty_line(error.error_message)

    return (
        f"| `{_escape_table_cell(error.block_id)}` | "
        f"{_escape_table_cell(page)} | "
        f"`{_escape_table_cell(error.category)}` | "
        f"{_escape_table_cell(error_type)} | "
        f"{_escape_table_cell(error_message)} | "
        f"`{_escape_table_cell(error.result_path)}` |"
    )


def _render_skipped_priority_row(error: ChapterReportError) -> str:
    page = error.page if error.page is not None else "페이지 정보 없음"
    skip_type = error.error_type or "정보 없음"
    skip_reason = _first_non_empty_line(error.error_message)
    skip_evidence = _render_skip_evidence(error)

    return (
        f"| `{_escape_table_cell(error.block_id)}` | "
        f"{_escape_table_cell(page)} | "
        f"`{_escape_table_cell(error.category)}` | "
        f"{_escape_table_cell(skip_type)} | "
        f"{_escape_table_cell(skip_reason)} | "
        f"{_escape_table_cell(skip_evidence)} | "
        f"`{_escape_table_cell(error.result_path)}` |"
    )


def _render_skip_evidence(error: ChapterReportError) -> str:
    for key in (
        "missing_required_files",
        "environment_modules",
        "code_type",
        "run_skip_reason",
    ):
        value = error.meta.get(key)
        if value:
            return f"{key}={value}"
    return "정보 없음"


def _first_non_empty_line(value: str | None) -> str:
    if value is None:
        return "정보 없음"

    for line in value.splitlines():
        stripped_line = line.strip()
        if stripped_line:
            return stripped_line
    return "정보 없음"


def _render_error_markdown(error: ChapterReportError) -> list[str]:
    page = error.page if error.page is not None else "페이지 정보 없음"
    error_type = error.error_type or "정보 없음"
    error_message = error.error_message or "정보 없음"
    exit_code = str(error.exit_code) if error.exit_code is not None else "없음"
    setup_code = _extract_source_section(error.source_block_text, "SETUP")
    type_label = _result_type_label(error.status)
    message_label = _result_message_label(error.status)

    lines = [
        f"### `{error.block_id}`",
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| 페이지 | {_escape_table_cell(page)} |",
        f"| 상태 | `{_escape_table_cell(error.status)}` |",
        f"| Category | `{error.category}` |",
        f"| 결과 파일 | `{_escape_table_cell(error.result_path)}` |",
        f"| {type_label} | {_escape_table_cell(error_type)} |",
        f"| {message_label} | {_escape_table_cell(error_message)} |",
        *_render_skip_evidence_rows(error),
        f"| Exit code | {exit_code} |",
        f"| 실행 시간(ms) | {error.duration_ms} |",
        f"| stdout 잘림 | {_yes_no(error.stdout_truncated)} |",
        f"| stderr 잘림 | {_yes_no(error.stderr_truncated)} |",
        "",
        f"**확인 안내:** {error.review_reason}",
        "",
        "#### Meta",
        "",
        *_render_meta_markdown(error.meta),
        "",
        "#### 코드",
        "",
        _fenced_block(error.code, "python"),
        "",
    ]

    if setup_code.strip():
        lines.extend(
            [
                "#### Setup 코드",
                "",
                _fenced_block(setup_code, "python"),
                "",
            ]
        )

    lines.extend(
        [
            "#### 원본 block",
            "",
            _fenced_block(error.source_block_text, "text"),
            "",
            "#### 입력",
            "",
            _fenced_block(error.stdin, "text"),
            "",
            "#### Packages",
            "",
        ]
    )

    if error.packages:
        lines.extend(f"- `{package.raw}`" for package in error.packages)
    else:
        lines.append("필요한 package가 없습니다.")

    lines.extend(
        [
            "",
            "#### 예상 출력",
            "",
            _fenced_block(error.expected_output or "", "text"),
            "",
            "#### 실제 stdout",
            "",
            _fenced_block(error.stdout, "text"),
            "",
        ]
    )

    if error.category == "output_mismatch":
        lines.extend(
            [
                "#### 출력 diff",
                "",
                _fenced_block(
                    _build_output_diff(error.expected_output, error.stdout),
                    "diff",
                ),
                "",
            ]
        )

    lines.extend(
        [
            "#### stderr / traceback",
            "",
            _fenced_block(error.stderr, "text"),
            "",
        ]
    )
    return lines


def _escape_table_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", "<br>")


def _yes_no(value: bool) -> str:
    return "예" if value else "아니오"


def _render_meta_markdown(meta: dict[str, str]) -> list[str]:
    if not meta:
        return ["meta가 없습니다."]

    return [
        "| Key | Value |",
        "| --- | --- |",
        *[
            f"| `{_escape_table_cell(key)}` | {_escape_table_cell(value)} |"
            for key, value in sorted(meta.items())
        ],
    ]


def _build_output_diff(expected_output: str | None, stdout: str) -> str:
    diff = "".join(
        _format_diff_line(line)
        for line in difflib.unified_diff(
            _split_diff_lines(expected_output or ""),
            _split_diff_lines(stdout),
            fromfile="expected",
            tofile="stdout",
        )
    )
    return diff or "출력 차이가 없습니다.\n"


def _format_diff_line(line: str) -> str:
    if line.endswith("\n"):
        return line

    formatted_line = f"{line}\n"
    if _is_diff_body_line(line):
        formatted_line += "\\ No newline at end of file\n"
    return formatted_line


def _is_diff_body_line(line: str) -> bool:
    return bool(line) and line[0] in {" ", "+", "-"}


def _split_diff_lines(value: str) -> list[str]:
    return value.splitlines(keepends=True)


def _result_type_label(status: str) -> str:
    return "스킵 타입" if status == STATUS_SKIPPED else "실패 타입"


def _result_message_label(status: str) -> str:
    return "스킵 사유" if status == STATUS_SKIPPED else "실패 메시지"


def _render_skip_evidence_rows(error: ChapterReportError) -> list[str]:
    if error.status != STATUS_SKIPPED:
        return []

    return [f"| 주요 근거 | {_escape_table_cell(_render_skip_evidence(error))} |"]


def _fenced_block(content: str, language: str) -> str:
    longest_backticks = max(
        (len(match.group(0)) for match in re.finditer(r"`+", content)),
        default=0,
    )
    fence = "`" * max(3, longest_backticks + 1)
    normalized_content = content
    if normalized_content and not normalized_content.endswith("\n"):
        normalized_content += "\n"
    return f"{fence}{language}\n{normalized_content}{fence}"


def _extract_source_section(source_block_text: str, section: str) -> str:
    match = re.search(
        rf"\[{section}\]\n(.*?)(?=\n\[|$)",
        source_block_text,
        re.DOTALL,
    )
    return match.group(1).strip() if match else ""
