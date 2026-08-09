import pytest

from qa_platform.contract.constants import (
    CATEGORY_ERROR_FINDING,
    CATEGORY_ENVIRONMENT_DEPENDENT,
    CATEGORY_EXECUTOR_INPUT_ERROR,
    CATEGORY_MISSING_REQUIRED_FILE,
    CATEGORY_NAME_ERROR,
    CATEGORY_OUTPUT_MISMATCH,
    CATEGORY_PARSE_ERROR,
    CATEGORY_TIMEOUT,
    CATEGORY_UNSUPPORTED_PACKAGE,
    PARSER_ERROR_EMPTY_CODE,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
)
from qa_platform.execution.docker import DockerBlockExecutor
from qa_platform.execution.docker_runtime import (
    DockerCleanupError,
    DockerCliUnavailableError,
    DockerDaemonUnavailableError,
    DockerExecutorConfig,
    DockerImageBuildError,
    DockerImageUnavailableError,
    DockerLifecycleError,
)
from qa_platform.execution.support import ProcessOutcome
from qa_platform.contract.models import (
    BlockSpec,
    PackageSpec,
    ParseError,
    ParseResult,
)
from qa_platform.shared.json_io import (
    read_json,
    write_json,
)


class FakeDockerRuntime:
    def __init__(
        self,
        outcome: ProcessOutcome | None = None,
        error: Exception | None = None,
    ) -> None:
        self.outcome = outcome
        self.error = error
        self.ready_configs: list[DockerExecutorConfig] = []
        self.run_calls: list[dict[str, object]] = []

    def ensure_ready(self, config: DockerExecutorConfig) -> None:
        self.ready_configs.append(config)
        if self.error is not None:
            raise self.error

    def run(self, **kwargs: object) -> ProcessOutcome:
        self.run_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.outcome is None:
            raise AssertionError("Fake runtime outcome is not configured.")
        return self.outcome


def write_successful_execution_files(
    block_dir,
    *,
    code: str = "print('hello')\n",
    stdin: str = "",
    expected_output: str = "hello\n",
    packages: list[PackageSpec] | None = None,
    meta: dict[str, str] | None = None,
) -> None:
    block_dir.mkdir()
    parse_result = ParseResult(
        parse_success=True,
        block_id=block_dir.name,
        spec=BlockSpec(
            code=code,
            stdin=stdin,
            packages=packages or [],
            expected_output=expected_output,
            meta=meta or {},
        ),
    )
    write_json(block_dir / "block.json", parse_result.to_dict())
    (block_dir / "normalized.py").write_text(code, encoding="utf-8")
    (block_dir / "stdin.txt").write_text(stdin, encoding="utf-8")


def successful_outcome(
    *,
    stdout: str = "hello\n",
) -> ProcessOutcome:
    return ProcessOutcome(
        exit_code=0,
        duration_ms=15,
        stdout=stdout,
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
    )


def test_parse_failure_does_not_call_docker_runtime(tmp_path) -> None:
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
    runtime = FakeDockerRuntime(successful_outcome())

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_PARSE_ERROR
    assert runtime.ready_configs == []
    assert runtime.run_calls == []
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_prepare_chapter_derives_dependency_image_from_parse_results() -> None:
    executor = DockerBlockExecutor(runtime=FakeDockerRuntime())
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_001",
        spec=BlockSpec(
            code="import numpy as np\nprint(np.array([1, 2, 3]))\n",
            stdin="",
            packages=[
                PackageSpec(name="numpy", specifier="", raw="numpy"),
            ],
            expected_output="[1 2 3]\n",
            meta={},
        ),
    )

    executor.prepare_chapter([parse_result])

    assert executor.config.install_requirements == ("numpy",)
    assert executor.config.image.startswith("qa-platform-python:3.11-deps-")


