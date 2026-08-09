from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from google.genai import types

from qa_platform.contract.constants import (
    CODE_TYPE_COMPLETE,
    CODE_TYPE_INCOMPLETE_SNIPPET,
    DEFAULT_META_OUTPUT_DETERMINISM,
    DEFAULT_META_STDIN_EXHAUSTION,
    EXECUTION_MODE_REPL,
    EXECUTION_MODE_SCRIPT,
    META_EXECUTION_MODE_KEY,
    META_OUTPUT_DETERMINISM_KEY,
)
from qa_platform.contract.models import PackageSpec
from qa_platform.contract.package_resolver import resolve_block_packages
from qa_platform.contract.source_skip_classifier import (
    META_ENVIRONMENT_MODULES_KEY,
    META_MISSING_REQUIRED_FILES_KEY,
    META_RUN_SKIP_REASON_KEY,
    RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT,
    RUN_SKIP_REASON_MISSING_REQUIRED_FILE,
    detect_source_skip,
    source_skip_metadata,
)


@dataclass
class RawBlock:
    meta: dict[str, str]
    packages: str
    setup_code: str
    code: str
    input_text: str
    output_text: str


BLOCK_FILE_PATTERN = re.compile(r"^block_(?P<number>\d+)\.txt$")
NONE_VALUE = "NONE"
CONTEXT_FALLBACK_LOOKBACK_BLOCKS = 5
SAFE_OUTPUT_CHECK_TIMEOUT_SECONDS = 2.0
SAFE_OUTPUT_CHECK_MAX_LITERAL_CHARS = 10000
SAFE_OUTPUT_CHECK_MAX_NUMERIC_ABS = 1_000_000
UNSAFE_EXPRESSION = object()
INCOMPLETE_PLACEHOLDER_PATTERNS = [
    re.compile(r"\(\s*,"),
    re.compile(r",\s*\)"),
    re.compile(r"\(\s{4,}"),
    re.compile(r"\s{4,},"),
    re.compile(r"\.\.\."),
]
REPL_ECHO_CALL_BUILTINS = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "float",
    "int",
    "len",
    "list",
    "max",
    "min",
    "repr",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "type",
}
PACKAGE_VERSION_OPERATOR_PATTERN = re.compile(r"(===|==|~=|!=|<=|>=|<|>)")
PACKAGE_VERSION_OPERATOR_PREFIX_PATTERN = re.compile(
    r"^\s*(===|==|~=|!=|<=|>=|<|>)"
)


@dataclass
class ContextDefinition:
    symbol: str
    source: str
    block_id: str


def get_unresolved_and_defined_vars(code_str: str) -> tuple[set[str], set[str]]:
    class VariableVisitor(ast.NodeVisitor):
        def __init__(self):
            self.defined: set[str] = set()
            self.used: set[str] = set()
            self.builtins = set(dir(builtins))

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Store):
                self.defined.add(node.id)
            elif isinstance(node.ctx, ast.Load):
                self.used.add(node.id)
            self.generic_visit(node)

        def visit_Import(self, node):
            for alias in node.names:
                self.defined.add(alias.asname or alias.name.split(".")[0])
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            for alias in node.names:
                self.defined.add(alias.asname or alias.name)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            self.defined.add(node.name)
            for arg in node.args.args:
                self.defined.add(arg.arg)
            if node.args.vararg:
                self.defined.add(node.args.vararg.arg)
            if node.args.kwarg:
                self.defined.add(node.args.kwarg.arg)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            self.defined.add(node.name)
            for arg in node.args.args:
                self.defined.add(arg.arg)
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            self.defined.add(node.name)
            self.generic_visit(node)

        def visit_For(self, node):
            if isinstance(node.target, ast.Name):
                self.defined.add(node.target.id)
            elif isinstance(node.target, ast.Tuple):
                for elt in node.target.elts:
                    if isinstance(elt, ast.Name):
                        self.defined.add(elt.id)
            self.generic_visit(node)

        def visit_ListComp(self, node):
            for generator in node.generators:
                if isinstance(generator.target, ast.Name):
                    self.defined.add(generator.target.id)
            self.generic_visit(node)

    try:
        tree = ast.parse(code_str)
    except SyntaxError:
        return set(), set()
    visitor = VariableVisitor()
    visitor.visit(tree)
    return visitor.used - visitor.defined - visitor.builtins, visitor.defined


def is_runnable(code_str: str) -> tuple[bool, str]:
    clean_code = (
        code_str.replace("\xa0", " ").replace("\u3000", " ").replace("\t", "    ")
    )
    try:
        ast.parse(clean_code)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"
    unresolved, _ = get_unresolved_and_defined_vars(clean_code)
    if unresolved:
        return False, f"Unresolved variables: {sorted(unresolved)}"
    return True, "OK"


