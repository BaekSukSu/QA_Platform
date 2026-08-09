from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest

from qa_platform.chapter.runner import ChapterRunner
from qa_platform.execution.docker import DockerBlockExecutor
from qa_platform.shared.json_io import read_json


RUN_DOCKER_TESTS = os.environ.get("QA_PLATFORM_RUN_DOCKER_TESTS") == "1"
FIXED_RUN_TIME = datetime(2026, 6, 22, 16, 30, 12, tzinfo=timezone.utc)

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not RUN_DOCKER_TESTS,
        reason="Set QA_PLATFORM_RUN_DOCKER_TESTS=1 to run Docker tests.",
    ),
]


BLOCK_CASES = [
    ("print('hello')\n", "", "hello\n"),
    ("name = input()\nprint(name)\n", "Ada\n", "Ada\n"),
    ("print(2 + 3)\n", "", "5\n"),
    ("for number in range(3):\n    print(number)\n", "", "0\n1\n2\n"),
    (
        "values = [3, 1, 2]\n"
        "print(','.join(str(value) for value in sorted(values)))\n",
        "",
        "1,2,3\n",
    ),
    (
        "text = input()\nprint(text.upper())\n",
        "python\n",
        "PYTHON\n",
    ),
    (
        "from pathlib import Path\n"
        "path = Path('sample.txt')\n"
        "path.write_text('saved', encoding='utf-8')\n"
        "print(path.read_text(encoding='utf-8'))\n",
        "",
        "saved\n",
    ),
    (
        "data = {'a': 1, 'b': 2}\nprint(sum(data.values()))\n",
        "",
        "3\n",
    ),
]


def write_chapter_blocks(blocks_dir: Path) -> None:
    blocks_dir.mkdir()
    for index, (code, stdin, expected_output) in enumerate(
        BLOCK_CASES,
        start=1,
    ):
        (blocks_dir / f"block_{index:03d}.txt").write_text(
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
                f"page={index}\n"
                "input_source=generated_sample\n"
                "output_source=generated_sample\n"
            ),
            encoding="utf-8",
        )


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


def test_chapter_runner_with_docker_executor(tmp_path) -> None:
    blocks_dir = tmp_path / "chapter_blocks"
    write_chapter_blocks(blocks_dir)
    runner = ChapterRunner(
        executor=DockerBlockExecutor(),
        clock=lambda: FIXED_RUN_TIME,
    )

    result = runner.run(blocks_dir, tmp_path / "run")

    assert result.run_id == "260622_163012"
    assert result.total_blocks == 8
    assert result.passed_blocks == 8
    assert result.failed_blocks == 0
    assert result.skipped_blocks == 0

    for number in range(1, 9):
        block_dir = result.run_dir / "blocks" / f"block_{number:03d}"
        assert {
            path.name for path in block_dir.iterdir()
        } >= {
            "block.txt",
            "block.json",
            "normalized.py",
            "stdin.txt",
            "result.json",
        }

    index_entries = [
        json.loads(line)
        for line in (result.run_dir / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(index_entries) == 8
    assert all(entry["status"] == "passed" for entry in index_entries)

    manifest = read_json(result.run_dir / "run_manifest.json")
    assert manifest["status"] == "completed"
    assert manifest["processed_blocks"] == 8
    assert manifest["passed_blocks"] == 8
    assert manifest["failed_blocks"] == 0
    assert manifest["skipped_blocks"] == 0

    report = read_json(result.report_json_path)
    assert report["summary"] == {
        "total_blocks": 8,
        "passed_blocks": 8,
        "failed_blocks": 0,
        "skipped_blocks": 0,
        "category_counts": {},
    }
    assert report["errors"] == []
    markdown = result.report_markdown_path.read_text(
        encoding="utf-8"
    )
    assert "실패 block이 없습니다." in markdown
    assert "건너뜀 block이 없습니다." in markdown
    assert managed_container_ids() == []
