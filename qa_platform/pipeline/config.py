from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal

from qa_platform.execution.docker_runtime import DockerExecutorConfig
from qa_platform.extraction.config import load_document_extraction_config
from qa_platform.extraction.models import DocumentExtractionConfig
from qa_platform.shared.paths import (
    resolve_workspace_command_path,
    resolve_workspace_path,
    resolve_workspace_root,
)


ExecutionBackend = Literal["docker"]


@dataclass(frozen=True)
class QaPipelineConfig:
    extractor: DocumentExtractionConfig
    execution_backend: ExecutionBackend = "docker"
    run_root: Path = Path("run")
    docker: DockerExecutorConfig = DockerExecutorConfig()
    workspace_root: Path = Path(".")

    def __post_init__(self) -> None:
        if self.execution_backend != "docker":
            raise ValueError(
                "Docker-only execution is supported. "
                "Remove execution.backend or set it to 'docker'."
            )


def load_qa_pipeline_config(
    config_data: dict[str, Any] | str | Path,
    *,
    config_dir: Path | None = None,
    workspace_root_override: str | Path | None = None,
    env_file_override: str | Path | None = None,
) -> QaPipelineConfig:
    if isinstance(config_data, (str, Path)):
        config_path = Path(config_data).expanduser()
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
        if config_dir is None:
            config_dir = config_path.parent
    else:
        raw_config = dict(config_data)

    paths = dict(raw_config.get("paths", {}))
    if workspace_root_override is not None:
        paths["workspace_root"] = str(workspace_root_override)
    if env_file_override is not None:
        paths["env_file"] = str(env_file_override)
    raw_config["paths"] = paths

    extractor_config = load_document_extraction_config(
        raw_config,
        config_dir=config_dir,
    )
    project = raw_config.get("project", {})
    execution = raw_config.get("execution", {})
    if "python_version" in project:
        python_version = project["python_version"]
        if not isinstance(python_version, str):
            raise ValueError("project.python_version must be a string.")
    else:
        python_version = "3.11"

    backend = str(execution.get("backend", "docker"))
    if backend != "docker":
        raise ValueError(
            "Docker-only execution is supported. "
            "Remove execution.backend or set it to 'docker'."
        )

    workspace_root = resolve_workspace_root(
        paths.get("workspace_root"),
        config_dir=config_dir,
    )

    return QaPipelineConfig(
        extractor=extractor_config,
        execution_backend=backend,
        run_root=resolve_workspace_path(
            paths.get("run_root", "run"),
            workspace_root,
        ),
        docker=_load_docker_config(
            execution.get("docker", {}),
            python_version=python_version,
            workspace_root=workspace_root,
        ),
        workspace_root=workspace_root,
    )


def _load_docker_config(
    config_data: dict[str, Any],
    *,
    python_version: str,
    workspace_root: Path,
) -> DockerExecutorConfig:
    if not isinstance(config_data, dict):
        raise TypeError("execution.docker must be an object.")

    if "python_version" in config_data:
        raise ValueError(
            "Use project.python_version instead of "
            "execution.docker.python_version."
        )

    allowed_fields = {field.name for field in fields(DockerExecutorConfig)}
    unknown_fields = sorted(set(config_data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise ValueError(f"Unknown execution.docker option: {joined}")

    normalized_config = dict(config_data)
    if "docker_cmd" in normalized_config:
        normalized_config["docker_cmd"] = resolve_workspace_command_path(
            normalized_config["docker_cmd"],
            workspace_root,
        )
    for path_key in ("image_build_context", "image_build_dockerfile"):
        path_value = normalized_config.get(path_key)
        if path_value is not None and str(path_value).strip():
            normalized_config[path_key] = resolve_workspace_path(
                path_value,
                workspace_root,
            )

    return DockerExecutorConfig(
        python_version=python_version,
        **normalized_config,
    )
