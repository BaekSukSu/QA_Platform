from qa_platform.extraction.block_postprocessor import (
    classify_metadata_via_ai,
    generate_dummy_input_via_ai,
    is_runnable,
    merge_physical_blocks,
    normalize_external_package_sections,
    postprocess_extracted_blocks,
    parse_raw_block_file,
    predict_output_via_ai,
    save_raw_block_file,
    validate_extracted_outputs,
)


def test_is_runnable_rejects_unresolved_variable() -> None:
    ok, message = is_runnable("print(answer)")

    assert ok is False
    assert "answer" in message


def test_parse_and_save_block_file_preserves_sections(tmp_path) -> None:
    block_path = tmp_path / "block_1.txt"
    block_path.write_text(
        "[META]\n"
        "page : 2\n"
        "code_type : COMPLETE_CODE\n\n"
        "[PACKAGES]\n"
        "NONE\n\n"
        "[CODE]\n"
        "print('hello')\n\n"
        "[INPUT]\n"
        "NONE\n\n"
        "[OUTPUT]\n"
        "hello",
        encoding="utf-8",
    )

    block = parse_raw_block_file(block_path)
    block.meta["output_source"] = "textbook"
    output_path = tmp_path / "block_001.txt"
    save_raw_block_file(output_path, block)

    assert "output_source : textbook" in output_path.read_text(encoding="utf-8")


def test_parse_and_save_raw_block_preserves_setup_section(tmp_path) -> None:
    block_path = tmp_path / "block_1.txt"
    block_path.write_text(
        "[META]\npage : 15\n\n"
        "[PACKAGES]\nNONE\n\n"
        "[SETUP]\ndef greet(name, msg):\n    print(name, msg)\n\n"
        "[CODE]\ngreet(\"영희\")\n\n"
        "[INPUT]\nNONE\n\n"
        "[OUTPUT]\nTypeError: greet() missing 1 required positional argument: 'msg'\n",
        encoding="utf-8",
    )

    block = parse_raw_block_file(block_path)
    output_path = tmp_path / "block_001.txt"
    save_raw_block_file(output_path, block)

    saved = output_path.read_text(encoding="utf-8")
    assert "[SETUP]\ndef greet(name, msg):" in saved
    assert "[CODE]\ngreet(\"영희\")" in saved


def test_ai_helpers_use_injected_client() -> None:
    class FakeResponse:
        def __init__(self, text):
            self.text = text

    class FakeModels:
        def generate_content(self, **kwargs):
            joined = str(kwargs.get("contents", ""))
            if "JSON" in joined:
                return FakeResponse(
                    (
                        '{"output_determinism": "nondeterministic", '
                        '"stdin_exhaustion": "accept"}'
                    )
                )
            if "사용자 입력" in joined:
                return FakeResponse("0")
            return FakeResponse("<RESULT>\nhello\n</RESULT>")

    class FakeClient:
        models = FakeModels()

    client = FakeClient()

    assert predict_output_via_ai("print('hello')", "NONE", client) == "hello"
    assert generate_dummy_input_via_ai("value = input()", client) == "0"
    assert classify_metadata_via_ai("import random", client) == (
        "nondeterministic",
        "accept",
    )


def test_ai_helpers_treat_missing_response_text_as_none() -> None:
    class FakeResponse:
        text = None

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    client = FakeClient()

    assert generate_dummy_input_via_ai("value = input()", client) == "NONE"
    assert predict_output_via_ai("print('hello')", "NONE", client) == "NONE"
    assert classify_metadata_via_ai("print('hello')", client) == (
        "deterministic",
        "deny",
    )


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def generate_content(self, **kwargs):
        joined = str(kwargs.get("contents", ""))
        if "output_determinism" in joined and "stdin_exhaustion" in joined:
            return FakeResponse(
                (
                    '{"output_determinism": "deterministic", '
                    '"stdin_exhaustion": "deny"}'
                )
            )
        if "사용자 입력" in joined:
            return FakeResponse("Ada")
        return FakeResponse("<RESULT>\nAda\n</RESULT>")


