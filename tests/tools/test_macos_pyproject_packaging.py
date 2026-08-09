import tomllib
from pathlib import Path


def test_pyproject_limits_setuptools_package_discovery() -> None:
    pyproject = tomllib.loads(
        Path("pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["tool"]["setuptools"]["packages"]["find"] == {
        "include": ["qa_platform*", "tools*"],
    }
