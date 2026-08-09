from __future__ import annotations

import io
from pathlib import Path
import re

from google.genai import types
from PIL import Image

from qa_platform.contract.constants import CODE_TYPE_COMPLETE


IMAGE_OCR_PROMPT = """
You are a PRECISE DATA PARSER and MECHANICAL OCR SCANNER.
Your job is to extract Python code from textbook images and classify its intent.

[CRITICAL ANTI-HALLUCINATION RULES]
1. LOOK AT THE IMAGE. Is there literal, executable Python code visually written in it?
2. If the image only contains Korean explanations, speech bubbles, or conceptual descriptions of how Python works, output EXACTLY and ONLY this string: NOT_PYTHON_CODE

[INTENT CLASSIFICATION RULES]
Analyze the surrounding Korean text and the code structure in the image to assign ONE of the following to 'code_type':
1. 'ERROR_FINDING': If the text explicitly asks to find or fix an error (e.g., "오류를 찾으시오", "잘못된 부분").
2. 'INCOMPLETE_SNIPPET': STRICTLY for partial fragments that are physically unrunnable (e.g., clearly missing variable assignments, missing imports, or containing placeholders like '...').
3. 'COMPLETE_CODE': For fully independent, runnable code. [CRITICAL] Even if the surrounding text is merely explaining a concept, if the code itself is structurally complete and runnable, it MUST be classified as 'COMPLETE_CODE'.

[EXECUTION MODE CLASSIFICATION]
- Use execution_mode 'repl' for interactive prompt markers >>> or ... or expression echo output.
- If the source uses >>> print(value), it is still execution_mode 'repl'.
- Use execution_mode 'script' for standalone program/lab/file examples.
- Do not rewrite expression statements into print(...); preserve code and classify mode.
- When uncertain, prefer script unless expected output depends on REPL expression echo.
- Remove visible REPL prompt markers (>>> and ...) from [CODE], but preserve that context by setting execution_mode : repl.

[NO INFERENCE / IDE SCREENSHOT RULES]
- Extract visible characters only. Never infer hidden, cropped, blurred, or occluded code.
- If an IDE screenshot contains an editor pane and a console pane, keep their roles separate.
- The editor pane may contain source code. The console pane may contain execution commands and output.
- Spyder/IPython wrapper commands such as runfile(...), In [7]:, paths, and wdir values are execution context, not textbook source code.
- If the editor pane is partially covered by menus, panels, or cropping and the full source is not visible, do not reconstruct the missing source from the console output.
- If visible source code and visible console output cannot be paired with confidence, classify the block as INCOMPLETE_SNIPPET and preserve only the visible code/output.

[STRICT EXTRACTION RULES (ONLY IF PHYSICAL CODE EXISTS)]
1. [META]: Must contain ONLY the 'code_type : <type>' and 'execution_mode : <script_or_repl>' lines.
2. [PACKAGES]: List external pip packages only (e.g., pandas, pillow, opencv-python) IF AND ONLY IF there is an "import" statement requiring a third-party pip install. Do not list Python standard-library modules. Do not list GUI/environment modules such as turtle or tkinter. If none, write NONE.
3. [CODE]: DO NOT REFACTOR, OPTIMIZE, OR FIX LOGIC. Preserve exactly every single space for indentation. Copy the code character by character except for visible REPL prompt markers.
4. [INPUT]: Extract ONLY the keystroke values explicitly written in the textbook's execution example. If none, write NONE.
5. [OUTPUT]: Extract the execution result exactly as printed. If NOT visually provided, write NONE.

[OUTPUT FORMAT]
[META]
code_type : <CLASSIFIED_TYPE>
execution_mode : <script_or_repl>

[PACKAGES]
<PACKAGES_OR_NONE>

[CODE]
<EXACT_CODE>

[INPUT]
<INPUT_OR_NONE>

[OUTPUT]
<OUTPUT_OR_NONE>
"""


def normalize_ocr_text(ocr_text: str, page_num: str) -> str:
    meta_text = _extract_section(ocr_text, "META")

    code_type = CODE_TYPE_COMPLETE
    if meta_text != "NONE":
        match = re.search(r"code_type\s*:\s*([A-Z_]+)", meta_text)
        if match:
            code_type = match.group(1).strip()
    execution_mode = "script"
    if meta_text != "NONE":
        match = re.search(
            r"execution_mode\s*:\s*[\"']?(script|repl)[\"']?",
            meta_text,
            re.IGNORECASE,
        )
        if match:
            execution_mode = match.group(1).strip().lower()

    packages_text = _extract_section(ocr_text, "PACKAGES")
    input_text = _extract_section(ocr_text, "INPUT")
    code_text = _extract_section(ocr_text, "CODE")
    output_text = _extract_section(ocr_text, "OUTPUT")

    return (
        f"[META]\npage : {page_num}\nsource_kind : image\n"
        f"code_type : {code_type}\n"
        f"execution_mode : {execution_mode}\n\n"
        f"[PACKAGES]\n{packages_text}\n\n"
        f"[CODE]\n{code_text}\n\n"
        f"[INPUT]\n{input_text}\n\n"
        f"[OUTPUT]\n{output_text}"
    )


def process_image_ocr(image_path: Path, client) -> tuple[str | None, str]:
    image = Image.open(image_path)
    if image.format not in ["PNG", "JPEG", "WEBP", "HEIC", "HEIF"]:
        image = image.convert("RGB")
        byte_stream = io.BytesIO()
        image.save(byte_stream, format="PNG")
        byte_stream.seek(0)
        image = Image.open(byte_stream)

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[IMAGE_OCR_PROMPT, image],
        config=types.GenerateContentConfig(
            temperature=0.0,
            top_p=0.1,
            top_k=1,
            seed=42,
        ),
    )
    text = response.text.strip()
    if text == "NOT_PYTHON_CODE" or not text or len(text) < 4:
        return None, "not_python_code"
    return text, "success"


def extract_image_blocks_to_files(
    image_paths: list[Path],
    output_dir: Path,
    *,
    start_idx: int,
    client,
    keep_temp: bool = False,
) -> int:
    file_idx = start_idx
    processed_count = 0

    for image_path in image_paths:
        image_path = Path(image_path)
        page_num = _page_number_from_image_path(image_path)
        ocr_text, _status = process_image_ocr(image_path, client)

        if ocr_text and "NOT_PYTHON_CODE" not in ocr_text:
            final_content = normalize_ocr_text(ocr_text, page_num)
            if not _has_extracted_code(final_content):
                if not keep_temp:
                    image_path.unlink(missing_ok=True)
                continue
            (output_dir / f"block_{file_idx}.txt").write_text(
                final_content,
                encoding="utf-8",
            )
            file_idx += 1
            processed_count += 1

        if not keep_temp:
            image_path.unlink(missing_ok=True)

    return processed_count


def _page_number_from_image_path(image_path: Path) -> str:
    parts = image_path.stem.split("_")
    if len(parts) > 1 and parts[1]:
        return parts[1]
    return "Unknown"


def _extract_section(content: str, name: str) -> str:
    match = re.search(rf"\[{name}\]\n(.*?)(?=\n\[|$)", content, re.DOTALL)
    if not match:
        return "NONE"
    value = match.group(1).strip()
    return value if value else "NONE"


def _has_extracted_code(content: str) -> bool:
    code_text = _extract_section(content, "CODE")
    return bool(code_text.strip()) and code_text.strip().upper() != "NONE"
