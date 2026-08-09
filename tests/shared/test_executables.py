from pathlib import Path

import pytest

from qa_platform.shared.executables import ExecutableNotFoundError, resolve_executable


def test_resolve_executable_prefers_configured_path(tmp_path) -> None:
    configured = tmp_path / "bin" / "tool"
    configured.parent.mkdir()
    configured.write_text("#!/bin/sh\n", encoding="utf-8")
    configured.chmod(0o755)

    assert resolve_executable("tool", configured_path=configured) == configured


def test_resolve_executable_uses_path_for_configured_command_name(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/local/bin/{name}")

    assert resolve_executable("tool", configured_path="tool") == Path(
        "/usr/local/bin/tool"
    )


def test_resolve_executable_reports_missing_configured_command_name(
    monkeypatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ExecutableNotFoundError) as exc_info:
        resolve_executable("tool", configured_path="missing-tool")

    message = str(exc_info.value)
    assert "tool executable was not found" in message
    assert "configured command name: missing-tool" in message


def test_resolve_executable_keeps_configured_relative_path_strict(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/local/bin/tool" if name == "bin/tool" else None,
    )

    with pytest.raises(ExecutableNotFoundError) as exc_info:
        resolve_executable("tool", configured_path="bin/tool")

    assert "configured path: bin/tool" in str(exc_info.value)


def test_resolve_executable_rejects_non_executable_configured_path(
    tmp_path,
) -> None:
    configured = tmp_path / "bin" / "tool"
    configured.parent.mkdir()
    configured.write_text("#!/bin/sh\n", encoding="utf-8")
    configured.chmod(0o644)

    with pytest.raises(ExecutableNotFoundError) as exc_info:
        resolve_executable("tool", configured_path=configured)

    assert "not executable" in str(exc_info.value)


def test_resolve_executable_uses_bundled_path_before_path_lookup(
    monkeypatch,
    tmp_path,
) -> None:
    bundled = tmp_path / "resources" / "tool"
    bundled.parent.mkdir()
    bundled.write_text("#!/bin/sh\n", encoding="utf-8")
    bundled.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tool")

    assert resolve_executable("tool", bundled_path=bundled) == bundled


def test_resolve_executable_rejects_non_executable_bundled_path(
    monkeypatch,
    tmp_path,
) -> None:
    bundled = tmp_path / "resources" / "tool"
    bundled.parent.mkdir()
    bundled.write_text("#!/bin/sh\n", encoding="utf-8")
    bundled.chmod(0o644)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tool")

    with pytest.raises(ExecutableNotFoundError):
        resolve_executable("tool", bundled_path=bundled)


def test_resolve_executable_uses_path_lookup(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/opt/homebrew/bin/tool")

    assert resolve_executable("tool") == Path("/opt/homebrew/bin/tool")


def test_resolve_executable_uses_candidate_paths_when_path_lookup_fails(
    monkeypatch,
    tmp_path,
) -> None:
    candidate = tmp_path / "candidate-tool"
    candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert resolve_executable("tool", candidate_paths=(candidate,)) == candidate


def test_resolve_executable_skips_non_executable_candidate_paths(
    monkeypatch,
    tmp_path,
) -> None:
    candidate = tmp_path / "candidate-tool"
    candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate.chmod(0o644)
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ExecutableNotFoundError) as exc_info:
        resolve_executable("tool", candidate_paths=(candidate,))

    message = str(exc_info.value)
    assert "tool executable was not found" in message
    assert "not executable" in message


def test_resolve_executable_raises_clear_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ExecutableNotFoundError) as exc_info:
        resolve_executable("tool", candidate_paths=(tmp_path / "missing-tool",))

    assert "tool executable was not found" in str(exc_info.value)
