"""macOS pkg installation layout helpers."""

from pathlib import Path, PurePosixPath


APP_SUPPORT_ROOT = PurePosixPath("/Library/Application Support/QA Platform")
APP_INSTALL_DIR = APP_SUPPORT_ROOT / "app" / "qa-platform"
RESOURCE_INSTALL_DIR = APP_SUPPORT_ROOT / "resources"
CLI_WRAPPER_PATH = PurePosixPath("/usr/local/bin/qa-platform")


def payload_path(payload_root: Path, install_path: PurePosixPath) -> Path:
    """Map an absolute install path to its location under the payload root."""
    if not install_path.is_absolute():
        raise ValueError("install_path must be absolute")

    return payload_root.joinpath(*install_path.parts[1:])


def wrapper_script() -> str:
    """Return the shell wrapper that execs the installed PyInstaller binary."""
    return (
        "#!/bin/sh\n"
        'exec "/Library/Application Support/QA Platform/app/qa-platform/qa-platform" "$@"\n'
    )
