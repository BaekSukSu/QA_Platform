from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from qa_platform.contract.constants import (
    CATEGORY_ERROR_FINDING,
    CATEGORY_ENVIRONMENT_DEPENDENT,
    CATEGORY_EXECUTOR_INPUT_ERROR,
    CATEGORY_INCOMPLETE_SNIPPET,
    CATEGORY_INPUT_REQUIRED_OR_INVALID,
    CATEGORY_MISSING_REQUIRED_FILE,
    CATEGORY_OUTPUT_MISMATCH,
    CATEGORY_PARSE_ERROR,
    CATEGORY_TIMEOUT,
    CODE_TYPE_ERROR_FINDING,
    CODE_TYPE_INCOMPLETE_SNIPPET,
    DEFAULT_META_CODE_TYPE,
    DEFAULT_META_OUTPUT_DETERMINISM,
    DEFAULT_META_STDIN_EXHAUSTION,
    LEGACY_META_MODE_KEY,
    META_CODE_TYPE_KEY,
    META_OUTPUT_DETERMINISM_KEY,
    META_STDIN_EXHAUSTION_KEY,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
)
from qa_platform.contract.models import (
    ExecutionResult,
    ParseResult,
)
from qa_platform.contract.source_skip_classifier import (
    META_ENVIRONMENT_MODULES_KEY,
    META_MISSING_REQUIRED_FILES_KEY,
    META_RUN_SKIP_REASON_KEY,
    RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT,
    RUN_SKIP_REASON_MISSING_REQUIRED_FILE,
    detect_external_file_reads,
)
from qa_platform.shared.json_io import (
    read_json,
    write_json,
)
from qa_platform.execution.output_comparator import OutputComparator
from qa_platform.execution.result_classifier import ResultClassifier


STDIN_EXHAUSTION_ERROR_MESSAGE = "EOF when reading a line"
EXPECTED_ERROR_PATTERN = re.compile(
    r"(?P<type>[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)):\s*(?P<message>.+)"
)
SKIPPED_CODE_TYPE_CATEGORIES = {
    CODE_TYPE_INCOMPLETE_SNIPPET: CATEGORY_INCOMPLETE_SNIPPET,
    CODE_TYPE_ERROR_FINDING: CATEGORY_ERROR_FINDING,
}


@dataclass(frozen=True)
class ExecutionContext:
    parse_result: ParseResult
    stdin: str


@dataclass(frozen=True)
class ProcessOutcome:
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool


def build_executable_source(setup_code: str, code: str) -> str:
    parts = [
        part.rstrip()
        for part in (setup_code, code)
        if part.strip()
    ]
    return "\n\n".join(parts) + "\n"


def load_execution_context(
    block_dir: Path,
) -> tuple[ExecutionContext | None, ExecutionResult | None]:
    try:
        parse_result = ParseResult.from_dict(
            read_json(block_dir / "block.json")
        )
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return None, _build_input_error_result(
            block_id=block_dir.name,
            input_name="block.json",
            exc=exc,
            expected_output=None,
            meta={},
        )

    if not parse_result.parse_success:
        return None, _build_parse_error_result(parse_result)

    spec = parse_result.spec
    if spec is None:
        exc = ValueError("parse_success=true requires a spec.")
        return None, _build_input_error_result(
            block_id=parse_result.block_id,
            input_name="block.json",
            exc=exc,
            expected_output=None,
            meta={},
        )

    normalized_path = block_dir / "normalized.py"
    if not normalized_path.is_file():
        exc = FileNotFoundError("normalized.py")
        return None, _build_input_error_result(
            block_id=parse_result.block_id,
            input_name="normalized.py",
            exc=exc,
            expected_output=spec.expected_output,
            meta=spec.meta,
        )

    try:
        stdin = (block_dir / "stdin.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, _build_input_error_result(
            block_id=parse_result.block_id,
            input_name="stdin.txt",
            exc=exc,
            expected_output=spec.expected_output,
            meta=spec.meta,
        )

    return ExecutionContext(parse_result=parse_result, stdin=stdin), None