def test_missing_block_json_does_not_call_docker_runtime(tmp_path) -> None:
    block_dir = tmp_path / "block_002"
    block_dir.mkdir()
    runtime = FakeDockerRuntime(successful_outcome())

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.category == CATEGORY_EXECUTOR_INPUT_ERROR
    assert runtime.ready_configs == []
    assert runtime.run_calls == []


def test_supported_external_package_runs_with_prepared_dependency_image(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_003"
    write_successful_execution_files(
        block_dir,
        code="import numpy as np\nprint(np.array([1, 2, 3]))\n",
        expected_output="[1 2 3]\n",
        packages=[
            PackageSpec(
                name="numpy",
                specifier="",
                raw="numpy",
            )
        ],
        meta={"page": "14"},
    )
    runtime = FakeDockerRuntime(successful_outcome(stdout="[1 2 3]\n"))
    executor = DockerBlockExecutor(runtime=runtime)

    executor.prepare_chapter(
        [ParseResult.from_dict(read_json(block_dir / "block.json"))]
    )
    result = executor.execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert runtime.ready_configs[0].install_requirements == ("numpy",)
    assert runtime.run_calls
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_supported_external_package_direct_execution_uses_dependency_image(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_direct_package"
    write_successful_execution_files(
        block_dir,
        code="import numpy as np\nprint(np.array([1, 2, 3]))\n",
        expected_output="[1 2 3]\n",
        packages=[
            PackageSpec(
                name="numpy",
                specifier="",
                raw="numpy",
            )
        ],
        meta={"page": "14"},
    )
    runtime = FakeDockerRuntime(successful_outcome(stdout="[1 2 3]\n"))

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert runtime.ready_configs[0].install_requirements == ("numpy",)
    assert runtime.ready_configs[0].image.startswith(
        "qa-platform-python:3.11-deps-"
    )
    assert runtime.run_calls
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_unsupported_external_package_is_rejected_before_docker_runtime(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_unsupported_package"
    write_successful_execution_files(
        block_dir,
        code="import seaborn as sns\nprint(sns.__name__)\n",
        expected_output="seaborn\n",
        packages=[
            PackageSpec(
                name="seaborn",
                specifier="",
                raw="seaborn",
            )
        ],
        meta={"page": "14"},
    )
    runtime = FakeDockerRuntime(successful_outcome(stdout="seaborn\n"))

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_UNSUPPORTED_PACKAGE
    assert result.error_type == "UnsupportedPackageError"
    assert "seaborn" in result.error_message
    assert result.expected_output == "seaborn\n"
    assert result.meta == {"page": "14"}
    assert runtime.ready_configs == []
    assert runtime.run_calls == []
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_environment_module_block_is_skipped_before_docker_runtime(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_gui"
    write_successful_execution_files(
        block_dir,
        code="import turtle\nturtle.forward(100)\n",
        expected_output="",
        meta={"page": "19"},
    )
    runtime = FakeDockerRuntime(successful_outcome())

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_ENVIRONMENT_DEPENDENT
    assert result.error_type == "EnvironmentModuleSkipped"
    assert "turtle" in result.error_message
    assert result.meta["environment_modules"] == "turtle"
    assert runtime.ready_configs == []
    assert runtime.run_calls == []
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_preclassified_environment_module_skip_is_saved_before_runtime(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_preclassified_environment"
    write_successful_execution_files(
        block_dir,
        code="print('metadata already classified')\n",
        expected_output="metadata already classified\n",
        meta={
            "run_skip_reason": "environment_dependent",
            "environment_modules": "tkinter",
        },
    )
    runtime = FakeDockerRuntime(successful_outcome())

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_ENVIRONMENT_DEPENDENT
    assert result.error_type == "EnvironmentModuleSkipped"
    assert result.meta["run_skip_reason"] == "environment_dependent"
    assert result.meta["environment_modules"] == "tkinter"
    assert runtime.ready_configs == []
    assert runtime.run_calls == []
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_external_file_read_block_is_skipped_before_package_resolution_and_runtime(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_external_file"
    write_successful_execution_files(
        block_dir,
        code=(
            "from bs4 import BeautifulSoup\n"
            "page = open('d://simple.html', 'r').read()\n"
            "print(BeautifulSoup(page, 'html.parser').title)\n"
        ),
        expected_output="",
        packages=[
            PackageSpec(
                name="bs4",
                specifier="",
                raw="bs4",
            )
        ],
        meta={"page": "10"},
    )
    runtime = FakeDockerRuntime(successful_outcome())

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.error_type == "MissingRequiredFileSkipped"
    assert result.meta == {
        "page": "10",
        "missing_required_files": "d://simple.html",
    }
    assert runtime.ready_configs == []
    assert runtime.run_calls == []
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_preclassified_external_file_skip_is_saved_before_runtime(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_preclassified_external_file"
    write_successful_execution_files(
        block_dir,
        code="print('metadata already classified')\n",
        expected_output="",
        packages=[
            PackageSpec(
                name="bs4",
                specifier="",
                raw="bs4",
            )
        ],
        meta={
            "run_skip_reason": "missing_required_file",
            "missing_required_files": "sample.csv",
        },
    )
    runtime = FakeDockerRuntime(successful_outcome())

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.error_type == "MissingRequiredFileSkipped"
    assert result.category != CATEGORY_UNSUPPORTED_PACKAGE
    assert result.error_type != "UnsupportedPackageError"
    assert result.meta["run_skip_reason"] == "missing_required_file"
    assert result.meta["missing_required_files"] == "sample.csv"
    assert runtime.ready_configs == []
    assert runtime.run_calls == []
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_error_finding_block_is_skipped_before_docker_runtime(tmp_path) -> None:
    block_dir = tmp_path / "block_error_finding"
    write_successful_execution_files(
        block_dir,
        code="print('Hello World)\n",
        expected_output="",
        meta={"code_type": "ERROR_FINDING", "page": "8"},
    )
    runtime = FakeDockerRuntime(successful_outcome())

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_ERROR_FINDING
    assert result.error_type == "SkippedByCodeType"
    assert "ERROR_FINDING" in result.error_message
    assert result.expected_output == ""
    assert result.meta == {"code_type": "ERROR_FINDING", "page": "8"}
    assert runtime.ready_configs == []
    assert runtime.run_calls == []
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_successful_runtime_result_is_saved_as_passed(tmp_path) -> None:
    block_dir = tmp_path / "block_004"
    write_successful_execution_files(
        block_dir,
        stdin="Ada\n",
        expected_output="hello\n",
        meta={"page": "15"},
    )
    runtime = FakeDockerRuntime(successful_outcome())

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.output_matched is True
    assert runtime.ready_configs == [DockerBlockExecutor().config]
    assert runtime.run_calls == [
        {
            "block_dir": block_dir,
            "block_id": "block_004",
            "stdin": "Ada\n",
            "config": DockerBlockExecutor().config,
            "script_name": "normalized.py",
        }
    ]
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_repl_execution_mode_generates_repl_artifact_and_runtime_meta(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_repl"
    write_successful_execution_files(
        block_dir,
        code="numbers = [1, 2, 3]\nnumbers\n",
        expected_output="[1, 2, 3]\n",
        meta={"execution_mode": "repl", "page": "21"},
    )
    runtime = FakeDockerRuntime(successful_outcome(stdout="[1, 2, 3]\n"))

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert (block_dir / "repl_executable.py").is_file()
    assert runtime.run_calls == [
        {
            "block_dir": block_dir,
            "block_id": "block_repl",
            "stdin": "",
            "config": DockerBlockExecutor().config,
            "script_name": "repl_executable.py",
        }
    ]
    assert result.status == STATUS_PASSED
    assert result.meta == {
        "execution_mode": "repl",
        "page": "21",
        "execution_strategy": "repl_displayhook",
    }
    assert read_json(block_dir / "result.json") == result.to_dict()


def test_docker_executor_runs_setup_code_with_block_code(tmp_path) -> None:
    block_dir = tmp_path / "block_setup"
    block_dir.mkdir()
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_setup",
        spec=BlockSpec(
            setup_code="def greet(name, msg):\n    print(name, msg)\n",
            code='greet("영희")\n',
            stdin="",
            expected_output=(
                "TypeError: greet() missing 1 required positional argument: "
                "'msg'\n"
            ),
            meta={"execution_mode": "repl"},
        ),
    )
    write_json(block_dir / "block.json", parse_result.to_dict())
    (block_dir / "normalized.py").write_text(
        "def greet(name, msg):\n    print(name, msg)\n\n"
        'greet("영희")\n',
        encoding="utf-8",
    )
    (block_dir / "stdin.txt").write_text("", encoding="utf-8")
    runtime = FakeDockerRuntime(
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                "TypeError: greet() missing 1 required positional argument: 'msg'\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        )
    )

    DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert (
        "def greet(name, msg):"
        in (block_dir / "repl_executable.py").read_text(encoding="utf-8")
    )


def test_output_mismatch_uses_shared_result_contract(tmp_path) -> None:
    block_dir = tmp_path / "block_005"
    write_successful_execution_files(
        block_dir,
        expected_output="expected\n",
    )
    runtime = FakeDockerRuntime(
        successful_outcome(stdout="actual\n")
    )

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_OUTPUT_MISMATCH
    assert result.output_matched is False


def test_nondeterministic_policy_uses_shared_result_contract(tmp_path) -> None:
    block_dir = tmp_path / "block_nondeterministic"
    write_successful_execution_files(
        block_dir,
        stdin="seed input\n",
        expected_output="expected\n",
        meta={"output_determinism": "nondeterministic"},
    )
    runtime = FakeDockerRuntime(
        successful_outcome(stdout="actual\n")
    )

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert runtime.run_calls[0]["stdin"] == "seed input\n"
    assert result.meta["output_determinism"] == "nondeterministic"
    assert result.status == STATUS_PASSED
    assert result.output_matched is None


def test_runtime_error_uses_shared_result_classifier(tmp_path) -> None:
    block_dir = tmp_path / "block_006"
    write_successful_execution_files(block_dir, expected_output="")
    runtime = FakeDockerRuntime(
        ProcessOutcome(
            exit_code=1,
            duration_ms=7,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                "NameError: name 'missing_name' is not defined\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        )
    )

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_NAME_ERROR
    assert result.error_type == "NameError"


def test_timeout_uses_shared_result_contract(tmp_path) -> None:
    block_dir = tmp_path / "block_007"
    write_successful_execution_files(block_dir, expected_output="")
    runtime = FakeDockerRuntime(
        ProcessOutcome(
            exit_code=None,
            duration_ms=101,
            stdout="partial",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=True,
        )
    )

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_TIMEOUT
    assert result.error_type == "TimeoutError"


@pytest.mark.parametrize(
    "error",
    [
        DockerCliUnavailableError("docker missing"),
        DockerDaemonUnavailableError("daemon stopped"),
        DockerImageBuildError("build failed"),
        DockerImageUnavailableError("image missing"),
        DockerLifecycleError("create failed"),
        DockerCleanupError("remove failed"),
    ],
)
def test_docker_runtime_errors_become_executor_input_error(
    tmp_path,
    error: Exception,
) -> None:
    block_dir = tmp_path / "block_008"
    write_successful_execution_files(
        block_dir,
        expected_output="hello\n",
        meta={"page": "16"},
    )
    runtime = FakeDockerRuntime(error=error)

    result = DockerBlockExecutor(runtime=runtime).execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_EXECUTOR_INPUT_ERROR
    assert result.error_type == error.__class__.__name__
    assert result.error_message == str(error)
    assert result.expected_output == "hello\n"
    assert result.meta == {"page": "16"}
    assert read_json(block_dir / "result.json") == result.to_dict()
