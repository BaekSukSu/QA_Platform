from pathlib import Path
import io
import subprocess
import tempfile

import pytest

from qa_platform.execution.docker_runtime import (
    DEFAULT_DOCKERFILE_TEMPLATE,
    DockerCleanupError,
    DockerCliRuntime,
    DockerCliUnavailableError,
    DockerDaemonUnavailableError,
    DockerExecutorConfig,
    DockerImageBuildError,
    DockerLifecycleError,
    _BoundedTextBuffer,
    python_version_matches,
)


def patch_docker_cli(monkeypatch) -> None:
    monkeypatch.setattr(
        DockerCliRuntime,
        "resolve_docker_cli",
        lambda self, config: Path("docker"),
    )


def test_default_docker_executor_config() -> None:
    config = DockerExecutorConfig()

    assert config.python_version == "3.11"
    assert config.image == "qa-platform-python-stdlib:3.11"
    assert config.timeout_seconds == 5
    assert config.output_limit_chars == 20_000
    assert config.memory_limit == "256m"
    assert config.cpu_limit == 0.5
    assert config.pids_limit == 64
    assert config.work_tmpfs_size == "64m"
    assert config.temp_tmpfs_size == "64m"
    assert config.user == "10001:10001"
    assert config.image_build_context is None
    assert config.image_build_dockerfile is None
    assert config.image_build_timeout_seconds == 300


def test_default_config_has_no_repo_bound_build_context() -> None:
    config = DockerExecutorConfig()

    assert config.image_build_context is None
    assert config.image_build_dockerfile is None


def test_docker_executor_config_derives_image_from_python_version() -> None:
    config = DockerExecutorConfig(python_version="3.12")

    assert config.python_version == "3.12"
    assert config.image == "qa-platform-python-stdlib:3.12"


def test_docker_executor_config_allows_explicit_image_override() -> None:
    config = DockerExecutorConfig(
        python_version="3.12",
        image="custom-python:book",
    )

    assert config.python_version == "3.12"
    assert config.image == "custom-python:book"


def test_docker_executor_config_rejects_explicit_dependency_image() -> None:
    with pytest.raises(
        ValueError,
        match="install_requirements.*image",
    ):
        DockerExecutorConfig(
            image="custom-python:deps",
            install_requirements=("numpy",),
        )


def test_docker_executor_config_derives_dependency_image() -> None:
    config = DockerExecutorConfig(
        python_version="3.11",
        install_requirements=("pandas", "numpy"),
    )

    assert config.install_requirements == ("numpy", "pandas")
    assert config.image.startswith("qa-platform-python:3.11-deps-")


def test_docker_executor_config_rejects_invalid_python_version() -> None:
    with pytest.raises(ValueError, match="python_version"):
        DockerExecutorConfig(python_version="latest")


def test_docker_executor_config_rejects_numeric_python_version() -> None:
    with pytest.raises(ValueError, match="python_version"):
        DockerExecutorConfig(python_version=3.10)


def test_docker_executor_config_normalizes_build_paths() -> None:
    config = DockerExecutorConfig(
        image_build_context="custom/context",
        image_build_dockerfile="custom/context/Dockerfile",
    )

    assert config.image_build_context == Path("custom/context")
    assert config.image_build_dockerfile == Path("custom/context/Dockerfile")


def test_docker_executor_config_accepts_docker_cmd(tmp_path) -> None:
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\n", encoding="utf-8")
    docker.chmod(0o755)

    config = DockerExecutorConfig(docker_cmd=str(docker))

    assert config.docker_cmd == str(docker)


@pytest.mark.parametrize(
    ("requested", "actual", "expected"),
    [
        ("3.11", "3.11.9", True),
        ("3.11.9", "3.11.9", True),
        ("3.11.9", "3.11.10", False),
        ("3.11", "3.12.0", False),
        ("3.11", "3.11.not-a-version", False),
    ],
)
def test_python_version_matches_policy(
    requested: str,
    actual: str,
    expected: bool,
) -> None:
    assert python_version_matches(requested, actual) is expected


def test_ensure_ready_rejects_missing_docker_cli(tmp_path) -> None:
    missing_docker = tmp_path / "missing-docker"

    with pytest.raises(
        DockerCliUnavailableError,
        match="Docker CLI is not available.*Docker-only",
    ):
        DockerCliRuntime().ensure_ready(
            DockerExecutorConfig(docker_cmd=str(missing_docker))
        )


def test_ensure_ready_wraps_cli_launch_error(monkeypatch) -> None:
    patch_docker_cli(monkeypatch)

    def raise_os_error(command, **kwargs):
        raise FileNotFoundError("docker disappeared")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        raise_os_error,
    )

    with pytest.raises(
        DockerCliUnavailableError,
        match="docker disappeared",
    ):
        DockerCliRuntime().ensure_ready(DockerExecutorConfig())


def test_ensure_ready_rejects_unavailable_daemon(monkeypatch) -> None:
    patch_docker_cli(monkeypatch)

    def fake_run(command, **kwargs):
        assert command[:2] == ["docker", "version"]
        return subprocess.CompletedProcess(
            command,
            returncode=1,
            stdout="",
            stderr="Cannot connect to the Docker daemon",
        )

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(
        DockerDaemonUnavailableError,
        match="Docker daemon is unavailable",
    ) as exc_info:
        DockerCliRuntime().ensure_ready(DockerExecutorConfig())

    assert "Docker-only" in str(exc_info.value)
    assert "Cannot connect to the Docker daemon" in str(exc_info.value)