class FakeClient:
    models = FakeModels()


def write_raw_block(
    path,
    *,
    page: str,
    code_type: str = "COMPLETE_CODE",
    packages: str = "NONE",
    setup_code: str = "NONE",
    code: str,
    input_text: str = "NONE",
    output_text: str = "NONE",
) -> None:
    path.write_text(
        "[META]\n"
        f"page : {page}\n"
        f"code_type : {code_type}\n\n"
        "[PACKAGES]\n"
        f"{packages}\n\n"
        "[SETUP]\n"
        f"{setup_code}\n\n"
        "[CODE]\n"
        f"{code}\n\n"
        "[INPUT]\n"
        f"{input_text}\n\n"
        "[OUTPUT]\n"
        f"{output_text}",
        encoding="utf-8",
    )


def write_raw_block_with_meta(
    path,
    *,
    meta_text: str,
    code: str,
    output_text: str = "NONE",
) -> None:
    path.write_text(
        "[META]\n"
        f"{meta_text}\n\n"
        "[PACKAGES]\n"
        "NONE\n\n"
        "[CODE]\n"
        f"{code}\n\n"
        "[INPUT]\n"
        "NONE\n\n"
        "[OUTPUT]\n"
        f"{output_text}",
        encoding="utf-8",
    )


def test_validate_extracted_outputs_corrects_small_image_ocr_output_loss(
    tmp_path,
) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text=(
            "page : 13\n"
            "source_kind : image\n"
            "code_type : COMPLETE_CODE\n"
            "execution_mode : repl\n"
            "output_source : textbook"
        ),
        code='print("Hello World!")',
        output_text="Hello World",
    )

    corrected_count = validate_extracted_outputs(tmp_path)

    assert corrected_count == 1
    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.output_text == "Hello World!"
    assert block.meta["output_validation"] == "corrected_by_execution"
    assert block.meta["output_correction_reason"] == "probable_ocr_loss"


def test_validate_extracted_outputs_corrects_repeated_text_truncation(
    tmp_path,
) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text=(
            "page : 20\n"
            "source_kind : image\n"
            "code_type : COMPLETE_CODE\n"
            "execution_mode : script\n"
            "output_source : textbook"
        ),
        code='print("얌얌"*10)',
        output_text="얌얌얌얌얌얌얌얌얌얌",
    )

    corrected_count = validate_extracted_outputs(tmp_path)

    assert corrected_count == 1
    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.output_text == "얌얌얌얌얌얌얌얌얌얌얌얌얌얌얌얌얌얌얌얌"
    assert block.meta["output_validation"] == "corrected_by_execution"


def test_validate_extracted_outputs_marks_image_alignment_mismatch(
    tmp_path,
) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text=(
            "page : 23\n"
            "source_kind : image\n"
            "code_type : COMPLETE_CODE\n"
            "execution_mode : script\n"
            "output_source : textbook"
        ),
        code=(
            'print("파이썬에 오신 것을 환영합니다!")\n'
            'print("프로그래밍 공부를 즐기셨으면 합니다.")'
        ),
        output_text=(
            "안녕하세요? 파이썬에 오신 것을 환영합니다!\n"
            "프로그래밍 공부를 즐기셨으면 합니다.\n"
            "안녕!안녕!안녕"
        ),
    )

    corrected_count = validate_extracted_outputs(tmp_path)

    assert corrected_count == 0
    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.meta["code_type"] == "INCOMPLETE_SNIPPET"
    assert block.meta["extraction_issue"] == "output_alignment_mismatch"
    assert block.meta["output_validation"] == "failed_execution_crosscheck"


def test_validate_extracted_outputs_skips_print_rebinding_payload(tmp_path) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text=(
            "page : 30\n"
            "source_kind : image\n"
            "code_type : COMPLETE_CODE\n"
            "execution_mode : script\n"
            "output_source : textbook"
        ),
        code=(
            "print = eval\n"
            'print("__import__(\'builtins\').print(5)")'
        ),
        output_text="5",
    )

    corrected_count = validate_extracted_outputs(tmp_path)

    assert corrected_count == 0
    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.meta["code_type"] == "COMPLETE_CODE"
    assert "output_validation" not in block.meta


