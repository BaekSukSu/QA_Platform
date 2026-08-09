import os
from pathlib import Path
import subprocess

import pytest

from qa_platform.contract.parser import BlockSpecParser
from qa_platform.contract.constants import (
    CATEGORY_NAME_ERROR,
    CATEGORY_TIMEOUT,
    STATUS_FAILED,
    STATUS_PASSED,
)
from qa_platform.execution.docker import DockerBlockExecutor
from qa_platform.execution.docker_runtime import DockerExecutorConfig


RUN_DOCKER_TESTS = os.environ.get("QA_PLATFORM_RUN_DOCKER_TESTS") == "1"

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not RUN_DOCKER_TESTS,
        reason="Set QA_PLATFORM_RUN_DOCKER_TESTS=1 to run Docker tests.",
    ),
]


def write_block(
    block_dir: Path,
    *,
    code: str,
    stdin: str = "",
    expected_output: str = "",
    meta: dict[str, str] | None = None,
) -> None:
    meta_lines = [
        "input_source=generated_sample",
        "output_source=generated_sample",
    ]
    meta_lines.extend(
        f"{key}={value}" for key, value in (meta or {}).items()
    )
    meta_text = "\n".join(meta_lines)
    block_dir.mkdir()
    (block_dir / "block.txt").write_text(
        (
            "[CODE]\n"
            f"{code.rstrip()}\n"
            "\n"
            "[INPUT]\n"
            f"{stdin.rstrip()}\n"
            "\n"
            "[PACKAGES]\n"
            "\n"
            "[OUTPUT]\n"
            f"{expected_output.rstrip()}\n"
            "\n"
            "[META]\n"
            f"{meta_text}\n"
        ),
        encoding="utf-8",
    )
    parse_result = BlockSpecParser().parse_block_dir(block_dir)
    assert parse_result.parse_success is True


def managed_container_ids() -> list[str]:
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "label=qa-platform.managed=true",
            "--format",
            "{{.ID}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


@pytest.fixture(autouse=True)
def assert_no_managed_containers() -> None:
    assert managed_container_ids() == []
    yield
    assert managed_container_ids() == []


def test_docker_executes_stdin_with_matching_output(tmp_path) -> None:
    block_dir = tmp_path / "block_001"
    write_block(
        block_dir,
        code="name = input()\nprint(f'hello {name}')\n",
        stdin="Ada\n",
        expected_output="hello Ada\n",
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.exit_code == 0
    assert result.stdout == "hello Ada\n"
    assert result.output_matched is True


def test_docker_executes_repl_expression_echo(tmp_path) -> None:
    block_dir = tmp_path / "block_repl_echo"
    write_block(
        block_dir,
        code=(
            "numbers = [1, 2, 3]\n"
            "numbers\n"
            "word = 'python'\n"
            "word\n"
            "print('done')\n"
        ),
        expected_output="[1, 2, 3]\n'python'\ndone\n",
        meta={"execution_mode": "repl"},
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.exit_code == 0
    assert result.stdout == "[1, 2, 3]\n'python'\ndone\n"
    assert result.output_matched is True
    assert result.meta["execution_mode"] == "repl"
    assert result.meta["execution_strategy"] == "repl_displayhook"
    assert (block_dir / "repl_executable.py").is_file()


def test_docker_skips_nondeterministic_output_comparison(tmp_path) -> None:
    block_dir = tmp_path / "block_nondeterministic"
    write_block(
        block_dir,
        code="import os\nprint(os.getpid())\n",
        expected_output="fixed pid\n",
        meta={"output_determinism": "nondeterministic"},
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.exit_code == 0
    assert result.stdout.strip().isdigit()
    assert result.output_matched is None


def test_docker_accepts_configured_stdin_exhaustion(tmp_path) -> None:
    block_dir = tmp_path / "block_stdin_exhaustion"
    write_block(
        block_dir,
        code=(
            "value = input()\n"
            "while value != 'stop':\n"
            "    print(value)\n"
            "    value = input()\n"
        ),
        stdin="one\ntwo\n",
        expected_output="finished\n",
        meta={"stdin_exhaustion": "accept"},
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.exit_code == 1
    assert result.stdout == "one\ntwo\n"
    assert result.error_type == "EOFError"
    assert result.error_message == "EOF when reading a line"
    assert result.output_matched is None


def test_docker_classifies_name_error(tmp_path) -> None:
    block_dir = tmp_path / "block_002"
    write_block(
        block_dir,
        code="print(missing_name)\n",
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_NAME_ERROR
    assert result.error_type == "NameError"


def test_docker_kills_infinite_loop_on_timeout(tmp_path) -> None:
    block_dir = tmp_path / "block_003"
    write_block(
        block_dir,
        code="while True:\n    pass\n",
    )
    executor = DockerBlockExecutor(
        config=DockerExecutorConfig(timeout_seconds=0.2),
    )

    result = executor.execute(block_dir)

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_TIMEOUT
    assert result.exit_code is None


def test_docker_allows_relative_file_write_in_work_tmpfs(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_004"
    write_block(
        block_dir,
        code=(
            "from pathlib import Path\n"
            "path = Path('created.txt')\n"
            "path.write_text('hello', encoding='utf-8')\n"
            "print(path.read_text(encoding='utf-8'))\n"
        ),
        expected_output="hello\n",
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_PASSED
    assert not (block_dir / "created.txt").exists()


def test_docker_mounts_input_directory_read_only(tmp_path) -> None:
    block_dir = tmp_path / "block_005"
    write_block(
        block_dir,
        code=(
            "from pathlib import Path\n"
            "try:\n"
            "    Path('/input/created.txt').write_text('no')\n"
            "except OSError:\n"
            "    print('read-only')\n"
        ),
        expected_output="read-only\n",
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_PASSED
    assert not (block_dir / "created.txt").exists()


def test_docker_runs_as_non_root_user(tmp_path) -> None:
    block_dir = tmp_path / "block_006"
    write_block(
        block_dir,
        code="import os\nprint(os.getuid(), os.getgid())\n",
        expected_output="10001 10001\n",
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.stdout == "10001 10001\n"


def test_docker_blocks_external_network(tmp_path) -> None:
    block_dir = tmp_path / "block_007"
    write_block(
        block_dir,
        code=(
            "import socket\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=0.2)\n"
            "except OSError:\n"
            "    print('blocked')\n"
        ),
        expected_output="blocked\n",
    )

    result = DockerBlockExecutor().execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.stdout == "blocked\n"


def test_docker_truncates_long_stdout_and_stderr(tmp_path) -> None:
    block_dir = tmp_path / "block_008"
    write_block(
        block_dir,
        code=(
            "import sys\n"
            "print('x' * 25, end='')\n"
            "sys.stderr.write('y' * 25)\n"
        ),
    )
    executor = DockerBlockExecutor(
        config=DockerExecutorConfig(output_limit_chars=10),
    )

    result = executor.execute(block_dir)

    assert result.status == STATUS_PASSED
    assert result.stdout == "x" * 10
    assert result.stderr == "y" * 10
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
