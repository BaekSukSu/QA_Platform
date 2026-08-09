from __future__ import annotations

import ast
import re
from collections.abc import Iterable


_UNKNOWN = object()
_PANDAS_SERIES_FOOTER_PATTERN = re.compile(r"(?:Name: .+, )?dtype: .+")
_PANDAS_CALLABLE_POSITIONAL_METHODS = {
    "agg",
    "aggregate",
    "apply",
    "applymap",
    "groupby",
    "map",
    "mask",
    "pipe",
    "rename",
    "rename_axis",
    "transform",
    "where",
}
_PANDAS_CALLABLE_KEYWORDS_BY_METHOD = {
    "agg": {"func", "funcs"},
    "aggregate": {"func", "funcs"},
    "apply": {"func"},
    "applymap": {"func"},
    "groupby": {"by"},
    "map": {"arg", "mapper"},
    "mask": {"cond", "other"},
    "pipe": {"func"},
    "read_csv": {"converters", "date_parser", "on_bad_lines", "skiprows", "usecols"},
    "read_excel": {"converters", "date_parser", "skiprows", "usecols"},
    "read_fwf": {"converters", "skiprows", "usecols"},
    "read_table": {"converters", "date_parser", "on_bad_lines", "skiprows", "usecols"},
    "rename": {"columns", "index", "mapper"},
    "rename_axis": {"columns", "index", "mapper"},
    "sort_index": {"key"},
    "sort_values": {"key"},
    "to_string": {"float_format", "formatters"},
    "transform": {"func"},
    "where": {"cond", "other"},
}
_PANDAS_CALLABLE_ALL_KEYWORD_METHODS = {"assign"}


class OutputComparator:
    @staticmethod
    def compare(
        expected_output: str,
        stdout: str,
        *,
        code: str = "",
        stdin: str = "",
        packages: Iterable[str] = (),
    ) -> bool | None:
        if expected_output == "":
            return None
        expected = _normalize_terminal_transcript(
            expected_output,
            code=code,
            stdin=stdin,
            drop_stdin_echo_only=True,
        )
        actual = _normalize_terminal_transcript(
            stdout,
            code=code,
            stdin=stdin,
            drop_stdin_echo_only=False,
        )
        repl_display_candidate_line_indexes = _repl_display_candidate_line_indexes(code)
        if _normalize_line_trimmed_output(expected) == _normalize_line_trimmed_output(
            actual
        ):
            return True
        if _normalize_output(
            expected,
            repl_display_candidate_line_indexes=repl_display_candidate_line_indexes,
        ) == _normalize_output(
            actual,
            repl_display_candidate_line_indexes=repl_display_candidate_line_indexes,
        ):
            return True
        return _uses_pandas(code, packages) and _pandas_outputs_match(
            expected,
            actual,
            code=code,
        )


def _normalize_terminal_transcript(
    output: str,
    *,
    code: str,
    stdin: str,
    drop_stdin_echo_only: bool,
) -> str:
    prompt_specs = _input_prompt_specs(code)
    if not prompt_specs:
        return output

    normalized = output
    stdin_values = stdin.splitlines()
    for index, (prompt, line_index) in enumerate(prompt_specs):
        input_value = stdin_values[index] if index < len(stdin_values) else ""
        normalized = _strip_prompt_artifact(
            normalized,
            prompt=prompt,
            line_index=line_index,
            input_value=input_value,
            drop_stdin_echo_only=drop_stdin_echo_only,
        )
    return normalized


def _strip_prompt_artifact(
    output: str,
    *,
    prompt: str,
    line_index: int,
    input_value: str,
    drop_stdin_echo_only: bool,
) -> str:
    if not prompt:
        return output

    lines = output.splitlines(keepends=True)
    if line_index >= len(lines):
        return output

    line = lines[line_index]
    if not line.startswith(prompt):
        return output

    stripped_line = line[len(prompt):]
    without_newline = stripped_line.rstrip("\r\n")
    newline = stripped_line[len(without_newline):]

    normalized_lines = lines[:line_index]
    if not (
        without_newline == ""
        or (drop_stdin_echo_only and input_value and without_newline == input_value)
    ):
        normalized_lines.append(f"{without_newline}{newline}")
    normalized_lines.extend(lines[line_index + 1:])
    return "".join(normalized_lines)