def test_validate_extracted_outputs_skips_repl_expression_echo(tmp_path) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text=(
            "page : 31\n"
            "source_kind : image\n"
            "code_type : COMPLETE_CODE\n"
            "execution_mode : repl\n"
            "output_source : textbook"
        ),
        code="2 + 3",
        output_text="5",
    )

    corrected_count = validate_extracted_outputs(tmp_path)

    assert corrected_count == 0
    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.meta["code_type"] == "COMPLETE_CODE"
    assert "output_validation" not in block.meta


def test_validate_extracted_outputs_does_not_correct_ambiguous_numeric_prefix(
    tmp_path,
) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text=(
            "page : 32\n"
            "source_kind : image\n"
            "code_type : COMPLETE_CODE\n"
            "execution_mode : script\n"
            "output_source : textbook"
        ),
        code="print(10)",
        output_text="1",
    )

    corrected_count = validate_extracted_outputs(tmp_path)

    assert corrected_count == 0
    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.meta["code_type"] == "INCOMPLETE_SNIPPET"
    assert block.meta["output_validation"] == "failed_execution_crosscheck"
    assert "output_correction_reason" not in block.meta


def test_validate_extracted_outputs_skips_large_string_repetition(tmp_path) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text=(
            "page : 33\n"
            "source_kind : image\n"
            "code_type : COMPLETE_CODE\n"
            "execution_mode : script\n"
            "output_source : textbook"
        ),
        code='print("x" * 20001)',
        output_text="x",
    )

    corrected_count = validate_extracted_outputs(tmp_path)

    assert corrected_count == 0
    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.meta["code_type"] == "COMPLETE_CODE"
    assert "output_validation" not in block.meta


def test_merge_adds_script_execution_mode_for_missing_metadata(tmp_path) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text="",
        code="x = 1\nprint(x)",
        output_text="1",
    )

    merge_physical_blocks(tmp_path)

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "execution_mode : script" in processed


def test_merge_preserves_explicit_repl_execution_mode(tmp_path) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text="execution_mode : repl",
        code="print('hello')",
        output_text="hello",
    )

    merge_physical_blocks(tmp_path)

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "execution_mode : repl" in processed
    assert "execution_mode : script" not in processed


def test_merge_infers_repl_execution_mode_from_prompt_markers(tmp_path) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text="",
        code=">>> value",
        output_text="10",
    )

    merge_physical_blocks(tmp_path)

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "execution_mode : repl" in processed


def test_merge_infers_repl_execution_mode_for_expression_echo(tmp_path) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text="",
        code="values[1:]",
        output_text="[2, 3]",
    )

    merge_physical_blocks(tmp_path)

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "execution_mode : repl" in processed


def test_merge_infers_repl_execution_mode_for_call_expression_echo(
    tmp_path,
) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text="",
        code="len([1, 2, 3])",
        output_text="3",
    )

    merge_physical_blocks(tmp_path)

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "execution_mode : repl" in processed


def test_merge_keeps_user_defined_function_call_with_output_as_script(
    tmp_path,
) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text="",
        code='def main():\n    print("hi")\nmain()',
        output_text="hi",
    )

    merge_physical_blocks(tmp_path)

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "execution_mode : script" in processed
    assert "execution_mode : repl" not in processed


