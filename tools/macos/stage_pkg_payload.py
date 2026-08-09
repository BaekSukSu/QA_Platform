from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from tools.macos.pkg_layout import (
    APP_INSTALL_DIR,
    CLI_WRAPPER_PATH,
    payload_path,
    wrapper_script,
)


DEFAULT_EXECUTABLE_DIR = Path("build/macos/executable/qa-platform")
DEFAULT_PAYLOAD_ROOT = Path("build/macos/pkg-root")


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)


def stage_payload(
    *,
    executable_dir: Path,
    payload_root: Path,
) -> None:
    executable = executable_dir / "qa-platform"
    if not executable.is_file():
        raise FileNotFoundError(f"qa-platform executable not found: {executable}")

    if payload_root.exists():
        shutil.rmtree(payload_root)
    payload_root.mkdir(parents=True)

    _copy_tree(executable_dir, payload_path(payload_root, APP_INSTALL_DIR))

    wrapper = payload_path(payload_root, CLI_WRAPPER_PATH)
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(wrapper_script(), encoding="utf-8")
    wrapper.chmod(0o755)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage macOS pkg payload.")
    parser.add_argument(
        "--executable-dir",
        type=Path,
        default=DEFAULT_EXECUTABLE_DIR,
    )
    parser.add_argument(
        "--payload-root",
        type=Path,
        default=DEFAULT_PAYLOAD_ROOT,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stage_payload(
        executable_dir=args.executable_dir,
        payload_root=args.payload_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