def test_check_cli_and_daemon_only_checks_docker_version(monkeypatch) -> None:
    patch_docker_cli(monkeypatch)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    docker_cmd = DockerCliRuntime().check_cli_and_daemon(DockerExecutorConfig())

    assert docker_cmd == Path("docker")
    assert commands == [["docker", "version", "--format", "{{.Server.Version}}"]]


def test_ensure_ready_uses_configured_docker_cmd(
    monkeypatch,
    tmp_path,
) -> None:
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\n", encoding="utf-8")
    docker.chmod(0o755)
    config = DockerExecutorConfig(docker_cmd=str(docker))
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["version", "--format"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[1:3] == ["run", "--rm"]:
            return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    DockerCliRuntime().ensure_ready(config)

    assert commands[0][0] == str(docker.resolve())


def test_ensure_ready_resolves_docker_cli_once_for_readiness_flow(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    runtime = DockerCliRuntime()
    docker_cmd = Path("/opt/task7/docker")
    resolve_calls: list[DockerExecutorConfig] = []
    commands: list[list[str]] = []
    inspect_count = 0

    def fake_resolve(config_arg):
        resolve_calls.append(config_arg)
        return docker_cmd

    def fake_run(command, **kwargs):
        nonlocal inspect_count
        commands.append(command)
        assert command[0] == str(docker_cmd)
        if command[1:3] == ["version", "--format"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[1:3] == ["image", "inspect"]:
            inspect_count += 1
            return subprocess.CompletedProcess(
                command,
                returncode=0 if inspect_count == 2 else 1,
                stdout="image-id\n" if inspect_count == 2 else "",
                stderr="" if inspect_count == 2 else "No such image",
            )
        if command[1] == "build":
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        if command[1:3] == ["run", "--rm"]:
            return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(runtime, "resolve_docker_cli", fake_resolve)
    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    runtime.ensure_ready(config)

    assert resolve_calls == [config]
    assert [command[1] for command in commands] == [
        "version",
        "image",
        "build",
        "image",
        "run",
    ]


def test_ensure_ready_builds_missing_image(monkeypatch, tmp_path) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)
    commands: list[list[str]] = []
    build_contexts: list[Path] = []
    build_dockerfile_texts: list[str] = []
    build_requirements_texts: list[str] = []
    inspect_count = 0

    def fake_run(command, **kwargs):
        nonlocal inspect_count
        commands.append(command)
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(
                command,
                returncode=0,
                stdout="28.0.0\n",
                stderr="",
            )
        if command[:3] == ["docker", "image", "inspect"]:
            inspect_count += 1
            return subprocess.CompletedProcess(
                command,
                returncode=0 if inspect_count == 2 else 1,
                stdout="image-id\n" if inspect_count == 2 else "",
                stderr="" if inspect_count == 2 else "No such image",
            )
        if command[:2] == ["docker", "build"]:
            build_context = Path(command[-1])
            build_contexts.append(build_context)
            build_dockerfile_texts.append(
                (build_context / "Dockerfile").read_text()
            )
            build_requirements_texts.append(
                (build_context / "requirements.txt").read_text()
            )
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    DockerCliRuntime().ensure_ready(config)

    assert [command[:3] for command in commands] == [
        ["docker", "version", "--format"],
        ["docker", "image", "inspect"],
        ["docker", "build", "--tag"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
    ]
    assert commands[2][:7] == [
        "docker",
        "build",
        "--tag",
        "custom-python:latest",
        "--build-arg",
        "PYTHON_VERSION=3.11",
        "--file",
    ]
    build_dockerfile = Path(commands[2][7])
    build_context = Path(commands[2][8])
    assert build_dockerfile == build_context / "Dockerfile"
    assert build_contexts == [build_context]
    assert build_dockerfile_texts == [dockerfile.read_text()]
    assert build_requirements_texts == [""]
    assert not build_context.exists()


def test_build_image_command_uses_configured_context_and_dockerfile(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    dockerfile = context / "Containerfile"
    config = DockerExecutorConfig(
        python_version="3.12",
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )

    patch_docker_cli(monkeypatch)

    command = DockerCliRuntime().build_image_command(config)

    assert command == [
        "docker",
        "build",
        "--tag",
        "custom-python:latest",
        "--build-arg",
        "PYTHON_VERSION=3.12",
        "--file",
        str(dockerfile.resolve()),
        str(context.resolve()),
    ]


def test_build_image_command_uses_configured_docker_cmd(tmp_path) -> None:
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\n", encoding="utf-8")
    docker.chmod(0o755)
    config = DockerExecutorConfig(docker_cmd=str(docker), image="qa-test:latest")
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim-bookworm\n", encoding="utf-8")

    command = DockerCliRuntime().build_image_command(
        config,
        context=context,
        dockerfile=dockerfile,
    )

    assert command[0] == str(docker.resolve())


def test_prepare_image_build_context_materializes_dependency_requirements(
    monkeypatch,
    tmp_path,
) -> None:
    config = DockerExecutorConfig(
        python_version="3.11",
        install_requirements=("pandas", "numpy"),
    )

    patch_docker_cli(monkeypatch)

    context = DockerCliRuntime().prepare_image_build_context(
        config,
        root=tmp_path,
    )
    command = DockerCliRuntime().build_image_command(
        config,
        build_context=context,
    )

    assert (context / "Dockerfile").read_text() == DEFAULT_DOCKERFILE_TEMPLATE
    assert (context / "requirements.txt").read_text() == "numpy\npandas\n"
    assert command == [
        "docker",
        "build",
        "--tag",
        config.image,
        "--build-arg",
        "PYTHON_VERSION=3.11",
        "--file",
        str((context / "Dockerfile").resolve()),
        str(context.resolve()),
    ]


def test_prepare_image_build_context_generates_default_dockerfile(
    tmp_path,
) -> None:
    config = DockerExecutorConfig(install_requirements=("requests", "numpy"))

    context = DockerCliRuntime().prepare_image_build_context(
        config,
        root=tmp_path,
    )

    assert (context / "Dockerfile").read_text(
        encoding="utf-8"
    ) == DEFAULT_DOCKERFILE_TEMPLATE
    assert (context / "requirements.txt").read_text(
        encoding="utf-8"
    ) == "numpy\nrequests\n"


def test_prepare_image_build_context_generates_empty_requirements_for_stdlib_image(
    tmp_path,
) -> None:
    config = DockerExecutorConfig()

    context = DockerCliRuntime().prepare_image_build_context(
        config,
        root=tmp_path,
    )

    assert (context / "requirements.txt").read_text(encoding="utf-8") == ""


def test_prepare_image_build_context_uses_root_as_temp_parent(
    tmp_path,
) -> None:
    sentinel_dir = tmp_path / "context"
    sentinel_dir.mkdir()
    sentinel = sentinel_dir / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    generated_context = DockerCliRuntime().prepare_image_build_context(
        DockerExecutorConfig(),
        root=tmp_path,
    )

    assert generated_context.parent == tmp_path
    assert generated_context != sentinel_dir
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert (generated_context / "Dockerfile").read_text(
        encoding="utf-8"
    ) == DEFAULT_DOCKERFILE_TEMPLATE


def test_build_image_command_requires_materialized_default_context() -> None:
    with pytest.raises(
        DockerImageBuildError,
        match="context is not materialized",
    ):
        DockerCliRuntime().build_image_command(DockerExecutorConfig())


def test_prepare_image_build_context_preserves_configured_context_files(
    tmp_path,
) -> None:
    source_context = tmp_path / "source-context"
    source_context.mkdir()
    (source_context / "Containerfile").write_text("FROM python:3.11-slim\n")
    (source_context / "helper.sh").write_text("#!/bin/sh\n")
    nested = source_context / "nested"
    nested.mkdir()
    (nested / "asset.txt").write_text("asset\n")
    (source_context / "requirements.txt").write_text("old\n")
    config = DockerExecutorConfig(
        python_version="3.11",
        install_requirements=("numpy",),
        image_build_context=source_context,
        image_build_dockerfile=source_context / "Containerfile",
    )

    context = DockerCliRuntime().prepare_image_build_context(
        config,
        root=tmp_path,
    )

    assert (context / "Dockerfile").read_text() == "FROM python:3.11-slim\n"
    assert (context / "helper.sh").read_text() == "#!/bin/sh\n"
    assert (context / "nested" / "asset.txt").read_text() == "asset\n"
    assert (context / "requirements.txt").read_text() == "numpy\n"


def test_prepare_image_build_context_supports_custom_context_and_dockerfile(
    tmp_path,
) -> None:
    source_context = tmp_path / "source-context"
    source_context.mkdir()
    (source_context / "extra.txt").write_text("extra", encoding="utf-8")
    custom_dockerfile = tmp_path / "Custom.Dockerfile"
    custom_dockerfile.write_text(
        "FROM python:3.11-slim-bookworm\n",
        encoding="utf-8",
    )
    config = DockerExecutorConfig(
        image_build_context=source_context,
        image_build_dockerfile=custom_dockerfile,
        install_requirements=("requests",),
    )

    context = DockerCliRuntime().prepare_image_build_context(
        config,
        root=tmp_path / "build",
    )

    assert (context / "extra.txt").read_text(encoding="utf-8") == "extra"
    assert (context / "Dockerfile").read_text(
        encoding="utf-8"
    ) == "FROM python:3.11-slim-bookworm\n"
    assert (context / "requirements.txt").read_text(
        encoding="utf-8"
    ) == "requests\n"


def test_prepare_image_build_context_requires_custom_context_and_dockerfile_together(
    tmp_path,
) -> None:
    source_context = tmp_path / "source-context"
    source_context.mkdir()

    with pytest.raises(
        DockerImageBuildError,
        match="image_build_context and image_build_dockerfile",
    ):
        DockerCliRuntime().prepare_image_build_context(
            DockerExecutorConfig(image_build_context=source_context),
            root=tmp_path,
        )


def test_prepare_image_build_context_rejects_missing_custom_context(
    tmp_path,
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.11-slim-bookworm\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DockerImageBuildError,
        match="Docker build context does not exist",
    ):
        DockerCliRuntime().prepare_image_build_context(
            DockerExecutorConfig(
                image_build_context=tmp_path / "missing-context",
                image_build_dockerfile=dockerfile,
            ),
            root=tmp_path,
        )


def test_prepare_image_build_context_rejects_missing_custom_dockerfile(
    tmp_path,
) -> None:
    source_context = tmp_path / "source-context"
    source_context.mkdir()

    with pytest.raises(
        DockerImageBuildError,
        match="Dockerfile does not exist",
    ):
        DockerCliRuntime().prepare_image_build_context(
            DockerExecutorConfig(
                image_build_context=source_context,
                image_build_dockerfile=tmp_path / "missing.Dockerfile",
            ),
            root=tmp_path,
        )


def test_prepare_image_build_context_removes_context_after_write_failure(
    monkeypatch,
    tmp_path,
) -> None:
    source_context = tmp_path / "source-context"
    source_context.mkdir()
    dockerfile = source_context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        image="custom-python:latest",
        image_build_context=source_context,
        image_build_dockerfile=dockerfile,
    )
    contexts: list[Path] = []
    original_mkdtemp = tempfile.mkdtemp
    original_write_text = Path.write_text

    def fake_mkdtemp(*args, **kwargs):
        context = Path(original_mkdtemp(*args, **kwargs))
        contexts.append(context)
        return str(context)

    def fail_generated_dockerfile_write(
        path,
        data,
        *args,
        **kwargs,
    ):
        if contexts and Path(path) == contexts[0] / "Dockerfile":
            raise OSError("cannot write generated Dockerfile")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.tempfile.mkdtemp",
        fake_mkdtemp,
    )
    monkeypatch.setattr(Path, "write_text", fail_generated_dockerfile_write)

    with pytest.raises(
        DockerImageBuildError,
        match="materialize Docker image build context",
    ) as exc_info:
        DockerCliRuntime().prepare_image_build_context(config)

    assert isinstance(exc_info.value.__cause__, OSError)
    assert len(contexts) == 1
    assert not contexts[0].exists()


def test_build_image_uses_prepare_context_missing_context_validation(
    monkeypatch,
    tmp_path,
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.11-slim-bookworm\n",
        encoding="utf-8",
    )
    config = DockerExecutorConfig(
        image_build_context=tmp_path / "missing-context",
        image_build_dockerfile=dockerfile,
    )
    runtime = DockerCliRuntime()

    def fail_resolve(config_arg):
        raise DockerCliUnavailableError("should not resolve before validation")

    monkeypatch.setattr(runtime, "resolve_docker_cli", fail_resolve)

    def unexpected_run(command, **kwargs):
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        unexpected_run,
    )

    with pytest.raises(
        DockerImageBuildError,
        match="Docker build context does not exist",
    ):
        runtime.build_image(config)


def test_build_image_removes_materialized_context_when_docker_cli_resolution_fails(
    monkeypatch,
    tmp_path,
) -> None:
    source_context = tmp_path / "source-context"
    source_context.mkdir()
    dockerfile = source_context / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.11-slim-bookworm\n",
        encoding="utf-8",
    )
    config = DockerExecutorConfig(
        image_build_context=source_context,
        image_build_dockerfile=dockerfile,
    )
    runtime = DockerCliRuntime()
    contexts: list[Path] = []
    original_mkdtemp = tempfile.mkdtemp

    def fake_mkdtemp(*args, **kwargs):
        context = Path(original_mkdtemp(*args, **kwargs))
        contexts.append(context)
        return str(context)

    def fail_resolve(config_arg):
        raise DockerCliUnavailableError("docker unavailable")

    def unexpected_run(command, **kwargs):
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.tempfile.mkdtemp",
        fake_mkdtemp,
    )
    monkeypatch.setattr(runtime, "resolve_docker_cli", fail_resolve)
    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        unexpected_run,
    )

    with pytest.raises(DockerCliUnavailableError, match="docker unavailable"):
        runtime.build_image(config)

    assert len(contexts) == 1
    assert not contexts[0].exists()