def test_postprocess_adds_setup_code_from_previous_definition(tmp_path) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="15",
        code=(
            "def greet(name, msg):\n"
            "    print(\"안녕 \", name + ', ' + msg)\n\n"
            "greet(\"철수\",\"좋은 아침!\")"
        ),
        output_text="안녕  철수, 좋은 아침!",
    )
    write_raw_block(
        tmp_path / "block_2.txt",
        page="15",
        code='greet("영희")',
        output_text=(
            "TypeError: greet() missing 1 required positional argument: 'msg'"
        ),
    )

    postprocess_extracted_blocks(tmp_path, client=FakeClient())

    processed = (tmp_path / "block_002.txt").read_text(encoding="utf-8")
    assert "[SETUP]\ndef greet(name, msg):" in processed
    assert "[CODE]\ngreet(\"영희\")" in processed
    assert "context_source_blocks : block_001" in processed
    assert "context_symbols : greet" in processed


def test_postprocess_normalizes_packages_to_external_requirements(tmp_path) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="22",
        packages="random\nPIL\ncv2",
        code=(
            "import random\n"
            "from PIL import Image\n"
            "import cv2\n"
            "print(random.randint(1, 2))"
        ),
        output_text="1",
    )

    postprocess_extracted_blocks(tmp_path, client=FakeClient())

    block = parse_raw_block_file(tmp_path / "block_001.txt")
    assert block.packages.splitlines() == ["opencv-python", "pillow"]
    assert "random" not in block.packages


def test_normalize_packages_preserves_declared_version_range(tmp_path) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="22",
        packages="numpy>=1,<2",
        code="import numpy as np\nprint(np.array([1]))",
        output_text="[1]",
    )

    normalize_external_package_sections(tmp_path)

    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.packages == "numpy>=1,<2"


def test_normalize_packages_splits_names_after_version_range(tmp_path) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="22",
        packages="numpy>=1,<2, pandas",
        code="import numpy as np\nimport pandas as pd\nprint(np.array([1]))",
        output_text="[1]",
    )

    normalize_external_package_sections(tmp_path)

    block = parse_raw_block_file(tmp_path / "block_1.txt")
    assert block.packages.splitlines() == ["numpy>=1,<2", "pandas"]


def test_postprocess_records_environment_modules_outside_packages(tmp_path) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="23",
        packages="turtle",
        code="import turtle\nturtle.forward(100)",
    )

    postprocess_extracted_blocks(tmp_path, client=FakeClient())

    block = parse_raw_block_file(tmp_path / "block_001.txt")
    assert block.packages == "NONE"
    assert block.meta["environment_modules"] == "turtle"


def test_postprocess_skips_ai_helpers_for_external_file_read_block(tmp_path) -> None:
    class NoCallModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("Gemini should not be called")

    class NoCallClient:
        def __init__(self):
            self.models = NoCallModels()

    client = NoCallClient()
    write_raw_block(
        tmp_path / "block_1.txt",
        page="24",
        code="print(open('sample.csv').read())",
        input_text="NONE",
        output_text="NONE",
    )

    postprocess_extracted_blocks(tmp_path, client=client)

    assert client.models.calls == []
    block = parse_raw_block_file(tmp_path / "block_001.txt")
    assert block.meta["run_skip_reason"] == "missing_required_file"
    assert block.meta["missing_required_files"] == "sample.csv"
    assert block.meta["output_source"] == "empty"
    assert block.meta["output_determinism"] == "deterministic"
    assert block.meta["stdin_exhaustion"] == "deny"


def test_postprocess_trusts_preclassified_missing_file_skip_before_ai(
    tmp_path,
) -> None:
    class NoCallModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("Gemini should not be called")

    class NoCallClient:
        def __init__(self):
            self.models = NoCallModels()

    client = NoCallClient()
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text=(
            "page : 24\n"
            "code_type : COMPLETE_CODE\n"
            "run_skip_reason : missing_required_file\n"
            "missing_required_files : sample.csv"
        ),
        code="name = input()\nprint(name)",
        output_text="NONE",
    )

    postprocess_extracted_blocks(tmp_path, client=client)

    assert client.models.calls == []
    block = parse_raw_block_file(tmp_path / "block_001.txt")
    assert block.meta["run_skip_reason"] == "missing_required_file"
    assert block.meta["missing_required_files"] == "sample.csv"
    assert block.meta["output_source"] == "empty"
    assert block.meta["output_determinism"] == "deterministic"
    assert block.meta["stdin_exhaustion"] == "deny"


