import ast
from dataclasses import dataclass
from pathlib import Path

from qa_platform.contract.constants import (
    EXECUTION_MODE_REPL,
    EXECUTION_MODE_SCRIPT,
    META_EXECUTION_MODE_KEY,
)

SCRIPT_ENTRYPOINT_NAME = "normalized.py"
REPL_ENTRYPOINT_NAME = "repl_executable.py"
META_EXECUTION_STRATEGY_KEY = "execution_strategy"

EXECUTION_STRATEGY_SCRIPT_NORMALIZED = "script_normalized"
EXECUTION_STRATEGY_REPL_DISPLAYHOOK = "repl_displayhook"
EXECUTION_STRATEGY_REPL_TRANSFORM_FAILED_SCRIPT_FALLBACK = (
    "repl_transform_failed_script_fallback"
)
REPL_TRANSFORM_FALLBACK_ERRORS = (SyntaxError, RecursionError)


@dataclass(frozen=True)
class ExecutionArtifact:
    script_name: str
    meta: dict[str, str]


def normalize_execution_mode(value: str | None) -> str:
    if value == EXECUTION_MODE_REPL:
        return EXECUTION_MODE_REPL
    return EXECUTION_MODE_SCRIPT


def prepare_execution_artifact(
    block_dir: Path,
    *,
    code: str,
    meta: dict[str, str],
) -> ExecutionArtifact:
    execution_mode = normalize_execution_mode(meta.get(META_EXECUTION_MODE_KEY))
    artifact_meta = {
        **meta,
        META_EXECUTION_MODE_KEY: execution_mode,
    }

    if execution_mode != EXECUTION_MODE_REPL:
        artifact_meta[META_EXECUTION_STRATEGY_KEY] = (
            EXECUTION_STRATEGY_SCRIPT_NORMALIZED
        )
        return ExecutionArtifact(script_name=SCRIPT_ENTRYPOINT_NAME, meta=artifact_meta)

    try:
        repl_source = build_repl_executable_source(code)
    except REPL_TRANSFORM_FALLBACK_ERRORS:
        artifact_meta[META_EXECUTION_STRATEGY_KEY] = (
            EXECUTION_STRATEGY_REPL_TRANSFORM_FAILED_SCRIPT_FALLBACK
        )
        return ExecutionArtifact(script_name=SCRIPT_ENTRYPOINT_NAME, meta=artifact_meta)

    (block_dir / REPL_ENTRYPOINT_NAME).write_text(repl_source, encoding="utf-8")
    artifact_meta[META_EXECUTION_STRATEGY_KEY] = EXECUTION_STRATEGY_REPL_DISPLAYHOOK
    return ExecutionArtifact(script_name=REPL_ENTRYPOINT_NAME, meta=artifact_meta)


def build_repl_executable_source(code: str) -> str:
    module = ast.parse(code)
    module.body = [
        _wrap_expression_with_displayhook(statement)
        if isinstance(statement, ast.Expr)
        else statement
        for statement in module.body
    ]
    ast.fix_missing_locations(module)
    source = (
        "# Generated REPL executable. Do not edit by hand.\n"
        f"{ast.unparse(module)}\n"
    )
    compile(source, REPL_ENTRYPOINT_NAME, "exec")
    return source


def _wrap_expression_with_displayhook(statement: ast.Expr) -> ast.Expr:
    return ast.Expr(
        value=ast.Call(
            func=ast.Attribute(
                value=ast.Call(
                    func=ast.Name(id="__import__", ctx=ast.Load()),
                    args=[ast.Constant(value="sys")],
                    keywords=[],
                ),
                attr="displayhook",
                ctx=ast.Load(),
            ),
            args=[statement.value],
            keywords=[],
        )
    )
