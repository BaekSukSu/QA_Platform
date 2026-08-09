import json
from pathlib import Path


def _fake_pipeline_result(tmp_path: Path):
    class FakeExtraction:
        imported_output_dir = tmp_path / "blocks"

    class FakeChapter:
        run_id = "260701_120000"
        run_dir = tmp_path / "run" / "260701_120000"
        total_blocks = 3
        passed_blocks = 2
        failed_blocks = 1
        report_json_path = run_dir / "chapter_error_report.json"
        report_markdown_path = run_dir / "chapter_error_report.md"

    class FakeResult:
        extraction = FakeExtraction()
        chapter = FakeChapter()
        summary_path = FakeChapter.run_dir / "qa_pipeline.json"

    return FakeResult()


def _patch_pipeline_runner(monkeypatch, pipeline_cli, tmp_path: Path):
    captured_config = {}
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    def fake_run_qa_pipeline(config):
        captured_config["config"] = config
        return _fake_pipeline_result(tmp_path)

    monkeypatch.setattr(
        pipeline_cli,
        "run_qa_pipeline",
        fake_run_qa_pipeline,
    )
    return captured_config


def _write_pipeline_config(config_path: Path, input_pdf: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    input_pdf.parent.mkdir(parents=True, exist_ok=True)
    input_pdf.write_bytes(b"%PDF")
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "book_id": "python_junior",
                    "chapter_number": 2,
                    "python_version": "3.11",
                    "extractor_engine": "pdf",
                },
                "paths": {
                    "input_pdf": str(input_pdf),
                    "run_root": str(config_path.parent / "run"),
                },
                "execution": {"backend": "docker"},
            }
        ),
        encoding="utf-8",
    )


def _assert_summary_output(output: str) -> None:
    assert "QA pipeline completed" in output
    assert "Blocks: " in output
    assert "Run: " in output
    assert "Report: " in output
    assert "Summary: " in output


