from pathlib import Path

from qa_platform.shared.resources import (
    MACOS_APPLICATION_SUPPORT_RESOURCE_DIR,
    RESOURCE_ENV_VAR,
    default_resource_candidates,
    resolve_resource_root,
)


def test_resolve_resource_root_prefers_configured_path(tmp_path) -> None:
    configured = tmp_path / "configured" / "resources"
    configured.mkdir(parents=True)

    assert resolve_resource_root(configured) == configured


def test_resolve_resource_root_rejects_configured_file(tmp_path) -> None:
    configured = tmp_path / "resources"
    configured.write_text("not a directory")

    assert resolve_resource_root(configured) is None


def test_resolve_resource_root_prefers_env_before_candidates(monkeypatch, tmp_path) -> None:
    env_root = tmp_path / "env" / "resources"
    env_root.mkdir(parents=True)
    candidate = tmp_path / "candidate" / "resources"
    candidate.mkdir(parents=True)
    monkeypatch.setenv(RESOURCE_ENV_VAR, str(env_root))

    assert resolve_resource_root(None, candidates=(candidate,)) == env_root


def test_resolve_resource_root_rejects_env_file(monkeypatch, tmp_path) -> None:
    env_root = tmp_path / "env_resources"
    env_root.write_text("not a directory")
    candidate = tmp_path / "candidate" / "resources"
    candidate.mkdir(parents=True)
    monkeypatch.setenv(RESOURCE_ENV_VAR, str(env_root))

    assert resolve_resource_root(None, candidates=(candidate,)) is None


def test_resolve_resource_root_rejects_missing_env_before_candidates(
    monkeypatch, tmp_path
) -> None:
    candidate = tmp_path / "candidate" / "resources"
    candidate.mkdir(parents=True)
    monkeypatch.setenv(RESOURCE_ENV_VAR, str(tmp_path / "missing"))

    assert resolve_resource_root(None, candidates=(candidate,)) is None


def test_resolve_resource_root_uses_first_existing_candidate(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(RESOURCE_ENV_VAR, raising=False)
    missing = tmp_path / "missing"
    existing = tmp_path / "existing"
    existing.mkdir()

    assert resolve_resource_root(None, candidates=(missing, existing)) == existing


def test_resolve_resource_root_rejects_candidate_file(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(RESOURCE_ENV_VAR, raising=False)
    candidate_file = tmp_path / "resources"
    candidate_file.write_text("not a directory")

    assert resolve_resource_root(None, candidates=(candidate_file,)) is None


def test_resolve_resource_root_returns_none_when_no_candidate_exists(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv(RESOURCE_ENV_VAR, raising=False)

    assert resolve_resource_root(None, candidates=(tmp_path / "missing",)) is None


def test_default_resource_candidates_include_executable_sibling(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "qa-platform"
    monkeypatch.setattr("sys.executable", str(executable))

    candidates = default_resource_candidates()

    assert executable.parent / "resources" in candidates


def test_default_resource_candidates_include_macos_pkg_application_support(
    monkeypatch,
    tmp_path,
) -> None:
    executable = tmp_path / "qa-platform"
    monkeypatch.setattr("sys.executable", str(executable))

    candidates = default_resource_candidates()

    assert MACOS_APPLICATION_SUPPORT_RESOURCE_DIR in candidates
