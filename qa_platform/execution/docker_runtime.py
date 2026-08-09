from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Protocol, TextIO

from qa_platform.contract.package_resolver import image_tag_for_requirements
from qa_platform.execution.support import ProcessOutcome
from qa_platform.shared.executables import (
    ExecutableNotFoundError,
    resolve_executable,
)


DEFAULT_PYTHON_VERSION = "3.11"
DEFAULT_IMAGE_REPOSITORY = "qa-platform-python-stdlib"
DEFAULT_DEPENDENCY_IMAGE_REPOSITORY = "qa-platform-python"
DEFAULT_DOCKERFILE_TEMPLATE = """ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1

COPY requirements.txt /tmp/qa-requirements.txt

RUN if [ -s /tmp/qa-requirements.txt ]; then \\
        python -m pip install --no-cache-dir -r /tmp/qa-requirements.txt; \\
    fi \\
    && rm -f /tmp/qa-requirements.txt

RUN groupadd --gid 10001 qa \\
    && useradd \\
        --uid 10001 \\
        --gid 10001 \\
        --no-create-home \\
        --shell /usr/sbin/nologin \\
        qa \\
    && mkdir -p /work \\
    && chown 10001:10001 /work

USER 10001:10001
WORKDIR /work

CMD ["python", "--version"]
"""
PYTHON_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){1,2}$")
PYTHON_VERSION_PROBE = "import platform; print(platform.python_version())"
MIN_PYTHON_VERSION_PROBE_TIMEOUT_SECONDS = 5.0
DOCKER_CANDIDATE_PATHS = (
    Path("/usr/local/bin/docker"),
    Path("/opt/homebrew/bin/docker"),
    Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
)