def test_postprocess_skips_ai_helpers_for_environment_module_block(tmp_path) -> None:
    class NoCallModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("Gemini should not be called")

    class NoCallClient:
        def __init__(self):
            self.models = NoCallModels()

    client = NoCallClient()
    write_raw_block(
        tmp_path / "block_1.txt",
        page="25",
        code="import turtle\nturtle.forward(100)",
        input_text="NONE",
        output_text="NONE",
    )

    postprocess_extracted_blocks(tmp_path, client=client)

    assert client.models.calls == []
    block = parse_raw_block_file(tmp_path / "block_001.txt")
    assert block.meta["run_skip_reason"] == "environment_dependent"
    assert block.meta["environment_modules"] == "turtle"
    assert block.meta["output_source"] == "empty"
    assert block.meta["output_determinism"] == "deterministic"
    assert block.meta["stdin_exhaustion"] == "deny"


def test_postprocess_preserves_environment_skip_metadata_on_second_run(
    tmp_path,
) -> None:
    class NoCallModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("Gemini should not be called")

    class NoCallClient:
        def __init__(self):
            self.models = NoCallModels()

    client = NoCallClient()
    write_raw_block(
        tmp_path / "block_1.txt",
        page="26",
        packages="tkinter",
        code="print('ready')",
        input_text="NONE",
        output_text="NONE",
    )

    postprocess_extracted_blocks(tmp_path, client=client)
    postprocess_extracted_blocks(tmp_path, client=client)

    assert client.models.calls == []
    block = parse_raw_block_file(tmp_path / "block_001.txt")
    assert block.meta["run_skip_reason"] == "environment_dependent"
    assert block.meta["environment_modules"] == "tkinter"
    assert block.packages == "NONE"


def test_postprocess_marks_source_skipped_textbook_output(tmp_path) -> None:
    class NoCallModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("Gemini should not be called")

    class NoCallClient:
        def __init__(self):
            self.models = NoCallModels()

    client = NoCallClient()
    write_raw_block(
        tmp_path / "block_1.txt",
        page="27",
        code="print(open('sample.csv').read())",
        input_text="NONE",
        output_text="shown output",
    )

    postprocess_extracted_blocks(tmp_path, client=client)

    assert client.models.calls == []
    block = parse_raw_block_file(tmp_path / "block_001.txt")
    assert block.output_text == "shown output"
    assert block.meta["run_skip_reason"] == "missing_required_file"
    assert block.meta["output_source"] == "textbook"
    assert "output_validation" not in block.meta


def test_context_resolver_does_not_copy_previous_call_statement(
    tmp_path,
) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="15",
        code=(
            "def greet(name, msg):\n"
            "    print(name, msg)\n\n"
            "greet(\"철수\", \"좋은 아침!\")"
        ),
        output_text="철수 좋은 아침!",
    )
    write_raw_block(
        tmp_path / "block_2.txt",
        page="15",
        code='greet("영희")',
        output_text=(
            "TypeError: greet() missing 1 required positional argument: 'msg'"
        ),
    )

    postprocess_extracted_blocks(tmp_path, client=FakeClient())

    block = parse_raw_block_file(tmp_path / "block_002.txt")
    assert 'greet("철수", "좋은 아침!")' not in block.setup_code
    assert "def greet(name, msg):" in block.setup_code


def test_context_resolver_reuses_same_page_definition_for_multiple_blocks(
    tmp_path,
) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="16",
        code="def calc(x, y, z):\n    return x+y+z",
        output_text="NONE",
    )
    write_raw_block(
        tmp_path / "block_2.txt",
        page="16",
        code="calc(10, 20, 30)",
        output_text="60",
    )
    write_raw_block(
        tmp_path / "block_3.txt",
        page="16",
        code="calc(x=10, y=20, z=30)",
        output_text="60",
    )
    write_raw_block(
        tmp_path / "block_4.txt",
        page="16",
        code="calc(y=20, x=10, z=30)",
        output_text="60",
    )

    postprocess_extracted_blocks(tmp_path, client=FakeClient())

    for block_name in ("block_002.txt", "block_003.txt", "block_004.txt"):
        block = parse_raw_block_file(tmp_path / block_name)
        assert block.meta["code_type"] == "COMPLETE_CODE"
        assert block.meta["context_symbols"] == "calc"
        assert block.meta["context_source_blocks"] == "block_001"
        assert "def calc(x, y, z):" in block.setup_code


