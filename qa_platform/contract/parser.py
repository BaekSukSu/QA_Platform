from __future__ import annotations

import re
from pathlib import Path

from qa_platform.contract.constants import (
    ALLOWED_SECTIONS,
    META_ENUM_VALUES,
    PARSER_ERROR_CONTENT_BEFORE_HEADER,
    PARSER_ERROR_DUPLICATE_SECTION,
    PARSER_ERROR_EMPTY_CODE,
    PARSER_ERROR_INVALID_META,
    PARSER_ERROR_MISSING_SECTION,
    PARSER_ERROR_READ_ERROR,
    PARSER_ERROR_UNKNOWN_SECTION,
    SECTION_CODE,
    SECTION_INPUT,
    SECTION_META,
    SECTION_OUTPUT,
    SECTION_PACKAGES,
    SECTION_SETUP,
)
from qa_platform.contract.models import (
    BlockSpec,
    PackageSpec,
    ParseError,
    ParseResult,
)
from qa_platform.shared.json_io import write_json

REQUIRED_SECTIONS = [
    SECTION_CODE,
    SECTION_INPUT,
    SECTION_PACKAGES,
    SECTION_OUTPUT,
    SECTION_META,
]
PACKAGE_VERSION_OPERATOR_PATTERN = re.compile(r"(==|>=|<=|~=|!=|>|<)")


class BlockSpecParser:
    def parse_block_dir(self, block_dir: Path) -> ParseResult:
        block_path = block_dir / "block.txt"
        block_id = block_dir.name

        try:
            content = block_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            return self._write_failure(
                block_dir=block_dir,
                block_id=block_id,
                error_type=PARSER_ERROR_READ_ERROR,
                message=str(exc),
            )

        normalized_content = _normalize_line_endings(content)
        sections, parse_error = _scan_sections(normalized_content)
        if parse_error is not None:
            return self._write_failure_from_error(block_dir, block_id, parse_error)

        missing_section = _find_missing_section(sections)
        if missing_section is not None:
            return self._write_failure(
                block_dir=block_dir,
                block_id=block_id,
                error_type=PARSER_ERROR_MISSING_SECTION,
                message=f"Missing [{missing_section}] section.",
            )

        trimmed_sections = {
            section: _trim_boundary_blank_lines(lines)
            for section, lines in sections.items()
        }

        if not trimmed_sections[SECTION_CODE]:
            return self._write_failure(
                block_dir=block_dir,
                block_id=block_id,
                error_type=PARSER_ERROR_EMPTY_CODE,
                message="[CODE] section is empty.",
            )

        meta, parse_error = _parse_meta(trimmed_sections[SECTION_META])
        if parse_error is not None:
            return self._write_failure_from_error(block_dir, block_id, parse_error)

        setup_code = _lines_to_section_text(
            trimmed_sections.get(SECTION_SETUP, [])
        )
        code = _lines_to_section_text(trimmed_sections[SECTION_CODE])
        spec = BlockSpec(
            setup_code=setup_code,
            code=code,
            stdin=_lines_to_section_text(trimmed_sections[SECTION_INPUT]),
            packages=_parse_packages(trimmed_sections[SECTION_PACKAGES]),
            expected_output=_lines_to_section_text(trimmed_sections[SECTION_OUTPUT]),
            meta=meta,
        )
        result = ParseResult(parse_success=True, block_id=block_id, spec=spec)
        write_json(block_dir / "block.json", result.to_dict())
        (block_dir / "normalized.py").write_text(
            _build_executable_source(setup_code, code),
            encoding="utf-8",
        )
        (block_dir / "stdin.txt").write_text(spec.stdin, encoding="utf-8")
        return result

    def _write_failure(
        self,
        block_dir: Path,
        block_id: str,
        error_type: str,
        message: str,
        line: int | None = None,
    ) -> ParseResult:
        error = ParseError(error_type=error_type, message=message, line=line)
        return self._write_failure_from_error(block_dir, block_id, error)

    def _write_failure_from_error(
        self,
        block_dir: Path,
        block_id: str,
        error: ParseError,
    ) -> ParseResult:
        result = ParseResult(parse_success=False, block_id=block_id, error=error)
        write_json(block_dir / "block.json", result.to_dict())
        return result


def _normalize_line_endings(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _scan_sections(content: str) -> tuple[dict[str, list[str]], ParseError | None]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for line_number, line in enumerate(content.split("\n"), start=1):
        stripped_line = line.strip()
        header = _parse_section_header(stripped_line)

        if header is not None:
            if header not in ALLOWED_SECTIONS:
                return sections, ParseError(
                    error_type=PARSER_ERROR_UNKNOWN_SECTION,
                    message=f"Unknown section [{header}].",
                    line=line_number,
                )
            if header in sections:
                return sections, ParseError(
                    error_type=PARSER_ERROR_DUPLICATE_SECTION,
                    message=f"Duplicate [{header}] section.",
                    line=line_number,
                )
            sections[header] = []
            current_section = header
            continue

        if current_section is None:
            if stripped_line == "":
                continue
            return sections, ParseError(
                error_type=PARSER_ERROR_CONTENT_BEFORE_HEADER,
                message="Content before first section header.",
                line=line_number,
            )

        sections[current_section].append(line)

    return sections, None


def _parse_section_header(stripped_line: str) -> str | None:
    if not (
        len(stripped_line) >= 3
        and stripped_line.startswith("[")
        and stripped_line.endswith("]")
    ):
        return None

    section = stripped_line[1:-1]
    if section in ALLOWED_SECTIONS:
        return section
    return None


def _find_missing_section(sections: dict[str, list[str]]) -> str | None:
    for section in REQUIRED_SECTIONS:
        if section not in sections:
            return section
    return None


def _trim_boundary_blank_lines(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)

    while start < end and lines[start].strip() == "":
        start += 1
    while end > start and lines[end - 1].strip() == "":
        end -= 1

    return lines[start:end]


def _lines_to_section_text(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _build_executable_source(setup_code: str, code: str) -> str:
    parts = [
        part.rstrip()
        for part in (setup_code, code)
        if part.strip()
    ]
    return "\n\n".join(parts) + "\n"


def _parse_packages(lines: list[str]) -> list[PackageSpec]:
    packages: list[PackageSpec] = []

    for line in lines:
        raw = line.strip()
        if raw == "" or raw.upper() == "NONE":
            continue
        operator_match = PACKAGE_VERSION_OPERATOR_PATTERN.search(raw)
        if operator_match is None:
            name = raw
            specifier = ""
        else:
            name = raw[: operator_match.start()].strip()
            specifier = raw[operator_match.start() :].strip()
        packages.append(PackageSpec(name=name, specifier=specifier, raw=raw))

    return packages


def _parse_meta(lines: list[str]) -> tuple[dict[str, str], ParseError | None]:
    meta: dict[str, str] = {}

    for offset, line in enumerate(lines, start=1):
        if line.strip() == "":
            continue
        if "=" not in line:
            return meta, ParseError(
                error_type=PARSER_ERROR_INVALID_META,
                message="[META] line must use key=value format.",
                line=offset,
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "":
            return meta, ParseError(
                error_type=PARSER_ERROR_INVALID_META,
                message="[META] key must not be empty.",
                line=offset,
            )
        allowed_values = META_ENUM_VALUES.get(key)
        if allowed_values is not None and value not in allowed_values:
            return meta, ParseError(
                error_type=PARSER_ERROR_INVALID_META,
                message=f"[META] {key} has invalid value.",
                line=offset,
            )
        meta[key] = value

    return meta, None