def _input_prompt_specs(code: str) -> list[tuple[str, int]]:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return []

    prompt_specs: list[tuple[str, int]] = []
    constants: dict[str, object] = {}
    line_index = 0
    line_index_is_known = True
    for statement in module.body:
        if isinstance(statement, ast.Expr) and _is_direct_call(statement.value, "print"):
            if line_index_is_known:
                prompt_specs.extend(
                    (prompt, line_index)
                    for prompt in _input_prompts_in_node(statement)
                )
            print_line_count = _simple_print_line_count(statement.value, constants)
            if print_line_count is None:
                line_index_is_known = False
            elif line_index_is_known:
                line_index += print_line_count
            continue

        prompts = _runtime_input_prompts_in_statement(statement)
        if prompts:
            if line_index_is_known:
                prompt_specs.extend((prompt, line_index) for prompt in prompts)
            _update_constant_environment(statement, constants)
            continue

        _update_constant_environment(statement, constants)
        if not line_index_is_known or _statement_has_no_stdout(statement):
            continue
        if isinstance(statement, ast.Expr) and _is_supported_repl_display_expression(
            statement.value
        ):
            line_index += 1
            continue
        line_index_is_known = False
    return prompt_specs


def _input_prompts_in_node(node: ast.AST) -> list[str]:
    prompts: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if not isinstance(child.func, ast.Name) or child.func.id != "input":
            continue
        if not child.args:
            prompts.append("")
            continue
        first_arg = child.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            prompts.append(first_arg.value)
    return prompts


def _runtime_input_prompts_in_statement(statement: ast.stmt) -> list[str]:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    return _input_prompts_in_node(statement)


def _normalize_output(
    output: str,
    *,
    repl_display_candidate_line_indexes: set[int] | None = None,
) -> list[str]:
    lines = [
        line.rstrip()
        for line in _join_soft_wrapped_lines(output).splitlines()
    ]
    if not repl_display_candidate_line_indexes:
        return lines
    return [
        _normalize_repl_display_line(line)
        if index in repl_display_candidate_line_indexes
        else line
        for index, line in enumerate(lines)
    ]


def _normalize_line_trimmed_output(output: str) -> list[str]:
    return [line.rstrip() for line in output.splitlines()]


def _uses_pandas(code: str, packages: Iterable[str]) -> bool:
    if any(_is_pandas_module(package) for package in packages):
        return True

    try:
        module = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            if any(_is_pandas_module(alias.name) for alias in node.names):
                return True
            continue

        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and _is_pandas_module(node.module)
        ):
            return True
    return False


def _is_pandas_module(module_name: str) -> bool:
    normalized_name = _normalized_package_name(module_name)
    return normalized_name == "pandas" or normalized_name.startswith("pandas.")


def _normalized_package_name(package: str) -> str:
    return re.split(r"[<>=!~\[\];\s]", package.strip().lower(), maxsplit=1)[0]


def _pandas_outputs_match(expected: str, actual: str, *, code: str) -> bool:
    has_code = bool(code.strip())
    has_source_signal = (
        _has_exclusive_pandas_output_source_signal(code)
        if has_code
        else False
    )

    if _has_pandas_series_footer(expected) or _has_pandas_series_footer(actual):
        if has_code and not has_source_signal:
            return False
        expected_rows = _pandas_token_rows(expected)
        actual_rows = _pandas_token_rows(actual)
        return (
            _pandas_series_rows_are_unambiguous(expected_rows)
            and _pandas_series_rows_are_unambiguous(actual_rows)
            and expected_rows == actual_rows
        )

    if has_code and not has_source_signal:
        return False

    if not (
        _has_pandas_table_display_signal(
            expected,
            has_source_signal=has_source_signal,
        )
        or _has_pandas_table_display_signal(
            actual,
            has_source_signal=has_source_signal,
        )
    ):
        return False

    expected_rows = _pandas_token_rows(expected)
    actual_rows = _pandas_token_rows(actual)
    if not expected_rows and not actual_rows:
        return False
    if not (
        _pandas_table_rows_are_unambiguous(expected_rows)
        and _pandas_table_rows_are_unambiguous(actual_rows)
    ):
        return False
    return expected_rows == actual_rows


