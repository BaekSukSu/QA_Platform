from pathlib import Path

import pytest

from qa_platform.extraction.tesseract_filter import (
    TesseractRuntime,
    configure_pytesseract_runtime,
    resolve_tesseract_runtime,
)
from qa_platform.shared.executables import ExecutableNotFoundError


def test_resolve_tesseract_cmd_uses_existing_configured_path(tmp_path) -> None:
    from qa_platform.extraction.tesseract_filter import resolve_tesseract_cmd

    binary = tmp_path / "tesseract"
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o755)

    assert resolve_tesseract_cmd(str(binary)) == binary.resolve()


def test_resolve_tesseract_cmd_falls_back_to_path(monkeypatch) -> None:
    from qa_platform.extraction import tesseract_filter

    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/opt/homebrew/bin/tesseract" if name == "tesseract" else None,
    )

    assert tesseract_filter.resolve_tesseract_cmd(
        "",
        resource_root=None,
    ) == Path("/opt/homebrew/bin/tesseract").resolve()


def test_resolve_tesseract_runtime_rejects_resource_tesseract_without_installed_candidate(
    monkeypatch,
    tmp_path,
) -> None:
    resource_root = tmp_path / "resources"
    tesseract = resource_root / "tesseract" / "bin" / "tesseract"
    tessdata = resource_root / "tesseract" / "share" / "tessdata"
    tesseract.parent.mkdir(parents=True)
    tessdata.mkdir(parents=True)
    tesseract.write_text("#!/bin/sh\n", encoding="utf-8")
    tesseract.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ExecutableNotFoundError, match="tesseract"):
        resolve_tesseract_runtime(
            "",
            resource_root=resource_root,
            candidate_paths=(),
        )


def test_resolve_tesseract_runtime_prefers_installed_command_over_resource_tesseract(
    monkeypatch,
    tmp_path,
) -> None:
    resource_root = tmp_path / "resources"
    resource_tesseract = resource_root / "tesseract" / "bin" / "tesseract"
    resource_tessdata = resource_root / "tesseract" / "share" / "tessdata"
    path_tesseract = tmp_path / "path" / "tesseract"
    resource_tesseract.parent.mkdir(parents=True)
    resource_tessdata.mkdir(parents=True)
    path_tesseract.parent.mkdir()
    resource_tesseract.write_text("#!/bin/sh\n", encoding="utf-8")
    path_tesseract.write_text("#!/bin/sh\n", encoding="utf-8")
    resource_tesseract.chmod(0o755)
    path_tesseract.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: str(path_tesseract))

    runtime = resolve_tesseract_runtime("", resource_root=resource_root)

    assert runtime.command == path_tesseract.resolve()
    assert runtime.tessdata_dir is None


def test_resolve_tesseract_runtime_falls_back_to_path(
    monkeypatch,
    tmp_path,
) -> None:
    path_tesseract = tmp_path / "path-tesseract"
    path_tesseract.write_text("#!/bin/sh\n", encoding="utf-8")
    path_tesseract.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: str(path_tesseract))

    runtime = resolve_tesseract_runtime("", resource_root=None)

    assert runtime.command == path_tesseract.resolve()
    assert runtime.tessdata_dir is None


def test_resolve_tesseract_runtime_ignores_resource_tessdata_for_path_command(
    monkeypatch,
    tmp_path,
) -> None:
    resource_root = tmp_path / "resources"
    tessdata = resource_root / "tesseract" / "share" / "tessdata"
    path_tesseract = tmp_path / "path-tesseract"
    tessdata.mkdir(parents=True)
    path_tesseract.write_text("#!/bin/sh\n", encoding="utf-8")
    path_tesseract.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: str(path_tesseract))

    runtime = resolve_tesseract_runtime("", resource_root=resource_root)

    assert runtime.command == path_tesseract.resolve()
    assert runtime.tessdata_dir is None


def test_resolve_tesseract_runtime_ignores_resource_tessdata_for_configured_command(
    monkeypatch,
    tmp_path,
) -> None:
    resource_root = tmp_path / "resources"
    tessdata = resource_root / "tesseract" / "share" / "tessdata"
    configured_tesseract = tmp_path / "configured-tesseract"
    tessdata.mkdir(parents=True)
    configured_tesseract.write_text("#!/bin/sh\n", encoding="utf-8")
    configured_tesseract.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: None)

    runtime = resolve_tesseract_runtime(
        str(configured_tesseract),
        resource_root=resource_root,
    )

    assert runtime.command == configured_tesseract.resolve()
    assert runtime.tessdata_dir is None


def test_resolve_tesseract_runtime_uses_homebrew_candidates(
    monkeypatch,
    tmp_path,
) -> None:
    candidate = tmp_path / "homebrew" / "bin" / "tesseract"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: None)

    runtime = resolve_tesseract_runtime(
        "",
        resource_root=None,
        candidate_paths=(candidate,),
    )

    assert runtime.command == candidate.resolve()


def test_resolve_tesseract_runtime_rejects_non_executable_configured_path(
    tmp_path,
) -> None:
    configured = tmp_path / "tesseract"
    configured.write_text("#!/bin/sh\n", encoding="utf-8")
    configured.chmod(0o644)

    with pytest.raises(ExecutableNotFoundError, match="not executable"):
        resolve_tesseract_runtime(str(configured), resource_root=None)


