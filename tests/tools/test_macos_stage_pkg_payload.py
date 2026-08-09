import os
from pathlib import Path

import pytest

from tools.macos.pkg_layout import (
    APP_INSTALL_DIR,
    CLI_WRAPPER_PATH,
    RESOURCE_INSTALL_DIR,
    payload_path,
    wrapper_script,
)
from tools.macos.stage_pkg_payload import stage_payload


def _make_executable_tree(root: Path) -> Path:
    executable_dir = root / "qa-platform"
    executable_dir.mkdir(parents=True)
    executable = executable_dir / "qa-platform"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    (executable_dir / "_internal").mkdir()
    (executable_dir / "_internal" / "lib.txt").write_text(
        "lib",
        encoding="utf-8",
    )
    return executable_dir


def test_stage_payload_installs_app_and_wrapper_without_resources(tmp_path) -> None:
    executable_dir = _make_executable_tree(tmp_path / "executable")
    payload_root = tmp_path / "payload"

    stage_payload(
        executable_dir=executable_dir,
        payload_root=payload_root,
    )

    installed_executable = payload_path(payload_root, APP_INSTALL_DIR) / "qa-platform"
    wrapper = payload_path(payload_root, CLI_WRAPPER_PATH)

    assert installed_executable.is_file()
    assert not payload_path(payload_root, RESOURCE_INSTALL_DIR).exists()
    assert wrapper.read_text(encoding="utf-8") == wrapper_script()
    assert os.access(wrapper, os.X_OK)


def test_stage_payload_recreates_existing_payload_root(tmp_path) -> None:
    executable_dir = _make_executable_tree(tmp_path / "executable")
    payload_root = tmp_path / "payload"
    stale = payload_root / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    stage_payload(
        executable_dir=executable_dir,
        payload_root=payload_root,
    )

    assert not stale.exists()
    assert (payload_path(payload_root, APP_INSTALL_DIR) / "qa-platform").is_file()


def test_stage_payload_requires_pyinstaller_executable(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="qa-platform"):
        stage_payload(
            executable_dir=tmp_path / "missing",
            payload_root=tmp_path / "payload",
        )


def test_stage_payload_does_not_create_resource_payload(tmp_path) -> None:
    executable_dir = _make_executable_tree(tmp_path / "executable")
    payload_root = tmp_path / "payload"

    stage_payload(
        executable_dir=executable_dir,
        payload_root=payload_root,
    )

    assert (payload_path(payload_root, APP_INSTALL_DIR) / "qa-platform").is_file()
    assert not payload_path(payload_root, RESOURCE_INSTALL_DIR).exists()
    assert payload_path(payload_root, CLI_WRAPPER_PATH).is_file()
