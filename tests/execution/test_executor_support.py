from qa_platform.contract.constants import (
    CATEGORY_ENVIRONMENT_DEPENDENT,
    CATEGORY_EXECUTOR_INPUT_ERROR,
    CATEGORY_INPUT_REQUIRED_OR_INVALID,
    CATEGORY_MISSING_REQUIRED_FILE,
    CATEGORY_NAME_ERROR,
    CATEGORY_OUTPUT_MISMATCH,
    CATEGORY_PARSE_ERROR,
    CATEGORY_RUNTIME_ERROR,
    CATEGORY_SYNTAX_ERROR,
    CATEGORY_TIMEOUT,
    PARSER_ERROR_EMPTY_CODE,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
)
from qa_platform.execution.support import (
    ProcessOutcome,
    build_environment_module_skip_result,
    build_executable_source,
    build_execution_result,
    build_missing_required_file_skip_result,
    load_execution_context,
)
from qa_platform.contract.source_skip_classifier import (
    META_ENVIRONMENT_MODULES_KEY,
    META_RUN_SKIP_REASON_KEY,
    RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT,
)
from qa_platform.contract.models import (
    BlockSpec,
    PackageSpec,
    ParseError,
    ParseResult,
)
from qa_platform.shared.json_io import (
    write_json,
)


def write_successful_parse_files(
    block_dir,
    *,
    code: str = "print('hello')\n",
    stdin: str = "",
    expected_output: str = "hello\n",
    meta: dict[str, str] | None = None,
) -> ParseResult:
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
    return parse_result


def build_parse_result_for_external_file_skip(
    *,
    code: str,
    setup_code: str = "",
    stdin: str = "",
    block_id: str = "block_external_file",
) -> ParseResult:
    return ParseResult(
        parse_success=True,
        block_id=block_id,
        spec=BlockSpec(
            code=code,
            setup_code=setup_code,
            stdin=stdin,
            expected_output="",
            meta={"page": "5"},
        ),
    )


