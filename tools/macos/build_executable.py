from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable


DEFAULT_DIST_ROOT = Path("build/macos/executable")
DEFAULT_WORK_ROOT = Path("build/macos/pyinstaller-work")
DEFAULT_SPEC_ROOT = Path("build/macos/pyinstaller-spec")
ENTRY_SCRIPT = Path("distribution/macos/qa_platform_cli_entry.py")


def pyinstaller_args(
    *,
    project_root: Path,
    dist_root: Path,
    work_root: Path,
    spec_root: Path,
) -> list[str]:
    entry_script = project_root / ENTRY_SCRIPT
    return [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        "qa-platform",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_root),
        "--specpath",
        str(spec_root),
        "--collect-submodules",
        "qa_platform",
        "--hidden-import",
        "google.genai",
        "--hidden-import",
        "cv2",
        "--hidden-import",
        "fitz",
        "--hidden-import",
        "PIL",
        "--hidden-import",
        "pytesseract",
        str(entry_script),
    ]


def build_executable(
    *,
    project_root: Path,
    dist_root: Path = DEFAULT_DIST_ROOT,
    work_root: Path = DEFAULT_WORK_ROOT,
    spec_root: Path = DEFAULT_SPEC_ROOT,
    runner: Callable[[list[str]], object] | None = None,
) -> None:
    args = pyinstaller_args(
        project_root=project_root,
        dist_root=dist_root,
        work_root=work_root,
        spec_root=spec_root,
    )
    if runner is None:
        from PyInstaller.__main__ import run as pyinstaller_run

        runner = pyinstaller_run
    runner(args)


def _resolve_project_path(project_root: Path, value: Path) -> Path:
    path = value.expanduser()
    if path.is_absolute():
        return path
    return project_root / path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build macOS qa-platform executable.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--dist-root", type=Path, default=DEFAULT_DIST_ROOT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--spec-root", type=Path, default=DEFAULT_SPEC_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = args.project_root.resolve()
    build_executable(
        project_root=project_root,
        dist_root=_resolve_project_path(project_root, args.dist_root),
        work_root=_resolve_project_path(project_root, args.work_root),
        spec_root=_resolve_project_path(project_root, args.spec_root),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
