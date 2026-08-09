from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import Iterable

from qa_platform.contract.models import PackageSpec
from qa_platform.contract.package_resolver import resolve_block_packages


RUN_SKIP_REASON_MISSING_REQUIRED_FILE = "missing_required_file"
RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT = "environment_dependent"
META_RUN_SKIP_REASON_KEY = "run_skip_reason"
META_MISSING_REQUIRED_FILES_KEY = "missing_required_files"
META_ENVIRONMENT_MODULES_KEY = "environment_modules"

EXTERNAL_FILE_READERS = frozenset(
    {
        "pd.read_csv",
        "pandas.read_csv",
        "pd.read_table",
        "pandas.read_table",
        "pd.read_excel",
        "pandas.read_excel",
        "np.loadtxt",
        "numpy.loadtxt",
        "np.genfromtxt",
        "numpy.genfromtxt",
    }
)
EXTERNAL_FILE_EXTENSIONS = frozenset(
    {
        ".txt",
        ".csv",
        ".tsv",
        ".json",
        ".html",
        ".xml",
        ".xlsx",
        ".xls",
    }
)
EXTERNAL_FILE_READ_METHODS = frozenset({"read_text", "read_bytes"})
EXTERNAL_FILE_WRITE_METHODS = frozenset({"write_text", "write_bytes"})
WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[/\\]")
NESTED_SCOPE_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
)
FUNCTION_SCOPE_START = object()
FUNCTION_SCOPE_END = object()


@dataclass(frozen=True)
class SourceSkipDecision:
    reason: str
    missing_required_files: tuple[str, ...] = ()
    environment_modules: tuple[str, ...] = ()


def detect_source_skip(
    *,
    setup_code: str,
    code: str,
    stdin: str,
    packages: Iterable[PackageSpec],
) -> SourceSkipDecision | None:
    missing_required_files = detect_external_file_reads(
        setup_code=setup_code,
        code=code,
        stdin=stdin,
    )
    if missing_required_files:
        return SourceSkipDecision(
            reason=RUN_SKIP_REASON_MISSING_REQUIRED_FILE,
            missing_required_files=missing_required_files,
        )

    environment_modules = detect_environment_modules(
        setup_code=setup_code,
        code=code,
        packages=packages,
    )
    if environment_modules:
        return SourceSkipDecision(
            reason=RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT,
            environment_modules=environment_modules,
        )

    return None


def detect_external_file_reads(
    *,
    setup_code: str,
    code: str,
    stdin: str,
) -> tuple[str, ...]:
    source = _build_executable_source(setup_code, code)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()

    return tuple(_find_external_file_reads(tree, stdin))


def detect_environment_modules(
    *,
    setup_code: str,
    code: str,
    packages: Iterable[PackageSpec],
) -> tuple[str, ...]:
    resolution = resolve_block_packages(setup_code, code, packages)
    return resolution.environment_modules


def source_skip_metadata(decision: SourceSkipDecision) -> dict[str, str]:
    metadata = {META_RUN_SKIP_REASON_KEY: decision.reason}
    if (
        decision.reason == RUN_SKIP_REASON_MISSING_REQUIRED_FILE
        and decision.missing_required_files
    ):
        metadata[META_MISSING_REQUIRED_FILES_KEY] = ", ".join(
            decision.missing_required_files
        )
    elif (
        decision.reason == RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT
        and decision.environment_modules
    ):
        metadata[META_ENVIRONMENT_MODULES_KEY] = ",".join(
            decision.environment_modules
        )
    return metadata


def _build_executable_source(setup_code: str, code: str) -> str:
    parts = [
        part.rstrip()
        for part in (setup_code, code)
        if part.strip()
    ]
    return "\n\n".join(parts) + "\n"


