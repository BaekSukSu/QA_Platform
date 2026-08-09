from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Callable

from tools.macos.build_executable import (
    DEFAULT_DIST_ROOT as DEFAULT_EXECUTABLE_DIST_ROOT,
    DEFAULT_SPEC_ROOT as DEFAULT_EXECUTABLE_SPEC_ROOT,
    DEFAULT_WORK_ROOT as DEFAULT_EXECUTABLE_WORK_ROOT,
    build_executable,
)
from tools.macos.stage_pkg_payload import (
    DEFAULT_PAYLOAD_ROOT,
    stage_payload,
)


PRODUCT_IDENTIFIER = "com.qa-platform.cli"
DEFAULT_INTERMEDIATE_ROOT = Path("build/macos/intermediate")
DEFAULT_OUTPUT_PKG = Path("dist/qa-platform-macos-arm64.pkg")


def pkgbuild_command(
    *,
    payload_root: Path,
    identifier: str,
    version: str,
    component_pkg: Path,
) -> list[str]:
    return [
        "pkgbuild",
        "--root",
        str(payload_root),
        "--identifier",
        identifier,
        "--version",
        version,
        "--install-location",
        "/",
        str(component_pkg),
    ]


def productbuild_command(
    *,
    component_pkg: Path,
    output_pkg: Path,
    sign_identity: str,
) -> list[str]:
    command = ["productbuild"]
    if sign_identity:
        command.extend(["--sign", sign_identity])
    command.extend(["--package", str(component_pkg), str(output_pkg)])
    return command


def run_command(
    command: list[str],
    *,
    runner: Callable[[list[str]], object] | None = None,
) -> None:
    if runner is None:
        subprocess.run(command, check=True)
        return
    runner(command)


def build_pkg(
    *,
    project_root: Path,
    version: str,
    executable_dist_root: Path,
    executable_work_root: Path,
    executable_spec_root: Path,
    payload_root: Path,
    intermediate_root: Path,
    output_pkg: Path,
    sign_identity: str = "",
    runner: Callable[[list[str]], object] | None = None,
) -> Path:
    build_executable(
        project_root=project_root,
        dist_root=executable_dist_root,
        work_root=executable_work_root,
        spec_root=executable_spec_root,
    )
    stage_payload(
        executable_dir=executable_dist_root / "qa-platform",
        payload_root=payload_root,
    )

    intermediate_root.mkdir(parents=True, exist_ok=True)
    output_pkg.parent.mkdir(parents=True, exist_ok=True)
    component_pkg = intermediate_root / "qa-platform-component.pkg"

    run_command(
        pkgbuild_command(
            payload_root=payload_root,
            identifier=PRODUCT_IDENTIFIER,
            version=version,
            component_pkg=component_pkg,
        ),
        runner=runner,
    )
    run_command(
        productbuild_command(
            component_pkg=component_pkg,
            output_pkg=output_pkg,
            sign_identity=sign_identity,
        ),
        runner=runner,
    )
    return output_pkg


def _resolve_project_path(project_root: Path, value: Path) -> Path:
    path = value.expanduser()
    if path.is_absolute():
        return path
    return project_root / path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build macOS qa-platform pkg.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--executable-dist-root",
        type=Path,
        default=DEFAULT_EXECUTABLE_DIST_ROOT,
    )
    parser.add_argument(
        "--executable-work-root",
        type=Path,
        default=DEFAULT_EXECUTABLE_WORK_ROOT,
    )
    parser.add_argument(
        "--executable-spec-root",
        type=Path,
        default=DEFAULT_EXECUTABLE_SPEC_ROOT,
    )
    parser.add_argument(
        "--payload-root",
        type=Path,
        default=DEFAULT_PAYLOAD_ROOT,
    )
    parser.add_argument(
        "--intermediate-root",
        type=Path,
        default=DEFAULT_INTERMEDIATE_ROOT,
    )
    parser.add_argument("--output-pkg", type=Path, default=DEFAULT_OUTPUT_PKG)
    parser.add_argument("--sign-identity", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = args.project_root.resolve()
    output_pkg = build_pkg(
        project_root=project_root,
        version=args.version,
        executable_dist_root=_resolve_project_path(
            project_root,
            args.executable_dist_root,
        ),
        executable_work_root=_resolve_project_path(
            project_root,
            args.executable_work_root,
        ),
        executable_spec_root=_resolve_project_path(
            project_root,
            args.executable_spec_root,
        ),
        payload_root=_resolve_project_path(project_root, args.payload_root),
        intermediate_root=_resolve_project_path(
            project_root,
            args.intermediate_root,
        ),
        output_pkg=_resolve_project_path(project_root, args.output_pkg),
        sign_identity=args.sign_identity,
    )
    print(output_pkg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