def test_context_resolver_does_not_promote_placeholder_snippet(
    tmp_path,
) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="9",
        code="def get_sum(start, end):\n    return sum(range(start, end+1))",
        output_text="NONE",
    )
    write_raw_block(
        tmp_path / "block_2.txt",
        page="9",
        code=(
            "value = get_sum(            ,             )\n"
            "def get_sum (                ,                ):\n"
            "    sum=0\n"
            "    for i in range(start, end+1):\n"
            "        sum += i\n"
            "    return sum"
        ),
        code_type="INCOMPLETE_SNIPPET",
        output_text="NONE",
    )

    postprocess_extracted_blocks(tmp_path, client=FakeClient())

    trash_files = sorted(
        (tmp_path.parent / "trashes").glob(f"{tmp_path.name}_unrunnable*")
    )
    assert trash_files
    trash_text = trash_files[0].read_text(encoding="utf-8")
    assert "INCOMPLETE_SNIPPET" in trash_text
    assert "def get_sum(start, end):" not in trash_text


def test_merge_ignores_prompt_markers_in_output_when_inferring_execution_mode(
    tmp_path,
) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text="",
        code='print(">>> prompt-looking output")',
        output_text=">>> prompt-looking output",
    )

    merge_physical_blocks(tmp_path)

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "execution_mode : script" in processed
    assert "execution_mode : repl" not in processed


def test_merge_keeps_print_only_output_block_as_script(tmp_path) -> None:
    write_raw_block_with_meta(
        tmp_path / "block_1.txt",
        meta_text="",
        code="print('hello')",
        output_text="hello",
    )

    merge_physical_blocks(tmp_path)

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "execution_mode : script" in processed
    assert "execution_mode : repl" not in processed


def test_postprocess_merges_dependent_blocks_and_discards_incomplete(
    tmp_path,
) -> None:
    write_raw_block(tmp_path / "block_1.txt", page="2", code="x = 1")
    write_raw_block(
        tmp_path / "block_2.txt",
        page="2",
        code="print(x)",
        output_text="1",
    )
    write_raw_block(
        tmp_path / "block_3.txt",
        page="6",
        code_type="INCOMPLETE_SNIPPET",
        code="print(missing)",
    )

    postprocess_extracted_blocks(tmp_path, client=FakeClient())

    remaining = sorted(path.name for path in tmp_path.glob("block_*.txt"))
    assert remaining == ["block_001.txt"]
    merged = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "x = 1\nprint(x)" in merged
    assert "output_source : textbook" in merged
    assert "output_determinism : deterministic" in merged
    assert "stdin_exhaustion : deny" in merged
    trashes = sorted(
        (tmp_path.parent / "trashes").glob(f"{tmp_path.name}_unrunnable*")
    )
    assert len(trashes) == 1
    assert "INCOMPLETE_SNIPPET" in trashes[0].read_text(encoding="utf-8")


def test_postprocess_generates_missing_input_and_output(tmp_path) -> None:
    write_raw_block(
        tmp_path / "block_1.txt",
        page="3",
        code="name = input()\nprint(name)",
    )

    postprocess_extracted_blocks(tmp_path, client=FakeClient())

    processed = (tmp_path / "block_001.txt").read_text(encoding="utf-8")
    assert "input_source : generated_sample" in processed
    assert "[INPUT]\nAda" in processed
    assert "output_source : generated_sample" in processed
    assert "[OUTPUT]\nAda" in processed
