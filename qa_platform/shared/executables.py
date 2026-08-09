import os
import shutil
from pathlib import Path


class ExecutableNotFoundError(RuntimeError):
    pass


def _existing_executable(path: Path) -> Path | None:
    if path.is_file() and os.access(path, os.X_OK):
        return path.resolve()
    return None


def _has_path_separator(value: str) -> bool:
    separators = {os.sep}
    if os.altsep is not None:
        separators.add(os.altsep)
    return any(separator in value for separator in separators)


def resolve_executable(
    name: str,
    *,
    configured_path: str | Path | None = None,
    bundled_path: str | Path | None = None,
    candidate_paths: tuple[Path, ...] = (),
) -> Path:
    configured_value = (
        str(configured_path).strip() if configured_path is not None else ""
    )
    if configured_value:
        configured_path_value = Path(configured_value).expanduser()
        if (
            not configured_path_value.is_absolute()
            and not _has_path_separator(configured_value)
        ):
            path_result = shutil.which(configured_value)
            if path_result:
                return Path(path_result).resolve()
            raise ExecutableNotFoundError(
                f"{name} executable was not found or is not executable "
                f"for configured command name: {configured_value}"
            )

        configured = _existing_executable(configured_path_value)
        if configured is not None:
            return configured
        raise ExecutableNotFoundError(
            f"{name} executable was not found or is not executable "
            f"at configured path: {configured_path}"
        )

    if bundled_path is not None:
        bundled_path_value = Path(bundled_path).expanduser()
        bundled = _existing_executable(bundled_path_value)
        if bundled is not None:
            return bundled
        if bundled_path_value.is_file():
            raise ExecutableNotFoundError(
                f"{name} executable was not found or is not executable "
                f"at bundled path: {bundled_path}"
            )

    path_result = shutil.which(name)
    if path_result:
        return Path(path_result).resolve()

    for candidate_path in candidate_paths:
        candidate = _existing_executable(candidate_path.expanduser())
        if candidate is not None:
            return candidate

    raise ExecutableNotFoundError(
        f"{name} executable was not found or is not executable"
    )
