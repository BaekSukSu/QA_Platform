from pathlib import Path
import importlib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DOMAIN_MODULES = [
    "qa_platform.extraction.pipeline",
    "qa_platform.extraction.config",
    "qa_platform.extraction.models",
    "qa_platform.contract.constants",
    "qa_platform.contract.models",
    "qa_platform.contract.parser",
    "qa_platform.execution.base",
    "qa_platform.execution.docker",
    "qa_platform.execution.docker_runtime",
    "qa_platform.execution.support",
    "qa_platform.execution.output_comparator",
    "qa_platform.execution.result_classifier",
    "qa_platform.chapter.models",
    "qa_platform.chapter.runner",
    "qa_platform.reporting.report_builder",
    "qa_platform.pipeline.config",
    "qa_platform.pipeline.orchestrator",
    "qa_platform.pipeline.cli",
    "qa_platform.shared.json_io",
    "qa_platform.shared.paths",
    "qa_platform.shared.session",
]

REMOVED_TOP_LEVEL_MODULES = [
    "qa_platform.block_executor",
    "qa_platform.block_parser",
    "qa_platform.chapter_models",
    "qa_platform.chapter_runner",
    "qa_platform.constants",
    "qa_platform.docker_executor",
    "qa_platform.docker_runtime",
    "qa_platform.executor_support",
    "qa_platform.models",
    "qa_platform.output_comparator",
    "qa_platform.pipeline_cli",
    "qa_platform.pipeline_config",
    "qa_platform.pipeline_orchestrator",
    "qa_platform.report_builder",
    "qa_platform.result_classifier",
    "qa_platform.session",
]


def test_domain_package_modules_are_importable() -> None:
    for module_name in DOMAIN_MODULES:
        assert importlib.import_module(module_name)


def test_top_level_package_contains_only_package_initializer() -> None:
    package_dir = PROJECT_ROOT / "qa_platform"
    top_level_python_files = sorted(
        path.name
        for path in package_dir.glob("*.py")
        if path.name != "__init__.py"
    )

    assert top_level_python_files == []


@pytest.mark.parametrize("module_name", REMOVED_TOP_LEVEL_MODULES)
def test_legacy_top_level_import_paths_are_removed(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError) as exc_info:
        importlib.import_module(module_name)

    assert exc_info.value.name == module_name


def test_removed_extractor_import_paths_are_removed() -> None:
    removed_package = "qa_platform." + "extractors"
    removed_modules = [
        removed_package,
        removed_package + ".cli",
        removed_package + ".block_importer",
        removed_package + ".pipeline",
    ]

    for module_name in removed_modules:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            assert exc.name in {module_name, removed_package}
            continue
        raise AssertionError(
            f"{module_name} should be removed after extractors shim removal"
        )


def test_removed_executor_import_paths_are_removed() -> None:
    removed_modules = [
        "qa_platform.execution." + "local",
        "qa_platform." + "local_executor",
    ]

    for module_name in removed_modules:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            assert exc.name == module_name
            continue
        raise AssertionError(f"{module_name} should be removed in Phase 2")