def _find_external_file_reads(tree: ast.AST, stdin: str) -> list[str]:
    function_defs = _collect_function_defs(tree)
    executable_nodes = list(_iter_executable_nodes(tree, function_defs))
    names_from_input: set[str] = set()
    literal_paths_by_name: dict[str, str] = {}
    stdin_path = _first_stdin_line(stdin)
    paths: list[str] = []
    seen: set[str] = set()
    written_paths: set[str] = set()
    scope_stack: list[tuple[set[str], dict[str, str]]] = []

    for node in executable_nodes:
        if node is FUNCTION_SCOPE_START:
            scope_stack.append(
                (names_from_input.copy(), literal_paths_by_name.copy())
            )
            continue
        if node is FUNCTION_SCOPE_END:
            names_from_input, literal_paths_by_name = scope_stack.pop()
            continue

        _update_path_name_assignments(
            node,
            names_from_input,
            literal_paths_by_name,
        )
        if not isinstance(node, ast.Call):
            continue
        written_path = (
            _external_path_for_written_open_call(
                node,
                names_from_input,
                literal_paths_by_name,
                stdin_path,
            )
            or _external_path_for_pathlib_write_call(
                node,
                names_from_input,
                literal_paths_by_name,
                stdin_path,
            )
        )
        if written_path is not None:
            written_paths.add(written_path)
            continue
        path = (
            _external_path_for_open_call(
                node,
                names_from_input,
                literal_paths_by_name,
                stdin_path,
            )
            or _external_path_for_reader_call(
                node,
                names_from_input,
                literal_paths_by_name,
                stdin_path,
            )
            or _external_path_for_pathlib_read_call(
                node,
                names_from_input,
                literal_paths_by_name,
                stdin_path,
            )
        )
        if (
            path is not None
            and path not in written_paths
            and path not in seen
        ):
            paths.append(path)
            seen.add(path)

    return paths


def _collect_function_defs(node: ast.AST) -> dict[str, ast.FunctionDef]:
    body = getattr(node, "body", [])
    return {
        statement.name: statement
        for statement in body
        if isinstance(statement, ast.FunctionDef)
    }


def _iter_executable_nodes(
    node: ast.AST,
    function_defs: dict[str, ast.FunctionDef],
    active_functions: set[str] | None = None,
):
    if active_functions is None:
        active_functions = set()
    if isinstance(node, NESTED_SCOPE_NODES):
        return

    yield node
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function_def = function_defs.get(node.func.id)
        if (
            function_def is not None
            and function_def.name not in active_functions
        ):
            active_functions.add(function_def.name)
            scoped_function_defs = {
                **function_defs,
                **_collect_function_defs(function_def),
            }
            yield FUNCTION_SCOPE_START
            for statement in function_def.body:
                yield from _iter_executable_nodes(
                    statement,
                    scoped_function_defs,
                    active_functions,
                )
            yield FUNCTION_SCOPE_END
            active_functions.remove(function_def.name)

    for child in ast.iter_child_nodes(node):
        yield from _iter_executable_nodes(
            child,
            function_defs,
            active_functions,
        )


def _update_path_name_assignments(
    node: ast.AST,
    names_from_input: set[str],
    literal_paths_by_name: dict[str, str],
) -> None:
    target_names = _assignment_target_names(node)
    if not target_names:
        return

    value = node.value
    if _is_input_value(value):
        for name in target_names:
            names_from_input.add(name)
            literal_paths_by_name.pop(name, None)
        return

    path = _path_from_literal(value)
    if path is not None:
        for name in target_names:
            literal_paths_by_name[name] = path
            names_from_input.discard(name)
        return

    path = _path_from_pathlib_call(value)
    if path is not None:
        for name in target_names:
            literal_paths_by_name[name] = path
            names_from_input.discard(name)
        return

    for name in target_names:
        names_from_input.discard(name)
        literal_paths_by_name.pop(name, None)


def _assignment_target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        return [
            target.id
            for target in node.targets
            if isinstance(target, ast.Name)
        ]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _first_stdin_line(stdin: str) -> str | None:
    for line in stdin.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _external_path_for_open_call(
    call: ast.Call,
    names_from_input: set[str],
    literal_paths_by_name: dict[str, str],
    stdin_path: str | None,
) -> str | None:
    if not _is_named_call(call, "open", "io.open"):
        return None

    path_node = call.args[0] if call.args else _keyword_value(call, "file")
    if path_node is None:
        return None

    mode_node = (
        call.args[1]
        if len(call.args) > 1
        else _keyword_value(call, "mode")
    )
    if not _open_mode_is_read(mode_node):
        return None

    return _literal_or_input_path(
        path_node,
        names_from_input,
        literal_paths_by_name,
        stdin_path,
    )


def _external_path_for_written_open_call(
    call: ast.Call,
    names_from_input: set[str],
    literal_paths_by_name: dict[str, str],
    stdin_path: str | None,
) -> str | None:
    if not _is_named_call(call, "open", "io.open"):
        return None

    path_node = call.args[0] if call.args else _keyword_value(call, "file")
    if path_node is None:
        return None

    mode_node = (
        call.args[1]
        if len(call.args) > 1
        else _keyword_value(call, "mode")
    )
    if not _open_mode_is_write(mode_node):
        return None

    return _literal_or_input_path(
        path_node,
        names_from_input,
        literal_paths_by_name,
        stdin_path,
    )