def test_load_execution_context_returns_parse_error_without_process_run(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_001"
    block_dir.mkdir()
    parse_result = ParseResult(
        parse_success=False,
        block_id="block_001",
        error=ParseError(
            error_type=PARSER_ERROR_EMPTY_CODE,
            message="[CODE] section is empty.",
        ),
    )
    write_json(block_dir / "block.json", parse_result.to_dict())

    context, early_result = load_execution_context(block_dir)

    assert context is None
    assert early_result is not None
    assert early_result.status == STATUS_FAILED
    assert early_result.category == CATEGORY_PARSE_ERROR
    assert early_result.error_type == PARSER_ERROR_EMPTY_CODE
    assert early_result.error_message == "[CODE] section is empty."


def test_load_execution_context_rejects_missing_block_json(tmp_path) -> None:
    block_dir = tmp_path / "block_002"
    block_dir.mkdir()

    context, early_result = load_execution_context(block_dir)

    assert context is None
    assert early_result is not None
    assert early_result.block_id == "block_002"
    assert early_result.category == CATEGORY_EXECUTOR_INPUT_ERROR
    assert early_result.error_type == "FileNotFoundError"
    assert "block.json" in early_result.error_message


def test_load_execution_context_rejects_missing_normalized_python(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_003"
    write_successful_parse_files(
        block_dir,
        expected_output="hello\n",
        meta={"page": "12"},
    )
    (block_dir / "normalized.py").unlink()

    context, early_result = load_execution_context(block_dir)

    assert context is None
    assert early_result is not None
    assert early_result.category == CATEGORY_EXECUTOR_INPUT_ERROR
    assert early_result.error_type == "FileNotFoundError"
    assert "normalized.py" in early_result.error_message
    assert early_result.expected_output == "hello\n"
    assert early_result.meta == {"page": "12"}


def test_load_execution_context_rejects_missing_stdin(tmp_path) -> None:
    block_dir = tmp_path / "block_004"
    write_successful_parse_files(block_dir)
    (block_dir / "stdin.txt").unlink()

    context, early_result = load_execution_context(block_dir)

    assert context is None
    assert early_result is not None
    assert early_result.category == CATEGORY_EXECUTOR_INPUT_ERROR
    assert early_result.error_type == "FileNotFoundError"
    assert "stdin.txt" in early_result.error_message


def test_load_execution_context_returns_stdin_and_parse_result(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_005"
    parse_result = write_successful_parse_files(
        block_dir,
        stdin="Ada\n",
    )

    context, early_result = load_execution_context(block_dir)

    assert early_result is None
    assert context is not None
    assert context.parse_result == parse_result
    assert context.stdin == "Ada\n"


def test_build_executable_source_joins_setup_and_code() -> None:
    source = build_executable_source(
        "def greet(name, msg):\n    print(name, msg)\n",
        'greet("영희")\n',
    )

    assert source == (
        "def greet(name, msg):\n"
        "    print(name, msg)\n"
        "\n"
        'greet("영희")\n'
    )


def test_build_missing_required_file_skip_result_detects_literal_open_read() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="f = open('d://weather.csv')\nprint(f.read())\n",
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.exit_code is None
    assert result.error_type == "MissingRequiredFileSkipped"
    assert result.error_message == (
        "Block execution skipped because it reads external files "
        "not provided by QA fixtures: d://weather.csv."
    )
    assert result.expected_output == ""
    assert result.output_matched is None
    assert result.meta == {
        "page": "5",
        "missing_required_files": "d://weather.csv",
    }


def test_build_missing_required_file_skip_result_ignores_syntax_errors() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="if True print('bad')\n",
    )

    assert build_missing_required_file_skip_result(parse_result) is None


def test_build_missing_required_file_skip_result_detects_setup_read_csv() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        setup_code=(
            "import pandas as pd\n"
            "df = pd.read_csv('d:/sample.csv', index_col=0)\n"
        ),
        code="df\n",
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.error_type == "MissingRequiredFileSkipped"
    assert result.meta["missing_required_files"] == "d:/sample.csv"


def test_build_missing_required_file_skip_result_detects_input_filename() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "fname = input('입력 파일 이름: ')\n"
            "file = open(fname, 'r')\n"
            "print(file.read())\n"
        ),
        stdin="input.txt\n",
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["missing_required_files"] == "input.txt"


def test_build_missing_required_file_skip_result_detects_path_read_bytes() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="from pathlib import Path\nprint(Path('DATA.CSV').read_bytes())\n",
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["missing_required_files"] == "DATA.CSV"


def test_build_missing_required_file_skip_result_detects_path_object_variable_read() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "from pathlib import Path\n"
            "path = Path('missing.csv')\n"
            "print(path.read_text())\n"
        ),
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["missing_required_files"] == "missing.csv"


def test_build_missing_required_file_skip_result_detects_read_update_mode() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="with open('missing.csv', 'r+') as file:\n    print(file.read())\n",
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["missing_required_files"] == "missing.csv"


def test_build_missing_required_file_skip_result_ignores_non_file_reads() -> None:
    in_memory_parse_result = build_parse_result_for_external_file_skip(
        setup_code=(
            "import io\n"
            "import pandas as pd\n"
            "csv_data = 'name,score\\nAda,10\\n'\n"
        ),
        code="df = pd.read_csv(io.StringIO(csv_data))\nprint(df)\n",
    )
    write_mode_parse_result = build_parse_result_for_external_file_skip(
        code="f = open('output.txt', 'w')\nf.write('saved')\nf.close()\n",
    )
    url_parse_result = build_parse_result_for_external_file_skip(
        code="import pandas as pd\ndf = pd.read_csv('https://example.com/data.csv')\n",
    )

    assert build_missing_required_file_skip_result(in_memory_parse_result) is None
    assert build_missing_required_file_skip_result(write_mode_parse_result) is None
    assert build_missing_required_file_skip_result(url_parse_result) is None


def test_build_missing_required_file_skip_result_ignores_literal_non_file_strings() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="f = open('not_a_fixture')\nprint(f.read())\n",
    )

    assert build_missing_required_file_skip_result(parse_result) is None


def test_build_missing_required_file_skip_result_strips_literal_paths() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="f = open(' DATA.CSV ')\nprint(f.read())\n",
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.meta["missing_required_files"] == "DATA.CSV"


