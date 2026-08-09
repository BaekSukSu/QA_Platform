from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qa_platform.contract.models import PackageSpec


@dataclass(frozen=True)
class ChapterRunWarning:
    warning_type: str
    message: str
    block_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "warning_type": self.warning_type,
            "message": self.message,
            "block_ids": self.block_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChapterRunWarning:
        return cls(
            warning_type=str(data["warning_type"]),
            message=str(data["message"]),
            block_ids=[str(block_id) for block_id in data.get("block_ids", [])],
        )


@dataclass(frozen=True)
class ResultIndexEntry:
    block_id: str
    status: str
    category: str | None
    result_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "status": self.status,
            "category": self.category,
            "result_path": self.result_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResultIndexEntry:
        return cls(
            block_id=str(data["block_id"]),
            status=str(data["status"]),
            category=data.get("category"),
            result_path=str(data["result_path"]),
        )


@dataclass(frozen=True)
class ChapterRunManifest:
    schema_version: int
    run_id: str
    source_blocks_dir: str
    started_at: str
    completed_at: str | None
    status: str
    total_blocks: int
    processed_blocks: int
    passed_blocks: int
    failed_blocks: int
    skipped_blocks: int = 0
    warnings: list[ChapterRunWarning] = field(default_factory=list)
    run_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "source_blocks_dir": self.source_blocks_dir,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "total_blocks": self.total_blocks,
            "processed_blocks": self.processed_blocks,
            "passed_blocks": self.passed_blocks,
            "failed_blocks": self.failed_blocks,
            "skipped_blocks": self.skipped_blocks,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "run_error": self.run_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChapterRunManifest:
        return cls(
            schema_version=int(data["schema_version"]),
            run_id=str(data["run_id"]),
            source_blocks_dir=str(data["source_blocks_dir"]),
            started_at=str(data["started_at"]),
            completed_at=data.get("completed_at"),
            status=str(data["status"]),
            total_blocks=int(data["total_blocks"]),
            processed_blocks=int(data["processed_blocks"]),
            passed_blocks=int(data["passed_blocks"]),
            failed_blocks=int(data["failed_blocks"]),
            skipped_blocks=int(data.get("skipped_blocks", 0)),
            warnings=[
                ChapterRunWarning.from_dict(warning)
                for warning in data.get("warnings", [])
            ],
            run_error=data.get("run_error"),
        )


@dataclass(frozen=True)
class ChapterRunResult:
    run_id: str
    run_dir: Path
    total_blocks: int
    passed_blocks: int
    failed_blocks: int
    report_json_path: Path
    report_markdown_path: Path
    skipped_blocks: int = 0


@dataclass(frozen=True)
class ChapterReportSummary:
    total_blocks: int
    passed_blocks: int
    failed_blocks: int
    skipped_blocks: int = 0
    category_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_blocks": self.total_blocks,
            "passed_blocks": self.passed_blocks,
            "failed_blocks": self.failed_blocks,
            "skipped_blocks": self.skipped_blocks,
            "category_counts": {
                category: self.category_counts[category]
                for category in sorted(self.category_counts)
            },
        }


@dataclass(frozen=True)
class ChapterReportError:
    block_id: str
    page: str | None
    status: str
    category: str
    review_reason: str
    error_type: str | None
    error_message: str | None
    exit_code: int | None
    duration_ms: int
    code: str
    source_block_text: str
    stdin: str
    packages: list[PackageSpec]
    expected_output: str | None
    stdout: str
    stderr: str
    output_matched: bool | None
    stdout_truncated: bool
    stderr_truncated: bool
    meta: dict[str, str]
    result_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page": self.page,
            "status": self.status,
            "category": self.category,
            "review_reason": self.review_reason,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "code": self.code,
            "source_block_text": self.source_block_text,
            "stdin": self.stdin,
            "packages": [package.to_dict() for package in self.packages],
            "expected_output": self.expected_output,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "output_matched": self.output_matched,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "meta": self.meta,
            "result_path": self.result_path,
        }


@dataclass(frozen=True)
class ChapterErrorReport:
    schema_version: int
    run_id: str
    source_blocks_dir: str
    generated_at: str
    summary: ChapterReportSummary
    warnings: list[ChapterRunWarning]
    errors: list[ChapterReportError]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "source_blocks_dir": self.source_blocks_dir,
            "generated_at": self.generated_at,
            "summary": self.summary.to_dict(),
            "warnings": [warning.to_dict() for warning in self.warnings],
            "errors": [error.to_dict() for error in self.errors],
        }
