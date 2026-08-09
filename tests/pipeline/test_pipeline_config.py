import json
from pathlib import Path

import pytest

from qa_platform.execution.docker_runtime import DockerExecutorConfig
from qa_platform.extraction.models import DocumentExtractionConfig
from qa_platform.pipeline.config import QaPipelineConfig, load_qa_pipeline_config


def test_load_qa_pipeline_config_defaults_to_docker(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_pdf = tmp_path / "chapter02.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_qa_pipeline_config(
        {
            "project": {
                "book_id": "python_junior",
                "chapter_number": 2,
                "extractor_engine": "pdf",
            },
            "paths": {
                "input_pdf": str(input_pdf),
                "run_root": str(tmp_path / "qa_pipeline_runs"),
            },
            "api": {},
        }
    )

    assert isinstance(config, QaPipelineConfig)
    assert config.extractor.input_hwp is None
    assert config.extractor.input_pdf == input_pdf
    assert config.extractor.book_id == "python_junior"
    assert config.extractor.chapter_number == 2
    assert config.execution_backend == "docker"
    assert config.run_root == tmp_path / "qa_pipeline_runs"
    assert isinstance(config.docker, DockerExecutorConfig)
    assert config.docker.python_version == "3.11"


def test_load_qa_pipeline_config_defaults_run_root_to_run(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    input_pdf = workspace_root / "chapter02.pdf"
    workspace_root.mkdir()
    input_pdf.write_bytes(b"%PDF")

    config = load_qa_pipeline_config(
        {
            "project": {
                "chapter_number": 2,
                "extractor_engine": "pdf",
            },
            "paths": {"input_pdf": str(input_pdf)},
            "api": {},
        },
        workspace_root_override=workspace_root,
    )

    assert config.workspace_root == workspace_root
    assert config.run_root == workspace_root / "run"


def test_load_qa_pipeline_config_resolves_run_root_from_workspace_root(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    input_hwp = workspace_root / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")
    input_pdf = workspace_root / "chapter02.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_qa_pipeline_config(
        {
            "project": {"chapter_number": 2},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_hwp": "chapter02.hwp",
                "input_pdf": "chapter02.pdf",
                "run_root": "run",
            },
            "api": {},
        }
    )

    assert config.workspace_root == workspace_root
    assert config.extractor.input_hwp == workspace_root / "chapter02.hwp"
    assert config.extractor.input_pdf == workspace_root / "chapter02.pdf"
    assert config.run_root == workspace_root / "run"


def test_load_qa_pipeline_config_resolves_workspace_root_from_config_dir(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    config_dir = workspace_root / "config"
    config_dir.mkdir(parents=True)
    input_hwp = workspace_root / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")
    input_pdf = workspace_root / "chapter02.pdf"
    input_pdf.write_bytes(b"%PDF")

    config = load_qa_pipeline_config(
        {
            "project": {"chapter_number": 2},
            "paths": {
                "workspace_root": "..",
                "input_hwp": "chapter02.hwp",
                "input_pdf": "chapter02.pdf",
                "run_root": "run",
            },
            "api": {},
        },
        config_dir=config_dir,
    )

    assert config.workspace_root == workspace_root
    assert config.extractor.input_hwp == workspace_root / "chapter02.hwp"
    assert config.extractor.input_pdf == workspace_root / "chapter02.pdf"
    assert config.run_root == workspace_root / "run"


def test_load_qa_pipeline_config_workspace_override_applies_before_path_resolution(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    config_workspace = tmp_path / "config-workspace"
    override_workspace = tmp_path / "override-workspace"
    override_workspace.mkdir()
    input_pdf = override_workspace / "input" / "chapter02.pdf"
    input_pdf.parent.mkdir()
    input_pdf.write_bytes(b"%PDF")

    config = load_qa_pipeline_config(
        {
            "project": {
                "chapter_number": 2,
                "extractor_engine": "pdf",
            },
            "paths": {
                "workspace_root": str(config_workspace),
                "input_pdf": "input/chapter02.pdf",
                "run_root": "run/qa_pipeline",
            },
            "api": {},
        },
        workspace_root_override=override_workspace,
    )

    assert config.workspace_root == override_workspace
    assert config.extractor.input_pdf == input_pdf
    assert config.run_root == override_workspace / "run" / "qa_pipeline"


def test_load_qa_pipeline_config_reads_json_file_path_with_workspace_override(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    input_pdf = workspace_root / "input" / "chapter02.pdf"
    input_pdf.parent.mkdir(parents=True)
    input_pdf.write_bytes(b"%PDF")
    config_path = tmp_path / "config" / "qa_pipeline.local.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "chapter_number": 2,
                    "extractor_engine": "pdf",
                },
                "paths": {
                    "workspace_root": "old-workspace",
                    "input_pdf": "input/chapter02.pdf",
                    "run_root": "run",
                },
                "api": {},
            }
        ),
        encoding="utf-8",
    )

    config = load_qa_pipeline_config(
        config_path,
        workspace_root_override=workspace_root,
    )

    assert config.workspace_root == workspace_root
    assert config.extractor.input_pdf == input_pdf
    assert config.run_root == workspace_root / "run"