def _has_pandas_series_footer(output: str) -> bool:
    return any(
        _PANDAS_SERIES_FOOTER_PATTERN.fullmatch(line.strip())
        for line in output.splitlines()
    )


def _has_pandas_table_display_signal(
    output: str,
    *,
    has_source_signal: bool,
) -> bool:
    non_empty_lines = [line for line in output.splitlines() if line.strip()]
    multi_space_line_count = sum(
        1
        for line in non_empty_lines
        if re.search(r"\S\s{2,}\S", line) is not None
    )
    if has_source_signal:
        return len(non_empty_lines) >= 2 and multi_space_line_count >= 1
    return len(non_empty_lines) >= 3 and multi_space_line_count >= 2


def _has_exclusive_pandas_output_source_signal(code: str) -> bool:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return False

    pandas_aliases: set[str] = set()
    pandas_imported_names: set[str] = set()
    pandas_like_names: set[str] = set()
    local_function_names: set[str] = set()
    stdout_callable_names: set[str] = set()
    has_pandas_output = False
    for statement in module.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local_function_names.add(statement.name)
        _record_pandas_imports(
            statement,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
        )
        if _is_pandas_output_statement(
            statement,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        ):
            has_pandas_output = True
            continue
        if _is_non_pandas_output_statement(
            statement,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        ):
            return False
        _update_stdout_callable_names(
            statement,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        )
        _update_pandas_like_names(
            statement,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
        )
    return has_pandas_output


def _record_pandas_imports(
    statement: ast.stmt,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
) -> None:
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            if _is_pandas_module(alias.name):
                pandas_aliases.add(alias.asname or alias.name.split(".", maxsplit=1)[0])
        return

    if not (
        isinstance(statement, ast.ImportFrom)
        and statement.module is not None
        and _is_pandas_module(statement.module)
    ):
        return

    for alias in statement.names:
        pandas_imported_names.add(alias.asname or alias.name)


def _update_pandas_like_names(
    statement: ast.stmt,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
) -> None:
    if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
        return

    value = statement.value
    target_names = _assignment_target_names(statement)
    if not target_names:
        return

    is_pandas_like = value is not None and _is_pandas_like_expression(
        value,
        pandas_aliases=pandas_aliases,
        pandas_imported_names=pandas_imported_names,
        pandas_like_names=pandas_like_names,
    )
    for name in target_names:
        if is_pandas_like:
            pandas_like_names.add(name)
        else:
            pandas_like_names.discard(name)


