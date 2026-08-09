from pathlib import Path

from qa_platform.shared.paths import (
    default_workspace_root,
    resolve_env_file_path,
    resolve_optional_workspace_path,
    resolve_workspace_path,
    resolve_workspace_root,
)


def test_default_workspace_root_uses_documents_qa_platform(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert default_workspace_root() == tmp_path / "Documents" / "QA Platform"


def test_resolve_workspace_root_uses_explicit_absolute_path(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"

    assert resolve_workspace_root(str(workspace_root), config_dir=None) == workspace_root


def test_resolve_workspace_root_allows_omitted_config_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_workspace_root("workspace") == (tmp_path / "workspace").resolve()


def test_resolve_workspace_root_uses_config_value_before_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QA_PLATFORM_WORKSPACE", str(tmp_path / "env-workspace"))

    assert resolve_workspace_root(
        f"  {tmp_path / 'config-workspace'}  ",
        config_dir=None,
    ) == (tmp_path / "config-workspace").resolve()


def test_resolve_workspace_root_uses_env_when_config_is_blank(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QA_PLATFORM_WORKSPACE", f"  {tmp_path / 'env-workspace'}  ")

    assert resolve_workspace_root("  ", config_dir=None) == (
        tmp_path / "env-workspace"
    ).resolve()


def test_resolve_workspace_root_defaults_to_user_documents(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("QA_PLATFORM_WORKSPACE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert resolve_workspace_root(None, config_dir=None) == (
        tmp_path / "Documents" / "QA Platform"
    ).resolve()


def test_resolve_workspace_root_keeps_relative_config_value_config_dir_relative(
    tmp_path,
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    assert resolve_workspace_root("../workspace", config_dir=config_dir) == (
        tmp_path / "workspace"
    )


def test_resolve_env_file_path_prefers_explicit_path(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"

    assert resolve_env_file_path(
        value=str(tmp_path / "custom.env"),
        workspace_root=workspace_root,
    ) == tmp_path / "custom.env"


def test_resolve_env_file_path_uses_workspace_for_relative_path(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"

    assert resolve_env_file_path(
        value="  config/dev.env  ",
        workspace_root=workspace_root,
    ) == (workspace_root / "config" / "dev.env").resolve()


def test_resolve_env_file_path_uses_env_before_workspace_default(
    monkeypatch,
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("QA_PLATFORM_ENV_FILE", f"  {tmp_path / 'env-file'}  ")

    assert resolve_env_file_path(value="  ", workspace_root=workspace_root) == (
        tmp_path / "env-file"
    ).resolve()


def test_resolve_env_file_path_defaults_to_workspace_dotenv(monkeypatch, tmp_path) -> None:
    workspace_root = tmp_path / "workspace" / ".." / "workspace"
    monkeypatch.delenv("QA_PLATFORM_ENV_FILE", raising=False)

    assert resolve_env_file_path(value=None, workspace_root=workspace_root) == (
        workspace_root / ".env"
    ).resolve()


def test_resolve_workspace_path_keeps_absolute_path(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    absolute_path = tmp_path / "input" / "chapter02.hwp"

    assert resolve_workspace_path(absolute_path, workspace_root) == absolute_path


def test_resolve_workspace_path_joins_relative_path(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"

    assert resolve_workspace_path("data/blocks", workspace_root) == (
        workspace_root / "data" / "blocks"
    )


def test_resolve_optional_workspace_path_handles_blank_values(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"

    assert resolve_optional_workspace_path(None, workspace_root) is None
    assert resolve_optional_workspace_path("", workspace_root) is None
    assert resolve_optional_workspace_path("input.pdf", workspace_root) == (
        workspace_root / "input.pdf"
    )
