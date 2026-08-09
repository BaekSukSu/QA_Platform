from pathlib import Path

from qa_platform.pipeline.config import load_qa_pipeline_config


def test_qa_pipeline_example_matches_current_config_contract(monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "config" / "qa_pipeline.example.json"
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    config = load_qa_pipeline_config(config_path)

    assert config.workspace_root == project_root
    assert config.execution_backend == "docker"
    assert config.extractor.book_id == "sample_book"
    assert config.extractor.chapter_number == 1
    assert config.extractor.extractor_engine == "pdf"
    assert config.extractor.input_hwp is None
    assert config.extractor.input_pdf == project_root / "input/chapter01.pdf"
    assert config.extractor.output_root == project_root / "extracted_blocks"
    assert config.extractor.work_root == project_root / "run/document_extraction"
    assert config.run_root == project_root / "run/qa_pipeline"
    assert config.extractor.tesseract_cmd == "tesseract"
    assert config.docker.docker_cmd == "docker"
    assert config.docker.python_version == "3.11"
    assert config.docker.image == "qa-platform-python-stdlib:3.11"
    assert config.docker.timeout_seconds == 5
    assert config.docker.output_limit_chars == 20_000
    assert config.docker.memory_limit == "256m"
    assert config.docker.cpu_limit == 0.5
    assert config.docker.pids_limit == 64
    assert config.docker.work_tmpfs_size == "64m"
    assert config.docker.temp_tmpfs_size == "64m"
    assert config.docker.user == "10001:10001"
    assert config.docker.image_build_timeout_seconds == 300
