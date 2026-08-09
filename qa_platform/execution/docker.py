from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from qa_platform.contract.constants import (
    CATEGORY_EXECUTOR_INPUT_ERROR,
    CATEGORY_UNSUPPORTED_PACKAGE,
)
from qa_platform.contract.models import (
    ExecutionResult,
    ParseResult,
)
from qa_platform.contract.package_resolver import (
    PackageResolution,
    resolve_block_packages,
)
from qa_platform.execution.docker_runtime import (
    DEFAULT_IMAGE_REPOSITORY,
    DockerCliRuntime,
    DockerExecutorConfig,
    DockerRuntime,
    DockerRuntimeError,
)
from qa_platform.execution.repl_artifact import prepare_execution_artifact
from qa_platform.execution.support import (
    build_code_type_skip_result,
    build_environment_module_skip_result,
    build_executable_source,
    build_execution_result,
    build_executor_failure_result,
    build_missing_required_file_skip_result,
    load_execution_context,
    write_execution_result,
)


class DockerBlockExecutor:
    def __init__(
        self,
        config: DockerExecutorConfig | None = None,
        runtime: DockerRuntime | None = None,
    ) -> None:
        self.config = config or DockerExecutorConfig()
        self.runtime = runtime or DockerCliRuntime()

    def prepare_chapter(self, parse_results: list[ParseResult]) -> None:
        requirements: set[str] = set()
        for parse_result in parse_results:
            if not parse_result.parse_success or parse_result.spec is None:
                continue
            resolution = _package_resolution(parse_result)
            requirements.update(resolution.requirements)

        if not requirements:
            return

        self.config = _with_supported_requirements(
            self.config,
            requirements,
        )

    def execute(self, block_dir: Path) -> ExecutionResult:
        context, early_result = load_execution_context(block_dir)
        if early_result is not None:
            return write_execution_result(block_dir, early_result)
        if context is None:
            raise RuntimeError("Executor context is missing.")

        spec = context.parse_result.spec
        if spec is None:
            raise RuntimeError("Executor spec is missing.")

        skipped_result = build_code_type_skip_result(context.parse_result)
        if skipped_result is not None:
            return write_execution_result(block_dir, skipped_result)

        missing_file_skip_result = build_missing_required_file_skip_result(
            context.parse_result
        )
        if missing_file_skip_result is not None:
            return write_execution_result(block_dir, missing_file_skip_result)

        preclassified_environment_skip_result = (
            build_environment_module_skip_result(context.parse_result, ())
        )
        if preclassified_environment_skip_result is not None:
            return write_execution_result(
                block_dir,
                preclassified_environment_skip_result,
            )

        package_resolution = _package_resolution(context.parse_result)
        environment_skip_result = build_environment_module_skip_result(
            context.parse_result,
            package_resolution.environment_modules,
        )
        if environment_skip_result is not None:
            return write_execution_result(block_dir, environment_skip_result)

        unsupported_requirements = (
            package_resolution.unsupported_requirements
        )
        if unsupported_requirements:
            package_list = ", ".join(unsupported_requirements)
            result = build_executor_failure_result(
                context.parse_result,
                category=CATEGORY_UNSUPPORTED_PACKAGE,
                error_type="UnsupportedPackageError",
                error_message=(
                    "Unsupported external package requirements: "
                    f"{package_list}"
                ),
            )
            return write_execution_result(block_dir, result)

        self.config = _with_supported_requirements(
            self.config,
            package_resolution.requirements,
        )

        try:
            self.runtime.ensure_ready(self.config)
            executable_source = build_executable_source(
                spec.setup_code,
                spec.code,
            )
            artifact = prepare_execution_artifact(
                block_dir,
                code=executable_source,
                meta=spec.meta,
            )
            outcome = self.runtime.run(
                block_dir=block_dir,
                block_id=context.parse_result.block_id,
                stdin=context.stdin,
                config=self.config,
                script_name=artifact.script_name,
            )
        except DockerRuntimeError as exc:
            result = build_executor_failure_result(
                context.parse_result,
                category=CATEGORY_EXECUTOR_INPUT_ERROR,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            return write_execution_result(block_dir, result)

        result = build_execution_result(
            context.parse_result,
            outcome,
            meta=artifact.meta,
        )
        return write_execution_result(block_dir, result)


def _package_resolution(parse_result: ParseResult) -> PackageResolution:
    spec = parse_result.spec
    if spec is None:
        return PackageResolution(
            requirements=(),
            unsupported_requirements=(),
            environment_modules=(),
            import_roots=(),
        )

    return resolve_block_packages(
        spec.setup_code,
        spec.code,
        spec.packages,
    )


def _with_supported_requirements(
    config: DockerExecutorConfig,
    requirements: tuple[str, ...] | set[str],
) -> DockerExecutorConfig:
    if not requirements:
        return config

    default_image = f"{DEFAULT_IMAGE_REPOSITORY}:{config.python_version}"
    managed_dependency_prefix = (
        f"{config.dependency_image_repository}:"
        f"{config.python_version}-deps-"
    )
    is_default_or_managed_image = (
        config.image == default_image
        or config.image.startswith(managed_dependency_prefix)
    )
    if not is_default_or_managed_image:
        return config

    install_requirements = tuple(
        sorted(
            {*config.install_requirements, *requirements},
            key=str.casefold,
        )
    )
    if install_requirements == config.install_requirements:
        return config

    return replace(
        config,
        image="",
        install_requirements=install_requirements,
    )
