from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from qa_platform.extraction.models import DocumentExtractionConfig
from qa_platform.shared.env import load_key_value_env_file
from qa_platform.shared.paths import (
    resolve_env_file_path,
    resolve_optional_workspace_path,
    resolve_workspace_command_path,
    resolve_workspace_path,
    resolve_workspace_root,
)
from qa_platform.shared.resources import resolve_resource_root


def load_document_extraction_config(
    config_data: dict[str, Any],
    *,
    config_dir: Path | None = None,
) -> DocumentExtractionConfig:
    project = config_data.get("project", {})
    paths = config_data.get("paths", {})

    workspace_root = resolve_workspace_root(
        paths.get("workspace_root"),
        config_dir=config_dir,
    )
    env_file = resolve_env_file_path(
        paths.get("env_file"),
        workspace_root=workspace_root,
    )
    load_key_value_env_file(env_file)

    gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_api_key:
        raise ValueError(
            "GEMINI_API_KEY 환경변수 또는 workspace_root/.env 설정이 필요합니다."
        )

    input_hwp = resolve_optional_workspace_path(
        paths.get("input_hwp"),
        workspace_root,
    )
    input_pdf = resolve_optional_workspace_path(
        paths.get("input_pdf"),
        workspace_root,
    )

    resource_root_value = paths.get("resource_root")
    if resource_root_value is not None and str(resource_root_value).strip():
        resource_root_value = resolve_workspace_path(
            resource_root_value,
            workspace_root,
        )
    resource_root = resolve_resource_root(resource_root_value)

    return DocumentExtractionConfig(
        input_hwp=input_hwp,
        input_pdf=input_pdf,
        chapter_number=int(project["chapter_number"]),
        book_id=str(project.get("book_id", "default")),
        gemini_api_key=str(gemini_api_key),
        extractor_engine=str(project.get("extractor_engine", "auto")),
        tesseract_cmd=resolve_workspace_command_path(
            paths.get("tesseract_cmd"),
            workspace_root,
        ),
        keep_temp_images=bool(project.get("keep_temp_images", False)),
        session_id=project.get("session_id") or None,
        resource_root=resource_root,
        output_root=resolve_workspace_path(
            paths.get("output_root", "extracted_blocks"),
            workspace_root,
        ),
        work_root=resolve_workspace_path(
            paths.get("work_root", "run/document_extraction"),
            workspace_root,
        ),
        security_module_name=str(
            project.get("security_module_name", "SecurityModule")
        ),
    )