def test_pipeline_cli_runs_pipeline_from_explicit_config(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    config_path = tmp_path / "config" / "qa_pipeline.local.json"
    _write_pipeline_config(config_path, tmp_path / "chapter02.pdf")
    _patch_pipeline_runner(monkeypatch, pipeline_cli, tmp_path)

    exit_code = pipeline_cli.main(["run", "--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    _assert_summary_output(captured.out)


def test_pipeline_cli_keeps_legacy_config_argument(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    config_path = tmp_path / "config" / "qa_pipeline.local.json"
    _write_pipeline_config(config_path, tmp_path / "chapter02.pdf")
    _patch_pipeline_runner(monkeypatch, pipeline_cli, tmp_path)

    exit_code = pipeline_cli.main(["--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "QA pipeline completed" in captured.out


def test_pipeline_cli_run_uses_default_local_config(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    workspace_root = tmp_path / "Documents" / "QA Platform"
    config_path = workspace_root / "config" / "qa_pipeline.local.json"
    _write_pipeline_config(config_path, workspace_root / "chapter01.pdf")
    _patch_pipeline_runner(monkeypatch, pipeline_cli, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    exit_code = pipeline_cli.main(["run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "QA pipeline completed" in captured.out


def test_pipeline_cli_run_reports_missing_default_config(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    monkeypatch.setenv("HOME", str(tmp_path))

    exit_code = pipeline_cli.main(["run"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert str(tmp_path / "Documents" / "QA Platform" / "config") in captured.err
    assert "qa_pipeline.local.json" in captured.err
    assert "init-config" in captured.err


def test_pipeline_cli_init_config_writes_minimal_template(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    monkeypatch.setenv("HOME", str(tmp_path))

    exit_code = pipeline_cli.main(["init-config"])

    workspace_root = tmp_path / "Documents" / "QA Platform"
    config_path = workspace_root / "config" / "qa_pipeline.local.json"
    env_path = workspace_root / ".env"
    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "project": {
            "book_id": "python_junior",
            "chapter_number": 1,
            "python_version": "3.11",
        },
        "paths": {
            "workspace_root": str(workspace_root),
            "input_pdf": "input/chapter01.pdf",
            "output_root": "extracted_blocks",
            "work_root": "run/document_extraction",
            "run_root": "run/qa_pipeline",
        },
    }
    assert config_path.read_text(encoding="utf-8").endswith("\n")
    assert env_path.read_text(encoding="utf-8") == "GEMINI_API_KEY=\n"
    assert (workspace_root / "input").is_dir()
    assert (workspace_root / "extracted_blocks").is_dir()
    assert (workspace_root / "run").is_dir()
    assert (workspace_root / "logs").is_dir()
    assert f"Workspace: {workspace_root}" in captured.out
    assert f"Config: {config_path}" in captured.out
    assert f"Env: {env_path}" in captured.out


def test_pipeline_cli_init_config_writes_workspace_override(
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    workspace_root = tmp_path / "workspace"

    exit_code = pipeline_cli.main(
        ["init-config", "--workspace-root", str(workspace_root)]
    )

    config_path = workspace_root / "config" / "qa_pipeline.local.json"
    env_path = workspace_root / ".env"
    captured = capsys.readouterr()
    assert exit_code == 0
    assert config_path.is_file()
    assert env_path.read_text(encoding="utf-8") == "GEMINI_API_KEY=\n"
    assert json.loads(config_path.read_text(encoding="utf-8"))["paths"][
        "workspace_root"
    ] == str(workspace_root)
    assert (workspace_root / "input").is_dir()
    assert (workspace_root / "extracted_blocks").is_dir()
    assert (workspace_root / "run").is_dir()
    assert (workspace_root / "logs").is_dir()
    assert f"Workspace: {workspace_root}" in captured.out
    assert f"Config: {config_path}" in captured.out
    assert f"Env: {env_path}" in captured.out


def test_pipeline_cli_init_config_writes_custom_path(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    monkeypatch.setenv("HOME", str(tmp_path))
    custom_path = tmp_path / "custom" / "pipeline.json"

    exit_code = pipeline_cli.main(["init-config", "--path", str(custom_path)])

    workspace_root = tmp_path / "Documents" / "QA Platform"
    captured = capsys.readouterr()
    assert exit_code == 0
    assert custom_path.is_file()
    assert json.loads(custom_path.read_text(encoding="utf-8")) == (
        pipeline_cli._default_config_payload(workspace_root)
    )
    assert not (workspace_root / "config" / "qa_pipeline.local.json").exists()
    assert f"Config: {custom_path}" in captured.out


def test_pipeline_cli_init_config_refuses_overwrite(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = (
        tmp_path / "Documents" / "QA Platform" / "config" / "qa_pipeline.local.json"
    )
    config_path.parent.mkdir(parents=True)
    config_path.write_text("existing\n", encoding="utf-8")

    exit_code = pipeline_cli.main(["init-config"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "already exists" in captured.err
    assert config_path.read_text(encoding="utf-8") == "existing\n"


def test_pipeline_cli_init_config_rejects_directory_path_even_with_force(
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    directory_path = tmp_path / "config"
    directory_path.mkdir()

    exit_code = pipeline_cli.main(
        ["init-config", "--path", str(directory_path), "--force"]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "not a file" in captured.err


def test_pipeline_cli_init_config_force_overwrites(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = (
        tmp_path / "Documents" / "QA Platform" / "config" / "qa_pipeline.local.json"
    )
    config_path.parent.mkdir(parents=True)
    config_path.write_text("existing\n", encoding="utf-8")

    exit_code = pipeline_cli.main(["init-config", "--force"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "project" in json.loads(config_path.read_text(encoding="utf-8"))
    assert f"Config: {config_path}" in captured.out


def test_pipeline_cli_without_command_prints_help(capsys) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    exit_code = pipeline_cli.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "usage: qa-platform" in captured.out
    assert "run" in captured.out
    assert "init-config" in captured.out
    assert "doctor" in captured.out
    assert captured.err == ""


def test_pipeline_cli_top_level_help_lists_commands(capsys) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    exit_code = pipeline_cli.main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage: qa-platform" in captured.out
    assert "run" in captured.out
    assert "init-config" in captured.out
    assert "doctor" in captured.out
    assert captured.err == ""


def test_doctor_subcommand_returns_zero_when_all_checks_pass(monkeypatch) -> None:
    from qa_platform.pipeline import cli
    from qa_platform.pipeline.doctor import DoctorCheck, DoctorResult

    monkeypatch.setattr(
        cli,
        "run_doctor",
        lambda **kwargs: DoctorResult(
            checks=(DoctorCheck(name="workspace", ok=True, message="ready"),)
        ),
    )

    assert cli.main(["doctor"]) == 0


def test_doctor_subcommand_returns_one_and_prints_fail_output(
    monkeypatch,
    capsys,
) -> None:
    from qa_platform.pipeline import cli
    from qa_platform.pipeline.doctor import DoctorCheck, DoctorResult

    monkeypatch.setattr(
        cli,
        "run_doctor",
        lambda **kwargs: DoctorResult(
            checks=(
                DoctorCheck(
                    name="docker",
                    ok=False,
                    message="Docker Desktop is not running",
                ),
            )
        ),
    )

    assert cli.main(["doctor"]) == 1

    captured = capsys.readouterr()
    assert "[FAIL] docker: Docker Desktop is not running" in captured.out


def test_pipeline_cli_passes_config_dir_for_relative_workspace_paths(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    workspace_root = tmp_path / "workspace"
    config_dir = workspace_root / "config"
    config_dir.mkdir(parents=True)
    input_pdf = workspace_root / "chapter02.pdf"
    input_pdf.write_bytes(b"%PDF")
    config_path = config_dir / "qa_pipeline.local.json"
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "book_id": "python_junior",
                    "chapter_number": 2,
                    "python_version": "3.11",
                    "extractor_engine": "pdf",
                },
                "paths": {
                    "workspace_root": "..",
                    "input_pdf": "chapter02.pdf",
                    "run_root": "run",
                },
                "execution": {"backend": "docker"},
            }
        ),
        encoding="utf-8",
    )
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    captured_config = _patch_pipeline_runner(monkeypatch, pipeline_cli, tmp_path)
    monkeypatch.chdir(other_cwd)

    exit_code = pipeline_cli.main(["--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "QA pipeline completed" in captured.out
    assert captured_config["config"].extractor.input_hwp is None
    assert captured_config["config"].extractor.input_pdf == (
        workspace_root / "chapter02.pdf"
    )
    assert captured_config["config"].run_root == workspace_root / "run"


def test_pipeline_cli_run_uses_workspace_default_config(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    workspace_root = tmp_path / "workspace"
    config_path = workspace_root / "config" / "qa_pipeline.local.json"
    input_pdf = workspace_root / "input" / "book.pdf"
    input_pdf.parent.mkdir(parents=True)
    input_pdf.write_bytes(b"%PDF")
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "book_id": "python_junior",
                    "chapter_number": 2,
                    "python_version": "3.11",
                    "extractor_engine": "pdf",
                },
                "paths": {
                    "input_pdf": "input/book.pdf",
                    "run_root": "run/qa_pipeline",
                },
                "execution": {"backend": "docker"},
            }
        ),
        encoding="utf-8",
    )
    captured_config = _patch_pipeline_runner(monkeypatch, pipeline_cli, tmp_path)

    exit_code = pipeline_cli.main(["run", "--workspace-root", str(workspace_root)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "QA pipeline completed" in captured.out
    assert captured_config["config"].workspace_root == workspace_root
    assert captured_config["config"].extractor.input_pdf == input_pdf
    assert captured_config["config"].run_root == workspace_root / "run" / "qa_pipeline"


def test_pipeline_cli_run_uses_env_file_override(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    from qa_platform.pipeline import cli as pipeline_cli

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    config_path = workspace_root / "config" / "qa_pipeline.local.json"
    input_pdf = workspace_root / "input" / "book.pdf"
    env_file = tmp_path / "custom.env"
    input_pdf.parent.mkdir(parents=True)
    input_pdf.write_bytes(b"%PDF")
    env_file.write_text("GEMINI_API_KEY=file-key\n", encoding="utf-8")
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "book_id": "python_junior",
                    "chapter_number": 2,
                    "python_version": "3.11",
                    "extractor_engine": "pdf",
                },
                "paths": {
                    "input_pdf": "input/book.pdf",
                    "run_root": "run/qa_pipeline",
                },
                "execution": {"backend": "docker"},
            }
        ),
        encoding="utf-8",
    )
    captured_config = {}

    def fake_run_qa_pipeline(config):
        captured_config["config"] = config
        return _fake_pipeline_result(tmp_path)

    monkeypatch.setattr(pipeline_cli, "run_qa_pipeline", fake_run_qa_pipeline)

    exit_code = pipeline_cli.main(
        [
            "run",
            "--workspace-root",
            str(workspace_root),
            "--env-file",
            str(env_file),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "QA pipeline completed" in captured.out
    assert captured_config["config"].extractor.gemini_api_key == "file-key"
