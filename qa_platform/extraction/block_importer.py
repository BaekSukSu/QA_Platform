from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from qa_platform.contract.constants import (
    SECTION_CODE,
    SECTION_INPUT,
    SECTION_META,
    SECTION_OUTPUT,
    SECTION_PACKAGES,
    SECTION_SETUP,
)
from qa_platform.shared.session import build_session_id


BLOCK_FILE_PATTERN = re.compile(r"^block_(?P<number>\d+)\.txt$")
SECTION_HEADER_PATTERN = re.compile(r"^\[(?P<name>[A-Z_]+)\]\s*$")
SOURCE_VALUE_MAP = {
    "ai_generated": "generated_sample",
    "sample": "generated_sample",
}
CANONICAL_SECTION_ORDER = [
    SECTION_META,
    SECTION_PACKAGES,
    SECTION_SETUP,
    SECTION_CODE,
    SECTION_INPUT,
    SECTION_OUTPUT,
]


@dataclass(frozen=True)
class BlockImportResult:
    output_dir: Path
    block_files: list[Path]


def import_extracted_chapter_blocks(
    source_dir: Path,
    *,
    output_root: Path = Path("extracted_blocks"),
    book_id: str,
    chapter_number: int,
    clock: Callable[[], datetime] | None = None,
    session_id: str | None = None,
) -> BlockImportResult:
    resolved_session_id = session_id or build_session_id(clock)
    output_dir = (
        output_root
        / f"{book_id}_ch{chapter_number}_{resolved_session_id}"
    )
    return import_raw_block_files(source_dir, output_dir)


def import_raw_block_files(
    source_dir: Path,
    output_dir: Path,
) -> BlockImportResult:
    source_paths = _find_raw_block_files(source_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    for index, source_path in enumerate(source_paths, start=1):
        output_path = output_dir / f"block_{index:03d}.txt"
        normalized_text = normalize_raw_block_text(
            source_path.read_text(encoding="utf-8-sig")
        )
        output_path.write_text(normalized_text, encoding="utf-8")
        output_paths.append(output_path)

    return BlockImportResult(output_dir=output_dir, block_files=output_paths)


def normalize_raw_block_text(raw_text: str) -> str:
    sections = _parse_sections(raw_text)
    normalized_sections: dict[str, list[str]] = {}

    for section in CANONICAL_SECTION_ORDER:
        lines = sections.get(section, [])
        if section == SECTION_META:
            normalized_sections[section] = _normalize_meta_lines(lines)
        else:
            normalized_sections[section] = _normalize_body_lines(lines)

    return _render_sections(normalized_sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import raw extractor block_*.txt files into the "
            "QA_Platform block_###.txt contract."
        )
    )
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("extracted_blocks"),
    )
    parser.add_argument("--book-id")
    parser.add_argument("--chapter-number", type=int)
    parser.add_argument("--session-id")
    args = parser.parse_args(argv)

    if args.output_dir is not None:
        result = import_raw_block_files(args.source_dir, args.output_dir)
    else:
        if args.book_id is None or args.chapter_number is None:
            parser.error(
                "--book-id and --chapter-number are required when "
                "--output-dir is omitted"
            )
        result = import_extracted_chapter_blocks(
            args.source_dir,
            output_root=args.output_root,
            book_id=args.book_id,
            chapter_number=args.chapter_number,
            session_id=args.session_id,
        )

    print(f"Imported {len(result.block_files)} blocks into {result.output_dir}")
    return 0


def _find_raw_block_files(source_dir: Path) -> list[Path]:
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_dir}")

    block_paths = [
        path
        for path in source_dir.iterdir()
        if path.is_file() and BLOCK_FILE_PATTERN.fullmatch(path.name)
    ]
    if not block_paths:
        raise FileNotFoundError(f"No block_*.txt files found in {source_dir}")

    return sorted(
        block_paths,
        key=lambda path: int(BLOCK_FILE_PATTERN.fullmatch(path.name).group("number")),
    )


def _parse_sections(raw_text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = SECTION_HEADER_PATTERN.fullmatch(line.strip())
        if match is not None:
            current_section = match.group("name")
            sections[current_section] = []
            continue
        if current_section is not None:
            sections[current_section].append(line)

    return {
        section: _trim_boundary_blank_lines(lines)
        for section, lines in sections.items()
    }


def _normalize_meta_lines(lines: list[str]) -> list[str]:
    normalized_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "":
            continue
        key, value = _split_meta_line(stripped)
        value = SOURCE_VALUE_MAP.get(value, value)
        normalized_lines.append(f"{key}={value}")
    return normalized_lines


def _split_meta_line(line: str) -> tuple[str, str]:
    if "=" in line:
        key, value = line.split("=", 1)
    elif ":" in line:
        key, value = line.split(":", 1)
    else:
        raise ValueError(f"Invalid META line: {line}")

    key = key.strip()
    value = value.strip()
    if key == "":
        raise ValueError(f"Invalid META line: {line}")
    return key, value


def _normalize_body_lines(lines: list[str]) -> list[str]:
    trimmed_lines = _trim_boundary_blank_lines(lines)
    if len(trimmed_lines) == 1 and trimmed_lines[0].strip().upper() == "NONE":
        return []
    return trimmed_lines


def _trim_boundary_blank_lines(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)

    while start < end and lines[start].strip() == "":
        start += 1
    while end > start and lines[end - 1].strip() == "":
        end -= 1

    return lines[start:end]


def _render_sections(sections: dict[str, list[str]]) -> str:
    rendered_parts: list[str] = []
    for section in CANONICAL_SECTION_ORDER:
        lines = sections[section]
        body = "\n".join(lines)
        if body:
            rendered_parts.append(f"[{section}]\n{body}")
        else:
            rendered_parts.append(f"[{section}]")
    return "\n\n".join(rendered_parts) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