def test_build_missing_required_file_skip_result_joins_multiple_paths() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="open('a.csv')\nopen('b.txt')\nopen('a.csv')\n",
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.meta["missing_required_files"] == "a.csv, b.txt"
    assert result.error_message == (
        "Block execution skipped because it reads external files "
        "not provided by QA fixtures: a.csv, b.txt."
    )


def test_build_missing_required_file_skip_result_ignores_self_created_files() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "with open('created.txt', 'w') as file:\n"
            "    file.write('hello')\n"
            "with open('created.txt') as file:\n"
            "    print(file.read())\n"
        ),
    )

    assert build_missing_required_file_skip_result(parse_result) is None


def test_build_missing_required_file_skip_result_detects_variable_literal_path() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "filename = 'weather.csv'\n"
            "with open(filename) as file:\n"
            "    print(file.read())\n"
        ),
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["missing_required_files"] == "weather.csv"


def test_build_missing_required_file_skip_result_ignores_pathlib_self_created_files() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "from pathlib import Path\n"
            "Path('created.txt').write_text('hello')\n"
            "print(Path('created.txt').read_text())\n"
        ),
    )

    assert build_missing_required_file_skip_result(parse_result) is None


def test_build_missing_required_file_skip_result_uses_literal_assignment_at_read_time() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "filename = 'missing.csv'\n"
            "open(filename)\n"
            "filename = 'other.txt'\n"
        ),
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.meta["missing_required_files"] == "missing.csv"


def test_build_missing_required_file_skip_result_uses_write_assignment_at_write_time() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "filename = 'created.txt'\n"
            "with open(filename, 'w') as file:\n"
            "    file.write('hello')\n"
            "filename = 'missing.csv'\n"
            "open(filename)\n"
        ),
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.meta["missing_required_files"] == "missing.csv"


def test_build_missing_required_file_skip_result_detects_called_function_read() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "def load_weather():\n"
            "    return open('weather.csv').read()\n"
            "print(load_weather())\n"
        ),
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["missing_required_files"] == "weather.csv"


def test_build_missing_required_file_skip_result_detects_called_nested_function_read() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "def load_weather():\n"
            "    def read_file():\n"
            "        return open('weather.csv').read()\n"
            "    return read_file()\n"
            "print(load_weather())\n"
        ),
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["missing_required_files"] == "weather.csv"


def test_build_missing_required_file_skip_result_keeps_nested_function_names_scoped() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "def load_weather():\n"
            "    def read_file():\n"
            "        return open('weather.csv').read()\n"
            "    return 'ready'\n"
            "print(read_file())\n"
        ),
    )

    assert build_missing_required_file_skip_result(parse_result) is None


def test_build_missing_required_file_skip_result_keeps_called_function_locals_scoped() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "filename = 'created.txt'\n"
            "with open(filename, 'w') as file:\n"
            "    file.write('hello')\n"
            "def read_missing():\n"
            "    filename = 'missing.csv'\n"
            "    return open(filename).read()\n"
            "read_missing()\n"
            "open(filename)\n"
        ),
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.meta["missing_required_files"] == "missing.csv"


def test_build_missing_required_file_skip_result_ignores_nested_scope_reads() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code=(
            "def unused():\n"
            "    fname = input('입력 파일 이름: ')\n"
            "    file = open(fname, 'r')\n"
            "    return file.read()\n"
            "print('ready')\n"
        ),
        stdin="input.txt\n",
    )

    assert build_missing_required_file_skip_result(parse_result) is None


def test_build_missing_required_file_skip_result_detects_uppercase_extension() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="from pathlib import Path\nprint(Path('INPUT.TXT').read_text())\n",
    )

    result = build_missing_required_file_skip_result(parse_result)

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["missing_required_files"] == "INPUT.TXT"


def test_build_missing_required_file_skip_result_uses_preclassified_metadata() -> None:
    parse_result = build_parse_result_for_external_file_skip(
        code="print('metadata already classified')\n",
        block_id="block_preclassified_file",
    )
    assert parse_result.spec is not None
    parse_result.spec.meta.update(
        {
            "run_skip_reason": "missing_required_file",
            "missing_required_files": "sample.csv",
        }
    )
    result = build_missing_required_file_skip_result(parse_result)
    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_MISSING_REQUIRED_FILE
    assert result.meta["run_skip_reason"] == "missing_required_file"
    assert result.meta["missing_required_files"] == "sample.csv"


