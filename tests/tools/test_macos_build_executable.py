from pathlib import Path

from tools.macos import build_executable as build_executable_module
from tools.macos.build_executable import build_executable, pyinstaller_args


def test_pyinstaller_args_use_onedir_console_entry(tmp_path) -> None:
    project_root = tmp_path / "project"
    dist_root = tmp_path / "dist"
    work_root = tmp_path / "work"
    spec_root = tmp_path / "spec"

    args = pyinstaller_args(
        project_root=project_root,
        dist_root=dist_root,
        work_root=work_root,
        spec_root=spec_root,
    )

    assert "--onedir" in args
    assert "--console" in args
    assert ["--name", "qa-platform"] == args[
        args.index("--name") : args.index("--name") + 2
    ]
    assert ["--distpath", str(dist_root)] == args[
        args.index("--distpath") : args.index("--distpath") + 2
    ]
    assert ["--workpath", str(work_root)] == args[
        args.index("--workpath") : args.index("--workpath") + 2
    ]
    assert ["--specpath", str(spec_root)] == args[
        args.index("--specpath") : args.index("--specpath") + 2
    ]
    assert args[-1] == str(
        project_root / "distribution" / "macos" / "qa_platform_cli_entry.py"
    )


def test_build_executable_invokes_runner_with_generated_args(tmp_path) -> None:
    calls: list[list[str]] = []

    build_executable(
        project_root=tmp_path,
        dist_root=tmp_path / "dist",
        work_root=tmp_path / "work",
        spec_root=tmp_path / "spec",
        runner=calls.append,
    )

    assert len(calls) == 1
    assert calls[0][-1] == str(
        tmp_path / "distribution" / "macos" / "qa_platform_cli_entry.py"
    )


def test_main_resolves_default_build_paths_under_project_root(
    monkeypatch,
    tmp_path,
) -> None:
    captured = {}
    project_root = tmp_path / "project"
    project_root.mkdir()

    def fake_build_executable(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        build_executable_module,
        "build_executable",
        fake_build_executable,
    )

    exit_code = build_executable_module.main(
        ["--project-root", str(project_root)]
    )

    assert exit_code == 0
    assert captured["project_root"] == project_root.resolve()
    assert captured["dist_root"] == (
        project_root / "build" / "macos" / "executable"
    )
    assert captured["work_root"] == (
        project_root / "build" / "macos" / "pyinstaller-work"
    )
    assert captured["spec_root"] == (
        project_root / "build" / "macos" / "pyinstaller-spec"
    )
