from pathlib import PurePosixPath

import pytest

from tools.macos.pkg_layout import (
    APP_INSTALL_DIR,
    APP_SUPPORT_ROOT,
    CLI_WRAPPER_PATH,
    RESOURCE_INSTALL_DIR,
    payload_path,
    wrapper_script,
)


def test_install_paths_are_pkg_system_paths() -> None:
    assert APP_SUPPORT_ROOT == PurePosixPath(
        "/Library/Application Support/QA Platform"
    )
    assert APP_INSTALL_DIR == PurePosixPath(
        "/Library/Application Support/QA Platform/app/qa-platform"
    )
    assert RESOURCE_INSTALL_DIR == PurePosixPath(
        "/Library/Application Support/QA Platform/resources"
    )
    assert CLI_WRAPPER_PATH == PurePosixPath("/usr/local/bin/qa-platform")


def test_payload_path_maps_absolute_install_path_under_payload_root(tmp_path) -> None:
    assert payload_path(tmp_path, APP_INSTALL_DIR) == (
        tmp_path / "Library" / "Application Support" / "QA Platform" / "app" / "qa-platform"
    )
    assert payload_path(tmp_path, CLI_WRAPPER_PATH) == (
        tmp_path / "usr" / "local" / "bin" / "qa-platform"
    )


def test_payload_path_rejects_relative_install_path(tmp_path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        payload_path(tmp_path, PurePosixPath("usr/local/bin/qa-platform"))


def test_wrapper_script_execs_installed_pyinstaller_binary() -> None:
    assert wrapper_script() == (
        "#!/bin/sh\n"
        'exec "/Library/Application Support/QA Platform/app/qa-platform/qa-platform" "$@"\n'
    )
