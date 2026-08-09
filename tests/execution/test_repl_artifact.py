import subprocess
import sys

from qa_platform.execution.repl_artifact import (
    EXECUTION_STRATEGY_REPL_DISPLAYHOOK,
    EXECUTION_STRATEGY_REPL_TRANSFORM_FAILED_SCRIPT_FALLBACK,
    EXECUTION_STRATEGY_SCRIPT_NORMALIZED,
    REPL_ENTRYPOINT_NAME,
    SCRIPT_ENTRYPOINT_NAME,
    build_repl_executable_source,
    prepare_execution_artifact,
)


def run_python_source(source: str, tmp_path):
    script_path = tmp_path / "generated.py"
    script_path.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-I", "-B", "-u", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_repl_source_echoes_top_level_expression_values(tmp_path) -> None:
    source = build_repl_executable_source(
        "numbers = [1, 2, 3]\n"
        "numbers\n"
        "print('done')\n"
    )

    result = run_python_source(source, tmp_path)

    assert result.returncode == 0
    assert result.stdout == "[1, 2, 3]\ndone\n"
    assert result.stderr == ""


def test_repl_source_uses_repr_for_strings(tmp_path) -> None:
    source = build_repl_executable_source(
        "word = 'python'\n"
        "word\n"
    )

    result = run_python_source(source, tmp_path)

    assert result.returncode == 0
    assert result.stdout == "'python'\n"


def test_repl_source_does_not_echo_none(tmp_path) -> None:
    source = build_repl_executable_source(
        "value = None\n"
        "value\n"
    )

    result = run_python_source(source, tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""


def test_repl_source_wraps_only_top_level_expressions(tmp_path) -> None:
    source = build_repl_executable_source(
        "def f():\n"
        "    123\n"
        "    return 'ok'\n"
        "\n"
        "f()\n"
    )

    result = run_python_source(source, tmp_path)

    assert result.returncode == 0
    assert result.stdout == "'ok'\n"


def test_prepare_execution_artifact_keeps_script_blocks_on_normalized_py(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_script"
    block_dir.mkdir()
    artifact = prepare_execution_artifact(
        block_dir,
        code="print('hello')\n",
        meta={"page": "10", "execution_mode": "script"},
    )

    assert artifact.script_name == SCRIPT_ENTRYPOINT_NAME
    assert artifact.meta == {
        "page": "10",
        "execution_mode": "script",
        "execution_strategy": EXECUTION_STRATEGY_SCRIPT_NORMALIZED,
    }
    assert not (block_dir / REPL_ENTRYPOINT_NAME).exists()


def test_prepare_execution_artifact_writes_repl_executable(tmp_path) -> None:
    block_dir = tmp_path / "block_repl"
    block_dir.mkdir()
    artifact = prepare_execution_artifact(
        block_dir,
        code="numbers = [1, 2, 3]\nnumbers\n",
        meta={"execution_mode": "repl"},
    )

    assert artifact.script_name == REPL_ENTRYPOINT_NAME
    assert artifact.meta == {
        "execution_mode": "repl",
        "execution_strategy": EXECUTION_STRATEGY_REPL_DISPLAYHOOK,
    }
    executable = block_dir / REPL_ENTRYPOINT_NAME
    assert executable.is_file()
    assert "__import__('sys').displayhook(numbers)" in executable.read_text(
        encoding="utf-8"
    )


def test_prepare_execution_artifact_falls_back_to_script_on_syntax_error(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_repl_syntax_error"
    block_dir.mkdir()
    artifact = prepare_execution_artifact(
        block_dir,
        code="if True print('bad')\n",
        meta={"execution_mode": "repl"},
    )

    assert artifact.script_name == SCRIPT_ENTRYPOINT_NAME
    assert artifact.meta == {
        "execution_mode": "repl",
        "execution_strategy": EXECUTION_STRATEGY_REPL_TRANSFORM_FAILED_SCRIPT_FALLBACK,
    }
    assert not (block_dir / REPL_ENTRYPOINT_NAME).exists()


def test_prepare_execution_artifact_falls_back_when_transform_breaks_future_import(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_repl_future_import"
    block_dir.mkdir()
    artifact = prepare_execution_artifact(
        block_dir,
        code=(
            '"""doc"""\n'
            "from __future__ import annotations\n"
            "x: list[int] = []\n"
            "x\n"
        ),
        meta={"execution_mode": "repl"},
    )

    assert artifact.script_name == SCRIPT_ENTRYPOINT_NAME
    assert artifact.meta == {
        "execution_mode": "repl",
        "execution_strategy": EXECUTION_STRATEGY_REPL_TRANSFORM_FAILED_SCRIPT_FALLBACK,
    }
    assert not (block_dir / REPL_ENTRYPOINT_NAME).exists()


def test_prepare_execution_artifact_falls_back_when_unparse_recurses(
    tmp_path,
    monkeypatch,
) -> None:
    def raise_recursion_error(_module):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(
        "qa_platform.execution.repl_artifact.ast.unparse",
        raise_recursion_error,
    )
    block_dir = tmp_path / "block_repl_unparse_recursion"
    block_dir.mkdir()

    artifact = prepare_execution_artifact(
        block_dir,
        code="value = 1\nvalue\n",
        meta={"execution_mode": "repl"},
    )

    assert artifact.script_name == SCRIPT_ENTRYPOINT_NAME
    assert artifact.meta == {
        "execution_mode": "repl",
        "execution_strategy": EXECUTION_STRATEGY_REPL_TRANSFORM_FAILED_SCRIPT_FALLBACK,
    }
    assert not (block_dir / REPL_ENTRYPOINT_NAME).exists()


def test_prepare_execution_artifact_defaults_missing_mode_to_script(tmp_path) -> None:
    block_dir = tmp_path / "block_legacy"
    block_dir.mkdir()
    artifact = prepare_execution_artifact(
        block_dir,
        code="value = 1\nvalue\n",
        meta={},
    )

    assert artifact.script_name == SCRIPT_ENTRYPOINT_NAME
    assert artifact.meta == {
        "execution_mode": "script",
        "execution_strategy": EXECUTION_STRATEGY_SCRIPT_NORMALIZED,
    }
