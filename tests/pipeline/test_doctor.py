import json
import os
from pathlib import Path
from types import SimpleNamespace

from qa_platform.shared.executables import ExecutableNotFoundError

from qa_platform.pipeline.doctor import (
    DoctorCheck,
    DoctorResult,
    format_doctor_result,
)


def test_format_doctor_result_marks_pass_and_fail() -> None:
    result = DoctorResult(
        checks=(
            DoctorCheck(name="workspace", ok=True, message="ready"),
            DoctorCheck(
                name="docker",
                ok=False,
                message="Docker Desktop is not running",
            ),
        )
    )

    output = format_doctor_result(result)

    assert "[OK] workspace: ready" in output
    assert "[FAIL] docker: Docker Desktop is not running" in output
    assert result.ok is False


def test_doctor_result_ok_requires_at_least_one_check() -> None:
    assert DoctorResult(checks=()).ok is False


def _patch_external_checks(monkeypatch, doctor, tmp_path) -> None:
    monkeypatch.setattr(doctor, "resolve_resource_root", lambda resource_root: tmp_path)
    monkeypatch.setattr(
        doctor,
        "resolve_tesseract_runtime",
        lambda configured_path, resource_root=None: SimpleNamespace(
            command=tmp_path / "tesseract"
        ),
    )
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "check_cli_and_daemon",
        lambda self, config: tmp_path / "docker",
        raising=False,
    )
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "ensure_ready",
        lambda self, config: None,
    )


def test_run_doctor_reports_missing_default_config(monkeypatch, tmp_path) -> None:
    from qa_platform.pipeline import doctor

    monkeypatch.setattr(
        doctor,
        "resolve_workspace_root",
        lambda value, config_dir=None: tmp_path / "workspace",
    )
    monkeypatch.setattr(
        doctor,
        "resolve_tesseract_runtime",
        lambda configured_path, resource_root=None: SimpleNamespace(
            command=tmp_path / "tesseract"
        ),
    )
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "ensure_ready",
        lambda self, config: None,
    )

    result = doctor.run_doctor(workspace_root=None, config_path=None)

    assert any(
        check.name == "config" and check.ok is False
        for check in result.checks
    )


def test_run_doctor_honors_workspace_env_var(monkeypatch, tmp_path) -> None:
    from qa_platform.pipeline import doctor

    workspace = tmp_path / "env-workspace"
    config_path = workspace / "config" / "qa_pipeline.local.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{}\n", encoding="utf-8")
    (workspace / ".env").write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    monkeypatch.setenv("QA_PLATFORM_WORKSPACE", str(workspace))
    _patch_external_checks(monkeypatch, doctor, tmp_path)

    result = doctor.run_doctor(workspace_root=None, config_path=None)

    assert any(
        check.name == "workspace"
        and check.ok is True
        and check.message == str(workspace)
        for check in result.checks
    )
    assert any(
        check.name == "config"
        and check.ok is True
        and check.message == str(config_path)
        for check in result.checks
    )


def test_run_doctor_honors_env_file_env_var(monkeypatch, tmp_path) -> None:
    from qa_platform.pipeline import doctor

    workspace = tmp_path / "workspace"
    config_path = workspace / "config" / "qa_pipeline.local.json"
    env_path = tmp_path / "custom.env"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{}\n", encoding="utf-8")
    env_path.write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    monkeypatch.setenv("QA_PLATFORM_ENV_FILE", str(env_path))
    _patch_external_checks(monkeypatch, doctor, tmp_path)

    result = doctor.run_doctor(workspace_root=workspace, config_path=None)

    assert any(
        check.name == "env"
        and check.ok is True
        and check.message == str(env_path)
        for check in result.checks
    )


