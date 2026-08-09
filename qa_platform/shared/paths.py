from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_WORKSPACE_DIRNAME = "QA Platform"
WORKSPACE_ENV_VAR = "QA_PLATFORM_WORKSPACE"
ENV_FILE_ENV_VAR = "QA_PLATFORM_ENV_FILE"


def default_workspace_root() -> Path:
    return Path.home() / "Documents" / DEFAULT_WORKSPACE_DIRNAME


def resolve_workspace_root(
    value: Any,
    *,
    config_dir: Path | None = None,
) -> Path:
    path_value = None if value is None else str(value).strip()
    if path_value is None or path_value == "":
        env_value = os.environ.get(WORKSPACE_ENV_VAR)
        path_value = None if env_value is None else env_value.strip()

    if path_value is None or path_value == "":
        return default_workspace_root().expanduser().resolve()

    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()

    base_dir = config_dir if config_dir is not None else Path.cwd()
    return (base_dir / path).resolve()


def resolve_env_file_path(value: Any, *, workspace_root: Path) -> Path:
    path_value = None if value is None else str(value).strip()
    if path_value is None or path_value == "":
        env_value = os.environ.get(ENV_FILE_ENV_VAR)
        path_value = None if env_value is None else env_value.strip()

    if path_value is None or path_value == "":
        return (workspace_root / ".env").resolve()

    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (workspace_root / path).resolve()


def resolve_workspace_path(value: Any, workspace_root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return workspace_root / path


def _has_path_separator(value: str) -> bool:
    separators = {os.sep}
    if os.altsep is not None:
        separators.add(os.altsep)
    return any(separator in value for separator in separators)


def resolve_workspace_command_path(value: Any, workspace_root: Path) -> str:
    command_value = "" if value is None else str(value).strip()
    if not command_value:
        return ""

    command_path = Path(command_value).expanduser()
    if command_path.is_absolute() or not _has_path_separator(command_value):
        return command_value
    return str(resolve_workspace_path(command_path, workspace_root))


def resolve_optional_workspace_path(
    value: Any,
    workspace_root: Path,
) -> Path | None:
    if value is None or value == "":
        return None
    return resolve_workspace_path(value, workspace_root)