def build_execution_result(
    parse_result: ParseResult,
    outcome: ProcessOutcome,
    *,
    meta: dict[str, str] | None = None,
) -> ExecutionResult:
    spec = parse_result.spec
    if not parse_result.parse_success or spec is None:
        raise ValueError("A successful parse result with spec is required.")

    result_meta = spec.meta if meta is None else meta

    if outcome.timed_out:
        category, error_type, error_message = ResultClassifier.classify(
            exit_code=None,
            stderr=outcome.stderr,
            timed_out=True,
        )
        return ExecutionResult(
            block_id=parse_result.block_id,
            status=STATUS_FAILED,
            category=category or CATEGORY_TIMEOUT,
            exit_code=None,
            duration_ms=outcome.duration_ms,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
            error_type=error_type,
            error_message=error_message,
            expected_output=spec.expected_output,
            output_matched=None,
            meta=result_meta,
        )

    if outcome.exit_code == 0:
        if _output_determinism(result_meta) == "nondeterministic":
            output_matched = None
        else:
            output_matched = OutputComparator.compare(
                spec.expected_output,
                outcome.stdout,
                code=build_executable_source(spec.setup_code, spec.code),
                stdin=spec.stdin,
                packages=tuple(package.name for package in spec.packages),
            )
        status = STATUS_FAILED if output_matched is False else STATUS_PASSED
        category = (
            CATEGORY_OUTPUT_MISMATCH
            if output_matched is False
            else None
        )
        return ExecutionResult(
            block_id=parse_result.block_id,
            status=status,
            category=category,
            exit_code=0,
            duration_ms=outcome.duration_ms,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
            error_type=None,
            error_message=None,
            expected_output=spec.expected_output,
            output_matched=output_matched,
            meta=result_meta,
        )

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=outcome.exit_code,
        stderr=outcome.stderr,
        timed_out=False,
    )
    if _runtime_error_matches_expected(
        expected_output=spec.expected_output,
        error_type=error_type,
        error_message=error_message,
    ):
        return ExecutionResult(
            block_id=parse_result.block_id,
            status=STATUS_PASSED,
            category=None,
            exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
            error_type=error_type,
            error_message=error_message,
            expected_output=spec.expected_output,
            output_matched=True,
            meta=result_meta,
        )
    if (
        result_meta.get(
            META_STDIN_EXHAUSTION_KEY,
            DEFAULT_META_STDIN_EXHAUSTION,
        )
        == "accept"
        and category == CATEGORY_INPUT_REQUIRED_OR_INVALID
        and error_type == "EOFError"
        and error_message == STDIN_EXHAUSTION_ERROR_MESSAGE
    ):
        return ExecutionResult(
            block_id=parse_result.block_id,
            status=STATUS_PASSED,
            category=None,
            exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
            error_type=error_type,
            error_message=error_message,
            expected_output=spec.expected_output,
            output_matched=None,
            meta=result_meta,
        )
    return ExecutionResult(
        block_id=parse_result.block_id,
        status=STATUS_FAILED,
        category=category,
        exit_code=outcome.exit_code,
        duration_ms=outcome.duration_ms,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        stdout_truncated=outcome.stdout_truncated,
        stderr_truncated=outcome.stderr_truncated,
        error_type=error_type,
        error_message=error_message,
        expected_output=spec.expected_output,
        output_matched=None,
        meta=result_meta,
    )


def build_executor_failure_result(
    parse_result: ParseResult,
    *,
    category: str,
    error_type: str,
    error_message: str,
) -> ExecutionResult:
    spec = parse_result.spec
    expected_output = spec.expected_output if spec is not None else None
    meta = spec.meta if spec is not None else {}
    return ExecutionResult(
        block_id=parse_result.block_id,
        status=STATUS_FAILED,
        category=category,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=error_type,
        error_message=error_message,
        expected_output=expected_output,
        output_matched=None,
        meta=meta,
    )


def build_code_type_skip_result(
    parse_result: ParseResult,
) -> ExecutionResult | None:
    spec = parse_result.spec
    if spec is None:
        return None

    code_type = spec.meta.get(META_CODE_TYPE_KEY, DEFAULT_META_CODE_TYPE)
    category = SKIPPED_CODE_TYPE_CATEGORIES.get(code_type)
    if category is None:
        return None

    return ExecutionResult(
        block_id=parse_result.block_id,
        status=STATUS_SKIPPED,
        category=category,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="SkippedByCodeType",
        error_message=(
            f"Block execution skipped because code_type={code_type}."
        ),
        expected_output=spec.expected_output,
        output_matched=None,
        meta=spec.meta,
    )


