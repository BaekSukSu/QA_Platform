from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

import cv2
import pytesseract

from qa_platform.shared.executables import resolve_executable


KEYWORD_PATTERN = re.compile(
    r"(def |import |print|class |return|>>>|\.\.\.|\=|\(|\)|\+)",
    re.IGNORECASE,
)
DEFAULT_TESSERACT_CANDIDATE_PATHS = (
    Path("/opt/homebrew/bin/tesseract"),
    Path("/usr/local/bin/tesseract"),
)
_RESOURCE_ROOT_UNSET = object()


@dataclass(frozen=True)
class TesseractRuntime:
    command: Path
    tessdata_dir: Path | None = None


def resolve_tesseract_runtime(
    configured_path: str | Path | None,
    *,
    resource_root: Path | None | object = _RESOURCE_ROOT_UNSET,
    candidate_paths: tuple[Path, ...] = DEFAULT_TESSERACT_CANDIDATE_PATHS,
) -> TesseractRuntime:
    configured_value = (
        str(configured_path).strip() if configured_path is not None else ""
    )
    del resource_root
    if configured_value:
        command = resolve_executable("tesseract", configured_path=configured_path)
    else:
        command = resolve_executable(
            "tesseract",
            candidate_paths=candidate_paths,
        )

    return TesseractRuntime(command=command)


def resolve_tesseract_cmd(
    configured_path: str | Path | None,
    *,
    resource_root: Path | None | object = _RESOURCE_ROOT_UNSET,
) -> Path:
    return resolve_tesseract_runtime(
        configured_path,
        resource_root=resource_root,
    ).command


def configure_pytesseract_runtime(runtime: TesseractRuntime) -> None:
    pytesseract.pytesseract.tesseract_cmd = str(runtime.command)
    if runtime.tessdata_dir is not None:
        os.environ["TESSDATA_PREFIX"] = str(runtime.tessdata_dir)


def filter_images_locally(
    image_paths: list[Path],
    tesseract_path: Path | TesseractRuntime,
    *,
    keep_temp: bool = False,
) -> list[Path]:
    had_tessdata_prefix = "TESSDATA_PREFIX" in os.environ
    previous_tessdata_prefix = os.environ.get("TESSDATA_PREFIX")
    valid_paths: list[Path] = []

    try:
        if isinstance(tesseract_path, TesseractRuntime):
            configure_pytesseract_runtime(tesseract_path)
        else:
            pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)

        for image_path in image_paths:
            try:
                image_cv = cv2.imread(str(image_path))
                if image_cv is None:
                    valid_paths.append(image_path)
                    continue
                gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
                _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
                extracted_text = pytesseract.image_to_string(binary)

                if KEYWORD_PATTERN.search(extracted_text):
                    valid_paths.append(image_path)
                elif not keep_temp:
                    image_path.unlink(missing_ok=True)
            except Exception:
                valid_paths.append(image_path)
    finally:
        if had_tessdata_prefix:
            os.environ["TESSDATA_PREFIX"] = previous_tessdata_prefix or ""
        else:
            os.environ.pop("TESSDATA_PREFIX", None)

    return valid_paths