def test_run_doctor_reports_usr_local_bin_missing_from_path(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    workspace = tmp_path / "workspace"
    config_path = workspace / "config" / "qa_pipeline.local.json"
    config_path.parent.mkdir(parents=True)
    (workspace / ".env").write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    config_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("PATH", "/bin:/usr/bin")
    _patch_external_checks(monkeypatch, doctor, tmp_path)

    result = doctor.run_doctor(workspace_root=workspace)

    assert any(
        check.name == "path"
        and check.ok is False
        and "/usr/local/bin is not on PATH" in check.message
        and "/usr/local/bin/qa-platform doctor" in check.message
        for check in result.checks
    )


def test_run_doctor_treats_missing_resources_as_optional(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    workspace = tmp_path / "workspace"
    config_path = workspace / "config" / "qa_pipeline.local.json"
    workspace.mkdir()
    config_path.parent.mkdir()
    config_path.write_text("{}\n", encoding="utf-8")
    (workspace / ".env").write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    monkeypatch.setenv("PATH", os.pathsep.join(("/usr/local/bin", "/bin", "/usr/bin")))
    monkeypatch.setattr(doctor, "resolve_resource_root", lambda resource_root: None)
    monkeypatch.setattr(
        doctor,
        "resolve_tesseract_runtime",
        lambda configured_path, resource_root=None: SimpleNamespace(
            command=tmp_path / "tesseract"
        ),
    )
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "check_cli_and_daemon",
        lambda self, config: tmp_path / "docker",
        raising=False,
    )

    result = doctor.run_doctor(workspace_root=workspace)
    resource_check = next(
        check for check in result.checks if check.name == "resources"
    )

    assert resource_check.ok is True
    assert "optional" in resource_check.message
    assert result.ok is True


def test_run_doctor_reports_tesseract_install_hint_when_missing(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    workspace = tmp_path / "workspace"
    config_path = workspace / "config" / "qa_pipeline.local.json"
    workspace.mkdir()
    config_path.parent.mkdir()
    config_path.write_text("{}\n", encoding="utf-8")
    (workspace / ".env").write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    monkeypatch.setenv("PATH", os.pathsep.join(("/usr/local/bin", "/bin", "/usr/bin")))
    monkeypatch.setattr(doctor, "resolve_resource_root", lambda resource_root: None)

    def fail_tesseract(configured_path, resource_root=None):
        raise ExecutableNotFoundError(
            "tesseract executable was not found or is not executable"
        )

    monkeypatch.setattr(doctor, "resolve_tesseract_runtime", fail_tesseract)
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "check_cli_and_daemon",
        lambda self, config: tmp_path / "docker",
        raising=False,
    )

    result = doctor.run_doctor(workspace_root=workspace)
    tesseract_check = next(
        check for check in result.checks if check.name == "tesseract"
    )

    assert tesseract_check.ok is False
    assert "brew install tesseract" in tesseract_check.message
    assert "--tesseract-cmd" in tesseract_check.message


def test_run_doctor_honors_config_runtime_and_path_settings(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    workspace = tmp_path / "workspace"
    env_path = workspace / "config" / "doctor.env"
    resource_root = workspace / "resources" / "custom"
    config_path = workspace / "config" / "qa_pipeline.local.json"
    env_path.parent.mkdir(parents=True)
    resource_root.mkdir(parents=True)
    env_path.write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "paths": {
                    "workspace_root": str(workspace),
                    "env_file": "config/doctor.env",
                    "resource_root": "resources/custom",
                    "tesseract_cmd": "configured-tesseract",
                },
                "execution": {
                    "docker": {
                        "docker_cmd": "configured-docker",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    calls = {}

    def fake_resolve_resource_root(resource_root_arg):
        calls["resource_root"] = resource_root_arg
        return Path(resource_root_arg)

    def fake_resolve_tesseract_runtime(configured_path, resource_root=None):
        calls["tesseract_cmd"] = configured_path
        calls["tesseract_resource_root"] = resource_root
        return SimpleNamespace(command=Path("/fake/tesseract"))

    def fake_check_cli_and_daemon(self, config):
        calls["docker_cmd"] = config.docker_cmd
        return Path("/fake/docker")

    monkeypatch.setattr(doctor, "resolve_resource_root", fake_resolve_resource_root)
    monkeypatch.setattr(
        doctor,
        "resolve_tesseract_runtime",
        fake_resolve_tesseract_runtime,
    )
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "check_cli_and_daemon",
        fake_check_cli_and_daemon,
        raising=False,
    )

    result = doctor.run_doctor(config_path=config_path)

    assert any(
        check.name == "env" and check.ok is True and check.message == str(env_path)
        for check in result.checks
    )
    assert calls == {
        "resource_root": resource_root,
        "tesseract_cmd": "configured-tesseract",
        "tesseract_resource_root": resource_root,
        "docker_cmd": "configured-docker",
    }


def test_run_doctor_cli_overrides_beat_config_values(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    config_workspace = tmp_path / "config-workspace"
    cli_workspace = tmp_path / "cli-workspace"
    config_path = config_workspace / "config" / "qa_pipeline.local.json"
    cli_resource_root = tmp_path / "cli-resources"
    cli_workspace.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    cli_resource_root.mkdir()
    (cli_workspace / ".env").write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "paths": {
                    "workspace_root": str(config_workspace),
                    "resource_root": "config-resources",
                    "tesseract_cmd": "config-tesseract",
                },
                "execution": {
                    "docker": {
                        "docker_cmd": "config-docker",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    calls = {}

    monkeypatch.setattr(
        doctor,
        "resolve_resource_root",
        lambda resource_root: calls.setdefault("resource_root", resource_root)
        or cli_resource_root,
    )
    def fake_resolve_tesseract_runtime(configured_path, resource_root=None):
        calls["tesseract_cmd"] = configured_path
        return SimpleNamespace(command=Path("/fake/tesseract"))

    monkeypatch.setattr(
        doctor,
        "resolve_tesseract_runtime",
        fake_resolve_tesseract_runtime,
    )
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "check_cli_and_daemon",
        lambda self, config: calls.setdefault("docker_cmd", config.docker_cmd),
        raising=False,
    )

    result = doctor.run_doctor(
        workspace_root=cli_workspace,
        config_path=config_path,
        resource_root=cli_resource_root,
        tesseract_cmd="cli-tesseract",
        docker_cmd="cli-docker",
    )

    assert any(
        check.name == "workspace"
        and check.ok is True
        and check.message == str(cli_workspace)
        for check in result.checks
    )
    assert calls == {
        "resource_root": cli_resource_root,
        "tesseract_cmd": "cli-tesseract",
        "docker_cmd": "cli-docker",
    }


def test_run_doctor_honors_config_workspace_root_relative_to_config_dir(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    workspace = tmp_path / "workspace"
    config_dir = tmp_path / "config"
    config_path = config_dir / "qa_pipeline.local.json"
    workspace.mkdir()
    config_dir.mkdir()
    (workspace / ".env").write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    config_path.write_text(
        json.dumps({"paths": {"workspace_root": "../workspace"}}),
        encoding="utf-8",
    )
    _patch_external_checks(monkeypatch, doctor, tmp_path)

    result = doctor.run_doctor(config_path=config_path)

    assert any(
        check.name == "workspace"
        and check.ok is True
        and check.message == str(workspace)
        for check in result.checks
    )
    assert any(
        check.name == "env"
        and check.ok is True
        and check.message == str(workspace / ".env")
        for check in result.checks
    )


def test_run_doctor_keeps_default_config_after_config_workspace_override(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    initial_workspace = tmp_path / "initial"
    declared_workspace = tmp_path / "declared"
    config_path = initial_workspace / "config" / "qa_pipeline.local.json"
    env_path = declared_workspace / ".env"
    config_path.parent.mkdir(parents=True)
    declared_workspace.mkdir()
    env_path.write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "paths": {
                    "workspace_root": str(declared_workspace),
                    "tesseract_cmd": "configured-tesseract",
                },
                "execution": {
                    "docker": {
                        "docker_cmd": "configured-docker",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    calls = {}

    def fake_resolve_tesseract_runtime(configured_path, resource_root=None):
        calls["tesseract_cmd"] = configured_path
        return SimpleNamespace(command=Path("/fake/tesseract"))

    monkeypatch.setenv("QA_PLATFORM_WORKSPACE", str(initial_workspace))
    monkeypatch.setattr(doctor, "resolve_resource_root", lambda resource_root: None)
    monkeypatch.setattr(
        doctor,
        "resolve_tesseract_runtime",
        fake_resolve_tesseract_runtime,
    )
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "check_cli_and_daemon",
        lambda self, config: calls.setdefault("docker_cmd", config.docker_cmd),
        raising=False,
    )

    result = doctor.run_doctor(workspace_root=None, config_path=None)

    assert any(
        check.name == "workspace"
        and check.ok is True
        and check.message == str(declared_workspace)
        for check in result.checks
    )
    assert any(
        check.name == "config"
        and check.ok is True
        and check.message == str(config_path)
        for check in result.checks
    )
    assert any(
        check.name == "env"
        and check.ok is True
        and check.message == str(env_path)
        for check in result.checks
    )
    assert calls == {
        "tesseract_cmd": "configured-tesseract",
        "docker_cmd": "configured-docker",
    }


def test_run_doctor_reports_invalid_json_config_without_crashing(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    config_path = tmp_path / "qa_pipeline.local.json"
    config_path.write_text("{invalid json", encoding="utf-8")
    _patch_external_checks(monkeypatch, doctor, tmp_path)

    result = doctor.run_doctor(workspace_root=tmp_path, config_path=config_path)

    assert any(
        check.name == "config"
        and check.ok is False
        and "invalid JSON" in check.message
        for check in result.checks
    )
    assert any(check.name == "docker" for check in result.checks)


def test_run_doctor_uses_non_mutating_docker_check(monkeypatch, tmp_path) -> None:
    from qa_platform.pipeline import doctor

    calls = []
    _patch_external_checks(monkeypatch, doctor, tmp_path)

    def fake_check_cli_and_daemon(self, config):
        calls.append(config)
        return tmp_path / "docker"

    def fail_ensure_ready(self, config):
        raise AssertionError("doctor must not call mutating ensure_ready")

    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "check_cli_and_daemon",
        fake_check_cli_and_daemon,
        raising=False,
    )
    monkeypatch.setattr(doctor.DockerCliRuntime, "ensure_ready", fail_ensure_ready)

    result = doctor.run_doctor(workspace_root=tmp_path, config_path=None)

    assert calls
    assert any(check.name == "docker" and check.ok is True for check in result.checks)


def test_run_doctor_reports_tesseract_and_docker_exceptions(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.pipeline import doctor

    monkeypatch.setattr(doctor, "resolve_resource_root", lambda resource_root: tmp_path)

    def fail_tesseract(configured_path, resource_root=None):
        raise RuntimeError("tesseract missing")

    def fail_docker(self, config):
        raise RuntimeError("docker unavailable")

    monkeypatch.setattr(doctor, "resolve_tesseract_runtime", fail_tesseract)
    monkeypatch.setattr(
        doctor.DockerCliRuntime,
        "check_cli_and_daemon",
        fail_docker,
        raising=False,
    )

    result = doctor.run_doctor(workspace_root=tmp_path, config_path=None)

    assert any(
        check.name == "tesseract"
        and check.ok is False
        and check.message == "tesseract missing"
        for check in result.checks
    )
    assert any(
        check.name == "docker"
        and check.ok is False
        and check.message == "docker unavailable"
        for check in result.checks
    )