def _external_path_for_reader_call(
    call: ast.Call,
    names_from_input: set[str],
    literal_paths_by_name: dict[str, str],
    stdin_path: str | None,
) -> str | None:
    if not _is_named_call(call, *EXTERNAL_FILE_READERS):
        return None

    path_node = (
        call.args[0]
        if call.args
        else _keyword_value(call, "filepath_or_buffer", "io", "fname")
    )
    if path_node is None:
        return None

    return _literal_or_input_path(
        path_node,
        names_from_input,
        literal_paths_by_name,
        stdin_path,
    )


def _external_path_for_pathlib_read_call(
    call: ast.Call,
    names_from_input: set[str],
    literal_paths_by_name: dict[str, str],
    stdin_path: str | None,
) -> str | None:
    if (
        not isinstance(call.func, ast.Attribute)
        or call.func.attr not in EXTERNAL_FILE_READ_METHODS
    ):
        return None

    path_node = _path_node_from_pathlib_object(call.func.value)
    if path_node is None:
        return None

    return _literal_or_input_path(
        path_node,
        names_from_input,
        literal_paths_by_name,
        stdin_path,
    )


def _external_path_for_pathlib_write_call(
    call: ast.Call,
    names_from_input: set[str],
    literal_paths_by_name: dict[str, str],
    stdin_path: str | None,
) -> str | None:
    if (
        not isinstance(call.func, ast.Attribute)
        or call.func.attr not in EXTERNAL_FILE_WRITE_METHODS
    ):
        return None

    path_node = _path_node_from_pathlib_object(call.func.value)
    if path_node is None:
        return None

    return _literal_or_input_path(
        path_node,
        names_from_input,
        literal_paths_by_name,
        stdin_path,
    )


def _open_mode_is_read(mode_node: ast.AST | None) -> bool:
    if mode_node is None:
        return True

    mode = _literal_string(mode_node)
    if mode is None:
        return False
    return mode.startswith("r")


def _open_mode_is_write(mode_node: ast.AST | None) -> bool:
    mode = _literal_string(mode_node)
    if mode is None:
        return False
    return any(flag in mode for flag in ("w", "a", "x"))


def _literal_or_input_path(
    node: ast.AST,
    names_from_input: set[str],
    literal_paths_by_name: dict[str, str],
    stdin_path: str | None,
) -> str | None:
    literal_path = _path_from_literal(node)
    if literal_path is not None:
        return literal_path

    if (
        isinstance(node, ast.Name)
        and node.id in literal_paths_by_name
    ):
        return literal_paths_by_name[node.id]

    if (
        isinstance(node, ast.Name)
        and node.id in names_from_input
        and stdin_path is not None
        and _looks_like_external_file_path(stdin_path)
    ):
        return stdin_path.strip()

    return None


def _path_from_literal(node: ast.AST | None) -> str | None:
    literal = _literal_string(node)
    if literal is None:
        return None
    path = literal.strip()
    if _looks_like_external_file_path(path):
        return path
    return None


def _path_from_pathlib_call(node: ast.AST | None) -> str | None:
    path_node = _path_node_from_pathlib_object(node)
    if path_node is None:
        return None
    return _path_from_literal(path_node)


def _path_node_from_pathlib_object(node: ast.AST | None) -> ast.AST | None:
    if isinstance(node, ast.Name):
        return node
    if (
        isinstance(node, ast.Call)
        and _is_named_call(node, "Path", "pathlib.Path")
        and node.args
    ):
        return node.args[0]
    return None


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _looks_like_external_file_path(path: str) -> bool:
    stripped_path = path.strip()
    if not stripped_path:
        return False
    lower_path = stripped_path.lower()
    if lower_path.startswith(("http://", "https://")):
        return False
    if WINDOWS_DRIVE_PATH_PATTERN.match(stripped_path):
        return True
    return any(
        lower_path.endswith(extension)
        for extension in EXTERNAL_FILE_EXTENSIONS
    )


def _is_input_value(node: ast.AST | None) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if _is_named_call(node, "input"):
        return True
    if isinstance(node.func, ast.Attribute) and node.func.attr in {
        "strip",
        "lstrip",
        "rstrip",
    }:
        return _is_input_value(node.func.value)
    return False


def _is_named_call(call: ast.Call, *names: str) -> bool:
    call_name = _call_name(call.func)
    return call_name in names


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base_name = _call_name(node.value)
        if base_name is None:
            return None
        return f"{base_name}.{node.attr}"
    return None


def _keyword_value(call: ast.Call, *names: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg in names:
            return keyword.value
    return None