def test_build_environment_module_skip_result_uses_preclassified_metadata() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_preclassified_environment",
        spec=BlockSpec(
            code="print('metadata already classified')\n",
            stdin="",
            packages=[],
            expected_output="metadata already classified\n",
            meta={
                META_RUN_SKIP_REASON_KEY: RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT,
                META_ENVIRONMENT_MODULES_KEY: "tkinter",
            },
        ),
    )

    result = build_environment_module_skip_result(parse_result, ())

    assert result is not None
    assert result.status == STATUS_SKIPPED
    assert result.category == CATEGORY_ENVIRONMENT_DEPENDENT
    assert result.error_type == "EnvironmentModuleSkipped"
    assert result.meta[META_RUN_SKIP_REASON_KEY] == (
        RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT
    )
    assert result.meta[META_ENVIRONMENT_MODULES_KEY] == "tkinter"


def test_build_execution_result_marks_matching_output_passed() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_006",
        spec=BlockSpec(
            code="print('hello')\n",
            stdin="",
            expected_output="hello\n",
            meta={"page": "13"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=12,
            stdout="hello\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.output_matched is True
    assert result.meta == {"page": "13"}


def test_build_execution_result_accepts_pandas_series_footer_from_package() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_pandas_series",
        spec=BlockSpec(
            setup_code=(
                "import pandas as pd\n"
                "data = {'population': [48422644, 310232863, "
                "127288000, 1330044000, 140702000]}\n"
                "index = ['KR', 'US', 'JP', 'CN', 'RU']\n"
                "df = pd.DataFrame(data, index=index)\n"
            ),
            code="df['population']\n",
            stdin="",
            packages=[
                PackageSpec(name="pandas", specifier="", raw="pandas"),
            ],
            expected_output=(
                "KR      48422644\n"
                "US     310232863\n"
                "JP     127288000\n"
                "CN    1330044000\n"
                "RU     140702000\n"
            ),
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=12,
            stdout=(
                "KR      48422644\n"
                "US     310232863\n"
                "JP     127288000\n"
                "CN    1330044000\n"
                "RU     140702000\n"
                "Name: population, dtype: int64\n"
            ),
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.output_matched is True


def test_build_execution_result_does_not_retry_pandas_without_source_signal() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_mixed_print_pandas",
        spec=BlockSpec(
            code=(
                "import pandas as pd\n"
                "print('value   one')\n"
            ),
            stdin="",
            packages=[PackageSpec(name="pandas", specifier="", raw="pandas")],
            expected_output="value one\ndtype: int64\n",
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=12,
            stdout="value   one\ndtype: int64\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_OUTPUT_MISMATCH
    assert result.output_matched is False


def test_build_execution_result_uses_runtime_meta_override() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_meta_override",
        spec=BlockSpec(
            code="value = 1\nvalue\n",
            stdin="",
            expected_output="1\n",
            meta={"execution_mode": "repl"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=8,
            stdout="1\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
        meta={
            "execution_mode": "repl",
            "execution_strategy": "repl_displayhook",
        },
    )

    assert result.status == STATUS_PASSED
    assert result.meta == {
        "execution_mode": "repl",
        "execution_strategy": "repl_displayhook",
    }


def test_build_execution_result_marks_output_mismatch_failed() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_007",
        spec=BlockSpec(
            code="print('actual')\n",
            stdin="",
            expected_output="expected\n",
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=5,
            stdout="actual\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_OUTPUT_MISMATCH
    assert result.output_matched is False


def test_build_execution_result_classifies_runtime_error() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_008",
        spec=BlockSpec(
            code="print(missing_name)\n",
            stdin="",
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=9,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                "NameError: name 'missing_name' is not defined\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_NAME_ERROR
    assert result.error_type == "NameError"
    assert result.error_message == "name 'missing_name' is not defined"
    assert result.output_matched is None


def test_build_execution_result_passes_expected_runtime_error() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_expected_error",
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

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                "  File \"/input/repl_executable.py\", line 5, in <module>\n"
                "    __import__('sys').displayhook(greet('영희'))\n"
                "TypeError: greet() missing 1 required positional argument: 'msg'\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.error_type == "TypeError"
    assert result.error_message == (
        "greet() missing 1 required positional argument: 'msg'"
    )
    assert result.output_matched is True


def test_build_execution_result_passes_expected_syntax_error_with_version_hint(
) -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_expected_syntax_error",
        spec=BlockSpec(
            code="print(Good Bye)\n",
            stdin="",
            expected_output=(
                'File "<ipython-input-4-0389bd3941f5>", line 1\n'
                "    print(Good Bye)\n"
                "                 ^\n"
                "SyntaxError: invalid syntax\n"
            ),
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr=(
                '  File "/input/normalized.py", line 1\n'
                "    print(Good Bye)\n"
                "          ^^^^^^^^\n"
                "SyntaxError: invalid syntax. Perhaps you forgot a comma?\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.error_type == "SyntaxError"
    assert result.output_matched is True


def test_build_execution_result_passes_expected_runtime_error_with_smart_quote(
) -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_expected_type_error",
        spec=BlockSpec(
            code="100 + '원'\n",
            stdin="",
            expected_output=(
                "Traceback (most recent call last):\n"
                '  File "<ipython-input-3-1b3ddc5be148>", line 1, in <module>\n'
                '    100+"원"\n'
                "TypeError: unsupported operand type(s) for +: 'int' and 'str’\n"
            ),
            meta={"execution_mode": "repl"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                '  File "/input/repl_executable.py", line 2, in <module>\n'
                "    __import__('sys').displayhook(100 + '원')\n"
                "                                  ~~~~^~~~~~\n"
                "TypeError: unsupported operand type(s) for +: 'int' and 'str'\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.error_type == "TypeError"
    assert result.output_matched is True


def test_build_execution_result_passes_expected_eol_syntax_error_alias(
) -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_expected_eol_syntax_error",
        spec=BlockSpec(
            code='msg = "Hello\n',
            stdin="",
            expected_output="SyntaxError: EOL while scanning string literal\n",
            meta={"execution_mode": "repl"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr=(
                '  File "/input/normalized.py", line 1\n'
                '    msg = "Hello\n'
                "          ^\n"
                "SyntaxError: unterminated string literal (detected at line 1)\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.error_type == "SyntaxError"
    assert result.output_matched is True


def test_build_execution_result_does_not_pass_different_expected_error_type(
) -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_expected_syntax_but_actual_name_error",
        spec=BlockSpec(
            code="msg = Hello\n",
            stdin="",
            expected_output="SyntaxError: invalid syntax\n",
            meta={"execution_mode": "repl"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                '  File "/input/repl_executable.py", line 2, in <module>\n'
                "    msg = Hello\n"
                "          ^^^^^\n"
                "NameError: name 'Hello' is not defined\n"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_NAME_ERROR
    assert result.error_type == "NameError"
    assert result.output_matched is None


def test_build_execution_result_fails_unexpected_runtime_error() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_unexpected_error",
        spec=BlockSpec(
            code='greet("영희")\n',
            stdin="",
            expected_output=(
                "TypeError: greet() missing 1 required positional argument: "
                "'msg'\n"
            ),
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr="NameError: name 'greet' is not defined\n",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_NAME_ERROR
    assert result.error_type == "NameError"
    assert result.output_matched is None


def test_build_execution_result_classifies_timeout() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_009",
        spec=BlockSpec(
            code="while True:\n    pass\n",
            stdin="",
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=None,
            duration_ms=101,
            stdout="partial",
            stderr="",
            stdout_truncated=True,
            stderr_truncated=False,
            timed_out=True,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_TIMEOUT
    assert result.exit_code is None
    assert result.error_type == "TimeoutError"
    assert result.error_message == "Execution timed out."
    assert result.stdout == "partial"
    assert result.stdout_truncated is True
    assert result.output_matched is None


def test_build_execution_result_skips_nondeterministic_output_comparison() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_010",
        spec=BlockSpec(
            code="print('actual')\n",
            stdin="",
            expected_output="expected\n",
            meta={"output_determinism": "nondeterministic"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=5,
            stdout="actual\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.exit_code == 0
    assert result.output_matched is None
    assert result.expected_output == "expected\n"
    assert result.stdout == "actual\n"


def test_build_execution_result_supports_legacy_mode_meta() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_legacy_mode",
        spec=BlockSpec(
            code="print('actual')\n",
            stdin="",
            expected_output="expected\n",
            meta={"mode": "nondeterministic"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=5,
            stdout="actual\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.output_matched is None
    assert result.meta == {"mode": "nondeterministic"}


def test_build_execution_result_uses_runtime_meta_for_nondeterministic_policy() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_runtime_mode",
        spec=BlockSpec(
            code="print('actual')\n",
            stdin="",
            expected_output="expected\n",
            meta={"output_determinism": "nondeterministic"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=5,
            stdout="actual\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
        meta={"output_determinism": "deterministic"},
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_OUTPUT_MISMATCH
    assert result.output_matched is False
    assert result.meta == {"output_determinism": "deterministic"}


def test_build_execution_result_uses_prompt_aware_output_comparison() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_prompt",
        spec=BlockSpec(
            code='i = int(input("몇 번째 항: "))\nprint(21)\n',
            stdin="9\n",
            expected_output="21\n",
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=0,
            duration_ms=5,
            stdout="몇 번째 항: 21\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.output_matched is True


def test_build_execution_result_accepts_eof_when_configured() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_011",
        spec=BlockSpec(
            code="input()\ninput()\n",
            stdin="one\n",
            expected_output="finished\n",
            meta={"stdin_exhaustion": "accept"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
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
        ),
    )

    assert result.status == STATUS_PASSED
    assert result.category is None
    assert result.exit_code == 1
    assert result.error_type == "EOFError"
    assert result.error_message == "EOF when reading a line"
    assert result.output_matched is None


def test_build_execution_result_uses_runtime_meta_for_stdin_exhaustion_policy() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_runtime_stdin_exhaustion",
        spec=BlockSpec(
            code="input()\ninput()\n",
            stdin="one\n",
            expected_output="finished\n",
            meta={"stdin_exhaustion": "accept"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
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
        ),
        meta={"stdin_exhaustion": "deny"},
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_INPUT_REQUIRED_OR_INVALID
    assert result.error_type == "EOFError"
    assert result.meta == {"stdin_exhaustion": "deny"}


def test_build_execution_result_denies_eof_by_default() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_012",
        spec=BlockSpec(
            code="input()\ninput()\n",
            stdin="one\n",
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="one\n",
            stderr="EOFError: EOF when reading a line\n",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_INPUT_REQUIRED_OR_INVALID
    assert result.error_type == "EOFError"


def test_stdin_exhaustion_accept_does_not_accept_manual_eof_error() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_manual_eof",
        spec=BlockSpec(
            code="raise EOFError('manual failure')\n",
            stdin="",
            meta={"stdin_exhaustion": "accept"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr="EOFError: manual failure\n",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_INPUT_REQUIRED_OR_INVALID
    assert result.error_type == "EOFError"
    assert result.error_message == "manual failure"


def test_stdin_exhaustion_accept_does_not_accept_name_error() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_013",
        spec=BlockSpec(
            code="print(missing_name)\n",
            stdin="",
            meta={"stdin_exhaustion": "accept"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr="NameError: name 'missing_name' is not defined\n",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_NAME_ERROR


def test_stdin_exhaustion_accept_does_not_accept_value_error() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_014",
        spec=BlockSpec(
            code="int('bad')\n",
            stdin="",
            meta={"stdin_exhaustion": "accept"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr="ValueError: invalid literal for int()\n",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_RUNTIME_ERROR


def test_stdin_exhaustion_accept_does_not_accept_timeout() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_015",
        spec=BlockSpec(
            code="while True:\n    pass\n",
            stdin="",
            meta={"stdin_exhaustion": "accept"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=None,
            duration_ms=101,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=True,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_TIMEOUT


def test_nondeterministic_mode_does_not_accept_syntax_error() -> None:
    parse_result = ParseResult(
        parse_success=True,
        block_id="block_016",
        spec=BlockSpec(
            code="else\n",
            stdin="",
            meta={"output_determinism": "nondeterministic"},
        ),
    )

    result = build_execution_result(
        parse_result,
        ProcessOutcome(
            exit_code=1,
            duration_ms=5,
            stdout="",
            stderr="SyntaxError: invalid syntax\n",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
        ),
    )

    assert result.status == STATUS_FAILED
    assert result.category == CATEGORY_SYNTAX_ERROR
