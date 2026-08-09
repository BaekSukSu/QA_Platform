import json

from qa_platform.extraction.image_block_extractor import (
    IMAGE_OCR_PROMPT,
    extract_image_blocks_to_files,
    normalize_ocr_text,
)
from qa_platform.extraction import text_block_extractor
from qa_platform.extraction.text_block_extractor import extract_text_blocks_to_files
from qa_platform.extraction.text_block_extractor import CodeBlock
from qa_platform.extraction.text_block_extractor import should_extract_text_page
from qa_platform.extraction.text_block_extractor import TEXT_EXTRACTION_PROMPT


def test_normalize_ocr_text_adds_page_meta() -> None:
    raw = """[META]
code_type : COMPLETE_CODE

[PACKAGES]
NONE

[CODE]
print("hello")

[INPUT]
NONE

[OUTPUT]
hello"""

    assert normalize_ocr_text(raw, "7") == (
        "[META]\n"
        "page : 7\n"
        "source_kind : image\n"
        "code_type : COMPLETE_CODE\n"
        "execution_mode : script\n\n"
        "[PACKAGES]\n"
        "NONE\n\n"
        "[CODE]\n"
        'print("hello")\n\n'
        "[INPUT]\n"
        "NONE\n\n"
        "[OUTPUT]\n"
        "hello"
    )


def test_normalize_ocr_text_preserves_execution_mode_meta() -> None:
    raw = """[META]
code_type : COMPLETE_CODE
execution_mode : "REPL"

[PACKAGES]
NONE

[CODE]
value

[INPUT]
NONE

[OUTPUT]
10"""

    assert normalize_ocr_text(raw, "12").startswith(
        "[META]\n"
        "page : 12\n"
        "source_kind : image\n"
        "code_type : COMPLETE_CODE\n"
        "execution_mode : repl\n\n"
    )


def test_normalize_ocr_text_defaults_missing_execution_mode_to_script() -> None:
    raw = """[META]
code_type : COMPLETE_CODE

[PACKAGES]
NONE

[CODE]
print("hello")

[INPUT]
NONE

[OUTPUT]
hello"""

    assert "execution_mode : script" in normalize_ocr_text(raw, "3")


