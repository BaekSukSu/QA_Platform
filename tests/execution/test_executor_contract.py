import pytest

from qa_platform.contract.constants import (
    CATEGORY_INCOMPLETE_SNIPPET,
    CATEGORY_EXECUTOR_INPUT_ERROR,
    CATEGORY_INPUT_REQUIRED_OR_INVALID,
    CATEGORY_NAME_ERROR,
    CATEGORY_OUTPUT_MISMATCH,
    CATEGORY_PARSE_ERROR,
    CATEGORY_TIMEOUT,
    CODE_TYPE_INCOMPLETE_SNIPPET,
    PARSER_ERROR_EMPTY_CODE,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
)
from qa_platform.execution.docker import DockerBlockExecutor
from qa_platform.execution.docker_runtime import DockerExecutorConfig
from qa_platform.execution.support import ProcessOutcome
from qa_platform.contract.models import (
    BlockSpec,
    ParseError,
    ParseResult,
)
from qa_platform.shared.json_io import (
    read_json,
    write_json,
)


class ContractDockerRuntime:
    def __init__(self, outcome: ProcessOutcome | None = None) -> None:
        self.outcome = outcome

    def ensure_ready(self, config: DockerExecutorConfig) -> None:
        return None

    def run(self, **kwargs: object) -> ProcessOutcome:
        if self.outcome is None:
            raise AssertionError("Docker runtime must not be called.")
        return self.outcome


def make_executor(
    *,
    outcome: ProcessOutcome | None = None,
    output_limit_chars: int = 20_000,
):
    return DockerBlockExecutor(
        config=DockerExecutorConfig(output_limit_chars=output_limit_chars),
        runtime=ContractDockerRuntime(outcome),
    )


def write_successful_execution_files(
    block_dir,
    *,
    code: str,
    stdin: str = "",
    expected_output: str = "",
    meta: dict[str, str] | None = None,
) -> None:
    block_dir.mkdir()
    parse_result = ParseResult(
        parse_success=True,
        block_id=block_dir.name,
        spec=BlockSpec(
            code=code,
            stdin=stdin,
            expected_output=expected_output,
            meta=meta or {},
        ),
    )
    write_json(block_dir / "block.json", parse_result.to_dict())
    (block_dir / "normalized.py").write_text(code, encoding="utf-8")
    (block_dir / "stdin.txt").write_text(stdin, encoding="utf-8")


def assert_result_was_saved(block_dir, result) -> None:
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_executor_contract_parse_error(tmp_path) -> None:
    block_dir = tmp_path / "block_001"
    block_dir.mkdir()
    write_json(
        block_dir / "block.json",
        ParseResult(
            parse_success=False,
            block_id="block_001",
            error=ParseError(
                error_type=PARSER_ERROR_EMPTY_CODE,
                message="[CODE] section is empty.",
            ),
        ).to_dict(),
    )

    result = make_executor().execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_PARSE_ERROR
    assert result.error_type == PARSER_ERROR_EMPTY_CODE
    assert_result_was_saved(block_dir, result)


