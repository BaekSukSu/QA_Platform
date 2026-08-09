import os
import sys
from pathlib import Path

RESOURCE_ENV_VAR = "QA_PLATFORM_RESOURCE_DIR"
MACOS_APPLICATION_SUPPORT_RESOURCE_DIR = Path(
    "/Library/Application Support/QA Platform/resources"
)


def default_resource_candidates() -> tuple[Path, ...]:
    executable_path = Path(sys.executable).resolve()
    package_root = Path(__file__).resolve().parents[2]
    return (
        executable_path.parent / "resources",
        MACOS_APPLICATION_SUPPORT_RESOURCE_DIR,
        package_root / "resources",
    )


def resolve_resource_root(
    configured_path: str | Path | None = None,
    *,
    candidates: tuple[Path, ...] | None = None,
) -> Path | None:
    configured_value = str(configured_path).strip() if configured_path is not None else ""
    if configured_value:
        configured = Path(configured_value).expanduser()
        return configured.resolve() if configured.is_dir() else None

    env_value = os.environ.get(RESOURCE_ENV_VAR, "").strip()
    if env_value:
        env_path = Path(env_value).expanduser()
        return env_path.resolve() if env_path.is_dir() else None

    for candidate in candidates if candidates is not None else default_resource_candidates():
        if candidate.is_dir():
            return candidate.resolve()
    return None