def _section(content: str, name: str) -> str:
    match = re.search(rf"\[{name}\]\n(.*?)(?=\n\[|$)", content, re.DOTALL)
    return match.group(1).strip() if match else "NONE"


def _normalize_optional_code_section(value: str) -> str:
    normalized = value.replace("\xa0", " ").replace("\u3000", " ")
    return "" if normalized.strip().upper() == NONE_VALUE else normalized


def parse_raw_block_file(path: Path) -> RawBlock:
    content = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    for line in _section(content, "META").split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        elif "=" in line:
            key, value = line.split("=", 1)
            meta[key.strip()] = value.strip()
    return RawBlock(
        meta=meta,
        packages=_section(content, "PACKAGES"),
        setup_code=_normalize_optional_code_section(_section(content, "SETUP")),
        code=_section(content, "CODE").replace("\xa0", " ").replace("\u3000", " "),
        input_text=_section(content, "INPUT"),
        output_text=_section(content, "OUTPUT"),
    )


def save_raw_block_file(path: Path, block: RawBlock) -> None:
    meta_text = "\n".join(f"{key} : {value}" for key, value in block.meta.items())
    path.write_text(
        f"[META]\n{meta_text}\n\n"
        f"[PACKAGES]\n{block.packages}\n\n"
        f"[SETUP]\n{block.setup_code}\n\n"
        f"[CODE]\n{block.code}\n\n"
        f"[INPUT]\n{block.input_text}\n\n"
        f"[OUTPUT]\n{block.output_text}",
        encoding="utf-8",
    )


def postprocess_extracted_blocks(output_dir: Path, client) -> None:
    resolve_context_setup_blocks(output_dir)
    merge_physical_blocks(output_dir, client=client)
    filter_unrunnable_blocks(output_dir, client=client)
    validate_extracted_outputs(output_dir)
    normalize_external_package_sections(output_dir)


def validate_extracted_outputs(output_dir: Path) -> int:
    corrected_count = 0

    for block_path in _find_block_paths(output_dir):
        block = parse_raw_block_file(block_path)
        if not _should_validate_extracted_output(block):
            continue

        stdout = _run_safe_output_check(block)
        if stdout is None:
            continue

        actual_output = stdout.rstrip("\r\n")
        expected_output = block.output_text.rstrip("\r\n")

        if actual_output == expected_output:
            block.meta["output_validation"] = "matched_execution"
            save_raw_block_file(block_path, block)
        elif _looks_like_ocr_output_loss(expected_output, actual_output):
            block.output_text = actual_output
            block.meta["output_validation"] = "corrected_by_execution"
            block.meta["output_correction_reason"] = "probable_ocr_loss"
            save_raw_block_file(block_path, block)
            corrected_count += 1
        else:
            block.meta["code_type"] = CODE_TYPE_INCOMPLETE_SNIPPET
            block.meta["extraction_issue"] = "output_alignment_mismatch"
            block.meta["output_validation"] = "failed_execution_crosscheck"
            save_raw_block_file(block_path, block)

    return corrected_count


def normalize_external_package_sections(output_dir: Path) -> int:
    normalized_count = 0

    for block_path in _find_block_paths(output_dir):
        block = parse_raw_block_file(block_path)
        previous_packages = block.packages
        previous_environment_modules = block.meta.get(META_ENVIRONMENT_MODULES_KEY)
        resolution = resolve_block_packages(
            block.setup_code,
            block.code,
            _parse_declared_package_specs(block.packages),
        )
        requirements = [
            *resolution.requirements,
            *resolution.unsupported_requirements,
        ]
        block.packages = "\n".join(requirements) if requirements else NONE_VALUE

        if resolution.environment_modules:
            block.meta[META_ENVIRONMENT_MODULES_KEY] = ",".join(
                resolution.environment_modules
            )
        elif not _has_stale_environment_source_skip_metadata(block):
            block.meta.pop(META_ENVIRONMENT_MODULES_KEY, None)

        if (
            block.packages != previous_packages
            or block.meta.get(META_ENVIRONMENT_MODULES_KEY)
            != previous_environment_modules
        ):
            save_raw_block_file(block_path, block)
            normalized_count += 1

    return normalized_count


