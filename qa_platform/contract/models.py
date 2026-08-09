from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qa_platform.shared.json_io import read_json, write_json


@dataclass(frozen=True)
class PackageSpec:
    name: str
    specifier: str
    raw: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "specifier": self.specifier,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PackageSpec:
        return cls(
            name=str(data["name"]),
            specifier=str(data.get("specifier", "")),
            raw=str(data["raw"]),
        )


@dataclass(frozen=True)
class ParseError:
    error_type: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.error_type,
            "message": self.message,
            "line": self.line,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParseError:
        return cls(
            error_type=str(data["type"]),
            message=str(data["message"]),
            line=data.get("line"),
        )


@dataclass(frozen=True)
class BlockSpec:
    code: str
    stdin: str
    packages: list[PackageSpec] = field(default_factory=list)
    expected_output: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    setup_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stdin": self.stdin,
            "packages": [package.to_dict() for package in self.packages],
            "expected_output": self.expected_output,
            "meta": self.meta,
            "setup_code": self.setup_code,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlockSpec:
        return cls(
            code=str(data["code"]),
            stdin=str(data.get("stdin", "")),
            packages=[
                PackageSpec.from_dict(package)
                for package in data.get("packages", [])
            ],
            expected_output=str(data.get("expected_output", "")),
            meta={
                str(key): str(value)
                for key, value in data.get("meta", {}).items()
            },
            setup_code=str(data.get("setup_code", "")),
        )


@dataclass(frozen=True)
class ParseResult:
    parse_success: bool
    block_id: str
    spec: BlockSpec | None = None
    error: ParseError | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "parse_success": self.parse_success,
            "block_id": self.block_id,
        }
        if self.parse_success:
            data["spec"] = self.spec.to_dict() if self.spec else None
        else:
            data["error"] = self.error.to_dict() if self.error else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParseResult:
        parse_success = bool(data["parse_success"])
        return cls(
            parse_success=parse_success,
            block_id=str(data["block_id"]),
            spec=(
                BlockSpec.from_dict(data["spec"])
                if parse_success and data.get("spec") is not None
                else None
            ),
            error=(
                ParseError.from_dict(data["error"])
                if not parse_success and data.get("error") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ExecutionResult:
    block_id: str
    status: str
    category: str | None
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    error_type: str | None
    error_message: str | None
    expected_output: str | None
    output_matched: bool | None
    meta: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "status": self.status,
            "category": self.category,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "expected_output": self.expected_output,
            "output_matched": self.output_matched,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResult:
        return cls(
            block_id=str(data["block_id"]),
            status=str(data["status"]),
            category=data.get("category"),
            exit_code=data.get("exit_code"),
            duration_ms=int(data["duration_ms"]),
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
            stdout_truncated=bool(data.get("stdout_truncated", False)),
            stderr_truncated=bool(data.get("stderr_truncated", False)),
            error_type=data.get("error_type"),
            error_message=data.get("error_message"),
            expected_output=data.get("expected_output"),
            output_matched=data.get("output_matched"),
            meta={
                str(key): str(value)
                for key, value in data.get("meta", {}).items()
            },
        )