@pytest.mark.parametrize(
    "missing_file",
    ["block.json", "normalized.py", "stdin.txt"],
)
def test_executor_contract_missing_input(
    missing_file,
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_002"
    if missing_file == "block.json":
        block_dir.mkdir()
    else:
        write_successful_execution_files(
            block_dir,
            code="print('hello')\n",
            expected_output="hello\n",
        )
        (block_dir / missing_file).unlink()

    result = make_executor().execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_EXECUTOR_INPUT_ERROR
    assert missing_file in result.error_message
    assert_result_was_saved(block_dir, result)


def test_executor_contract_matching_output(tmp_path) -> None:
    block_dir = tmp_path / "block_003"
    write_successful_execution_files(
        block_dir,
        code="name = input()\nprint(f'hello {name}')\n",
        stdin="Ada\n",
        expected_output="hello Ada\n",
        meta={"page": "20"},
    )
    outcome = ProcessOutcome(
        exit_code=0,
        duration_ms=11,
        stdout="hello Ada\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.exit_code == 0
    assert result.stdout == "hello Ada\n"
    assert result.output_matched is True
    assert result.meta == {
        "page": "20",
        "execution_mode": "script",
        "execution_strategy": "script_normalized",
    }
    assert_result_was_saved(block_dir, result)


def test_executor_contract_empty_expected_output(tmp_path) -> None:
    block_dir = tmp_path / "block_004"
    write_successful_execution_files(
        block_dir,
        code="print('reference output')\n",
        expected_output="",
    )
    outcome = ProcessOutcome(
        exit_code=0,
        duration_ms=4,
        stdout="reference output\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.output_matched is None
    assert_result_was_saved(block_dir, result)


def test_executor_contract_output_mismatch(tmp_path) -> None:
    block_dir = tmp_path / "block_005"
    write_successful_execution_files(
        block_dir,
        code="print('actual')\n",
        expected_output="expected\n",
    )
    outcome = ProcessOutcome(
        exit_code=0,
        duration_ms=5,
        stdout="actual\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_OUTPUT_MISMATCH
    assert result.output_matched is False
    assert_result_was_saved(block_dir, result)


def test_executor_contract_name_error(tmp_path) -> None:
    block_dir = tmp_path / "block_006"
    write_successful_execution_files(
        block_dir,
        code="print(missing_name)\n",
    )
    stderr = (
        "Traceback (most recent call last):\n"
        "NameError: name 'missing_name' is not defined\n"
    )
    outcome = ProcessOutcome(
        exit_code=1,
        duration_ms=6,
        stdout="",
        stderr=stderr,
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_NAME_ERROR
    assert result.error_type == "NameError"
    assert_result_was_saved(block_dir, result)


def test_executor_contract_timeout(tmp_path) -> None:
    block_dir = tmp_path / "block_007"
    write_successful_execution_files(
        block_dir,
        code="while True:\n    pass\n",
    )
    outcome = ProcessOutcome(
        exit_code=None,
        duration_ms=50,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=True,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_TIMEOUT
    assert result.exit_code is None
    assert result.error_type == "TimeoutError"
    assert_result_was_saved(block_dir, result)


def test_executor_contract_output_truncation(tmp_path) -> None:
    block_dir = tmp_path / "block_008"
    write_successful_execution_files(
        block_dir,
        code=(
            "import sys\n"
            "print('x' * 25, end='')\n"
            "sys.stderr.write('y' * 25)\n"
        ),
    )
    outcome = ProcessOutcome(
        exit_code=0,
        duration_ms=3,
        stdout="x" * 10,
        stderr="y" * 10,
        stdout_truncated=True,
        stderr_truncated=True,
        timed_out=False,
    )

    result = make_executor(
        outcome=outcome,
        output_limit_chars=10,
    ).execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.stdout == "x" * 10
    assert result.stderr == "y" * 10
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert_result_was_saved(block_dir, result)


def test_executor_contract_nondeterministic_output_mismatch_is_skipped(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_009"
    write_successful_execution_files(
        block_dir,
        code="print('actual')\n",
        expected_output="expected\n",
        meta={"output_determinism": "nondeterministic"},
    )
    outcome = ProcessOutcome(
        exit_code=0,
        duration_ms=5,
        stdout="actual\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.output_matched is None
    assert result.expected_output == "expected\n"
    assert_result_was_saved(block_dir, result)


def test_executor_contract_accepts_configured_stdin_exhaustion(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_010"
    write_successful_execution_files(
        block_dir,
        code=(
            "value = input()\n"
            "while value != 'stop':\n"
            "    print(value)\n"
            "    value = input()\n"
        ),
        stdin="one\n",
        expected_output="finished\n",
        meta={"stdin_exhaustion": "accept"},
    )
    outcome = ProcessOutcome(
        exit_code=1,
        duration_ms=5,
        stdout="one\n",
        stderr=(
            "Traceback (most recent call last):\n"
            "EOFError: EOF when reading a line\n"
        ),
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.exit_code == 1
    assert result.error_type == "EOFError"
    assert result.error_message == "EOF when reading a line"
    assert result.output_matched is None
    assert_result_was_saved(block_dir, result)


def test_executor_contract_denies_stdin_exhaustion_by_default(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_011"
    write_successful_execution_files(
        block_dir,
        code="input()\ninput()\n",
        stdin="one\n",
        meta={"output_determinism": "nondeterministic"},
    )
    outcome = ProcessOutcome(
        exit_code=1,
        duration_ms=5,
        stdout="",
        stderr="EOFError: EOF when reading a line\n",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_INPUT_REQUIRED_OR_INVALID
    assert result.error_type == "EOFError"
    assert_result_was_saved(block_dir, result)


def test_executor_contract_nondeterministic_name_error_still_fails(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_012"
    write_successful_execution_files(
        block_dir,
        code="print(missing_name)\n",
        meta={"output_determinism": "nondeterministic"},
    )
    outcome = ProcessOutcome(
        exit_code=1,
        duration_ms=5,
        stdout="",
        stderr="NameError: name 'missing_name' is not defined\n",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_NAME_ERROR
    assert_result_was_saved(block_dir, result)


def test_executor_contract_nondeterministic_timeout_still_fails(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_013"
    write_successful_execution_files(
        block_dir,
        code="while True:\n    pass\n",
        meta={"output_determinism": "nondeterministic"},
    )
    outcome = ProcessOutcome(
        exit_code=None,
        duration_ms=50,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=True,
    )

    result = make_executor(outcome=outcome).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_TIMEOUT
    assert_result_was_saved(block_dir, result)


def test_executor_contract_incomplete_snippet_is_skipped(tmp_path) -> None:
    block_dir = tmp_path / "block_014"
    meta = {"code_type": CODE_TYPE_INCOMPLETE_SNIPPET, "page": "21"}
    write_successful_execution_files(
        block_dir,
        code="print('partial')\n",
        expected_output="partial\n",
        meta=meta,
    )

    result = make_executor().execute(block_dir)

    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_INCOMPLETE_SNIPPET
    assert result.error_type == "SkippedByCodeType"
    assert result.meta == meta
    assert_result_was_saved(block_dir, result)
