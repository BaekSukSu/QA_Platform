from __future__ import annotations

import re

from qa_platform.contract.constants import (
    CATEGORY_ENVIRONMENT_DEPENDENT,
    CATEGORY_INPUT_REQUIRED_OR_INVALID,
    CATEGORY_MISSING_REQUIRED_FILE,
    CATEGORY_MODULE_NOT_FOUND,
    CATEGORY_NAME_ERROR,
    CATEGORY_RUNTIME_ERROR,
    CATEGORY_SYNTAX_ERROR,
    CATEGORY_TIMEOUT,
)


class ResultClassifier:
    @staticmethod
    def classify(
        exit_code: int | None,
        stderr: str,
        timed_out: bool,
    ) -> tuple[str | None, str | None, str | None]:
        if timed_out:
            return CATEGORY_TIMEOUT, "TimeoutError", "Execution timed out."

        error_type, error_message = _extract_last_exception(stderr)

        if _is_environment_dependent_error(stderr):
            return CATEGORY_ENVIRONMENT_DEPENDENT, error_type, error_message
        if "SyntaxError" in stderr:
            return CATEGORY_SYNTAX_ERROR, error_type, error_message
        if "NameError" in stderr:
            return CATEGORY_NAME_ERROR, error_type, error_message
        if "ModuleNotFoundError" in stderr:
            return CATEGORY_MODULE_NOT_FOUND, error_type, error_message
        if "FileNotFoundError" in stderr:
            return CATEGORY_MISSING_REQUIRED_FILE, error_type, error_message
        if "EOFError" in stderr:
            return CATEGORY_INPUT_REQUIRED_OR_INVALID, error_type, error_message
        if exit_code != 0:
            return CATEGORY_RUNTIME_ERROR, error_type, error_message

        return None, error_type, error_message


def _is_environment_dependent_error(stderr: str) -> bool:
    markers = (
        "libtk8.6.so",
        "no display name and no $DISPLAY environment variable",
        "No module named '_tkinter'",
        "_tkinter.TclError",
    )
    return any(marker in stderr for marker in markers)


def _extract_last_exception(stderr: str) -> tuple[str | None, str | None]:
    for line in reversed(stderr.splitlines()):
        stripped_line = line.strip()
        if not stripped_line:
            continue

        match = re.match(
            r"^(?P<error_type>[A-Za-z_][A-Za-z0-9_.]*):\s*(?P<message>.*)$",
            stripped_line,
        )
        if match:
            error_type = match.group("error_type").split(".")[-1]
            return error_type, match.group("message")
        return None, stripped_line

    return None, None