def normalize_python_version(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("python_version must be a string.")
    version = value.strip()
    if not PYTHON_VERSION_PATTERN.fullmatch(version):
        raise ValueError(
            "python_version must look like '3.11' or '3.11.9'."
        )
    return version


def python_version_matches(requested: str, actual: str) -> bool:
    try:
        requested_version = normalize_python_version(requested)
        actual_version = normalize_python_version(actual)
    except ValueError:
        return False
    requested_parts = requested_version.split(".")
    actual_parts = actual_version.split(".")
    if len(requested_parts) == 2 and len(actual_parts) >= 2:
        return requested_parts == actual_parts[:2]
    return requested_parts == actual_parts


@dataclass(frozen=True)
class DockerExecutorConfig:
    python_version: str = DEFAULT_PYTHON_VERSION
    docker_cmd: str = ""
    image: str = ""
    install_requirements: tuple[str, ...] = ()
    dependency_image_repository: str = DEFAULT_DEPENDENCY_IMAGE_REPOSITORY
    timeout_seconds: float = 5
    output_limit_chars: int = 20_000
    memory_limit: str = "256m"
    cpu_limit: float = 0.5
    pids_limit: int = 64
    work_tmpfs_size: str = "64m"
    temp_tmpfs_size: str = "64m"
    user: str = "10001:10001"
    image_build_context: Path | None = None
    image_build_dockerfile: Path | None = None
    image_build_timeout_seconds: float = 300

    def __post_init__(self) -> None:
        python_version = normalize_python_version(self.python_version)
        object.__setattr__(self, "python_version", python_version)
        install_requirements = tuple(
            sorted(
                {
                    requirement.strip()
                    for requirement in self.install_requirements
                    if requirement.strip()
                },
                key=str.casefold,
            )
        )
        object.__setattr__(
            self,
            "install_requirements",
            install_requirements,
        )
        if self.image and install_requirements:
            raise ValueError(
                "install_requirements cannot be combined with an explicit "
                "image; dependency-managed images derive a hash-based image "
                "tag."
            )
        if not self.image:
            image = (
                image_tag_for_requirements(
                    repository=self.dependency_image_repository,
                    python_version=python_version,
                    requirements=install_requirements,
                )
                if install_requirements
                else f"{DEFAULT_IMAGE_REPOSITORY}:{python_version}"
            )
            object.__setattr__(self, "image", image)
        if self.image_build_context is not None:
            object.__setattr__(
                self,
                "image_build_context",
                Path(self.image_build_context),
            )
        if self.image_build_dockerfile is not None:
            object.__setattr__(
                self,
                "image_build_dockerfile",
                Path(self.image_build_dockerfile),
            )


class DockerRuntimeError(RuntimeError):
    """Docker 실행 환경 또는 컨테이너 수명주기 오류."""


class DockerCliUnavailableError(DockerRuntimeError):
    """Docker CLI를 찾을 수 없음."""


class DockerDaemonUnavailableError(DockerRuntimeError):
    """Docker daemon에 연결할 수 없음."""


class DockerImageUnavailableError(DockerRuntimeError):
    """필요한 실행 image가 준비되지 않음."""


class DockerImageBuildError(DockerImageUnavailableError):
    """Docker image 자동 빌드 실패."""


class DockerLifecycleError(DockerRuntimeError):
    """컨테이너 생성, 실행, 종료 또는 조회 실패."""


class DockerCleanupError(DockerRuntimeError):
    """컨테이너 정리 실패."""


class DockerRuntime(Protocol):
    def ensure_ready(self, config: DockerExecutorConfig) -> None:
        ...

    def run(
        self,
        *,
        block_dir: Path,
        block_id: str,
        stdin: str,
        config: DockerExecutorConfig,
        script_name: str = "normalized.py",
    ) -> ProcessOutcome:
        ...


class _BoundedTextBuffer:
    def __init__(self, limit_chars: int) -> None:
        self.limit_chars = limit_chars
        self._chunks: list[str] = []
        self._stored_chars = 0
        self.truncated = False

    def append(self, text: str) -> None:
        if not text:
            return
        remaining = self.limit_chars - self._stored_chars
        if remaining > 0:
            stored = text[:remaining]
            self._chunks.append(stored)
            self._stored_chars += len(stored)
        if len(text) > remaining:
            self.truncated = True

    @property
    def value(self) -> str:
        return "".join(self._chunks)


class DockerCliRuntime:
    def resolve_docker_cli(self, config: DockerExecutorConfig) -> Path:
        try:
            return resolve_executable(
                "docker",
                configured_path=config.docker_cmd,
                candidate_paths=DOCKER_CANDIDATE_PATHS,
            )
        except ExecutableNotFoundError as exc:
            raise DockerCliUnavailableError(
                "Docker CLI is not available. QA Platform uses Docker-only "
                "execution; install Docker Desktop or another "
                "Docker-compatible runtime and start the Docker daemon. "
                f"{exc}"
            ) from exc

    def prepare_image_build_context(
        self,
        config: DockerExecutorConfig,
        *,
        root: Path | None = None,
    ) -> Path:
        root_path = Path(root) if root is not None else None
        if (
            config.image_build_context is None
        ) != (config.image_build_dockerfile is None):
            raise DockerImageBuildError(
                "image_build_context and image_build_dockerfile must be "
                "configured together"
            )
        if (
            config.image_build_context is not None
            and not config.image_build_context.exists()
        ):
            raise DockerImageBuildError(
                "Docker build context does not exist: "
                f"{config.image_build_context}"
            )
        if (
            config.image_build_dockerfile is not None
            and not config.image_build_dockerfile.exists()
        ):
            raise DockerImageBuildError(
                f"Dockerfile does not exist: {config.image_build_dockerfile}"
            )
        if root_path is not None:
            root_path.mkdir(parents=True, exist_ok=True)
        context = Path(
            tempfile.mkdtemp(
                prefix=f"{_safe_build_context_name(config.image)}-",
                dir=root_path,
            )
        )
        try:
            if config.image_build_context is not None:
                shutil.copytree(
                    config.image_build_context,
                    context,
                    dirs_exist_ok=True,
                )

            dockerfile = context / "Dockerfile"
            if config.image_build_dockerfile is not None:
                dockerfile.write_text(
                    config.image_build_dockerfile.read_text(
                        encoding="utf-8"
                    ),
                    encoding="utf-8",
                )
            else:
                dockerfile.write_text(
                    DEFAULT_DOCKERFILE_TEMPLATE,
                    encoding="utf-8",
                )

            requirements = "\n".join(config.install_requirements)
            if requirements:
                requirements += "\n"
            (context / "requirements.txt").write_text(
                requirements,
                encoding="utf-8",
            )
        except OSError as exc:
            shutil.rmtree(context, ignore_errors=True)
            raise DockerImageBuildError(
                "Failed to materialize Docker image build context: "
                f"{exc}"
            ) from exc
        return context

    def build_image_command(
        self,
        config: DockerExecutorConfig,
        *,
        build_context: Path | None = None,
        context: Path | None = None,
        dockerfile: Path | None = None,
        docker_cmd: Path | None = None,
    ) -> list[str]:
        if build_context is not None and context is not None:
            raise ValueError(
                "Use either build_context or context, not both."
            )
        context_path = (
            Path(build_context)
            if build_context is not None
            else Path(context)
            if context is not None
            else config.image_build_context
        )
        if context_path is None:
            raise DockerImageBuildError(
                "Docker image build context is not materialized. Call "
                "prepare_image_build_context() or pass build_context."
            )
        if dockerfile is not None:
            dockerfile_path = Path(dockerfile)
        elif build_context is not None or context is not None:
            dockerfile_path = context_path / "Dockerfile"
        else:
            dockerfile_path = config.image_build_dockerfile
        if dockerfile_path is None:
            raise DockerImageBuildError(
                "Docker image build Dockerfile is not configured. Pass "
                "dockerfile or build_context."
            )
        if docker_cmd is None:
            docker_cmd = self.resolve_docker_cli(config)
        return [
            str(docker_cmd),
            "build",
            "--tag",
            config.image,
            "--build-arg",
            f"PYTHON_VERSION={config.python_version}",
            "--file",
            str(dockerfile_path.resolve()),
            str(context_path.resolve()),
        ]

    def inspect_image(
        self,
        config: DockerExecutorConfig,
        *,
        docker_cmd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if docker_cmd is None:
            docker_cmd = self.resolve_docker_cli(config)
        try:
            return subprocess.run(
                [
                    str(docker_cmd),
                    "image",
                    "inspect",
                    config.image,
                    "--format",
                    "{{.Id}}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise DockerCliUnavailableError(
                f"Docker CLI could not be launched: {exc}"
            ) from exc

    def inspect_image_python_version(
        self,
        config: DockerExecutorConfig,
        *,
        docker_cmd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if docker_cmd is None:
            docker_cmd = self.resolve_docker_cli(config)
        container_name = self.make_container_name("python-version-probe")
        probe_timeout_seconds = max(
            config.timeout_seconds,
            MIN_PYTHON_VERSION_PROBE_TIMEOUT_SECONDS,
        )
        command = [
            str(docker_cmd),
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--memory",
            config.memory_limit,
            "--memory-swap",
            config.memory_limit,
            "--cpus",
            str(config.cpu_limit),
            "--pids-limit",
            str(config.pids_limit),
            "--read-only",
            "--tmpfs",
            (
                f"/tmp:rw,nosuid,nodev,noexec,"
                f"size={config.temp_tmpfs_size},mode=1777"
            ),
            "--user",
            config.user,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--label",
            "qa-platform.managed=true",
            "--entrypoint",
            "python",
            config.image,
            "-I",
            "-B",
            "-c",
            PYTHON_VERSION_PROBE,
        ]
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=probe_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            cleanup_result = self._remove_probe_container(
                container_name,
                docker_cmd=docker_cmd,
            )
            stderr = (
                "Docker image Python version check timed out after "
                f"{probe_timeout_seconds} seconds."
            )
            if cleanup_result.returncode != 0:
                cleanup_error = cleanup_result.stderr.strip()
                if not cleanup_error:
                    cleanup_error = (
                        "exit code "
                        f"{cleanup_result.returncode}"
                    )
                stderr = (
                    f"{stderr}\nDocker probe cleanup failed: "
                    f"{cleanup_error}"
                )
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                stderr,
            )
        except OSError as exc:
            raise DockerCliUnavailableError(
                f"Docker CLI could not be launched: {exc}"
            ) from exc

    def _remove_probe_container(
        self,
        container_name: str,
        *,
        docker_cmd: Path,
    ) -> subprocess.CompletedProcess[str]:
        command = [str(docker_cmd), "rm", "--force", container_name]
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                f"Docker probe cleanup could not be launched: {exc}",
            )

    def build_image(
        self,
        config: DockerExecutorConfig,
        *,
        docker_cmd: Path | None = None,
    ) -> None:
        build_context = self.prepare_image_build_context(config)
        try:
            if docker_cmd is None:
                docker_cmd = self.resolve_docker_cli(config)
            build_result = subprocess.run(
                self.build_image_command(
                    config,
                    build_context=build_context,
                    docker_cmd=docker_cmd,
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=config.image_build_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerImageBuildError(
                "Docker image build timed out after "
                f"{config.image_build_timeout_seconds} seconds."
            ) from exc
        except OSError as exc:
            raise DockerImageBuildError(
                f"Docker image build could not be launched: {exc}"
            ) from exc
        finally:
            shutil.rmtree(build_context, ignore_errors=True)

        if build_result.returncode != 0:
            raise DockerImageBuildError(
                _command_error_message(
                    f"Docker image build failed: {config.image}",
                    build_result.stderr,
                )
            )

    def check_cli_and_daemon(self, config: DockerExecutorConfig) -> Path:
        docker_cmd = self.resolve_docker_cli(config)

        try:
            daemon_result = subprocess.run(
                [
                    str(docker_cmd),
                    "version",
                    "--format",
                    "{{.Server.Version}}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise DockerCliUnavailableError(
                f"Docker CLI could not be launched: {exc}"
            ) from exc
        if daemon_result.returncode != 0:
            raise DockerDaemonUnavailableError(
                _command_error_message(
                    "Docker daemon is unavailable. QA Platform uses "
                    "Docker-only execution",
                    daemon_result.stderr,
                )
            )

        return docker_cmd

    def ensure_ready(self, config: DockerExecutorConfig) -> None:
        docker_cmd = self.check_cli_and_daemon(config)

        image_result = self.inspect_image(config, docker_cmd=docker_cmd)
        if image_result.returncode == 0 and self._image_python_matches(
            config,
            docker_cmd=docker_cmd,
        ):
            return

        self.build_image(config, docker_cmd=docker_cmd)
        image_result = self.inspect_image(config, docker_cmd=docker_cmd)
        if image_result.returncode != 0:
            raise DockerImageBuildError(
                _command_error_message(
                    "Docker image is still unavailable after build: "
                    f"{config.image}",
                    image_result.stderr,
                )
            )
        version_result = self.inspect_image_python_version(
            config,
            docker_cmd=docker_cmd,
        )
        if version_result.returncode != 0:
            raise DockerImageBuildError(
                _command_error_message(
                    "Docker image Python version check failed after build: "
                    f"{config.image}",
                    version_result.stderr,
                )
            )
        actual_version = version_result.stdout.strip()
        if not actual_version or not python_version_matches(
            config.python_version,
            actual_version,
        ):
            raise DockerImageBuildError(
                "Python version mismatch after Docker image build: "
                f"requested {config.python_version}, actual "
                f"{actual_version or 'unavailable'} for image "
                f"{config.image}."
            )

    def _image_python_matches(
        self,
        config: DockerExecutorConfig,
        *,
        docker_cmd: Path | None = None,
    ) -> bool:
        actual_version = self._image_python_version(
            config,
            docker_cmd=docker_cmd,
        )
        if not actual_version:
            return False
        return python_version_matches(config.python_version, actual_version)

    def _image_python_version(
        self,
        config: DockerExecutorConfig,
        *,
        docker_cmd: Path | None = None,
    ) -> str:
        version_result = self.inspect_image_python_version(
            config,
            docker_cmd=docker_cmd,
        )
        if version_result.returncode != 0:
            return ""
        return version_result.stdout.strip()

    def make_container_name(self, block_id: str) -> str:
        normalized = re.sub(r"[^a-z0-9_-]+", "-", block_id.lower())
        normalized = normalized.strip("-_") or "block"
        return f"qa-platform-{normalized}-{uuid.uuid4().hex[:12]}"

    def build_create_command(
        self,
        *,
        block_dir: Path,
        container_name: str,
        config: DockerExecutorConfig,
        script_name: str = "normalized.py",
        docker_cmd: Path | None = None,
    ) -> list[str]:
        input_script_path = _input_script_path(script_name)
        mount = (
            f"type=bind,source={block_dir.resolve()},"
            "target=/input,readonly"
        )
        user_id, group_id = config.user.split(":", maxsplit=1)
        if docker_cmd is None:
            docker_cmd = self.resolve_docker_cli(config)
        return [
            str(docker_cmd),
            "create",
            "--name",
            container_name,
            "--interactive",
            "--network",
            "none",
            "--memory",
            config.memory_limit,
            "--memory-swap",
            config.memory_limit,
            "--cpus",
            str(config.cpu_limit),
            "--pids-limit",
            str(config.pids_limit),
            "--read-only",
            "--tmpfs",
            (
                f"/work:rw,nosuid,nodev,size={config.work_tmpfs_size},"
                f"uid={user_id},gid={group_id},mode=0700"
            ),
            "--tmpfs",
            (
                f"/tmp:rw,nosuid,nodev,noexec,"
                f"size={config.temp_tmpfs_size},mode=1777"
            ),
            "--user",
            config.user,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--init",
            "--label",
            "qa-platform.managed=true",
            "--mount",
            mount,
            "--workdir",
            "/work",
            config.image,
            "python",
            "-I",
            "-B",
            "-u",
            input_script_path,
        ]

    def run(
        self,
        *,
        block_dir: Path,
        block_id: str,
        stdin: str,
        config: DockerExecutorConfig,
        script_name: str = "normalized.py",
    ) -> ProcessOutcome:
        container_name = self.make_container_name(block_id)
        created = False
        started_at = time.perf_counter()
        docker_cmd = self.resolve_docker_cli(config)

        try:
            try:
                create_result = subprocess.run(
                    self.build_create_command(
                        block_dir=block_dir,
                        container_name=container_name,
                        config=config,
                        script_name=script_name,
                        docker_cmd=docker_cmd,
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError as exc:
                raise DockerLifecycleError(
                    f"Docker create failed: {exc}"
                ) from exc
            if create_result.returncode != 0:
                raise DockerLifecycleError(
                    _command_error_message(
                        "Docker create failed",
                        create_result.stderr,
                    )
                )
            created = True

            try:
                process = subprocess.Popen(
                    [
                        str(docker_cmd),
                        "start",
                        "--attach",
                        "--interactive",
                        container_name,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as exc:
                raise DockerLifecycleError(
                    f"Docker start failed: {exc}"
                ) from exc

            if (
                process.stdin is None
                or process.stdout is None
                or process.stderr is None
            ):
                raise DockerLifecycleError(
                    "Docker start failed: attached pipes are unavailable."
                )

            stdout_buffer = _BoundedTextBuffer(
                config.output_limit_chars
            )
            stderr_buffer = _BoundedTextBuffer(
                config.output_limit_chars
            )
            stdout_thread = threading.Thread(
                target=_drain_stream,
                args=(process.stdout, stdout_buffer),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_drain_stream,
                args=(process.stderr, stderr_buffer),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()

            try:
                process.stdin.write(stdin)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                process.stdin.close()

            timed_out = False
            try:
                process.wait(timeout=config.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._run_lifecycle_command(
                    [str(docker_cmd), "kill", container_name],
                    stage="kill",
                )
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=1)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        raise DockerLifecycleError(
                            "Docker start attachment did not exit "
                            "after container kill."
                        ) from exc

            stdout_thread.join()
            stderr_thread.join()
            duration_ms = int(
                (time.perf_counter() - started_at) * 1000
            )

            if timed_out:
                return ProcessOutcome(
                    exit_code=None,
                    duration_ms=duration_ms,
                    stdout=stdout_buffer.value,
                    stderr=stderr_buffer.value,
                    stdout_truncated=stdout_buffer.truncated,
                    stderr_truncated=stderr_buffer.truncated,
                    timed_out=True,
                )

            inspect_result = self._run_lifecycle_command(
                [
                    str(docker_cmd),
                    "inspect",
                    container_name,
                    "--format",
                    "{{.State.ExitCode}}",
                ],
                stage="inspect",
            )
            try:
                exit_code = int(inspect_result.stdout.strip())
            except ValueError as exc:
                raise DockerLifecycleError(
                    "Docker inspect failed: invalid container exit code."
                ) from exc

            return ProcessOutcome(
                exit_code=exit_code,
                duration_ms=duration_ms,
                stdout=stdout_buffer.value,
                stderr=stderr_buffer.value,
                stdout_truncated=stdout_buffer.truncated,
                stderr_truncated=stderr_buffer.truncated,
                timed_out=False,
            )
        finally:
            if created:
                try:
                    cleanup_result = subprocess.run(
                        [str(docker_cmd), "rm", "--force", container_name],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except OSError as exc:
                    raise DockerCleanupError(
                        f"Docker remove failed: {exc}"
                    ) from exc
                if cleanup_result.returncode != 0:
                    raise DockerCleanupError(
                        _command_error_message(
                            "Docker remove failed",
                            cleanup_result.stderr,
                        )
                    )

    def _run_lifecycle_command(
        self,
        command: list[str],
        *,
        stage: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise DockerLifecycleError(
                f"Docker {stage} failed: {exc}"
            ) from exc
        if result.returncode != 0:
            raise DockerLifecycleError(
                _command_error_message(
                    f"Docker {stage} failed",
                    result.stderr,
                )
            )
        return result


def _command_error_message(prefix: str, stderr: str) -> str:
    detail = stderr.strip()[:500]
    return f"{prefix}: {detail}" if detail else prefix


def _safe_build_context_name(image: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", image)
    normalized = normalized.strip("-_.")
    return normalized or "qa-platform-python"


def _input_script_path(script_name: str) -> str:
    path = PurePosixPath(script_name)
    if (
        not script_name
        or "\0" in script_name
        or path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
        or len(path.parts) != 1
        or path.name != script_name
    ):
        raise ValueError(
            "script_name must be a single file name inside /input."
        )
    return f"/input/{script_name}"


def _drain_stream(
    stream: TextIO,
    buffer: _BoundedTextBuffer,
) -> None:
    while True:
        chunk = stream.read(4096)
        if not chunk:
            return
        buffer.append(chunk)