def test_configure_pytesseract_runtime_sets_tessdata_prefix(
    monkeypatch,
    tmp_path,
) -> None:
    tesseract = tmp_path / "tesseract"
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    configure_pytesseract_runtime(
        TesseractRuntime(command=tesseract, tessdata_dir=tessdata),
    )

    assert tesseract_filter_command() == str(tesseract)
    assert os_environ_value("TESSDATA_PREFIX") == str(tessdata)


def test_configure_pytesseract_runtime_preserves_existing_tessdata_prefix(
    monkeypatch,
    tmp_path,
) -> None:
    tesseract = tmp_path / "tesseract"
    monkeypatch.setenv("TESSDATA_PREFIX", "/caller/tessdata")

    configure_pytesseract_runtime(TesseractRuntime(command=tesseract))

    assert tesseract_filter_command() == str(tesseract)
    assert os_environ_value("TESSDATA_PREFIX") == "/caller/tessdata"


def test_filter_images_locally_with_path_preserves_existing_tessdata_prefix(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.extraction import tesseract_filter

    monkeypatch.setenv("TESSDATA_PREFIX", "/caller/tessdata")

    kept = tesseract_filter.filter_images_locally(
        [],
        tmp_path / "tesseract",
        keep_temp=False,
    )

    assert kept == []
    assert os_environ_value("TESSDATA_PREFIX") == "/caller/tessdata"


def test_filter_images_locally_sets_custom_tessdata_during_ocr_and_restores(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.extraction import tesseract_filter

    image_path = tmp_path / "1_1.bmp"
    image_path.write_bytes(b"image")
    tessdata = tmp_path / "custom" / "tessdata"
    tessdata.mkdir(parents=True)
    seen_prefixes = []
    monkeypatch.setenv("TESSDATA_PREFIX", "/caller/tessdata")
    monkeypatch.setattr(tesseract_filter.cv2, "imread", lambda path: str(path))
    monkeypatch.setattr(tesseract_filter.cv2, "cvtColor", lambda img, mode: img)
    monkeypatch.setattr(tesseract_filter.cv2, "threshold", lambda *args: (None, args[0]))

    def fake_image_to_string(img):
        seen_prefixes.append(os_environ_value("TESSDATA_PREFIX"))
        return "print('hello')"

    monkeypatch.setattr(
        tesseract_filter.pytesseract,
        "image_to_string",
        fake_image_to_string,
    )

    kept = tesseract_filter.filter_images_locally(
        [image_path],
        TesseractRuntime(command=tmp_path / "tesseract", tessdata_dir=tessdata),
        keep_temp=False,
    )

    assert kept == [image_path]
    assert seen_prefixes == [str(tessdata)]
    assert os_environ_value("TESSDATA_PREFIX") == "/caller/tessdata"


def test_filter_images_locally_removes_custom_tessdata_after_ocr_when_unset(
    monkeypatch,
    tmp_path,
) -> None:
    from qa_platform.extraction import tesseract_filter

    image_path = tmp_path / "1_1.bmp"
    image_path.write_bytes(b"image")
    tessdata = tmp_path / "custom" / "tessdata"
    tessdata.mkdir(parents=True)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr(tesseract_filter.cv2, "imread", lambda path: str(path))
    monkeypatch.setattr(tesseract_filter.cv2, "cvtColor", lambda img, mode: img)
    monkeypatch.setattr(tesseract_filter.cv2, "threshold", lambda *args: (None, args[0]))
    monkeypatch.setattr(
        tesseract_filter.pytesseract,
        "image_to_string",
        lambda img: "print('hello')",
    )

    kept = tesseract_filter.filter_images_locally(
        [image_path],
        TesseractRuntime(command=tmp_path / "tesseract", tessdata_dir=tessdata),
        keep_temp=False,
    )

    assert kept == [image_path]
    assert os_environ_value("TESSDATA_PREFIX") is None


def test_filter_images_locally_keeps_keyword_images(monkeypatch, tmp_path) -> None:
    from qa_platform.extraction import tesseract_filter

    image_path = tmp_path / "1_1.bmp"
    image_path.write_bytes(b"image")
    deleted_path = tmp_path / "2_1.bmp"
    deleted_path.write_bytes(b"image")

    monkeypatch.setattr(tesseract_filter.cv2, "imread", lambda path: object())
    monkeypatch.setattr(tesseract_filter.cv2, "cvtColor", lambda img, mode: img)
    monkeypatch.setattr(tesseract_filter.cv2, "threshold", lambda *args: (None, args[0]))
    texts = {
        str(image_path): "print('hello')",
        str(deleted_path): "plain korean text",
    }
    monkeypatch.setattr(
        tesseract_filter.pytesseract,
        "image_to_string",
        lambda img: texts[str(img)],
    )
    monkeypatch.setattr(
        tesseract_filter.cv2,
        "imread",
        lambda path: str(path),
    )

    kept = tesseract_filter.filter_images_locally(
        [image_path, deleted_path],
        Path("/usr/bin/tesseract"),
        keep_temp=False,
    )

    assert kept == [image_path]
    assert image_path.exists()
    assert not deleted_path.exists()


def tesseract_filter_command() -> str:
    from qa_platform.extraction import tesseract_filter

    return tesseract_filter.pytesseract.pytesseract.tesseract_cmd


def os_environ_value(name: str) -> str | None:
    import os

    return os.environ.get(name)
