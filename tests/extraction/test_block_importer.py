from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

from qa_platform.contract.parser import BlockSpecParser
from qa_platform.chapter.runner import _discover_block_files
from qa_platform.extraction.block_importer import (
    import_extracted_chapter_blocks,
    import_raw_block_files,
    main as importer_main,
    normalize_raw_block_text,
)


def test_extraction_block_importer_module_help_invokes_main() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, "-m", "qa_platform.extraction.block_importer", "--help"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )

    assert result.returncode == 0
    assert "Import raw extractor block_*.txt files" in result.stdout
    assert "--output-dir" in result.stdout


def test_normalize_raw_block_text_matches_qa_block_contract() -> None:
    raw_text = """[META]
page : 3
code_type : COMPLETE_CODE
input_source : ai_generated
output_source : sample

[PACKAGES]
NONE

[CODE]
name = input("name: ")
print(name)

[INPUT]
Ada

[OUTPUT]
Ada
"""

    normalized = normalize_raw_block_text(raw_text)

    assert "[META]\npage=3\ncode_type=COMPLETE_CODE\n" in normalized
    assert "input_source=generated_sample" in normalized
    assert "output_source=generated_sample" in normalized
    assert "[PACKAGES]\n\n[SETUP]\n\n[CODE]" in normalized
    assert "[INPUT]\nAda\n\n[OUTPUT]" in normalized


def test_import_raw_block_files_renames_and_parses_blocks(tmp_path) -> None:
    source_dir = tmp_path / "raw_output"
    source_dir.mkdir()
    (source_dir / "block_2.txt").write_text(
        """[META]
page : 2
input_source : empty
output_source : empty

[PACKAGES]
NONE

[CODE]
print("two")

[INPUT]
NONE

[OUTPUT]
NONE
""",
        encoding="utf-8",
    )
    (source_dir / "block_10.txt").write_text(
        """[META]
page : 10
input_source : textbook
output_source : sample

[PACKAGES]
requests

[CODE]
print("ten")

[INPUT]
NONE

[OUTPUT]
ten
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "qa_blocks"
    result = import_raw_block_files(source_dir, output_dir)

    assert result.output_dir == output_dir
    assert [path.name for path in result.block_files] == [
        "block_001.txt",
        "block_002.txt",
    ]

    block_files, warnings = _discover_block_files(output_dir)
    assert [path.name for path in block_files] == [
        "block_001.txt",
        "block_002.txt",
    ]
    assert warnings == []

    parse_dir = tmp_path / "parse_block"
    parse_dir.mkdir()
    (parse_dir / "block.txt").write_text(
        (output_dir / "block_001.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    parse_result = BlockSpecParser().parse_block_dir(parse_dir)

    assert parse_result.parse_success is True
    assert parse_result.spec is not None
    assert parse_result.spec.stdin == ""
    assert parse_result.spec.expected_output == ""
    assert parse_result.spec.packages == []
    assert parse_result.spec.meta == {
        "page": "2",
        "input_source": "empty",
        "output_source": "empty",
    }


def test_import_raw_block_files_preserves_setup_section(tmp_path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "block_1.txt").write_text(
        "[META]\npage : 15\n\n"
        "[PACKAGES]\nNONE\n\n"
        "[SETUP]\ndef greet(name, msg):\n    print(name, msg)\n\n"
        "[CODE]\ngreet(\"영희\")\n\n"
        "[INPUT]\nNONE\n\n"
        "[OUTPUT]\nTypeError: greet() missing 1 required positional argument: 'msg'\n",
        encoding="utf-8",
    )

    result = import_raw_block_files(source_dir, tmp_path / "out")

    assert result.block_files == [tmp_path / "out" / "block_001.txt"]
    imported = result.block_files[0].read_text(encoding="utf-8")
    assert "[SETUP]\ndef greet(name, msg):" in imported
    assert "[CODE]\ngreet(\"영희\")" in imported


def test_import_extracted_chapter_blocks_creates_default_output_dir(
    tmp_path,
) -> None:
    source_dir = tmp_path / "raw_output"
    source_dir.mkdir()
    (source_dir / "block_1.txt").write_text(
        """[META]
page : 1

[PACKAGES]
NONE

[CODE]
print("hello")

[INPUT]
NONE

[OUTPUT]
hello
""",
        encoding="utf-8",
    )
    fixed_time = datetime(2026, 6, 30, 12, 34, 56, tzinfo=timezone.utc)

    result = import_extracted_chapter_blocks(
        source_dir,
        output_root=tmp_path / "extracted_blocks",
        book_id="python_junior",
        chapter_number=2,
        clock=lambda: fixed_time,
    )

    assert result.output_dir == (
        tmp_path / "extracted_blocks" / "python_junior_ch2_260630_123456"
    )
    assert [path.name for path in result.block_files] == ["block_001.txt"]
    assert result.block_files[0].exists()


def test_import_extracted_chapter_blocks_defaults_to_top_level_extracted_blocks(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source_dir = tmp_path / "raw_output"
    source_dir.mkdir()
    (source_dir / "block_1.txt").write_text(
        """[META]
page : 1

[PACKAGES]
NONE

[CODE]
print("hello")

[INPUT]
NONE

[OUTPUT]
hello
""",
        encoding="utf-8",
    )

    result = import_extracted_chapter_blocks(
        source_dir,
        book_id="python_junior",
        chapter_number=2,
        session_id="260702_143015",
    )

    assert result.output_dir == (
        Path("extracted_blocks") / "python_junior_ch2_260702_143015"
    )
    assert result.output_dir.resolve() == (
        tmp_path / "extracted_blocks" / "python_junior_ch2_260702_143015"
    )
    assert [path.name for path in result.block_files] == ["block_001.txt"]


def test_importer_main_supports_explicit_output_dir(
    tmp_path,
    capsys,
) -> None:
    source_dir = tmp_path / "raw_output"
    source_dir.mkdir()
    (source_dir / "block_1.txt").write_text(
        """[META]
page : 1

[PACKAGES]
NONE

[CODE]
print("hello")

[INPUT]
NONE

[OUTPUT]
hello
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "qa_blocks"

    exit_code = importer_main(
        [
            str(source_dir),
            "--output-dir",
            str(output_dir),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Imported 1 blocks" in captured.out
    assert str(output_dir) in captured.out
    assert (output_dir / "block_001.txt").exists()
