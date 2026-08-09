from pathlib import Path

import pytest

from qa_platform.contract.parser import BlockSpecParser
from qa_platform.contract.constants import (
    PARSER_ERROR_CONTENT_BEFORE_HEADER,
    PARSER_ERROR_DUPLICATE_SECTION,
    PARSER_ERROR_EMPTY_CODE,
    PARSER_ERROR_INVALID_META,
    PARSER_ERROR_MISSING_SECTION,
)
from qa_platform.shared.json_io import read_json


def write_block(block_dir: Path, content: str, encoding: str = "utf-8") -> None:
    block_dir.mkdir()
    (block_dir / "block.txt").write_text(content, encoding=encoding)


def parse_block(block_dir: Path):
    return BlockSpecParser().parse_block_dir(block_dir)


def test_parse_normal_block_writes_success_artifacts(tmp_path) -> None:
    block_dir = tmp_path / "block_001"
    write_block(
        block_dir,
        """  [CODE]\x20\x20

print('hello')

[INPUT]

Alice

[PACKAGES]
numpy
numpy==1.26.4
pandas>=2.0
[META]
input_source=textbook
output_source=generated_sample
[OUTPUT]
hello
""",
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.block_id == "block_001"
    assert result.spec is not None
    assert result.spec.code == "print('hello')\n"
    assert result.spec.stdin == "Alice\n"
    assert [package.to_dict() for package in result.spec.packages] == [
        {"name": "numpy", "specifier": "", "raw": "numpy"},
        {"name": "numpy", "specifier": "==1.26.4", "raw": "numpy==1.26.4"},
        {"name": "pandas", "specifier": ">=2.0", "raw": "pandas>=2.0"},
    ]
    assert result.spec.expected_output == "hello\n"
    assert result.spec.meta == {
        "input_source": "textbook",
        "output_source": "generated_sample",
    }
    assert (
        (block_dir / "normalized.py").read_text(encoding="utf-8")
        == "print('hello')\n"
    )
    assert (block_dir / "stdin.txt").read_text(encoding="utf-8") == "Alice\n"
    assert read_json(block_dir / "block.json") == result.to_dict()


def test_parse_allows_empty_input_packages_output_and_meta(tmp_path) -> None:
    block_dir = tmp_path / "block_002"
    write_block(
        block_dir,
        """[CODE]
print('hello')
[INPUT]
[PACKAGES]
[OUTPUT]
[META]
""",
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.stdin == ""
    assert result.spec.packages == []
    assert result.spec.expected_output == ""
    assert result.spec.meta == {}
    assert (block_dir / "stdin.txt").read_text(encoding="utf-8") == ""


def test_parse_ignores_none_package_marker(tmp_path) -> None:
    block_dir = tmp_path / "block_none_packages"
    write_block(
        block_dir,
        """[CODE]
print('hello')
[INPUT]
[PACKAGES]
NONE
none
[OUTPUT]
hello
[META]
""",
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.packages == []


def test_parse_preserves_bracket_literals_in_output_section(tmp_path) -> None:
    block_dir = tmp_path / "block_output_literals"
    write_block(
        block_dir,
        """[META]
page=3
code_type=COMPLETE_CODE
input_source=empty
output_source=textbook

[PACKAGES]

[CODE]
values = [1, 2, 3]
values

[INPUT]

[OUTPUT]
[1, 2, 3]
['Kim', 178.9, 'Park', 173.5]
[(x, y) for x in [1,2,3] for y in [3,1,4] if x != y]
""",
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.expected_output == (
        "[1, 2, 3]\n"
        "['Kim', 178.9, 'Park', 173.5]\n"
        "[(x, y) for x in [1,2,3] for y in [3,1,4] if x != y]\n"
    )


def test_parse_optional_setup_section_writes_executable_source(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_setup"
    write_block(
        block_dir,
        """[META]
execution_mode=repl

[PACKAGES]

[SETUP]
def greet(name, msg):
    print("안녕 ", name + ', ' + msg)

[CODE]
greet("영희")

[INPUT]

[OUTPUT]
TypeError: greet() missing 1 required positional argument: 'msg'
""",
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.setup_code == (
        'def greet(name, msg):\n'
        '    print("안녕 ", name + \', \' + msg)\n'
    )
    assert result.spec.code == 'greet("영희")\n'
    assert (block_dir / "normalized.py").read_text(encoding="utf-8") == (
        'def greet(name, msg):\n'
        '    print("안녕 ", name + \', \' + msg)\n'
        "\n"
        'greet("영희")\n'
    )


def test_parse_treats_non_contract_bracket_header_as_section_text(
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_non_contract_bracket"
    write_block(
        block_dir,
        """[CODE]
print('hello')
[INPUT]
[FILES]
data.txt
[PACKAGES]
[OUTPUT]
hello
[META]
""",
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.stdin == "[FILES]\ndata.txt\n"


def test_parse_reads_utf8_sig_and_normalizes_crlf(tmp_path) -> None:
    block_dir = tmp_path / "block_003"
    block_dir.mkdir()
    (block_dir / "block.txt").write_text(
        "[CODE]\r\n"
        "print('hello')\r\n"
        "[INPUT]\r\n"
        "x\r\n"
        "[PACKAGES]\r\n"
        "[META]\r\n"
        "[OUTPUT]\r\n"
        "hello\r\n",
        encoding="utf-8-sig",
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.code == "print('hello')\n"
    assert result.spec.stdin == "x\n"
    assert result.spec.expected_output == "hello\n"


@pytest.mark.parametrize(
    ("output_determinism", "stdin_exhaustion"),
    [
        ("deterministic", "deny"),
        ("deterministic", "accept"),
        ("nondeterministic", "deny"),
        ("nondeterministic", "accept"),
    ],
)
def test_parse_accepts_execution_policy_meta(
    tmp_path,
    output_determinism: str,
    stdin_exhaustion: str,
) -> None:
    block_dir = tmp_path / "block_policy"
    write_block(
        block_dir,
        (
            "[CODE]\nprint('hello')\n"
            "[INPUT]\n"
            "[PACKAGES]\n"
            "[OUTPUT]\nhello\n"
            "[META]\n"
            f"output_determinism={output_determinism}\n"
            f"stdin_exhaustion={stdin_exhaustion}\n"
        ),
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.meta == {
        "output_determinism": output_determinism,
        "stdin_exhaustion": stdin_exhaustion,
    }


@pytest.mark.parametrize(
    "code_type",
    ["COMPLETE_CODE", "INCOMPLETE_SNIPPET", "ERROR_FINDING"],
)
def test_parse_accepts_code_type_meta(tmp_path, code_type: str) -> None:
    block_dir = tmp_path / "block_code_type"
    write_block(
        block_dir,
        (
            "[CODE]\nprint('hello')\n"
            "[INPUT]\n"
            "[PACKAGES]\n"
            "[OUTPUT]\nhello\n"
            "[META]\n"
            f"code_type={code_type}\n"
        ),
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.meta == {"code_type": code_type}


def test_parse_allows_missing_execution_mode_meta(tmp_path) -> None:
    block_dir = tmp_path / "block_missing_execution_mode"
    write_block(
        block_dir,
        (
            "[CODE]\nprint('hello')\n"
            "[INPUT]\n"
            "[PACKAGES]\n"
            "[OUTPUT]\nhello\n"
            "[META]\n"
            "code_type=COMPLETE_CODE\n"
            "output_source=textbook\n"
        ),
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert "execution_mode" not in result.spec.meta


@pytest.mark.parametrize("execution_mode", ["script", "repl"])
def test_parse_accepts_execution_mode_meta(
    tmp_path,
    execution_mode: str,
) -> None:
    block_dir = tmp_path / "block_execution_mode"
    write_block(
        block_dir,
        (
            "[CODE]\nvalue\n"
            "[INPUT]\n"
            "[PACKAGES]\n"
            "[OUTPUT]\n10\n"
            "[META]\n"
            "code_type=COMPLETE_CODE\n"
            f"execution_mode={execution_mode}\n"
            "output_source=textbook\n"
        ),
    )

    result = parse_block(block_dir)

    assert result.parse_success is True
    assert result.spec is not None
    assert result.spec.meta["execution_mode"] == execution_mode


@pytest.mark.parametrize(
    "meta_line",
    [
        "output_determinism=random",
        "mode=random",
        "stdin_exhaustion=ignore",
        "code_type=INCOMPLETE_CODE",
        "execution_mode=notebook",
        "execution_mode=console",
        "execution_mode=python",
    ],
)
def test_parse_rejects_invalid_execution_policy_meta(
    tmp_path,
    meta_line: str,
) -> None:
    block_dir = tmp_path / "block_invalid_policy"
    write_block(
        block_dir,
        (
            "[CODE]\nprint('hello')\n"
            "[INPUT]\n"
            "[PACKAGES]\n"
            "[OUTPUT]\nhello\n"
            f"[META]\n{meta_line}\n"
        ),
    )

    result = parse_block(block_dir)

    assert result.parse_success is False
    assert result.error is not None
    assert result.error.error_type == PARSER_ERROR_INVALID_META


@pytest.mark.parametrize(
    ("content", "error_type"),
    [
        (
            """[CODE]
print('hello')
[INPUT]
[PACKAGES]
[OUTPUT]
""",
            PARSER_ERROR_MISSING_SECTION,
        ),
        (
            """[CODE]
print('hello')
[CODE]
print('again')
[INPUT]
[PACKAGES]
[OUTPUT]
[META]
""",
            PARSER_ERROR_DUPLICATE_SECTION,
        ),
        (
            """text before header
[CODE]
print('hello')
[INPUT]
[PACKAGES]
[OUTPUT]
[META]
""",
            PARSER_ERROR_CONTENT_BEFORE_HEADER,
        ),
        (
            """[CODE]

[INPUT]
[PACKAGES]
[OUTPUT]
[META]
""",
            PARSER_ERROR_EMPTY_CODE,
        ),
        (
            """[CODE]
print('hello')
[INPUT]
[PACKAGES]
[OUTPUT]
[META]
input_source=external
""",
            PARSER_ERROR_INVALID_META,
        ),
        (
            """[CODE]
print('hello')
[INPUT]
[PACKAGES]
[OUTPUT]
[META]
broken_meta_line
""",
            PARSER_ERROR_INVALID_META,
        ),
        (
            """[CODE]
print('hello')
[INPUT]
[PACKAGES]
[OUTPUT]
[META]
=empty_key
""",
            PARSER_ERROR_INVALID_META,
        ),
    ],
)
def test_parse_failures_write_block_json_only(tmp_path, content, error_type) -> None:
    block_dir = tmp_path / "block_error"
    write_block(block_dir, content)

    result = parse_block(block_dir)

    assert result.parse_success is False
    assert result.block_id == "block_error"
    assert result.error is not None
    assert result.error.error_type == error_type
    assert read_json(block_dir / "block.json") == result.to_dict()
    assert not (block_dir / "normalized.py").exists()
    assert not (block_dir / "stdin.txt").exists()