def build_missing_required_file_skip_result(
    parse_result: ParseResult,
) -> ExecutionResult | None:
    spec = parse_result.spec
    if not parse_result.parse_success or spec is None:
        return None

    preclassified_file_list = spec.meta.get(META_MISSING_REQUIRED_FILES_KEY)
    if (
        spec.meta.get(META_RUN_SKIP_REASON_KEY)
        == RUN_SKIP_REASON_MISSING_REQUIRED_FILE
        and preclassified_file_list
    ):
        file_list = preclassified_file_list
    else:
        missing_required_files = detect_external_file_reads(
            setup_code=spec.setup_code,
            code=spec.code,
            stdin=spec.stdin,
        )
        if not missing_required_files:
            return None
        file_list = ", ".join(missing_required_files)

    return ExecutionResult(
        block_id=parse_result.block_id,
        status=STATUS_SKIPPED,
        category=CATEGORY_MISSING_REQUIRED_FILE,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="MissingRequiredFileSkipped",
        error_message=(
            "Block execution skipped because it reads external files "
            f"not provided by QA fixtures: {file_list}."
        ),
        expected_output=spec.expected_output,
        output_matched=None,
        meta={**spec.meta, META_MISSING_REQUIRED_FILES_KEY: file_list},
    )


def build_environment_module_skip_result(
    parse_result: ParseResult,
    environment_modules: tuple[str, ...],
) -> ExecutionResult | None:
    spec = parse_result.spec
    if spec is None:
        return None

    if environment_modules:
        module_list = ",".join(environment_modules)
    elif (
        spec.meta.get(META_RUN_SKIP_REASON_KEY)
        == RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT
        and spec.meta.get(META_ENVIRONMENT_MODULES_KEY)
    ):
        module_list = spec.meta[META_ENVIRONMENT_MODULES_KEY]
    else:
        return None

    meta = {**spec.meta, META_ENVIRONMENT_MODULES_KEY: module_list}
    return ExecutionResult(
        block_id=parse_result.block_id,
        status=STATUS_SKIPPED,
        category=CATEGORY_ENVIRONMENT_DEPENDENT,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type="EnvironmentModuleSkipped",
        error_message=(
            "Block execution skipped because it requires GUI/environment "
            f"modules: {module_list}."
        ),
        expected_output=spec.expected_output,
        output_matched=None,
        meta=meta,
    )


def _output_determinism(meta: dict[str, str]) -> str:
    return meta.get(
        META_OUTPUT_DETERMINISM_KEY,
        meta.get(LEGACY_META_MODE_KEY, DEFAULT_META_OUTPUT_DETERMINISM),
    )


def _expected_runtime_error(expected_output: str) -> tuple[str, str] | None:
    for line in reversed(expected_output.splitlines()):
        match = EXPECTED_ERROR_PATTERN.search(line.strip())
        if match is not None:
            return match.group("type"), match.group("message")
    return None


def _runtime_error_matches_expected(
    *,
    expected_output: str,
    error_type: str | None,
    error_message: str | None,
) -> bool:
    expected = _expected_runtime_error(expected_output)
    if expected is None or error_type is None or error_message is None:
        return False
    expected_type, expected_message = expected
    if error_type != expected_type:
        return False
    return _normalize_expected_error_message(
        expected_type,
        expected_message,
    ) == _normalize_expected_error_message(error_type, error_message)


def _normalize_expected_error_message(error_type: str, message: str) -> str:
    normalized = _normalize_error_quotes(message).strip()
    if error_type == "SyntaxError":
        normalized = re.sub(
            r"\s+\(detected at line \d+\)$",
            "",
            normalized,
        )
        normalized = normalized.split(".", maxsplit=1)[0].strip()
        if normalized == "EOL while scanning string literal":
            return "unterminated string literal"
    return normalized.strip()


def _normalize_error_quotes(message: str) -> str:
    return (
        message.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )


def write_execution_result(
    block_dir: Path,
    result: ExecutionResult,
) -> ExecutionResult:
    write_json(block_dir / "result.json", result.to_dict())
    return result


def truncate_output(output: str, limit_chars: int) -> tuple[str, bool]:
    if len(output) <= limit_chars:
        return output, False
    return output[:limit_chars], True


def coerce_process_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _build_parse_error_result(
    parse_result: ParseResult,
) -> ExecutionResult:
    error_type = parse_result.error.error_type if parse_result.error else None
    error_message = parse_result.error.message if parse_result.error else None
    return ExecutionResult(
        block_id=parse_result.block_id,
        status=STATUS_FAILED,
        category=CATEGORY_PARSE_ERROR,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=error_type,
        error_message=error_message,
        expected_output=None,
        output_matched=None,
        meta={},
    )


def _build_input_error_result(
    *,
    block_id: str,
    input_name: str,
    exc: Exception,
    expected_output: str | None,
    meta: dict[str, str],
) -> ExecutionResult:
    return ExecutionResult(
        block_id=block_id,
        status=STATUS_FAILED,
        category=CATEGORY_EXECUTOR_INPUT_ERROR,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=exc.__class__.__name__,
        error_message=f"Missing or unreadable executor input: {input_name}",
        expected_output=expected_output,
        output_matched=None,
        meta=meta,
    )