def resolve_context_setup_blocks(output_dir: Path) -> int:
    block_paths = _find_block_paths(output_dir)
    symbol_tables: dict[str, dict[str, ContextDefinition]] = {}
    recent_definitions: list[tuple[Path, RawBlock]] = []
    resolved_count = 0

    for index, block_path in enumerate(block_paths):
        block = parse_raw_block_file(block_path)
        block_id = f"block_{index + 1:03d}"

        if _is_incomplete_snippet_guard(block) or _has_text(block.setup_code):
            _remember_definitions(
                symbol_tables,
                block=block,
                block_id=block_id,
            )
            recent_definitions.append((block_path, block))
            recent_definitions = recent_definitions[
                -CONTEXT_FALLBACK_LOOKBACK_BLOCKS:
            ]
            continue

        unresolved, _defined = get_unresolved_and_defined_vars(block.code)
        definitions = _lookup_context_definitions(
            symbol_tables,
            block=block,
            unresolved=unresolved,
        )

        if not definitions and unresolved:
            fallback: dict[str, ContextDefinition] = {}
            for previous_path, previous_block in reversed(recent_definitions):
                previous_definitions = _extract_top_level_definition_sources(
                    previous_block.code
                )
                for symbol in sorted(unresolved & set(previous_definitions)):
                    if symbol not in fallback:
                        fallback[symbol] = ContextDefinition(
                            symbol=symbol,
                            source=previous_definitions[symbol],
                            block_id=previous_path.stem,
                        )
            definitions = list(fallback.values())

        if definitions:
            block.setup_code = "\n\n".join(
                definition.source for definition in definitions
            )
            block.meta["context_source_blocks"] = ",".join(
                definition.block_id for definition in definitions
            )
            block.meta["context_symbols"] = ",".join(
                sorted(definition.symbol for definition in definitions)
            )
            block.meta["code_type"] = CODE_TYPE_COMPLETE
            save_raw_block_file(block_path, block)
            resolved_count += 1

        _remember_definitions(
            symbol_tables,
            block=block,
            block_id=block_id,
        )
        recent_definitions.append((block_path, block))
        recent_definitions = recent_definitions[
            -CONTEXT_FALLBACK_LOOKBACK_BLOCKS:
        ]

    return resolved_count


def merge_physical_blocks(output_dir: Path, *, client=None) -> int:
    block_paths = _find_block_paths(output_dir)
    if not block_paths:
        return 0

    trash_dir = _get_trash_dir(output_dir)
    current_path = block_paths[0]
    current_block = _prepare_block(current_path, client=client)
    save_raw_block_file(current_path, current_block)
    moved_count = 0

    for next_path in block_paths[1:]:
        next_block = _prepare_block(next_path, client=client)
        save_raw_block_file(next_path, next_block)

        _, current_defined = get_unresolved_and_defined_vars(current_block.code)
        next_unresolved, _ = get_unresolved_and_defined_vars(
            _block_execution_code(next_block)
        )

        if (
            next_unresolved & current_defined
            and not _is_incomplete_snippet_guard(next_block)
        ):
            current_block.code = _join_non_none_sections(
                current_block.code,
                next_block.code,
            )
            current_block.output_text = _join_non_none_sections(
                current_block.output_text,
                next_block.output_text,
            )
            current_block.input_text = _join_non_none_sections(
                current_block.input_text,
                next_block.input_text,
            )
            save_raw_block_file(current_path, current_block)
            shutil.move(
                str(next_path),
                str(trash_dir / f"{output_dir.name}_merged_{next_path.name}"),
            )
            moved_count += 1
            continue

        current_path = next_path
        current_block = next_block

    _renumber_block_files(output_dir)
    return moved_count


def filter_unrunnable_blocks(output_dir: Path, *, client=None) -> int:
    trash_dir = _get_trash_dir(output_dir)
    discarded_count = 0

    for block_path in _find_block_paths(output_dir):
        block = _prepare_block(block_path, client=client)
        if block.meta.get(META_RUN_SKIP_REASON_KEY):
            save_raw_block_file(block_path, block)
            continue
        valid, _message = is_runnable(_block_execution_code(block))
        code_type = block.meta.get("code_type", CODE_TYPE_COMPLETE)
        if not valid and code_type == CODE_TYPE_INCOMPLETE_SNIPPET:
            shutil.move(
                str(block_path),
                str(trash_dir / f"{output_dir.name}_unrunnable_{block_path.name}"),
            )
            discarded_count += 1
            continue
        save_raw_block_file(block_path, block)

    valid_index = 1
    for block_path in _find_block_paths(output_dir):
        block = _prepare_block(block_path, client=client)
        if block.meta.get(META_RUN_SKIP_REASON_KEY):
            if _has_text(block.output_text):
                block.meta["output_source"] = "textbook"
            else:
                block.output_text = NONE_VALUE
                block.meta["output_source"] = "empty"
            new_path = output_dir / f"block_{valid_index:03d}.txt"
            save_raw_block_file(new_path, block)
            if block_path != new_path and block_path.exists():
                block_path.unlink()
            valid_index += 1
            continue
        valid, _message = is_runnable(_block_execution_code(block))
        code_type = block.meta.get("code_type", CODE_TYPE_COMPLETE)

        if _has_text(block.output_text):
            block.meta["output_source"] = "textbook"
        elif not valid or not _prints_or_returns(block.code):
            block.output_text = NONE_VALUE
            block.meta["output_source"] = "empty"
        else:
            generated_output = (
                predict_output_via_ai(block.code, block.input_text, client)
                if client is not None
                else NONE_VALUE
            )
            if (
                generated_output != NONE_VALUE
                and "Traceback (most recent call last)" in generated_output
                and code_type == CODE_TYPE_INCOMPLETE_SNIPPET
            ):
                shutil.move(
                    str(block_path),
                    str(
                        trash_dir
                        / f"{output_dir.name}_runtime_err_{block_path.name}"
                    ),
                )
                discarded_count += 1
                continue
            if (
                generated_output != NONE_VALUE
                and "Traceback (most recent call last)" not in generated_output
            ):
                block.output_text = generated_output
                block.meta["output_source"] = "generated_sample"
            else:
                block.output_text = NONE_VALUE
                block.meta["output_source"] = "empty"

        output_determinism, stdin_exhaustion = (
            classify_metadata_via_ai(block.code, client)
            if client is not None
            else (
                DEFAULT_META_OUTPUT_DETERMINISM,
                DEFAULT_META_STDIN_EXHAUSTION,
            )
        )
        block.meta[META_OUTPUT_DETERMINISM_KEY] = output_determinism
        block.meta["stdin_exhaustion"] = stdin_exhaustion

        new_path = output_dir / f"block_{valid_index:03d}.txt"
        save_raw_block_file(new_path, block)
        if block_path != new_path and block_path.exists():
            block_path.unlink()
        valid_index += 1

    return discarded_count


