from qa_platform.contract.models import PackageSpec
from qa_platform.contract.package_resolver import (
    dependency_hash,
    image_tag_for_requirements,
    resolve_block_packages,
)


def test_stdlib_imports_are_excluded() -> None:
    resolution = resolve_block_packages(
        setup_code="import os\nimport sys\n",
        code="import random\nfrom math import sqrt\n",
        declared_packages=[],
    )

    assert resolution.requirements == ()
    assert resolution.unsupported_requirements == ()
    assert resolution.environment_modules == ()
    assert resolution.import_roots == ("math", "os", "random", "sys")


def test_import_names_map_to_distribution_names_for_common_aliases() -> None:
    resolution = resolve_block_packages(
        setup_code="from PIL import Image\nimport cv2\n",
        code="import sklearn.model_selection\nimport yaml\n",
        declared_packages=[],
    )

    assert resolution.requirements == (
        "PyYAML",
        "opencv-python",
        "pillow",
        "scikit-learn",
    )
    assert resolution.unsupported_requirements == ()


def test_declared_version_specifier_is_preserved() -> None:
    resolution = resolve_block_packages(
        setup_code="",
        code="",
        declared_packages=[
            PackageSpec(name="numpy", specifier=">=2.0", raw="numpy>=2.0")
        ],
    )

    assert resolution.requirements == ("numpy>=2.0",)


def test_declared_alias_version_specifier_is_normalized() -> None:
    resolution = resolve_block_packages(
        setup_code="",
        code="",
        declared_packages=[
            PackageSpec(name="PIL", specifier=">=10", raw="PIL>=10")
        ],
    )

    assert resolution.requirements == ("pillow>=10",)


def test_declared_package_allowlist_matching_is_case_insensitive() -> None:
    resolution = resolve_block_packages(
        setup_code="",
        code="import yaml\nfrom PIL import Image\n",
        declared_packages=[
            PackageSpec(name="pyyaml", specifier=">=6", raw="pyyaml>=6"),
            PackageSpec(name="Pillow", specifier=">=10", raw="Pillow>=10"),
        ],
    )

    assert resolution.requirements == ("Pillow>=10", "pyyaml>=6")
    assert resolution.unsupported_requirements == ()


def test_turtle_is_environment_dependent_and_not_a_requirement() -> None:
    resolution = resolve_block_packages(
        setup_code="",
        code="import turtle\nimport tkinter as tk\n",
        declared_packages=[],
    )

    assert resolution.requirements == ()
    assert resolution.environment_modules == ("tkinter", "turtle")
    assert resolution.unsupported_requirements == ()


def test_unsupported_external_package_is_separated() -> None:
    resolution = resolve_block_packages(
        setup_code="",
        code="import numpy as np\nimport seaborn as sns\n",
        declared_packages=[],
    )

    assert resolution.requirements == ("numpy",)
    assert resolution.unsupported_requirements == ("seaborn",)


def test_empty_allowed_distributions_marks_external_import_unsupported() -> None:
    resolution = resolve_block_packages(
        setup_code="",
        code="import numpy as np\n",
        declared_packages=[],
        allowed_distributions=set(),
    )

    assert resolution.requirements == ()
    assert resolution.unsupported_requirements == ("numpy",)


def test_dependency_hash_is_stable_for_requirement_ordering() -> None:
    left_hash = dependency_hash(["pandas>=2", "numpy", "pandas>=2"])
    right_hash = dependency_hash(["numpy", "pandas>=2"])

    assert left_hash == right_hash
    assert len(left_hash) == 8


def test_image_tag_includes_python_version_and_dependency_hash() -> None:
    requirements = ["numpy", "pandas"]
    deps_hash = dependency_hash(requirements)

    assert image_tag_for_requirements(
        repository="qa-platform-python",
        python_version="3.12",
        requirements=[],
    ) == "qa-platform-python:3.12"
    assert image_tag_for_requirements(
        repository="qa-platform-python",
        python_version="3.12",
        requirements=requirements,
    ) == f"qa-platform-python:3.12-deps-{deps_hash}"