def _is_pandas_output_statement(
    statement: ast.stmt,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> bool:
    if not isinstance(statement, ast.Expr):
        return False

    value = statement.value
    if _is_direct_call(value, "print"):
        return bool(value.args) and all(
            _is_stdout_safe_pandas_expression(
                argument,
                pandas_aliases=pandas_aliases,
                pandas_imported_names=pandas_imported_names,
                pandas_like_names=pandas_like_names,
                local_function_names=local_function_names,
                stdout_callable_names=stdout_callable_names,
            )
            for argument in value.args
        )

    return _is_stdout_safe_pandas_expression(
        value,
        pandas_aliases=pandas_aliases,
        pandas_imported_names=pandas_imported_names,
        pandas_like_names=pandas_like_names,
        local_function_names=local_function_names,
        stdout_callable_names=stdout_callable_names,
    )


def _is_non_pandas_output_statement(
    statement: ast.stmt,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> bool:
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return _with_statement_has_stdout(
            statement,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        )
    if isinstance(statement, ast.Expr):
        value = statement.value
        return (
            _is_direct_call(value, "print")
            or _is_supported_repl_display_expression(value)
            or isinstance(value, ast.Call)
        )
    if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return _assignment_value_has_stdout(
            statement,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        )
    return not _statement_has_no_stdout(statement)


def _is_stdout_safe_pandas_expression(
    value: ast.expr,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> bool:
    return (
        _is_pandas_like_expression(
            value,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
        )
        and not _expression_contains_index_free_to_string(value)
        and not _expression_contains_direct_print(value)
        and not _expression_contains_pandas_callable_argument(
            value,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
        )
        and not _expression_contains_stdout_callable_reference(
            value,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        )
        and not _expression_contains_unknown_call(
            value,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
            allow_pandas_calls=True,
        )
    )


def _assignment_value_has_stdout(
    statement: ast.Assign | ast.AnnAssign | ast.AugAssign,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> bool:
    value = statement.value
    if value is None:
        return False
    if _expression_contains_direct_print(value):
        return True
    if not any(isinstance(node, ast.Call) for node in ast.walk(value)):
        return False
    if _expression_contains_stdout_callable_reference(
        value,
        local_function_names=local_function_names,
        stdout_callable_names=stdout_callable_names,
    ):
        return True
    if _expression_contains_pandas_callable_argument(
        value,
        pandas_aliases=pandas_aliases,
        pandas_imported_names=pandas_imported_names,
        pandas_like_names=pandas_like_names,
    ):
        return True
    if _expression_contains_unknown_call(
        value,
        pandas_aliases=pandas_aliases,
        pandas_imported_names=pandas_imported_names,
        pandas_like_names=pandas_like_names,
        allow_pandas_calls=True,
    ):
        return True
    return not _is_pandas_like_expression(
        value,
        pandas_aliases=pandas_aliases,
        pandas_imported_names=pandas_imported_names,
        pandas_like_names=pandas_like_names,
    )


def _expression_contains_direct_print(value: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        for node in ast.walk(value)
    )


def _expression_contains_index_free_to_string(value: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call) and _is_index_free_to_string_call(node)
        for node in ast.walk(value)
    )


def _expression_contains_pandas_callable_argument(
    value: ast.AST,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
) -> bool:
    return any(
        isinstance(node, ast.Call)
        and _is_pandas_like_call(
            node,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
        )
        and _pandas_call_has_dynamic_callable_argument(node)
        for node in ast.walk(value)
    )


def _pandas_call_has_dynamic_callable_argument(value: ast.Call) -> bool:
    if not isinstance(value.func, ast.Attribute):
        return False

    method_name = value.func.attr
    candidate_arguments: list[ast.expr] = []
    if method_name in _PANDAS_CALLABLE_POSITIONAL_METHODS:
        candidate_arguments.extend(value.args)

    callable_keyword_names = _PANDAS_CALLABLE_KEYWORDS_BY_METHOD.get(
        method_name,
        set(),
    )
    if method_name in _PANDAS_CALLABLE_ALL_KEYWORD_METHODS:
        candidate_arguments.extend(keyword.value for keyword in value.keywords)
    else:
        candidate_arguments.extend(
            keyword.value
            for keyword in value.keywords
            if keyword.arg in callable_keyword_names
        )

    return any(
        not _is_static_pandas_function_spec(argument)
        for argument in candidate_arguments
    )


def _is_static_pandas_function_spec(value: ast.expr) -> bool:
    if isinstance(value, ast.Constant):
        return isinstance(value.value, (str, int, float, bool)) or value.value is None
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_static_pandas_function_spec(element) for element in value.elts)
    if isinstance(value, ast.Dict):
        return all(
            (key is None or _is_static_pandas_function_spec(key))
            and _is_static_pandas_function_spec(item)
            for key, item in zip(value.keys, value.values)
        )
    return False


def _is_index_free_to_string_call(value: ast.Call) -> bool:
    return (
        isinstance(value.func, ast.Attribute)
        and value.func.attr == "to_string"
        and any(
            keyword.arg == "index"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in value.keywords
        )
    )


def _update_stdout_callable_names(
    statement: ast.stmt,
    *,
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> None:
    for name, value in _assignment_name_value_pairs(statement):
        if _is_stdout_callable_value(
            value,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        ):
            stdout_callable_names.add(name)
        else:
            stdout_callable_names.discard(name)


def _assignment_name_value_pairs(
    statement: ast.stmt,
) -> list[tuple[str, ast.expr | None]]:
    if isinstance(statement, ast.Assign):
        pairs: list[tuple[str, ast.expr | None]] = []
        for target in statement.targets:
            pairs.extend(_target_name_value_pairs(target, statement.value))
        return pairs

    if isinstance(statement, ast.AnnAssign):
        return _target_name_value_pairs(statement.target, statement.value)

    return []


def _target_name_value_pairs(
    target: ast.expr,
    value: ast.expr | None,
) -> list[tuple[str, ast.expr | None]]:
    if isinstance(target, ast.Name):
        return [(target.id, value)]

    if isinstance(target, (ast.Tuple, ast.List)):
        target_elements = target.elts
        if (
            isinstance(value, (ast.Tuple, ast.List))
            and len(value.elts) == len(target_elements)
        ):
            pairs: list[tuple[str, ast.expr | None]] = []
            for child_target, child_value in zip(target_elements, value.elts):
                pairs.extend(_target_name_value_pairs(child_target, child_value))
            return pairs
        return [(name, None) for name in _target_names(target)]

    return []


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for child_target in target.elts:
            names.extend(_target_names(child_target))
        return names
    return []


def _is_stdout_callable_value(
    value: ast.expr | None,
    *,
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> bool:
    return (
        isinstance(value, ast.Name)
        and (
            value.id == "print"
            or value.id in local_function_names
            or value.id in stdout_callable_names
        )
    )


def _expression_contains_stdout_callable_reference(
    value: ast.AST,
    *,
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> bool:
    return any(
        isinstance(node, ast.Lambda)
        or (
            isinstance(node, ast.Name)
            and (
                node.id == "print"
                or node.id in local_function_names
                or node.id in stdout_callable_names
            )
        )
        for node in ast.walk(value)
    )


def _expression_contains_unknown_call(
    value: ast.AST,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
    allow_pandas_calls: bool,
) -> bool:
    for node in ast.walk(value):
        if not isinstance(node, ast.Call):
            continue
        if allow_pandas_calls and _is_pandas_like_call(
            node,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
        ):
            continue
        return True
    return False


def _is_pandas_like_call(
    value: ast.Call,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
) -> bool:
    function_root_name = _expression_root_name(value.func)
    return (
        function_root_name in pandas_aliases
        or function_root_name in pandas_imported_names
        or function_root_name in pandas_like_names
    )


def _call_arguments_are_stdout_safe(
    value: ast.Call,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
    local_function_names: set[str],
    stdout_callable_names: set[str],
    allow_pandas_calls: bool,
) -> bool:
    arguments = [
        *value.args,
        *(keyword.value for keyword in value.keywords),
    ]
    return all(
        not _expression_contains_direct_print(argument)
        and not _expression_contains_stdout_callable_reference(
            argument,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        )
        and not _expression_contains_unknown_call(
            argument,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
            allow_pandas_calls=allow_pandas_calls,
        )
        for argument in arguments
    )


def _with_statement_has_stdout(
    statement: ast.With | ast.AsyncWith,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> bool:
    return any(
        _is_non_pandas_output_statement(
            child,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        )
        and not _is_stdout_safe_file_write_expression(
            child,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
            local_function_names=local_function_names,
            stdout_callable_names=stdout_callable_names,
        )
        for child in statement.body
    )


def _is_stdout_safe_file_write_expression(
    statement: ast.stmt,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
    local_function_names: set[str],
    stdout_callable_names: set[str],
) -> bool:
    if not (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "write"
    ):
        return False

    return _call_arguments_are_stdout_safe(
        statement.value,
        pandas_aliases=pandas_aliases,
        pandas_imported_names=pandas_imported_names,
        pandas_like_names=pandas_like_names,
        local_function_names=local_function_names,
        stdout_callable_names=stdout_callable_names,
        allow_pandas_calls=False,
    )


def _is_pandas_like_expression(
    value: ast.expr,
    *,
    pandas_aliases: set[str],
    pandas_imported_names: set[str],
    pandas_like_names: set[str],
) -> bool:
    root_name = _expression_root_name(value)
    if root_name in pandas_like_names:
        return True

    if isinstance(value, ast.Call):
        function_root_name = _expression_root_name(value.func)
        return (
            function_root_name in pandas_aliases
            or function_root_name in pandas_imported_names
        )

    if isinstance(value, ast.Compare):
        return any(
            _is_pandas_like_expression(
                expression,
                pandas_aliases=pandas_aliases,
                pandas_imported_names=pandas_imported_names,
                pandas_like_names=pandas_like_names,
            )
            for expression in [value.left, *value.comparators]
        )

    if isinstance(value, ast.BinOp):
        return any(
            _is_pandas_like_expression(
                expression,
                pandas_aliases=pandas_aliases,
                pandas_imported_names=pandas_imported_names,
                pandas_like_names=pandas_like_names,
            )
            for expression in (value.left, value.right)
        )

    if isinstance(value, ast.UnaryOp):
        return _is_pandas_like_expression(
            value.operand,
            pandas_aliases=pandas_aliases,
            pandas_imported_names=pandas_imported_names,
            pandas_like_names=pandas_like_names,
        )

    if isinstance(value, ast.BoolOp):
        return any(
            _is_pandas_like_expression(
                expression,
                pandas_aliases=pandas_aliases,
                pandas_imported_names=pandas_imported_names,
                pandas_like_names=pandas_like_names,
            )
            for expression in value.values
        )

    return False


def _expression_root_name(value: ast.expr) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return _expression_root_name(value.value)
    if isinstance(value, ast.Subscript):
        return _expression_root_name(value.value)
    if isinstance(value, ast.Call):
        return _expression_root_name(value.func)
    return None


def _pandas_token_rows(output: str) -> list[tuple[str, ...]]:
    lines = _drop_pandas_series_footer(output.splitlines())
    return [
        tuple(line.split())
        for line in lines
        if line.strip()
    ]


def _pandas_series_rows_are_unambiguous(rows: list[tuple[str, ...]]) -> bool:
    return bool(rows) and all(1 <= len(row) <= 2 for row in rows)


def _pandas_table_rows_are_unambiguous(rows: list[tuple[str, ...]]) -> bool:
    if len(rows) < 2:
        return False

    header_len = len(rows[0])
    if header_len == 0:
        return False

    skipped_index_name = False
    has_data_row = False
    for row in rows[1:]:
        if len(row) < header_len and not skipped_index_name:
            skipped_index_name = True
            continue
        if len(row) > header_len + 1:
            return False
        if len(row) > header_len and not _looks_like_pandas_index_token(row[0]):
            return False
        has_data_row = True
    return has_data_row


def _looks_like_pandas_index_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+|[A-Z]{1,3}|[a-z_][a-z0-9_]*", token))


def _drop_pandas_series_footer(lines: list[str]) -> list[str]:
    if (
        lines
        and _PANDAS_SERIES_FOOTER_PATTERN.fullmatch(lines[-1].strip())
    ):
        return lines[:-1]
    return lines


def _join_soft_wrapped_lines(output: str) -> str:
    lines = output.splitlines()
    if not lines:
        return output

    joined: list[str] = []
    buffer = lines[0]
    for line in lines[1:]:
        if (
            buffer.endswith(" ")
            and buffer.strip()
            and line
            and not line[0].isspace()
        ):
            buffer = f"{buffer}{line}"
            continue
        joined.append(buffer)
        buffer = line
    joined.append(buffer)
    result = "\n".join(joined)
    if joined[-1] == "":
        result = f"{result}\n"
    return result


def _repl_display_candidate_line_indexes(code: str) -> set[int]:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return set()

    candidate_line_indexes: set[int] = set()
    constants: dict[str, object] = {}
    line_index = 0
    for statement in module.body:
        if not isinstance(statement, ast.Expr):
            _update_constant_environment(statement, constants)
            if _statement_has_no_stdout(statement):
                continue
            return set()

        value = statement.value
        if _is_direct_call(value, "input"):
            continue
        if _is_direct_call(value, "print"):
            print_line_count = _simple_print_line_count(value, constants)
            if print_line_count is None:
                return set()
            line_index += print_line_count
            continue

        if not _is_supported_repl_display_expression(value):
            return set()

        candidate_line_indexes.add(line_index)
        line_index += 1
    return candidate_line_indexes


def _statement_has_no_stdout(statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return not _function_definition_has_runtime_call(statement)

    no_stdout_statement_types = (
        ast.Assign,
        ast.AnnAssign,
        ast.AugAssign,
        ast.Delete,
        ast.ClassDef,
        ast.Import,
        ast.ImportFrom,
        ast.Pass,
    )
    return isinstance(statement, no_stdout_statement_types) and not any(
        isinstance(node, ast.Call) for node in ast.walk(statement)
    )


def _function_definition_has_runtime_call(
    statement: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    runtime_expressions: list[ast.expr] = [
        *statement.decorator_list,
        *statement.args.defaults,
        *(default for default in statement.args.kw_defaults if default is not None),
    ]
    if statement.returns is not None:
        runtime_expressions.append(statement.returns)

    arguments = [
        *statement.args.posonlyargs,
        *statement.args.args,
        *statement.args.kwonlyargs,
    ]
    if statement.args.vararg is not None:
        arguments.append(statement.args.vararg)
    if statement.args.kwarg is not None:
        arguments.append(statement.args.kwarg)

    runtime_expressions.extend(
        argument.annotation
        for argument in arguments
        if argument.annotation is not None
    )

    return any(
        not _is_side_effect_free_expression(expression)
        for expression in runtime_expressions
    )


def _is_direct_call(value: ast.expr, name: str) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == name
    )


def _simple_print_line_count(
    value: ast.expr,
    constants: dict[str, object] | None = None,
) -> int | None:
    if not isinstance(value, ast.Call):
        return None

    constants = constants or {}
    end = "\n"
    sep = " "
    for keyword in value.keywords:
        if keyword.arg == "end":
            resolved_end = _constant_expression_value(keyword.value, constants)
            if resolved_end != "\n":
                return None
            end = resolved_end
            continue
        if keyword.arg == "sep":
            resolved_sep = _constant_expression_value(keyword.value, constants)
            if not isinstance(resolved_sep, str) or _has_line_break(resolved_sep):
                return None
            sep = resolved_sep
            continue
        if keyword.arg == "flush":
            continue
        return None

    arg_values: list[object] = []
    for arg in value.args:
        resolved_arg = _constant_expression_value(arg, constants)
        if not _is_static_print_value(resolved_arg):
            return None
        arg_values.append(resolved_arg)

    printed_output = f"{sep.join(str(arg) for arg in arg_values)}{end}"
    return len(printed_output.splitlines())


def _is_static_print_value(value: object) -> bool:
    return value is None or isinstance(value, (str, bool, int, float, complex))


def _update_constant_environment(
    statement: ast.stmt,
    constants: dict[str, object],
) -> None:
    if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return

    target_names = _assignment_target_names(statement)
    if isinstance(statement, ast.AugAssign):
        for name in target_names:
            constants.pop(name, None)
        return

    value = _constant_expression_value(statement.value, constants)
    for name in target_names:
        if value is _UNKNOWN:
            constants.pop(name, None)
        else:
            constants[name] = value


def _assignment_target_names(statement: ast.stmt) -> list[str]:
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
        targets = [statement.target]
    else:
        return []

    return [
        target.id
        for target in targets
        if isinstance(target, ast.Name)
    ]


def _constant_expression_value(
    value: ast.expr | None,
    constants: dict[str, object],
) -> object:
    if value is None:
        return _UNKNOWN
    if isinstance(value, ast.Constant):
        if _is_static_print_value(value.value):
            return value.value
        return _UNKNOWN
    if isinstance(value, ast.Name):
        return constants.get(value.id, _UNKNOWN)
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        left = _constant_expression_value(value.left, constants)
        right = _constant_expression_value(value.right, constants)
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}{right}"
    return _UNKNOWN


def _is_supported_repl_display_expression(value: ast.expr) -> bool:
    if _is_direct_call(value, "type"):
        return all(
            _is_side_effect_free_expression(argument)
            for argument in value.args
        ) and all(
            _is_side_effect_free_expression(keyword.value)
            for keyword in value.keywords
        )
    return _is_string_expression(value)


def _is_side_effect_free_expression(value: ast.expr) -> bool:
    return not any(isinstance(node, ast.Call) for node in ast.walk(value))


def _is_string_expression(value: ast.expr) -> bool:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return True
    return (
        isinstance(value, ast.BinOp)
        and isinstance(value.op, ast.Add)
        and _is_string_expression(value.left)
        and _is_string_expression(value.right)
    )


def _has_line_break(value: str) -> bool:
    line_breaks = (
        "\n",
        "\r",
        "\v",
        "\f",
        "\x1c",
        "\x1d",
        "\x1e",
        "\x85",
        "\u2028",
        "\u2029",
    )
    return any(line_break in value for line_break in line_breaks)


def _normalize_repl_display_line(line: str) -> str:
    type_match = re.fullmatch(r"<class '([^']+)'>", line)
    if type_match is not None:
        return type_match.group(1)

    if len(line) >= 2 and line[0] == line[-1] == "'":
        return line[1:-1]
    return line