def test_extract_text_blocks_to_files_uses_injected_client(tmp_path) -> None:
    text_path = tmp_path / "extracted_text.txt"
    text_path.write_text(
        "[page : 2]\n"
        "아래 코드를 실행하세요.\n"
        ">>> print('hello')\n"
        "hello\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "blocks"
    output_dir.mkdir()

    class FakeResponse:
        text = json.dumps(
            {
                "blocks": [
                    {
                        "code_type": "COMPLETE_CODE",
                        "execution_mode": "repl",
                        "packages": [],
                        "code": "print('hello')",
                        "user_input": "NONE",
                        "expected_output": "hello",
                    }
                ]
            }
        )

    class FakeModels:
        calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    client = FakeClient()

    count = extract_text_blocks_to_files(
        text_path,
        output_dir,
        start_idx=3,
        client=client,
    )

    assert count == 1
    assert (output_dir / "block_3.txt").read_text(encoding="utf-8") == (
        "[META]\n"
        "page : 2\n"
        "source_kind : text\n"
        "code_type : COMPLETE_CODE\n"
        "execution_mode : repl\n\n"
        "[PACKAGES]\n"
        "NONE\n\n"
        "[SETUP]\n"
        "NONE\n\n"
        "[CODE]\n"
        "print('hello')\n\n"
        "[INPUT]\n"
        "NONE\n\n"
        "[OUTPUT]\n"
        "hello"
    )
    prompt = client.models.calls[0]["contents"][0]
    assert "ERROR_FINDING" in prompt
    assert "INCOMPLETE_SNIPPET" in prompt
    assert "COMPLETE_CODE" in prompt
    assert "execution_mode" in prompt
    assert "setup_code" in prompt
    assert "FEW-SHOT" in prompt


def test_extract_text_blocks_to_files_skips_non_code_page_without_gemini_call(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(text_block_extractor.time, "sleep", lambda seconds: None)
    text_path = tmp_path / "extracted_text.txt"
    text_path.write_text(
        "[page : 8]\n"
        "이 단원에서는 문제 해결 과정을 단계별로 살펴봅니다.\n"
        "먼저 상황을 이해하고 필요한 정보를 정리한 다음, 알맞은 방법을 선택합니다.\n"
        "마지막으로 결과를 검토하여 더 나은 해결 방법을 생각해 봅니다.\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "blocks"
    output_dir.mkdir()
    calls = []

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("Gemini should not be called for prose pages")

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    count = extract_text_blocks_to_files(
        text_path,
        output_dir,
        start_idx=1,
        client=FakeClient(),
    )

    assert count == 0
    assert calls == []
    assert list(output_dir.iterdir()) == []


def test_text_page_prefilter_keeps_script_code_page(tmp_path) -> None:
    text_path = tmp_path / "extracted_text.txt"
    text_path.write_text(
        "[page : 9]\n"
        "다음 코드를 실행하여 이름을 입력받고 인사말을 출력합니다.\n"
        "name = input('name: ')\n"
        "print('Hello', name)\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "blocks"
    output_dir.mkdir()
    calls = []

    class FakeResponse:
        text = json.dumps(
            {
                "blocks": [
                    {
                        "code_type": "COMPLETE_CODE",
                        "execution_mode": "script",
                        "packages": [],
                        "setup_code": "NONE",
                        "code": "name = input('name: ')\nprint('Hello', name)",
                        "user_input": "NONE",
                        "expected_output": "NONE",
                    }
                ]
            }
        )

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    count = extract_text_blocks_to_files(
        text_path,
        output_dir,
        start_idx=1,
        client=FakeClient(),
    )

    assert count == 1
    assert len(calls) == 1
    assert "name = input" in (output_dir / "block_1.txt").read_text(
        encoding="utf-8",
    )


def test_text_page_prefilter_keeps_future_run_skip_code_page(tmp_path) -> None:
    text_path = tmp_path / "extracted_text.txt"
    text_path.write_text(
        "[page : 10]\n"
        "외부 파일에서 데이터를 읽는 예제입니다.\n"
        "data = open('sample.csv').read()\n"
        "print(data)\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "blocks"
    output_dir.mkdir()
    calls = []

    class FakeResponse:
        text = json.dumps({"blocks": []})

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    count = extract_text_blocks_to_files(
        text_path,
        output_dir,
        start_idx=1,
        client=FakeClient(),
    )

    assert count == 0
    assert len(calls) == 1
    assert list(output_dir.iterdir()) == []


def test_text_page_prefilter_keeps_identifier_function_and_method_calls() -> None:
    assert should_extract_text_page("calculate_total(10, 20)\n30")
    assert should_extract_text_page("student.average(score)")
    assert not should_extract_text_page("교재의 그림(1)을 보고 내용을 정리합니다.")


def test_text_page_prefilter_keeps_bare_expression_examples() -> None:
    assert should_extract_text_page("다음 식의 실행 결과입니다.\n3 + 4\n7")
    assert should_extract_text_page("score >= 80\nTrue")
    assert should_extract_text_page(
        "다음 식의 실행 결과입니다.\n"
        "'Python' + 'Programming'\n"
        "'PythonProgramming'"
    )
    assert should_extract_text_page(
        '다음 식의 실행 결과입니다.\n"Hi" * 3\n"HiHiHi"'
    )
    assert not should_extract_text_page("3-4단원에서는 자료/정보를 비교합니다.")


def test_text_page_prefilter_keeps_container_and_indexing_examples() -> None:
    assert should_extract_text_page("리스트 자료형\n[10, 20, 30]")
    assert should_extract_text_page('딕셔너리 자료형\n{"name": "Kim", "age": 20}')
    assert should_extract_text_page("문자열 인덱싱과 슬라이싱\ns[1:3]")
    assert should_extract_text_page("numbers[0]\n10")

    assert not should_extract_text_page("교재의 그림(1)을 보고 내용을 정리합니다.")
    assert not should_extract_text_page("3-4단원에서는 자료/정보를 비교합니다.")


def test_code_block_requires_known_execution_mode() -> None:
    block = CodeBlock(
        code_type="COMPLETE_CODE",
        execution_mode="script",
        packages=[],
        code="print('hello')",
        user_input="NONE",
        expected_output="hello",
    )

    assert block.execution_mode == "script"

    try:
        CodeBlock(
            code_type="COMPLETE_CODE",
            execution_mode="notebook",
            packages=[],
            code="print('hello')",
            user_input="NONE",
            expected_output="hello",
        )
    except Exception as exc:
        assert "execution_mode" in str(exc)
    else:
        raise AssertionError("unknown execution_mode should fail validation")


def test_extract_text_blocks_to_files_defaults_missing_execution_mode_to_script(
    tmp_path,
) -> None:
    text_path = tmp_path / "extracted_text.txt"
    text_path.write_text(
        "[page : 4]\n"
        "아래 코드를 실행하세요.\n"
        "print('hello')\n"
        "hello\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "blocks"
    output_dir.mkdir()

    class FakeResponse:
        text = json.dumps(
            {
                "blocks": [
                    {
                        "code_type": "COMPLETE_CODE",
                        "packages": [],
                        "code": "print('hello')",
                        "user_input": "NONE",
                        "expected_output": "hello",
                    }
                ]
            }
        )

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    count = extract_text_blocks_to_files(
        text_path,
        output_dir,
        start_idx=1,
        client=FakeClient(),
    )

    assert count == 1
    assert "execution_mode : script" in (
        output_dir / "block_1.txt"
    ).read_text(encoding="utf-8")


def test_text_extractor_writes_setup_section(tmp_path) -> None:
    class FakeResponse:
        text = json.dumps(
            {
                "blocks": [
                    {
                        "code_type": "COMPLETE_CODE",
                        "execution_mode": "repl",
                        "packages": [],
                        "setup_code": "def greet(name, msg):\n    print(name, msg)",
                        "code": 'greet("영희")',
                        "user_input": "NONE",
                        "expected_output": (
                            "TypeError: greet() missing 1 required positional "
                            'argument: "msg"'
                        ),
                    }
                ]
            }
        )

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    text_path = tmp_path / "extracted_text.txt"
    text_path.write_text(
        "[page : 15]\ndef greet(name, msg):\n"
        "    print(name, msg)\n>>> greet(\"영희\")\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "blocks"
    output_dir.mkdir()

    count = extract_text_blocks_to_files(
        text_path,
        output_dir,
        start_idx=1,
        client=FakeClient(),
    )

    assert count == 1
    assert "[SETUP]\ndef greet(name, msg):" in (
        output_dir / "block_1.txt"
    ).read_text(encoding="utf-8")


def test_text_extraction_prompt_defines_execution_mode_classification() -> None:
    prompt = TEXT_EXTRACTION_PROMPT

    assert "[EXECUTION MODE CLASSIFICATION]" in prompt
    assert 'execution_mode="repl"' in prompt
    assert 'execution_mode="script"' in prompt
    assert ">>> print(value)" in prompt
    assert "Do not rewrite expression statements into print(...)" in prompt
    assert 'prefer "script"' in prompt
    assert "Remove visible REPL prompt markers (>>> and ...)" in prompt
    assert 'execution_mode="repl"' in CodeBlock.model_fields["code"].description


def test_extraction_prompts_define_packages_as_external_pip_only() -> None:
    assert "external pip packages" in IMAGE_OCR_PROMPT
    assert "Do not list Python standard-library modules" in IMAGE_OCR_PROMPT
    assert "turtle, random" not in IMAGE_OCR_PROMPT

    assert "external pip packages" in TEXT_EXTRACTION_PROMPT
    assert "Do not list Python standard-library modules" in TEXT_EXTRACTION_PROMPT


def test_text_extraction_prompt_includes_repl_and_script_few_shots() -> None:
    prompt = TEXT_EXTRACTION_PROMPT

    assert '"execution_mode": "repl"' in prompt
    assert '"execution_mode": "script"' in prompt
    assert "temp_list = [1, 2, 3]" in prompt
    assert '"expected_output": "[1, 2, 3]"' in prompt
    assert "letters[0]" in prompt
    assert '"expected_output": "\'a\'\\n\'c\'"' in prompt
    assert 'name = input("name: ")' in prompt


def test_extract_image_blocks_to_files_uses_page_from_filename(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.extraction import image_block_extractor

    image_path = tmp_path / "4_9.bmp"
    image_path.write_bytes(b"image")
    output_dir = tmp_path / "blocks"
    output_dir.mkdir()

    monkeypatch.setattr(
        image_block_extractor,
        "process_image_ocr",
        lambda image_path, client: (
            "[META]\ncode_type : COMPLETE_CODE\n"
            "execution_mode : repl\n\n"
            "[PACKAGES]\nNONE\n\n"
            "[CODE]\nimage_value\n\n"
            "[INPUT]\nNONE\n\n"
            "[OUTPUT]\nimage",
            "success",
        ),
    )

    count = extract_image_blocks_to_files(
        [image_path],
        output_dir,
        start_idx=5,
        client=object(),
        keep_temp=True,
    )

    assert count == 1
    written = (output_dir / "block_5.txt").read_text(encoding="utf-8")
    assert "page : 9" in written
    assert "execution_mode : repl" in written
    assert image_path.exists()


def test_extract_image_blocks_to_files_skips_none_code(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.extraction import image_block_extractor

    image_path = tmp_path / "7_9.bmp"
    image_path.write_bytes(b"image")
    output_dir = tmp_path / "blocks"
    output_dir.mkdir()

    monkeypatch.setattr(
        image_block_extractor,
        "process_image_ocr",
        lambda image_path, client: (
            "[META]\ncode_type : COMPLETE_CODE\n\n"
            "[PACKAGES]\nNONE\n\n"
            "[CODE]\nNONE\n\n"
            "[INPUT]\nNONE\n\n"
            "[OUTPUT]\nNONE",
            "success",
        ),
    )

    count = extract_image_blocks_to_files(
        [image_path],
        output_dir,
        start_idx=1,
        client=object(),
        keep_temp=True,
    )

    assert count == 0
    assert list(output_dir.iterdir()) == []
    assert image_path.exists()


def test_image_ocr_prompt_defines_execution_mode_classification() -> None:
    prompt = IMAGE_OCR_PROMPT

    assert "execution_mode : <script_or_repl>" in prompt
    assert "execution_mode 'repl'" in prompt
    assert "execution_mode 'script'" in prompt
    assert ">>> print(value)" in prompt
    assert "Do not rewrite expression statements into print(...)" in prompt
    assert "Remove visible REPL prompt markers" in prompt
    assert "preserve that context by setting execution_mode : repl" in prompt


def test_image_ocr_prompt_forbids_inference_and_separates_ide_panes() -> None:
    prompt = IMAGE_OCR_PROMPT

    assert "Never infer hidden, cropped, blurred, or occluded code" in prompt
    assert "editor pane" in prompt
    assert "console pane" in prompt
    assert "runfile(" in prompt
    assert "visible characters only" in prompt