def test_build_image_removes_materialized_context_after_build_failure(
    monkeypatch,
    tmp_path,
) -> None:
    source_context = tmp_path / "source-context"
    source_context.mkdir()
    dockerfile = source_context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        image="custom-python:latest",
        image_build_context=source_context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)
    build_contexts: list[Path] = []

    def fake_run(command, **kwargs):
        build_contexts.append(Path(command[-1]))
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "build failed",
        )

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(DockerImageBuildError, match="build failed"):
        DockerCliRuntime().build_image(config)

    assert len(build_contexts) == 1
    assert not build_contexts[0].exists()


def test_build_image_removes_materialized_context_after_timeout(
    monkeypatch,
    tmp_path,
) -> None:
    source_context = tmp_path / "source-context"
    source_context.mkdir()
    dockerfile = source_context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        image="custom-python:latest",
        image_build_context=source_context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)
    build_contexts: list[Path] = []

    def fake_run(command, **kwargs):
        build_contexts.append(Path(command[-1]))
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=kwargs.get("timeout"),
        )

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(DockerImageBuildError, match="timed out"):
        DockerCliRuntime().build_image(config)

    assert len(build_contexts) == 1
    assert not build_contexts[0].exists()


def test_inspect_image_python_version_runs_named_sandboxed_probe(
    monkeypatch,
) -> None:
    config = DockerExecutorConfig(
        image="custom-python:latest",
        timeout_seconds=2.5,
        memory_limit="128m",
        cpu_limit=0.25,
        pids_limit=32,
        temp_tmpfs_size="16m",
        user="123:456",
    )
    runtime = DockerCliRuntime()
    patch_docker_cli(monkeypatch)
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: "qa-platform-python-version-probe-fixed",
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    result = runtime.inspect_image_python_version(config)

    assert result.stdout == "3.11.9\n"
    assert calls == [
        (
            [
                "docker",
                "run",
                "--rm",
                "--name",
                "qa-platform-python-version-probe-fixed",
                "--network",
                "none",
                "--memory",
                "128m",
                "--memory-swap",
                "128m",
                "--cpus",
                "0.25",
                "--pids-limit",
                "32",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
                "--user",
                "123:456",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--label",
                "qa-platform.managed=true",
                "--entrypoint",
                "python",
                "custom-python:latest",
                "-I",
                "-B",
                "-c",
                "import platform; print(platform.python_version())",
            ],
            {
                "capture_output": True,
                "text": True,
                "check": False,
                "timeout": 5.0,
            },
        )
    ]


