from pathlib import Path

from tools.macos import build_pkg as build_pkg_module
from tools.macos.build_pkg import (
    PRODUCT_IDENTIFIER,
    pkgbuild_command,
    productbuild_command,
    run_command,
)


def test_pkgbuild_command_installs_payload_at_root(tmp_path) -> None:
    command = pkgbuild_command(
        payload_root=tmp_path / "payload",
        identifier=PRODUCT_IDENTIFIER,
        version="0.1.0",
        component_pkg=tmp_path / "intermediate" / "qa-platform-component.pkg",
    )

    assert command == [
        "pkgbuild",
        "--root",
        str(tmp_path / "payload"),
        "--identifier",
        "com.qa-platform.cli",
        "--version",
        "0.1.0",
        "--install-location",
        "/",
        str(tmp_path / "intermediate" / "qa-platform-component.pkg"),
    ]


def test_productbuild_command_can_build_unsigned_pkg(tmp_path) -> None:
    command = productbuild_command(
        component_pkg=tmp_path / "intermediate" / "qa-platform-component.pkg",
        output_pkg=tmp_path / "dist" / "qa-platform-macos-arm64.pkg",
        sign_identity="",
    )

    assert command == [
        "productbuild",
        "--package",
        str(tmp_path / "intermediate" / "qa-platform-component.pkg"),
        str(tmp_path / "dist" / "qa-platform-macos-arm64.pkg"),
    ]


def test_productbuild_command_can_build_signed_pkg(tmp_path) -> None:
    command = productbuild_command(
        component_pkg=tmp_path / "intermediate" / "qa-platform-component.pkg",
        output_pkg=tmp_path / "dist" / "qa-platform-macos-arm64.pkg",
        sign_identity="Developer ID Installer: Example",
    )

    assert command == [
        "productbuild",
        "--sign",
        "Developer ID Installer: Example",
        "--package",
        str(tmp_path / "intermediate" / "qa-platform-component.pkg"),
        str(tmp_path / "dist" / "qa-platform-macos-arm64.pkg"),
    ]


def test_run_command_uses_injected_runner() -> None:
    calls: list[list[str]] = []

    run_command(["pkgbuild", "--version"], runner=calls.append)

    assert calls == [["pkgbuild", "--version"]]


def test_main_resolves_default_paths_under_project_root(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    captured = {}
    project_root = tmp_path / "project"
    project_root.mkdir()
    expected_output = project_root / "dist" / "qa-platform-macos-arm64.pkg"

    def fake_build_pkg(**kwargs):
        captured.update(kwargs)
        return expected_output

    monkeypatch.setattr(build_pkg_module, "build_pkg", fake_build_pkg)

    exit_code = build_pkg_module.main(
        ["--project-root", str(project_root), "--version", "0.1.0"]
    )

    assert exit_code == 0
    assert captured["project_root"] == project_root.resolve()
    assert captured["executable_dist_root"] == (
        project_root / "build" / "macos" / "executable"
    )
    assert captured["executable_work_root"] == (
        project_root / "build" / "macos" / "pyinstaller-work"
    )
    assert captured["executable_spec_root"] == (
        project_root / "build" / "macos" / "pyinstaller-spec"
    )
    assert captured["payload_root"] == (
        project_root / "build" / "macos" / "pkg-root"
    )
    assert captured["intermediate_root"] == (
        project_root / "build" / "macos" / "intermediate"
    )
    assert captured["output_pkg"] == expected_output
    assert captured["version"] == "0.1.0"
    assert captured["sign_identity"] == ""
    assert capsys.readouterr().out == f"{expected_output}\n"


def test_build_pkg_passes_all_executable_roots_to_build_executable(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[tuple[str, dict[str, object] | list[str]]] = []
    executable_dist_root = tmp_path / "executable"
    executable_app_dir = executable_dist_root / "qa-platform"
    executable_app_dir.mkdir(parents=True)
    (executable_app_dir / "qa-platform").write_text(
        "#!/bin/sh\n",
        encoding="utf-8",
    )

    def fake_build_executable(**kwargs) -> None:
        calls.append(("build_executable", kwargs))

    def fake_stage_payload(**kwargs) -> None:
        calls.append(("stage_payload", kwargs))

    def fake_run_command(command, *, runner=None) -> None:
        calls.append(("run_command", list(command)))
        if runner is not None:
            runner(command)

    monkeypatch.setattr(build_pkg_module, "build_executable", fake_build_executable)
    monkeypatch.setattr(build_pkg_module, "stage_payload", fake_stage_payload)
    monkeypatch.setattr(build_pkg_module, "run_command", fake_run_command)

    output_pkg = build_pkg_module.build_pkg(
        project_root=tmp_path,
        version="0.1.0",
        executable_dist_root=executable_dist_root,
        executable_work_root=tmp_path / "work",
        executable_spec_root=tmp_path / "spec",
        payload_root=tmp_path / "payload",
        intermediate_root=tmp_path / "intermediate",
        output_pkg=tmp_path / "dist" / "qa-platform-macos-arm64.pkg",
        runner=lambda command: None,
    )

    assert output_pkg == tmp_path / "dist" / "qa-platform-macos-arm64.pkg"
    assert calls[0] == (
        "build_executable",
        {
            "project_root": tmp_path,
            "dist_root": executable_dist_root,
            "work_root": tmp_path / "work",
            "spec_root": tmp_path / "spec",
        },
    )
    assert calls[1] == (
        "stage_payload",
        {
            "executable_dir": executable_dist_root / "qa-platform",
            "payload_root": tmp_path / "payload",
        },
    )
    assert calls[2][0] == "run_command"
    assert calls[3][0] == "run_command"