def sanitize_input_field(
    code_str: str,
    input_str: str,
    client=None,
) -> tuple[str, str]:
    cleaned_input = input_str.strip()
    if _has_text(cleaned_input):
        prompt_strings = re.findall(
            r"input\s*\(\s*[\"'](.*?)[\"']\s*\)",
            code_str,
        )
        for prompt in prompt_strings:
            prompt = prompt.strip()
            if prompt:
                cleaned_input = cleaned_input.replace(prompt, "")
        cleaned_input = re.sub(r"^[>:\s]+", "", cleaned_input).strip()
        if cleaned_input:
            return cleaned_input, "textbook"

    if "input" in code_str and client is not None:
        generated_input = generate_dummy_input_via_ai(code_str, client)
        if _has_text(generated_input):
            return generated_input, "generated_sample"

    return NONE_VALUE, "empty"


def predict_output_via_ai(code_str: str, input_str: str, client) -> str:
    prompt = f"""
다음 파이썬 코드의 실행 결과를 정확히 예측하시오.

[ 핵심 규칙 ]
1. 예측된 터미널 출력 결과는 반드시 <RESULT>와 </RESULT> 태그 사이에만 작성하시오.
2. 태그 내부의 데이터는 마침표(.), 느낌표(!) 등 구두점 하나도 빠짐없이 100% 보존하시오.
3. input() 함수의 안내 문자열은 출력에 포함하지 마시오.
4. 터미널 출력 결과가 없다면 <RESULT>NONE</RESULT> 라고만 작성하시오.

[INPUT]
{input_str}

[CODE]
{code_str}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                stop_sequences=None,
            ),
        )
    except Exception:
        return "NONE"

    raw_text = response.text or ""
    if not raw_text.strip():
        return "NONE"
    match = re.search(
        r"<RESULT>\n?(.*?)\n?</RESULT>",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    result = match.group(1) if match else raw_text
    result = result.strip(" \t\r\n")
    return result if result and result != "NONE" else "NONE"


def generate_dummy_input_via_ai(code_str: str, client) -> str:
    prompt = f"""
당신은 파이썬 코드의 실행 흐름을 분석하여, 프로그램이 에러 없이 무한 루프를 탈출하고 정상 종료되도록 만드는 완벽한 사용자 입력 시퀀스를 생성하는 기계입니다.

[ 절대 통제 규칙 ]
1. 어떠한 부연 설명도 없이 오직 입력할 값들만 줄바꿈으로 구분하여 반환하시오.
2. 데이터 타입 일치: 코드가 문자열을 원하면 문자열을, 정수를 원하면 정수를 제공하시오.
3. 루프 탈출: while문으로 메뉴를 선택하는 코드라면, 몇 번의 임의 조작 후 반드시 종료 조건에 해당하는 값을 마지막에 주입하시오.

[CODE]
{code_str}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
    except Exception:
        return "NONE"

    result = (response.text or "").strip()
    return result if result else "NONE"


