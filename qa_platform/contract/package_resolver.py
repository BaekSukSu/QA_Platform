from __future__ import annotations

import ast
import hashlib
import re
import sys
from dataclasses import dataclass
from typing import Iterable

from qa_platform.contract.models import PackageSpec


DEFAULT_ALLOWED_DISTRIBUTIONS = {
    "numpy",
    "pandas",
    "matplotlib",
    "pillow",
    "opencv-python",
    "scikit-learn",
    "PyYAML",
    "requests",
}
ENVIRONMENT_MODULES = {"tkinter", "turtle"}
IMPORT_DISTRIBUTION_ALIASES = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
}


@dataclass(frozen=True)
class PackageResolution:
    requirements: tuple[str, ...]
    unsupported_requirements: tuple[str, ...]
    environment_modules: tuple[str, ...]
    import_roots: tuple[str, ...]


def resolve_block_packages(
    setup_code: str,
    code: str,
    declared_packages: Iterable[PackageSpec],
    allowed_distributions: set[str] | None = None,
) -> PackageResolution:
    allowed = (
        DEFAULT_ALLOWED_DISTRIBUTIONS
        if allowed_distributions is None
        else allowed_distributions
    )
    allowed_lookup = {
        canonical_distribution_name(distribution)
        for distribution in allowed
    }
    import_roots = extract_import_roots(f"{setup_code}\n{code}")
    requirements_by_distribution: dict[str, str] = {}
    unsupported_requirements: set[str] = set()
    environment_modules: set[str] = set()

    for import_root in import_roots:
        distribution_name = distribution_name_for_import(import_root)
        if import_root in ENVIRONMENT_MODULES:
            environment_modules.add(import_root)
        elif is_stdlib_module(import_root):
            continue
        elif _distribution_allowed(distribution_name, allowed_lookup):
            requirements_by_distribution[
                canonical_distribution_name(distribution_name)
            ] = distribution_name
        else:
            unsupported_requirements.add(distribution_name)

    for package in declared_packages:
        distribution_name = distribution_name_for_import(package.name)
        requirement = f"{distribution_name}{package.specifier}"
        if package.name in ENVIRONMENT_MODULES:
            environment_modules.add(package.name)
        elif is_stdlib_module(package.name):
            continue
        elif _distribution_allowed(distribution_name, allowed_lookup):
            requirements_by_distribution[
                canonical_distribution_name(distribution_name)
            ] = requirement
        else:
            unsupported_requirements.add(requirement)

    return PackageResolution(
        requirements=tuple(sorted(set(requirements_by_distribution.values()))),
        unsupported_requirements=tuple(sorted(unsupported_requirements)),
        environment_modules=tuple(sorted(environment_modules)),
        import_roots=tuple(sorted(import_roots)),
    )


def extract_import_roots(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    import_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_roots.add(alias.name.split(".", maxsplit=1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_roots.add(node.module.split(".", maxsplit=1)[0])
    return import_roots


def is_stdlib_module(module_name: str) -> bool:
    import_root = module_name.split(".", maxsplit=1)[0]
    return (
        import_root in sys.builtin_module_names
        or import_root in sys.stdlib_module_names
    )


def distribution_name_for_import(import_root: str) -> str:
    return IMPORT_DISTRIBUTION_ALIASES.get(import_root, import_root)


def canonical_distribution_name(distribution_name: str) -> str:
    return re.sub(r"[-_.]+", "-", distribution_name).lower()


def _distribution_allowed(
    distribution_name: str,
    allowed_lookup: set[str],
) -> bool:
    return canonical_distribution_name(distribution_name) in allowed_lookup


def dependency_hash(requirements: Iterable[str]) -> str:
    normalized_requirements = sorted(set(requirements))
    payload = "\n".join(normalized_requirements).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:8]


def image_tag_for_requirements(
    *,
    repository: str,
    python_version: str,
    requirements: Iterable[str],
) -> str:
    unique_requirements = sorted(set(requirements))
    if not unique_requirements:
        return f"{repository}:{python_version}"
    return (
        f"{repository}:{python_version}-deps-"
        f"{dependency_hash(unique_requirements)}"
    )
