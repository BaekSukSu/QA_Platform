from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from qa_platform.execution.docker_runtime import (
    DockerCliRuntime,
    DockerExecutorConfig,
)
from qa_platform.extraction.tesseract_filter import resolve_tesseract_runtime
from qa_platform.shared.executables import ExecutableNotFoundError
from qa_platform.shared.paths import (
    resolve_env_file_path,
    resolve_workspace_command_path,
    resolve_workspace_path,
    resolve_workspace_root,
)
from qa_platform.shared.resources import resolve_resource_root


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class DoctorResult:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)


CLI_WRAPPER_DIR = Path("/usr/local/bin")
CLI_WRAPPER_PATH = CLI_WRAPPER_DIR / "qa-platform"


def _path_contains_cli_wrapper_dir() -> bool:
    entries = {
        Path(entry).expanduser()
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry.strip()
    }
    return CLI_WRAPPER_DIR in entries


def _build_path_check() -> DoctorCheck:
    if _path_contains_cli_wrapper_dir():
        return DoctorCheck(
            name="path",
            ok=True,
            message=f"{CLI_WRAPPER_DIR} is on PATH",
        )
    return DoctorCheck(
        name="path",
        ok=False,
        message=(
            f"{CLI_WRAPPER_DIR} is not on PATH; run "
            f"{CLI_WRAPPER_PATH} doctor or add {CLI_WRAPPER_DIR} to PATH"
        ),
    )


def _tesseract_install_hint(message: str) -> str:
    return (
        f"{message}. Install Tesseract (macOS: brew install tesseract) "
        "or pass --tesseract-cmd /path/to/tesseract."
    )


def format_doctor_result(result: DoctorResult) -> str:
    lines = []
    for check in result.checks:
        status = "OK" if check.ok else "FAIL"
        lines.append(f"[{status}] {check.name}: {check.message}")
    return "\n".join(lines)


def _nonblank(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _load_doctor_config(config_path: Path) -> tuple[dict[str, Any], DoctorCheck]:
    if not config_path.exists():
        return {}, DoctorCheck(
            name="config",
            ok=False,
            message=f"{config_path} does not exist",
        )

    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, DoctorCheck(
            name="config",
            ok=False,
            message=f"{config_path} has invalid JSON: {exc.msg}",
        )

    if not isinstance(loaded, dict):
        return {}, DoctorCheck(
            name="config",
            ok=False,
            message=f"{config_path} must contain a JSON object",
        )

    return loaded, DoctorCheck(name="config", ok=True, message=str(config_path))


def _resolve_configured_command(
    value: Any,
    *,
    workspace_root: Path,
) -> str | Path | None:
    return resolve_workspace_command_path(value, workspace_root) or None


def _config_sections(
    doctor_config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = doctor_config.get("paths", {})
    execution = doctor_config.get("execution", {})
    docker = execution.get("docker", {}) if isinstance(execution, dict) else {}
    return (
        paths if isinstance(paths, dict) else {},
        docker if isinstance(docker, dict) else {},
    )


def run_doctor(
    *,
    workspace_root: str | Path | None = None,
    config_path: str | Path | None = None,
    docker_cmd: str | Path | None = None,
    tesseract_cmd: str | Path | None = None,
    resource_root: str | Path | None = None,
) -> DoctorResult:
    checks: list[DoctorCheck] = []
    requested_config = Path(config_path).expanduser().resolve() if config_path else None
    initial_workspace = resolve_workspace_root(workspace_root, config_dir=None)
    effective_config = (
        requested_config
        if requested_config is not None
        else initial_workspace / "config" / "qa_pipeline.local.json"
    )
    doctor_config, config_check = _load_doctor_config(effective_config)
    config_paths, config_docker = _config_sections(doctor_config)

    if _nonblank(workspace_root):
        workspace = resolve_workspace_root(workspace_root, config_dir=None)
    elif _nonblank(config_paths.get("workspace_root")):
        workspace = resolve_workspace_root(
            config_paths.get("workspace_root"),
            config_dir=effective_config.parent,
        )
    else:
        workspace = resolve_workspace_root(None, config_dir=None)

    checks.append(
        DoctorCheck(
            name="workspace",
            ok=workspace.exists(),
            message=(
                str(workspace)
                if workspace.exists()
                else f"{workspace} does not exist; run qa-platform init-config"
            ),
        )
    )

    checks.append(config_check)

    env_path = resolve_env_file_path(
        config_paths.get("env_file"),
        workspace_root=workspace,
    )
    checks.append(
        DoctorCheck(
            name="env",
            ok=env_path.exists(),
            message=(
                str(env_path)
                if env_path.exists()
                else f"{env_path} does not exist"
            ),
        )
    )

    checks.append(_build_path_check())

    if _nonblank(resource_root):
        resource_root_value = resource_root
    elif _nonblank(config_paths.get("resource_root")):
        resource_root_value = resolve_workspace_path(
            config_paths.get("resource_root"),
            workspace,
        )
    else:
        resource_root_value = None
    resolved_resource_root = resolve_resource_root(resource_root_value)
    checks.append(
        DoctorCheck(
            name="resources",
            ok=True,
            message=(
                str(resolved_resource_root)
                if resolved_resource_root is not None
                else "resource directory was not found; resource directory is optional"
            ),
        )
    )

    if _nonblank(tesseract_cmd):
        effective_tesseract_cmd = tesseract_cmd
    else:
        effective_tesseract_cmd = _resolve_configured_command(
            config_paths.get("tesseract_cmd"),
            workspace_root=workspace,
        )

    try:
        tesseract = resolve_tesseract_runtime(
            effective_tesseract_cmd,
            resource_root=resolved_resource_root,
        )
        checks.append(
            DoctorCheck(
                name="tesseract",
                ok=True,
                message=str(tesseract.command),
            )
        )
    except ExecutableNotFoundError as exc:
        checks.append(
            DoctorCheck(
                name="tesseract",
                ok=False,
                message=_tesseract_install_hint(str(exc)),
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck(name="tesseract", ok=False, message=str(exc)))

    if _nonblank(docker_cmd):
        effective_docker_cmd = docker_cmd
    else:
        effective_docker_cmd = _resolve_configured_command(
            config_docker.get("docker_cmd"),
            workspace_root=workspace,
        )

    try:
        DockerCliRuntime().check_cli_and_daemon(
            DockerExecutorConfig(docker_cmd=str(effective_docker_cmd or ""))
        )
        checks.append(
            DoctorCheck(
                name="docker",
                ok=True,
                message="Docker CLI and daemon are ready",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck(name="docker", ok=False, message=str(exc)))

    return DoctorResult(checks=tuple(checks))