def test_qa_pipeline_config_preserves_legacy_positional_constructor_order(
    tmp_path,
) -> None:
    extractor = DocumentExtractionConfig(
        input_hwp=tmp_path / "chapter02.hwp",
        chapter_number=2,
        book_id="python_junior",
        gemini_api_key="key",
    )
    run_root = tmp_path / "run"
    docker = DockerExecutorConfig(timeout_seconds=9)

    config = QaPipelineConfig(extractor, "docker", run_root, docker)

    assert config.extractor is extractor
    assert config.execution_backend == "docker"
    assert config.run_root == run_root
    assert config.docker is docker
    assert config.workspace_root == Path(".")


def test_qa_pipeline_config_rejects_direct_legacy_backend(tmp_path) -> None:
    legacy_backend = "lo" + "cal"

    with pytest.raises(ValueError, match="Docker-only"):
        QaPipelineConfig(
            extractor=DocumentExtractionConfig(
                input_hwp=tmp_path / "chapter02.hwp",
                chapter_number=2,
                book_id="python_junior",
                gemini_api_key="key",
            ),
            execution_backend=legacy_backend,
        )


def test_load_qa_pipeline_config_rejects_legacy_backend(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_hwp = tmp_path / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")
    legacy_backend = "lo" + "cal"

    with pytest.raises(ValueError, match="Docker-only"):
        load_qa_pipeline_config(
            {
                "project": {"chapter_number": 2},
                "paths": {"input_hwp": str(input_hwp)},
                "api": {},
                "execution": {"backend": legacy_backend},
            }
        )


def test_load_qa_pipeline_config_rejects_unknown_backend(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_hwp = tmp_path / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")

    with pytest.raises(ValueError, match="Docker-only"):
        load_qa_pipeline_config(
            {
                "project": {"chapter_number": 2},
                "paths": {"input_hwp": str(input_hwp)},
                "api": {},
                "execution": {"backend": "remote"},
            }
        )


def test_load_qa_pipeline_config_maps_project_python_version(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_hwp = tmp_path / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")

    config = load_qa_pipeline_config(
        {
            "project": {
                "chapter_number": 2,
                "python_version": "3.12",
            },
            "paths": {"input_hwp": str(input_hwp)},
            "api": {},
        }
    )

    assert config.execution_backend == "docker"
    assert config.docker.python_version == "3.12"
    assert config.docker.image == "qa-platform-python-stdlib:3.12"


def test_load_qa_pipeline_config_maps_quoted_python_version_310(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_hwp = tmp_path / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")

    config = load_qa_pipeline_config(
        {
            "project": {
                "chapter_number": 2,
                "python_version": "3.10",
            },
            "paths": {"input_hwp": str(input_hwp)},
            "api": {},
        }
    )

    assert config.docker.python_version == "3.10"
    assert config.docker.image == "qa-platform-python-stdlib:3.10"


def test_load_qa_pipeline_config_rejects_numeric_python_version(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_hwp = tmp_path / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")

    with pytest.raises(ValueError, match="project.python_version"):
        load_qa_pipeline_config(
            {
                "project": {
                    "chapter_number": 2,
                    "python_version": 3.10,
                },
                "paths": {"input_hwp": str(input_hwp)},
                "api": {},
            }
        )


def test_load_qa_pipeline_config_rejects_invalid_python_version(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_hwp = tmp_path / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")

    with pytest.raises(ValueError, match="python_version"):
        load_qa_pipeline_config(
            {
                "project": {
                    "chapter_number": 2,
                    "python_version": "latest",
                },
                "paths": {"input_hwp": str(input_hwp)},
                "api": {},
            }
        )


def test_load_qa_pipeline_config_rejects_docker_python_version(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_hwp = tmp_path / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")

    with pytest.raises(ValueError, match="project.python_version"):
        load_qa_pipeline_config(
            {
                "project": {
                    "chapter_number": 2,
                    "python_version": "3.12",
                },
                "paths": {"input_hwp": str(input_hwp)},
                "api": {},
                "execution": {
                    "docker": {
                        "python_version": "3.11",
                    },
                },
            }
        )


def test_load_qa_pipeline_config_rejects_docker_auto_build_image(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_hwp = tmp_path / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")

    with pytest.raises(ValueError, match="auto_build_image"):
        load_qa_pipeline_config(
            {
                "project": {"chapter_number": 2},
                "paths": {"input_hwp": str(input_hwp)},
                "api": {},
                "execution": {"docker": {"auto_build_image": True}},
            }
        )


def test_load_qa_pipeline_config_maps_docker_options(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    input_hwp = workspace_root / "chapter02.hwp"
    input_hwp.write_bytes(b"hwp")

    config = load_qa_pipeline_config(
        {
            "project": {"chapter_number": 2},
            "paths": {
                "workspace_root": str(workspace_root),
                "input_hwp": str(input_hwp),
            },
            "api": {},
            "execution": {
                "backend": "docker",
                "docker": {
                    "image": "qa-platform-python-stdlib:3.11",
                    "timeout_seconds": 7,
                    "output_limit_chars": 1000,
                    "memory_limit": "512m",
                    "cpu_limit": 1.0,
                    "pids_limit": 128,
                    "work_tmpfs_size": "128m",
                    "temp_tmpfs_size": "128m",
                    "user": "10001:10001",
                    "image_build_context": "custom/context",
                    "image_build_dockerfile": "custom/context/Dockerfile",
                    "image_build_timeout_seconds": 600,
                },
            },
        }
    )

    assert config.docker.timeout_seconds == 7
    assert config.docker.output_limit_chars == 1000
    assert config.docker.memory_limit == "512m"
    assert config.docker.cpu_limit == 1.0
    assert config.docker.pids_limit == 128
    assert config.docker.work_tmpfs_size == "128m"
    assert config.docker.temp_tmpfs_size == "128m"
    assert config.docker.user == "10001:10001"
    assert config.docker.image_build_context == workspace_root / "custom/context"
    assert config.docker.image_build_dockerfile == workspace_root / Path(
        "custom/context/Dockerfile"
    )
    assert config.docker.image_build_timeout_seconds == 600


def test_load_qa_pipeline_config_resolves_docker_build_paths_from_workspace(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    config_dir = workspace_root / "config"
    other_dir = tmp_path / "other"
    input_pdf = workspace_root / "input" / "chapter02.pdf"
    input_pdf.parent.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    other_dir.mkdir()
    input_pdf.write_bytes(b"%PDF")
    config_path = config_dir / "qa_pipeline.local.json"
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "chapter_number": 2,
                    "extractor_engine": "pdf",
                },
                "paths": {
                    "workspace_root": "..",
                    "input_pdf": "input/chapter02.pdf",
                },
                "api": {},
                "execution": {
                    "docker": {
                        "image_build_context": "docker/custom",
                        "image_build_dockerfile": "docker/custom/Dockerfile",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(other_dir)

    config = load_qa_pipeline_config(config_path)

    assert config.docker.image_build_context == workspace_root / "docker/custom"
    assert config.docker.image_build_dockerfile == (
        workspace_root / "docker/custom/Dockerfile"
    )


def test_load_pipeline_config_maps_docker_cmd(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    input_pdf = tmp_path / "input" / "book.pdf"
    input_pdf.parent.mkdir()
    input_pdf.write_bytes(b"%PDF")
    config_path = tmp_path / "qa_pipeline.local.json"
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "book_id": "book",
                    "chapter_number": 1,
                    "python_version": "3.11",
                },
                "paths": {
                    "workspace_root": str(tmp_path),
                    "input_pdf": "input/book.pdf",
                },
                "api": {},
                "execution": {
                    "docker": {
                        "docker_cmd": (
                            "/Applications/Docker.app/Contents/Resources/bin/docker"
                        )
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    config = load_qa_pipeline_config(config_path)

    assert config.docker.docker_cmd == (
        "/Applications/Docker.app/Contents/Resources/bin/docker"
    )


def test_load_pipeline_config_resolves_runtime_paths_from_workspace(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    config_dir = workspace_root / "config"
    other_dir = tmp_path / "other"
    input_pdf = workspace_root / "input" / "book.pdf"
    resource_root = workspace_root / "resources"
    input_pdf.parent.mkdir(parents=True)
    resource_root.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    other_dir.mkdir()
    input_pdf.write_bytes(b"%PDF")
    config_path = config_dir / "qa_pipeline.local.json"
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "book_id": "book",
                    "chapter_number": 1,
                    "extractor_engine": "pdf",
                    "python_version": "3.11",
                },
                "paths": {
                    "workspace_root": "..",
                    "input_pdf": "input/book.pdf",
                    "resource_root": "resources",
                    "tesseract_cmd": "bin/tesseract",
                },
                "api": {},
                "execution": {
                    "docker": {
                        "docker_cmd": "bin/docker",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(other_dir)

    config = load_qa_pipeline_config(config_path)

    assert config.extractor.resource_root == resource_root.resolve()
    assert config.extractor.tesseract_cmd == str(workspace_root / "bin/tesseract")
    assert config.docker.docker_cmd == str(workspace_root / "bin/docker")


def test_load_pipeline_config_preserves_runtime_command_names(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    workspace_root = tmp_path / "workspace"
    input_pdf = workspace_root / "input" / "book.pdf"
    input_pdf.parent.mkdir(parents=True)
    input_pdf.write_bytes(b"%PDF")

    config = load_qa_pipeline_config(
        {
            "project": {
                "book_id": "book",
                "chapter_number": 1,
                "extractor_engine": "pdf",
                "python_version": "3.11",
            },
            "paths": {
                "workspace_root": str(workspace_root),
                "input_pdf": "input/book.pdf",
                "tesseract_cmd": "tesseract",
            },
            "api": {},
            "execution": {
                "docker": {
                    "docker_cmd": "docker",
                }
            },
        }
    )

    assert config.extractor.tesseract_cmd == "tesseract"
    assert config.docker.docker_cmd == "docker"