def test_ensure_ready_builds_missing_image_with_configured_timeout(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
        image_build_timeout_seconds=12.5,
    )
    patch_docker_cli(monkeypatch)
    commands: list[list[str]] = []
    build_timeouts: list[float | None] = []
    inspect_count = 0

    def fake_run(command, **kwargs):
        nonlocal inspect_count
        commands.append(command)
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["docker", "image", "inspect"]:
            inspect_count += 1
            return subprocess.CompletedProcess(
                command,
                returncode=0 if inspect_count == 2 else 1,
                stdout="image-id\n" if inspect_count == 2 else "",
                stderr="" if inspect_count == 2 else "No such image",
            )
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")
        if command[:2] == ["docker", "build"]:
            build_timeouts.append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    DockerCliRuntime().ensure_ready(config)

    assert [command[:3] for command in commands] == [
        ["docker", "version", "--format"],
        ["docker", "image", "inspect"],
        ["docker", "build", "--tag"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
    ]
    assert build_timeouts == [12.5]


def test_ensure_ready_reuses_existing_image_with_matching_python_version(
    monkeypatch,
) -> None:
    patch_docker_cli(monkeypatch)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")
        if command[:2] == ["docker", "build"]:
            raise AssertionError("Matching image should not be rebuilt.")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    DockerCliRuntime().ensure_ready(DockerExecutorConfig())

    assert [command[:3] for command in commands] == [
        ["docker", "version", "--format"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
    ]


def test_ensure_ready_rebuilds_existing_image_with_mismatched_python_version(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        python_version="3.11",
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)
    commands: list[list[str]] = []
    probe_versions = ["3.12.0\n", "3.11.9\n"]

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(
                command,
                0,
                probe_versions.pop(0),
                "",
            )
        if command[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    DockerCliRuntime().ensure_ready(config)

    assert [command[:3] for command in commands] == [
        ["docker", "version", "--format"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
        ["docker", "build", "--tag"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
    ]
    assert probe_versions == []


def test_ensure_ready_rebuilds_existing_image_with_invalid_python_version_probe(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        python_version="3.11",
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)
    commands: list[list[str]] = []
    probe_versions = ["3.11.not-a-version\n", "3.11.9\n"]

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(
                command,
                0,
                probe_versions.pop(0),
                "",
            )
        if command[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    DockerCliRuntime().ensure_ready(config)

    assert [command[:3] for command in commands] == [
        ["docker", "version", "--format"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
        ["docker", "build", "--tag"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
    ]
    assert probe_versions == []


def test_ensure_ready_rebuilds_when_existing_python_version_probe_times_out(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        python_version="3.11",
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    runtime = DockerCliRuntime()
    patch_docker_cli(monkeypatch)
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: "qa-platform-python-version-probe-fixed",
    )
    commands: list[list[str]] = []
    probe_count = 0

    def fake_run(command, **kwargs):
        nonlocal probe_count
        commands.append(command)
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            probe_count += 1
            if probe_count == 1:
                raise subprocess.TimeoutExpired(
                    cmd=command,
                    timeout=kwargs.get("timeout"),
                )
            return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")
        if command[:3] == ["docker", "rm", "--force"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    runtime.ensure_ready(config)

    assert [command[:3] for command in commands] == [
        ["docker", "version", "--format"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
        ["docker", "rm", "--force"],
        ["docker", "build", "--tag"],
        ["docker", "image", "inspect"],
        ["docker", "run", "--rm"],
    ]
    assert commands[3] == [
        "docker",
        "rm",
        "--force",
        "qa-platform-python-version-probe-fixed",
    ]
    assert probe_count == 2


def test_ensure_ready_passes_config_timeout_to_python_version_probe(
    monkeypatch,
) -> None:
    config = DockerExecutorConfig(timeout_seconds=7.5)
    patch_docker_cli(monkeypatch)
    probe_timeouts: list[float | None] = []

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            probe_timeouts.append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")
        if command[:2] == ["docker", "build"]:
            raise AssertionError("Matching image should not be rebuilt.")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    DockerCliRuntime().ensure_ready(config)

    assert probe_timeouts == [7.5]


def test_ensure_ready_uses_minimum_timeout_for_python_version_probe(
    monkeypatch,
) -> None:
    config = DockerExecutorConfig(timeout_seconds=0.2)
    patch_docker_cli(monkeypatch)
    probe_timeouts: list[float | None] = []

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            probe_timeouts.append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(command, 0, "3.11.9\n", "")
        if command[:2] == ["docker", "build"]:
            raise AssertionError("Matching image should not be rebuilt.")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    DockerCliRuntime().ensure_ready(config)

    assert probe_timeouts == [5.0]


def test_ensure_ready_raises_build_error_when_rebuilt_python_version_mismatches(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        python_version="3.11",
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(command, 0, "3.12.0\n", "")
        if command[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(
        DockerImageBuildError,
        match="Python version mismatch",
    ):
        DockerCliRuntime().ensure_ready(config)


def test_ensure_ready_raises_build_error_when_rebuilt_python_version_is_invalid(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        python_version="3.11",
        image="custom-python:latest",
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(
                command,
                0,
                "3.11.not-a-version\n",
                "",
            )
        if command[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(
        DockerImageBuildError,
        match="Python version mismatch",
    ):
        DockerCliRuntime().ensure_ready(config)


def test_ensure_ready_raises_build_error_when_rebuilt_python_probe_times_out(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        python_version="3.11",
        image="custom-python:latest",
        timeout_seconds=0.2,
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    runtime = DockerCliRuntime()
    patch_docker_cli(monkeypatch)
    probe_names = iter(
        [
            "qa-platform-python-version-probe-one",
            "qa-platform-python-version-probe-two",
        ]
    )
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: next(probe_names),
    )
    probe_count = 0
    cleanup_commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        nonlocal probe_count
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "image-id\n", "")
        if command[:2] == ["docker", "run"]:
            probe_count += 1
            raise subprocess.TimeoutExpired(
                cmd=command,
                timeout=kwargs.get("timeout"),
            )
        if command[:3] == ["docker", "rm", "--force"]:
            cleanup_commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(
        DockerImageBuildError,
        match="Python version check timed out after 5.0 seconds",
    ):
        runtime.ensure_ready(config)

    assert probe_count == 2
    assert cleanup_commands == [
        [
            "docker",
            "rm",
            "--force",
            "qa-platform-python-version-probe-one",
        ],
        [
            "docker",
            "rm",
            "--force",
            "qa-platform-python-version-probe-two",
        ],
    ]


def test_ensure_ready_raises_build_error_when_build_fails(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("not a dockerfile\n")
    config = DockerExecutorConfig(
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "No such image",
            )
        if command[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "Dockerfile parse error",
            )
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(
        DockerImageBuildError,
        match="Dockerfile parse error",
    ):
        DockerCliRuntime().ensure_ready(config)


def test_ensure_ready_raises_build_error_when_build_times_out(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        image_build_context=context,
        image_build_dockerfile=dockerfile,
        image_build_timeout_seconds=0.01,
    )
    patch_docker_cli(monkeypatch)

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "No such image",
            )
        if command[:2] == ["docker", "build"]:
            raise subprocess.TimeoutExpired(
                cmd=command,
                timeout=kwargs.get("timeout"),
            )
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(
        DockerImageBuildError,
        match="timed out after 0.01 seconds",
    ):
        DockerCliRuntime().ensure_ready(config)


def test_ensure_ready_raises_build_error_when_built_image_is_still_missing(
    monkeypatch,
    tmp_path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")
    config = DockerExecutorConfig(
        image_build_context=context,
        image_build_dockerfile=dockerfile,
    )
    patch_docker_cli(monkeypatch)

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "still missing after build",
            )
        if command[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(command, 0, "built\n", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )

    with pytest.raises(
        DockerImageBuildError,
        match="still missing after build",
    ):
        DockerCliRuntime().ensure_ready(config)


def test_build_create_command_applies_all_sandbox_limits(
    monkeypatch,
    tmp_path,
) -> None:
    block_dir = tmp_path / "blocks with spaces" / "block_001"
    block_dir.mkdir(parents=True)
    config = DockerExecutorConfig()
    patch_docker_cli(monkeypatch)

    command = DockerCliRuntime().build_create_command(
        block_dir=block_dir,
        container_name="qa-platform-block-001-fixed",
        config=config,
    )

    assert command == [
        "docker",
        "create",
        "--name",
        "qa-platform-block-001-fixed",
        "--interactive",
        "--network",
        "none",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "64",
        "--read-only",
        "--tmpfs",
        (
            "/work:rw,nosuid,nodev,size=64m,"
            "uid=10001,gid=10001,mode=0700"
        ),
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--init",
        "--label",
        "qa-platform.managed=true",
        "--mount",
        (
            f"type=bind,source={block_dir.resolve()},"
            "target=/input,readonly"
        ),
        "--workdir",
        "/work",
        "qa-platform-python-stdlib:3.11",
        "python",
        "-I",
        "-B",
        "-u",
        "/input/normalized.py",
    ]


def test_build_create_command_uses_configured_docker_cmd(tmp_path) -> None:
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\n", encoding="utf-8")
    docker.chmod(0o755)
    block_dir = tmp_path / "block_001"
    block_dir.mkdir()

    command = DockerCliRuntime().build_create_command(
        block_dir=block_dir,
        container_name="qa-platform-block-001-fixed",
        config=DockerExecutorConfig(docker_cmd=str(docker)),
    )

    assert command[0] == str(docker.resolve())


def test_build_create_command_uses_configured_script_name(
    monkeypatch,
    tmp_path,
) -> None:
    block_dir = tmp_path / "block_repl"
    block_dir.mkdir()
    patch_docker_cli(monkeypatch)

    command = DockerCliRuntime().build_create_command(
        block_dir=block_dir,
        container_name="qa-platform-block-repl-fixed",
        config=DockerExecutorConfig(),
        script_name="repl_executable.py",
    )

    assert command[-1] == "/input/repl_executable.py"


@pytest.mark.parametrize(
    "script_name",
    [
        "",
        ".",
        "..",
        "../repl_executable.py",
        "nested/repl_executable.py",
        "/input/repl_executable.py",
        "repl\0executable.py",
    ],
)
def test_build_create_command_rejects_invalid_script_name(
    monkeypatch,
    tmp_path,
    script_name: str,
) -> None:
    block_dir = tmp_path / "block_invalid"
    block_dir.mkdir()
    patch_docker_cli(monkeypatch)

    with pytest.raises(ValueError, match="script_name"):
        DockerCliRuntime().build_create_command(
            block_dir=block_dir,
            container_name="qa-platform-block-invalid-fixed",
            config=DockerExecutorConfig(),
            script_name=script_name,
        )


@pytest.mark.parametrize(
    ("block_id", "expected"),
    [
        ("block_001", "qa-platform-block_001-1234567890ab"),
        ("한글 block/002", "qa-platform-block-002-1234567890ab"),
    ],
)
def test_container_name_is_sanitized(
    block_id: str,
    expected: str,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.uuid.uuid4",
        lambda: type("Uuid", (), {"hex": "1234567890abcdef"})(),
    )

    assert DockerCliRuntime().make_container_name(block_id) == expected


class RecordingStdin:
    def __init__(self) -> None:
        self.content = ""
        self.closed = False

    def write(self, text: str) -> int:
        self.content += text
        return len(text)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeAttachedProcess:
    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        timeout_once: bool = False,
        timeout_count: int = 0,
    ) -> None:
        self.stdin = RecordingStdin()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.timeout_count = timeout_count or int(timeout_once)
        self.wait_calls: list[float | None] = []
        self.kill_called = False

    def wait(self, timeout=None) -> int:
        self.wait_calls.append(timeout)
        if self.timeout_count > 0:
            self.timeout_count -= 1
            raise subprocess.TimeoutExpired(
                cmd=["docker", "start"],
                timeout=timeout,
            )
        return 0

    def kill(self) -> None:
        self.kill_called = True
        self.timeout_count = 0


def install_fake_docker_commands(
    monkeypatch,
    *,
    process: FakeAttachedProcess | None = None,
    inspect_exit_code: int = 0,
    fail_stage: str | None = None,
) -> tuple[list[list[str]], FakeAttachedProcess]:
    patch_docker_cli(monkeypatch)
    commands: list[list[str]] = []
    attached_process = process or FakeAttachedProcess()

    def fake_run(command, **kwargs):
        commands.append(command)
        stage = command[1]
        if stage == "create":
            return subprocess.CompletedProcess(
                command,
                returncode=int(fail_stage == "create"),
                stdout="container-id\n",
                stderr="create failed" if fail_stage == "create" else "",
            )
        if stage == "inspect":
            return subprocess.CompletedProcess(
                command,
                returncode=int(fail_stage == "inspect"),
                stdout=f"{inspect_exit_code}\n",
                stderr="inspect failed" if fail_stage == "inspect" else "",
            )
        if stage == "kill":
            return subprocess.CompletedProcess(
                command,
                returncode=int(fail_stage == "kill"),
                stdout="",
                stderr="kill failed" if fail_stage == "kill" else "",
            )
        if stage == "rm":
            return subprocess.CompletedProcess(
                command,
                returncode=int(fail_stage == "rm"),
                stdout="",
                stderr="remove failed" if fail_stage == "rm" else "",
            )
        raise AssertionError(f"Unexpected Docker command: {command}")

    def fake_popen(command, **kwargs):
        commands.append(command)
        if fail_stage == "start":
            raise OSError("start failed")
        return attached_process

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.Popen",
        fake_popen,
    )
    return commands, attached_process


def test_run_collects_output_exit_code_and_cleans_container(
    tmp_path,
    monkeypatch,
) -> None:
    block_dir = tmp_path / "block_001"
    block_dir.mkdir()
    process = FakeAttachedProcess(
        stdout="hello Ada\n",
        stderr="warning\n",
    )
    commands, process = install_fake_docker_commands(
        monkeypatch,
        process=process,
        inspect_exit_code=0,
    )
    runtime = DockerCliRuntime()
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: "qa-platform-block_001-fixed",
    )

    outcome = runtime.run(
        block_dir=block_dir,
        block_id="block_001",
        stdin="Ada\n",
        config=DockerExecutorConfig(),
    )

    assert outcome.exit_code == 0
    assert outcome.duration_ms >= 0
    assert outcome.stdout == "hello Ada\n"
    assert outcome.stderr == "warning\n"
    assert outcome.stdout_truncated is False
    assert outcome.stderr_truncated is False
    assert outcome.timed_out is False
    assert process.stdin.content == "Ada\n"
    assert process.stdin.closed is True
    assert [command[1] for command in commands] == [
        "create",
        "start",
        "inspect",
        "rm",
    ]


def test_run_resolves_docker_cli_once_for_container_lifecycle(
    tmp_path,
    monkeypatch,
) -> None:
    block_dir = tmp_path / "block_001"
    block_dir.mkdir()
    process = FakeAttachedProcess(stdout="done\n")
    runtime = DockerCliRuntime()
    docker_cmd = Path("/opt/task7/docker")
    resolve_calls: list[DockerExecutorConfig] = []
    commands: list[list[str]] = []
    config = DockerExecutorConfig()

    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: "qa-platform-block_001-fixed",
    )

    def fake_resolve(config_arg):
        resolve_calls.append(config_arg)
        return docker_cmd

    def fake_run(command, **kwargs):
        commands.append(command)
        assert command[0] == str(docker_cmd)
        stage = command[1]
        if stage == "create":
            return subprocess.CompletedProcess(command, 0, "container-id\n", "")
        if stage == "inspect":
            return subprocess.CompletedProcess(command, 0, "0\n", "")
        if stage == "rm":
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"Unexpected Docker command: {command}")

    def fake_popen(command, **kwargs):
        commands.append(command)
        assert command[0] == str(docker_cmd)
        return process

    monkeypatch.setattr(runtime, "resolve_docker_cli", fake_resolve)
    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.Popen",
        fake_popen,
    )

    outcome = runtime.run(
        block_dir=block_dir,
        block_id="block_001",
        stdin="",
        config=config,
    )

    assert outcome.exit_code == 0
    assert resolve_calls == [config]
    assert [command[1] for command in commands] == [
        "create",
        "start",
        "inspect",
        "rm",
    ]


def test_run_passes_script_name_to_create_command(
    tmp_path,
    monkeypatch,
) -> None:
    block_dir = tmp_path / "block_repl"
    block_dir.mkdir()
    process = FakeAttachedProcess(stdout="[1, 2, 3]\n")
    commands, _ = install_fake_docker_commands(
        monkeypatch,
        process=process,
        inspect_exit_code=0,
    )
    runtime = DockerCliRuntime()
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: "qa-platform-block-repl-fixed",
    )

    outcome = runtime.run(
        block_dir=block_dir,
        block_id="block_repl",
        stdin="",
        config=DockerExecutorConfig(),
        script_name="repl_executable.py",
    )

    assert outcome.stdout == "[1, 2, 3]\n"
    assert commands[0][1] == "create"
    assert commands[0][-1] == "/input/repl_executable.py"


def test_run_kills_and_removes_container_on_timeout(
    tmp_path,
    monkeypatch,
) -> None:
    block_dir = tmp_path / "block_002"
    block_dir.mkdir()
    process = FakeAttachedProcess(
        stdout="partial",
        timeout_once=True,
    )
    commands, process = install_fake_docker_commands(
        monkeypatch,
        process=process,
    )
    runtime = DockerCliRuntime()
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: "qa-platform-block_002-fixed",
    )

    outcome = runtime.run(
        block_dir=block_dir,
        block_id="block_002",
        stdin="",
        config=DockerExecutorConfig(timeout_seconds=0.1),
    )

    assert outcome.exit_code is None
    assert outcome.timed_out is True
    assert outcome.stdout == "partial"
    assert process.wait_calls == [0.1, 2]
    assert [command[1] for command in commands] == [
        "create",
        "start",
        "kill",
        "rm",
    ]


def test_run_kills_stuck_attach_process_after_container_timeout(
    tmp_path,
    monkeypatch,
) -> None:
    block_dir = tmp_path / "block_stuck"
    block_dir.mkdir()
    process = FakeAttachedProcess(timeout_count=2)
    commands, process = install_fake_docker_commands(
        monkeypatch,
        process=process,
    )
    runtime = DockerCliRuntime()
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: "qa-platform-block_stuck-fixed",
    )

    outcome = runtime.run(
        block_dir=block_dir,
        block_id="block_stuck",
        stdin="",
        config=DockerExecutorConfig(timeout_seconds=0.1),
    )

    assert outcome.timed_out is True
    assert process.kill_called is True
    assert process.wait_calls == [0.1, 2, 1]
    assert [command[1] for command in commands] == [
        "create",
        "start",
        "kill",
        "rm",
    ]


def test_run_wraps_create_launch_error(tmp_path, monkeypatch) -> None:
    block_dir = tmp_path / "block_launch_error"
    block_dir.mkdir()
    patch_docker_cli(monkeypatch)

    def raise_os_error(command, **kwargs):
        raise OSError("cannot launch docker")

    monkeypatch.setattr(
        "qa_platform.execution.docker_runtime.subprocess.run",
        raise_os_error,
    )

    with pytest.raises(
        DockerLifecycleError,
        match="cannot launch docker",
    ):
        DockerCliRuntime().run(
            block_dir=block_dir,
            block_id="block_launch_error",
            stdin="",
            config=DockerExecutorConfig(),
        )


@pytest.mark.parametrize("fail_stage", ["start", "inspect"])
def test_run_removes_container_after_lifecycle_failure(
    tmp_path,
    monkeypatch,
    fail_stage: str,
) -> None:
    block_dir = tmp_path / f"block_{fail_stage}"
    block_dir.mkdir()
    commands, _ = install_fake_docker_commands(
        monkeypatch,
        fail_stage=fail_stage,
    )
    runtime = DockerCliRuntime()
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: f"qa-platform-{block_id}-fixed",
    )

    with pytest.raises(DockerLifecycleError, match=fail_stage):
        runtime.run(
            block_dir=block_dir,
            block_id=block_dir.name,
            stdin="",
            config=DockerExecutorConfig(),
        )

    assert commands[-1][1] == "rm"


def test_run_raises_cleanup_error_when_remove_fails(
    tmp_path,
    monkeypatch,
) -> None:
    block_dir = tmp_path / "block_003"
    block_dir.mkdir()
    install_fake_docker_commands(monkeypatch, fail_stage="rm")
    runtime = DockerCliRuntime()
    monkeypatch.setattr(
        runtime,
        "make_container_name",
        lambda block_id: "qa-platform-block_003-fixed",
    )

    with pytest.raises(DockerCleanupError, match="remove failed"):
        runtime.run(
            block_dir=block_dir,
            block_id="block_003",
            stdin="",
            config=DockerExecutorConfig(),
        )


def test_bounded_text_buffer_discards_excess_without_losing_prefix() -> None:
    buffer = _BoundedTextBuffer(limit_chars=5)

    buffer.append("abc")
    buffer.append("def")

    assert buffer.value == "abcde"
    assert buffer.truncated is True
