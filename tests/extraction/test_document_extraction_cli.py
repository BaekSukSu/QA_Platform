import json
from pathlib import Path
import subprocess
import sys


def test_extraction_cli_module_help_invokes_main() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, "-m", "qa_platform.extraction.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )

    assert result.returncode == 0
    assert "Run document extraction pipeline." in result.stdout
    assert "--config" in result.stdout


def test_cli_runs_pipeline_from_config(monkeypatch, tmp_path, capsys) -> None:
    from qa_platform.extraction import cli

    workspace_root = tmp_path / "workspace"
    config_dir = workspace_root / "config"
    config_dir.mkdir(parents=True)
    (workspace_root / ".env").write_text(
        "GEMINI_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    input_pdf = workspace_root / "sample.pdf"
    input_pdf.write_bytes(b"%PDF")
    config_path = config_dir / "document_extraction.local.json"
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "book_id": "book",
                    "chapter_number": 2,
                    "extractor_engine": "pdf",
                },
                "paths": {
                    "workspace_root": "..",
                    "input_pdf": "sample.pdf",
                },
            }
        ),
        encoding="utf-8",
    )
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    captured_config = {}

    class FakeResult:
        imported_output_dir = workspace_root / "out"
        block_files = [workspace_root / "out" / "block_001.txt"]

    def fake_run_document_extraction_pipeline(config):
        captured_config["config"] = config
        return FakeResult()

    monkeypatch.setattr(
        cli,
        "run_document_extraction_pipeline",
        fake_run_document_extraction_pipeline,
    )
    monkeypatch.chdir(other_cwd)

    exit_code = cli.main(["--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Imported 1 blocks" in captured.out
    assert captured_config["config"].input_hwp is None
    assert captured_config["config"].input_pdf == workspace_root / "sample.pdf"