def classify_metadata_via_ai(code_str: str, client) -> tuple[str, str]:
    prompt = f"""
당신은 파이썬 코드의 실행 컨텍스트를 분석하는 분류기입니다.
아래 코드를 분석하여 오직 JSON 포맷으로만 응답하십시오.

[ 분류 기준 ]
1. output_determinism:
   - "nondeterministic": random, time 모듈 등 실행할 때마다 결과나 분기가 달라지는 무작위 요소가 있는 경우
   - "deterministic": 입력값이 동일하면 항상 동일한 결과를 내는 경우
2. stdin_exhaustion:
   - "accept": while/for 루프 내부에서 input()을 호출하거나, sys.stdin 등 정적으로 준비된 입력값 개수를 초과하여 무한 대기에 빠질 위험이 있는 경우
   - "deny": 입력이 고정된 횟수만큼만 호출되거나 아예 없는 경우

[CODE]
{code_str}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "output_determinism": {"type": "STRING"},
                        "stdin_exhaustion": {"type": "STRING"},
                    },
                },
            ),
        )
        result = json.loads(response.text)
    except Exception:
        return "deterministic", "deny"

    return (
        result.get(
            "output_determinism",
            result.get("mode", "deterministic"),
        ),
        result.get("stdin_exhaustion", "deny"),
    )


def _prepare_block(path: Path, *, client=None) -> RawBlock:
    block = parse_raw_block_file(path)
    if _apply_source_skip_metadata(block):
        if "code_type" not in block.meta:
            block.meta["code_type"] = CODE_TYPE_COMPLETE
        return block
    previous_input_source = block.meta.get("input_source")
    block.input_text, input_source = sanitize_input_field(
        block.code,
        block.input_text,
        client=client,
    )
    if previous_input_source and previous_input_source != "empty" and _has_text(
        block.input_text
    ):
        block.meta["input_source"] = previous_input_source
    else:
        block.meta["input_source"] = input_source
    if "output_source" not in block.meta:
        block.meta["output_source"] = "empty"
    if "code_type" not in block.meta:
        block.meta["code_type"] = CODE_TYPE_COMPLETE
    if META_EXECUTION_MODE_KEY not in block.meta:
        block.meta[META_EXECUTION_MODE_KEY] = _infer_execution_mode(block)
    return block


def _apply_source_skip_metadata(block: RawBlock) -> bool:
    decision = detect_source_skip(
        setup_code=block.setup_code,
        code=block.code,
        stdin=block.input_text,
        packages=_parse_declared_package_specs(block.packages),
    )
    if decision is None:
        if not _has_trusted_source_skip_metadata(block):
            return False
        _apply_default_source_skip_metadata(block)
        return True

    block.meta.update(source_skip_metadata(decision))
    _apply_default_source_skip_metadata(block)
    return True


def _has_trusted_source_skip_metadata(block: RawBlock) -> bool:
    return (
        _has_preclassified_missing_file_source_skip_metadata(block)
        or _has_stale_environment_source_skip_metadata(block)
    )


def _has_preclassified_missing_file_source_skip_metadata(block: RawBlock) -> bool:
    return (
        block.meta.get(META_RUN_SKIP_REASON_KEY)
        == RUN_SKIP_REASON_MISSING_REQUIRED_FILE
        and bool(block.meta.get(META_MISSING_REQUIRED_FILES_KEY))
    )


def _has_stale_environment_source_skip_metadata(block: RawBlock) -> bool:
    return (
        block.meta.get(META_RUN_SKIP_REASON_KEY)
        == RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT
        and bool(block.meta.get(META_ENVIRONMENT_MODULES_KEY))
    )


def _apply_default_source_skip_metadata(block: RawBlock) -> None:
    block.meta.setdefault("input_source", "empty")
    block.meta.setdefault("output_source", "empty")
    block.meta.setdefault(
        META_OUTPUT_DETERMINISM_KEY,
        DEFAULT_META_OUTPUT_DETERMINISM,
    )
    block.meta.setdefault("stdin_exhaustion", DEFAULT_META_STDIN_EXHAUSTION)
    block.meta.setdefault(META_EXECUTION_MODE_KEY, _infer_execution_mode(block))


def _find_block_paths(output_dir: Path) -> list[Path]:
    output_dir = Path(output_dir)
    return sorted(
        [
            path
            for path in output_dir.iterdir()
            if path.is_file() and BLOCK_FILE_PATTERN.fullmatch(path.name)
        ],
        key=lambda path: int(BLOCK_FILE_PATTERN.fullmatch(path.name).group("number")),
    )


def _parse_declared_package_specs(packages_text: str) -> list[PackageSpec]:
    if not _has_text(packages_text):
        return []

    packages: list[PackageSpec] = []
    for raw_line in packages_text.splitlines():
        raw_values = _split_declared_package_line(raw_line)
        for raw_value in raw_values:
            package = _parse_declared_package_spec(raw_value)
            if package is not None:
                packages.append(package)
    return packages


def _split_declared_package_line(raw_line: str) -> list[str]:
    values: list[str] = []
    for part in raw_line.split(","):
        if PACKAGE_VERSION_OPERATOR_PREFIX_PATTERN.search(part) and values:
            values[-1] = f"{values[-1]},{part}"
        else:
            values.append(part)
    return values


def _parse_declared_package_spec(raw_value: str) -> PackageSpec | None:
    raw = raw_value.strip()
    if not raw or raw.upper() == NONE_VALUE:
        return None
    operator_match = PACKAGE_VERSION_OPERATOR_PATTERN.search(raw)
    if operator_match is None:
        name = raw
        specifier = ""
    else:
        name = raw[: operator_match.start()].strip()
        specifier = raw[operator_match.start() :].strip()
    if not name:
        return None
    return PackageSpec(name=name, specifier=specifier, raw=raw)


def _get_trash_dir(output_dir: Path) -> Path:
    trash_dir = Path(output_dir).parent / "trashes"
    trash_dir.mkdir(parents=True, exist_ok=True)
    return trash_dir


def _renumber_block_files(output_dir: Path) -> None:
    for index, path in enumerate(_find_block_paths(output_dir), start=1):
        new_path = Path(output_dir) / f"block_{index:03d}.txt"
        if path != new_path:
            path.rename(new_path)


def _block_execution_code(block: RawBlock) -> str:
    values = [
        value.rstrip()
        for value in (block.setup_code, block.code)
        if _has_text(value)
    ]
    return "\n\n".join(values)


def _should_validate_extracted_output(block: RawBlock) -> bool:
    return (
        block.meta.get("source_kind") == "image"
        and not block.meta.get(META_RUN_SKIP_REASON_KEY)
        and block.meta.get("output_source") == "textbook"
        and block.meta.get("code_type", CODE_TYPE_COMPLETE) == CODE_TYPE_COMPLETE
        and _has_text(block.output_text)
        and not _has_text(block.input_text)
        and _safe_output_check_source(block) is not None
    )


def _safe_output_check_source(block: RawBlock) -> str | None:
    source = _block_execution_code(block)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    safe_names: dict[str, object] = {}
    estimated_output_chars = 0
    has_print_call = False

    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            if not _store_safe_assignment(statement, safe_names):
                return None
            continue

        if isinstance(statement, ast.Expr):
            print_output_chars = _safe_print_output_chars(statement.value, safe_names)
            if print_output_chars is None:
                return None
            estimated_output_chars += print_output_chars
            if estimated_output_chars > SAFE_OUTPUT_CHECK_MAX_LITERAL_CHARS:
                return None
            has_print_call = True
            continue

        return None

    return source if has_print_call else None


def _store_safe_assignment(
    statement: ast.Assign,
    safe_names: dict[str, object],
) -> bool:
    if not statement.targets:
        return False
    for target in statement.targets:
        if not isinstance(target, ast.Name) or target.id == "print":
            return False

    value = _safe_expression_value(statement.value, safe_names)
    if value is UNSAFE_EXPRESSION:
        return False

    for target in statement.targets:
        safe_names[target.id] = value
    return True


def _safe_print_output_chars(
    value: ast.expr,
    safe_names: dict[str, object],
) -> int | None:
    if not isinstance(value, ast.Call):
        return None
    if not isinstance(value.func, ast.Name) or value.func.id != "print":
        return None

    sep = " "
    end = "\n"
    for keyword in value.keywords:
        if keyword.arg == "sep":
            keyword_value = _safe_constant_keyword_value(keyword.value)
            if not isinstance(keyword_value, str):
                return None
            sep = keyword_value
        elif keyword.arg == "end":
            keyword_value = _safe_constant_keyword_value(keyword.value)
            if not isinstance(keyword_value, str):
                return None
            end = keyword_value
        elif keyword.arg == "flush":
            keyword_value = _safe_constant_keyword_value(keyword.value)
            if not isinstance(keyword_value, bool):
                return None
        else:
            return None

    argument_values = []
    for argument in value.args:
        argument_value = _safe_expression_value(argument, safe_names)
        if argument_value is UNSAFE_EXPRESSION:
            return None
        argument_values.append(argument_value)

    output_text = sep.join(str(argument) for argument in argument_values) + end
    if len(output_text) > SAFE_OUTPUT_CHECK_MAX_LITERAL_CHARS:
        return None
    return len(output_text)


def _safe_constant_keyword_value(value: ast.expr) -> object:
    if not isinstance(value, ast.Constant):
        return UNSAFE_EXPRESSION
    if not _is_safe_constant_value(value.value):
        return UNSAFE_EXPRESSION
    return value.value


def _safe_expression_value(
    value: ast.expr,
    safe_names: dict[str, object],
) -> object:
    if isinstance(value, ast.Constant):
        if _is_safe_constant_value(value.value):
            return value.value
        return UNSAFE_EXPRESSION

    if isinstance(value, ast.Name):
        return safe_names.get(value.id, UNSAFE_EXPRESSION)

    if isinstance(value, ast.UnaryOp):
        operand = _safe_expression_value(value.operand, safe_names)
        return _safe_unary_expression_value(value.op, operand)

    if isinstance(value, ast.BinOp):
        left = _safe_expression_value(value.left, safe_names)
        right = _safe_expression_value(value.right, safe_names)
        return _safe_binary_expression_value(value.op, left, right)

    return UNSAFE_EXPRESSION


def _is_safe_constant_value(value: object) -> bool:
    if isinstance(value, str):
        return len(value) <= SAFE_OUTPUT_CHECK_MAX_LITERAL_CHARS
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, (int, float)):
        return abs(value) <= SAFE_OUTPUT_CHECK_MAX_NUMERIC_ABS
    return False


def _safe_unary_expression_value(operator: ast.unaryop, operand: object) -> object:
    if operand is UNSAFE_EXPRESSION or not _is_plain_number(operand):
        return UNSAFE_EXPRESSION
    if isinstance(operator, ast.UAdd):
        return operand
    if isinstance(operator, ast.USub):
        return _bounded_numeric_value(-operand)
    return UNSAFE_EXPRESSION


def _safe_binary_expression_value(
    operator: ast.operator,
    left: object,
    right: object,
) -> object:
    if left is UNSAFE_EXPRESSION or right is UNSAFE_EXPRESSION:
        return UNSAFE_EXPRESSION

    if isinstance(operator, ast.Add):
        if isinstance(left, str) and isinstance(right, str):
            return _bounded_string_value(left + right)
        if _is_plain_number(left) and _is_plain_number(right):
            return _bounded_numeric_value(left + right)
    elif isinstance(operator, ast.Sub):
        if _is_plain_number(left) and _is_plain_number(right):
            return _bounded_numeric_value(left - right)
    elif isinstance(operator, ast.Mult):
        if isinstance(left, str) and _is_plain_int(right):
            return _bounded_string_repetition(left, right)
        if _is_plain_int(left) and isinstance(right, str):
            return _bounded_string_repetition(right, left)
        if _is_plain_number(left) and _is_plain_number(right):
            return _bounded_numeric_value(left * right)
    elif isinstance(operator, ast.Div):
        if _is_plain_number(left) and _is_plain_number(right) and right != 0:
            return _bounded_numeric_value(left / right)
    elif isinstance(operator, ast.Mod):
        if _is_plain_number(left) and _is_plain_number(right) and right != 0:
            return _bounded_numeric_value(left % right)
    elif isinstance(operator, ast.Pow):
        if _is_plain_number(left) and _is_plain_int(right) and 0 <= right <= 6:
            return _bounded_numeric_value(left**right)

    return UNSAFE_EXPRESSION


def _is_plain_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bounded_numeric_value(value: int | float) -> object:
    if abs(value) > SAFE_OUTPUT_CHECK_MAX_NUMERIC_ABS:
        return UNSAFE_EXPRESSION
    return value


def _bounded_string_value(value: str) -> object:
    if len(value) > SAFE_OUTPUT_CHECK_MAX_LITERAL_CHARS:
        return UNSAFE_EXPRESSION
    return value


def _bounded_string_repetition(value: str, repeat_count: int) -> object:
    if repeat_count < 0:
        repeat_count = 0
    if len(value) * repeat_count > SAFE_OUTPUT_CHECK_MAX_LITERAL_CHARS:
        return UNSAFE_EXPRESSION
    return value * repeat_count


def _run_safe_output_check(block: RawBlock) -> str | None:
    source = _safe_output_check_source(block)
    if source is None:
        return None

    with tempfile.TemporaryDirectory(prefix="qa-output-check-") as tmp_dir:
        script_path = Path(tmp_dir) / "block.py"
        script_path.write_text(source, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(script_path)],
                text=True,
                capture_output=True,
                timeout=SAFE_OUTPUT_CHECK_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    if result.returncode != 0 or result.stderr:
        return None
    return result.stdout


def _looks_like_ocr_output_loss(expected_output: str, actual_output: str) -> bool:
    expected_lines = expected_output.splitlines()
    actual_lines = actual_output.splitlines()
    if len(expected_lines) != len(actual_lines):
        return False
    return all(
        _line_looks_like_ocr_loss(expected_line, actual_line)
        for expected_line, actual_line in zip(expected_lines, actual_lines)
    )


def _line_looks_like_ocr_loss(expected_line: str, actual_line: str) -> bool:
    if expected_line == actual_line:
        return True
    if expected_line == re.sub(r"[.!?！？。]+$", "", actual_line):
        return True
    return _line_looks_like_repeated_text_truncation(expected_line, actual_line)


def _line_looks_like_repeated_text_truncation(
    expected_line: str,
    actual_line: str,
) -> bool:
    if not expected_line or not actual_line.startswith(expected_line):
        return False

    repeated_unit = _small_repeating_unit(actual_line)
    if repeated_unit is None:
        return False
    if len(expected_line) < len(repeated_unit) * 2:
        return False
    if len(expected_line) % len(repeated_unit) != 0:
        return False
    return repeated_unit * (len(expected_line) // len(repeated_unit)) == expected_line


def _small_repeating_unit(value: str) -> str | None:
    max_unit_length = min(len(value) // 2, 8)
    for unit_length in range(1, max_unit_length + 1):
        if len(value) % unit_length != 0:
            continue
        unit = value[:unit_length]
        if unit * (len(value) // unit_length) == value:
            return unit
    return None


def _is_incomplete_snippet_guard(block: RawBlock) -> bool:
    code_type = block.meta.get("code_type", CODE_TYPE_COMPLETE)
    if code_type == CODE_TYPE_INCOMPLETE_SNIPPET:
        return True
    return any(pattern.search(block.code) for pattern in INCOMPLETE_PLACEHOLDER_PATTERNS)


def _extract_top_level_definition_sources(code: str) -> dict[str, str]:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return {}

    lines = code.splitlines()
    definitions: dict[str, str] = {}
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            source = _source_segment_from_lines(lines, node)
            if source.strip():
                definitions[node.name] = source
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            source = _source_segment_from_lines(lines, node)
            if not source.strip():
                continue
            for name in _defined_import_names(node):
                definitions[name] = source
    return definitions


def _source_segment_from_lines(lines: list[str], node: ast.AST) -> str:
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if start is None or end is None:
        return ""
    return "\n".join(lines[start - 1:end])


def _defined_import_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    names = []
    for alias in node.names:
        name = alias.asname or alias.name.split(".", maxsplit=1)[0]
        names.append(name)
    return names


def _context_scope_keys(block: RawBlock) -> list[str]:
    keys: list[str] = []
    section_id = block.meta.get("section_id", "").strip()
    page = block.meta.get("page", "").strip()
    if section_id:
        keys.append(f"section:{section_id}")
    if page:
        keys.append(f"page:{page}")
    keys.append("chapter")
    return keys


def _remember_definitions(
    symbol_tables: dict[str, dict[str, ContextDefinition]],
    *,
    block: RawBlock,
    block_id: str,
) -> None:
    definitions = _extract_top_level_definition_sources(block.code)
    for scope_key in _context_scope_keys(block):
        table = symbol_tables.setdefault(scope_key, {})
        for symbol, source in definitions.items():
            table[symbol] = ContextDefinition(
                symbol=symbol,
                source=source,
                block_id=block_id,
            )


def _lookup_context_definitions(
    symbol_tables: dict[str, dict[str, ContextDefinition]],
    *,
    block: RawBlock,
    unresolved: set[str],
) -> list[ContextDefinition]:
    found: dict[str, ContextDefinition] = {}
    for scope_key in _context_scope_keys(block):
        table = symbol_tables.get(scope_key, {})
        for symbol in sorted(unresolved):
            if symbol in table and symbol not in found:
                found[symbol] = table[symbol]
    return list(found.values())


def _join_non_none_sections(first: str, second: str) -> str:
    values = [value for value in (first, second) if _has_text(value)]
    return "\n".join(values) if values else NONE_VALUE


def _has_text(value: str) -> bool:
    return bool(value.strip()) and value.strip().upper() != NONE_VALUE


def _prints_or_returns(code: str) -> bool:
    return "print" in code or "return" in code


def _infer_execution_mode(block: RawBlock) -> str:
    if _has_repl_prompt_marker(block.code):
        return EXECUTION_MODE_REPL
    if _has_text(block.output_text) and _has_repl_echo_expression(block.code):
        return EXECUTION_MODE_REPL
    return EXECUTION_MODE_SCRIPT


def _has_repl_prompt_marker(value: str) -> bool:
    return bool(re.search(r"(?m)^\s*(?:>>>|\.\.\.)(?:\s|$)", value))


def _has_repl_echo_expression(code: str) -> bool:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return False

    return any(
        isinstance(node, ast.Expr)
        and _looks_like_repl_echo_candidate(node.value)
        for node in module.body
    )


def _looks_like_repl_echo_candidate(value: ast.expr) -> bool:
    if isinstance(value, ast.Call):
        return (
            isinstance(value.func, ast.Name)
            and value.func.id in REPL_ECHO_CALL_BUILTINS
        )
    return isinstance(
        value,
        (
            ast.Attribute,
            ast.BinOp,
            ast.BoolOp,
            ast.Compare,
            ast.Constant,
            ast.Dict,
            ast.List,
            ast.Name,
            ast.Set,
            ast.Subscript,
            ast.Tuple,
            ast.UnaryOp,
        ),
    )
