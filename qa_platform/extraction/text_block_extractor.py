from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Literal

from google.genai import types
from pydantic import BaseModel, Field


class CodeBlock(BaseModel):
    code_type: str = Field(
        description=(
            "MUST be one of: 'ERROR_FINDING', 'INCOMPLETE_SNIPPET', "
            "or 'COMPLETE_CODE'."
        )
    )
    execution_mode: Literal["script", "repl"] = Field(
        description=(
            "Execution context for this block. Use 'repl' when the original "
            "example is an interactive Python prompt or relies on expression "
            "echo. Use 'script' when it should be executed as a normal .py "
            "file."
        ),
    )
    packages: list[str] = Field(
        default_factory=list,
        description=(
            "List external pip packages only (e.g., ['pandas', 'numpy', "
            "'pillow']). Do not list Python standard-library modules or "
            "GUI/environment modules such as turtle or tkinter. Return empty "
            "list [] if none."
        ),
    )
    setup_code: str = Field(
        default="NONE",
        description=(
            "Definitions or initialization required to execute this block, "
            "copied from nearby previous textbook code on the same page or "
            "same conceptual section. Return 'NONE' when the block is "
            "self-contained. Do not include calls that produce stdout unless "
            "the current block itself is that call."
        ),
    )
    code: str = Field(
        description=(
            "Executable Python source code. Remove visible REPL prompt "
            'markers (>>> and ...) from code, but preserve that context by '
            'setting execution_mode="repl". '
            "MUST preserve 100% of original line breaks and indentation. "
            "NEVER merge unrelated lines."
        )
    )
    user_input: str = Field(
        default="NONE",
        description="Input values required for code execution. Return 'NONE' if none.",
    )
    expected_output: str = Field(
        default="NONE",
        description=(
            "Execution result explicitly shown in the text. input() prompt "
            "strings are NEVER outputs. GUI modules such as turtle have no "
            "console output and MUST return 'NONE'."
        ),
    )


class PageExtraction(BaseModel):
    blocks: list[CodeBlock]


TEXT_EXTRACTION_PROMPT = """You are a PRECISE DATA PARSER. Your job is to extract Python code, inputs, and outputs from textbook text.

[INTENT CLASSIFICATION RULES]
Analyze the surrounding Korean text and the code structure to assign ONE of the following to 'code_type':
1. 'ERROR_FINDING': If the text explicitly asks to find or fix an error (e.g., "오류를 찾으시오", "잘못된 부분").
2. 'INCOMPLETE_SNIPPET': STRICTLY for partial fragments that are physically unrunnable (e.g., clearly missing variable assignments, missing imports, or containing placeholders like '...').
3. 'COMPLETE_CODE': For fully independent, runnable code. [CRITICAL] Even if the surrounding text is merely explaining a concept, if the code itself is structurally complete and runnable, it MUST be classified as 'COMPLETE_CODE'.

[CRITICAL RULES]
0. VERIFY TERMINAL CHARACTERS: Before concluding any code block, you MUST perform a final check on the very last character of every line (e.g., '+', '1', ')', '"'). If the source ends with a specific character, the output MUST end with that exact character. NO truncations allowed.
1. ZERO LOGIC REFACTORING (ANTI-HALLUCINATION):
   - Preserve the exact logic, control flows (while, for, if), and operators (=, ==).
   - NEVER optimize, summarize, or alter the code's intended behavior.
2. FORMAT RECOVERY & REPL MERGING ALLOWED:
   - You MAY fix obvious OCR spacing errors (e.g., restoring Pythonic 4-space indentation).
   - Merge physically split but logically continuous REPL (>>>) sessions into a single, clean code block.
3. MULTIPLE BLOCKS ALLOWED: If the page contains multiple distinct code examples, extract EACH one as a separate block in the JSON array. Do not arbitrarily drop examples.
4. ZERO DATA INVENTION:
   - Extract ONLY explicit input values visible in the text.
   - DO NOT invent dummy data.
   - If no explicit input is visible, output "NONE".
5. OUTPUT STRICTNESS: GUI packages (turtle, tkinter) or lack of explicit console text means expected_output is "NONE".
6. EXERCISE AVOIDANCE: Ignore practice problems asking the reader to write code from scratch (e.g., "작성하세요"). Return no blocks for those prompts.
7. PACKAGE POLICY: The packages field contains external pip packages only. Do not list Python standard-library modules. Do not list GUI/environment modules such as turtle or tkinter. Return [] when no third-party pip install is required.

[OUTPUT FIELD REQUIREMENTS]
Each block MUST include code_type, execution_mode, packages, setup_code, code, user_input, and expected_output.

[CONTEXT SETUP RULES]
1. If a block calls a function/class/name defined earlier in the same page or same conceptual section, put only the required definitions or imports in setup_code.
2. Keep code as the exact current visible executable statement to verify.
3. Do not duplicate prior print/call statements in setup_code because they would add stdout that is not part of the current example.
4. If no prior context is required, setup_code must be "NONE".

[COMPLETE_CODE VS INCOMPLETE_SNIPPET RULES]
1. Do not classify a block as INCOMPLETE_SNIPPET only because it calls a symbol defined earlier. If the missing symbol can be supplied from nearby setup_code, classify it as COMPLETE_CODE.
2. Classify as INCOMPLETE_SNIPPET only when the code still cannot become a runnable textbook example after safe setup definitions are supplied.
3. Placeholder blanks, missing argument holes, ellipses used as omitted code, broken indentation fragments, or text that explicitly says an object is assumed to exist are strong INCOMPLETE_SNIPPET signals.
4. For COMPLETE_CODE + setup_code, setup_code must not contain previous statements that produce stdout, consume input, draw GUI output, mutate files, or otherwise perform the prior example.

[EXECUTION MODE CLASSIFICATION]
- Use execution_mode="repl" when the source block is shown as an interactive Python session.
- REPL signals include >>> prompts, ... continuation prompts, or textbook output caused by evaluating an expression without print().
- If the source uses >>> print(value), it is still execution_mode="repl" because the original context is interactive.
- Use execution_mode="script" when the block is a standalone program, lab exercise, file example, or code intended to run as a .py script.
- Do not rewrite expression statements into print(...) only to match output. Preserve the extracted code and classify the execution mode instead.
- When uncertain, prefer "script" unless expected output clearly depends on REPL expression echo.
- Remove visible REPL prompt markers (>>> and ...) from code, but preserve that context by setting execution_mode="repl".

[FEW-SHOT 1: REPL LIST EXPRESSION ECHO]
Text:
">>> temp_list = [1, 2, 3]
>>> temp_list
[1, 2, 3]"
Expected JSON:
{
  "blocks": [
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "repl",
      "packages": [],
      "setup_code": "NONE",
      "code": "temp_list = [1, 2, 3]\\ntemp_list",
      "user_input": "NONE",
      "expected_output": "[1, 2, 3]"
    }
  ]
}

[FEW-SHOT 2: REPL INDEXING AND SLICING EXPRESSION ECHO]
Text:
">>> letters = ['a', 'b', 'c']
>>> letters[0]
'a'
>>> letters[-1]
'c'"
Expected JSON:
{
  "blocks": [
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "repl",
      "packages": [],
      "setup_code": "NONE",
      "code": "letters = ['a', 'b', 'c']\\nletters[0]\\nletters[-1]",
      "user_input": "NONE",
      "expected_output": "'a'\\n'c'"
    }
  ]
}

[FEW-SHOT 3: PRINT INSIDE REPL]
Text:
">>> for i in range(3):
...     print(i)
0
1
2"
Expected JSON:
{
  "blocks": [
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "repl",
      "packages": [],
      "setup_code": "NONE",
      "code": "for i in range(3):\\n    print(i)",
      "user_input": "NONE",
      "expected_output": "0\\n1\\n2"
    }
  ]
}

[FEW-SHOT 4: NORMAL SCRIPT]
Text:
"name = input("name: ")
print("Hello", name)"
Expected JSON:
{
  "blocks": [
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "script",
      "packages": [],
      "setup_code": "NONE",
      "code": "name = input(\\"name: \\")\\nprint(\\"Hello\\", name)",
      "user_input": "NONE",
      "expected_output": "NONE"
    }
  ]
}

[FEW-SHOT 5: INCOMPLETE_SNIPPET]
Text:
"반복문을 사용하여 다각형을 그리는 핵심 로직은 다음과 같습니다. (turtle 객체 t가 생성되었다고 가정)
s = turtle.textinput('', '몇 각형?:')
n = int(s)
for i in range(n):
    t.forward(100)"
Expected JSON:
{
  "blocks": [
    {
      "code_type": "INCOMPLETE_SNIPPET",
      "execution_mode": "script",
      "packages": [],
      "setup_code": "NONE",
      "code": "s = turtle.textinput('', '몇 각형?:')\\nn = int(s)\\nfor i in range(n):\\n    t.forward(100)",
      "user_input": "NONE",
      "expected_output": "NONE"
    }
  ]
}

[FEW-SHOT 6: ERROR_FINDING]
Text:
"다음 코드에서 문법적으로 잘못된 부분을 찾아 올바르게 수정하시오.
print('Hello World)"
Expected JSON:
{
  "blocks": [
    {
      "code_type": "ERROR_FINDING",
      "execution_mode": "script",
      "packages": [],
      "setup_code": "NONE",
      "code": "print('Hello World)",
      "user_input": "NONE",
      "expected_output": "NONE"
    }
  ]
}

[FEW-SHOT 7: PREVIOUS FUNCTION CONTEXT]
Text:
"def greet(name, msg):
    print("안녕 ", name + ', ' + msg)
greet("철수","좋은 아침!")
안녕  철수, 좋은 아침!
만약 우리가 greet() 함수에 2개의 인수를 전달하지 않으면 오류가 발생한다.
>>> greet("영희")
TypeError: greet() missing 1 required positional argument: 'msg'"
Expected JSON:
{
  "blocks": [
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "script",
      "packages": [],
      "setup_code": "NONE",
      "code": "def greet(name, msg):\\n    print(\\"안녕 \\", name + ', ' + msg)\\n\\ngreet(\\"철수\\",\\"좋은 아침!\\")",
      "user_input": "NONE",
      "expected_output": "안녕  철수, 좋은 아침!"
    },
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "repl",
      "packages": [],
      "setup_code": "def greet(name, msg):\\n    print(\\"안녕 \\", name + ', ' + msg)",
      "code": "greet(\\"영희\\")",
      "user_input": "NONE",
      "expected_output": "TypeError: greet() missing 1 required positional argument: 'msg'"
    }
  ]
}

[FEW-SHOT 8: ONE DEFINITION USED BY MULTIPLE FOLLOWING BLOCKS]
Text:
"def calc(x, y, z):
    return x+y+z
물론 calc() 함수는 다음과 같이 호출할 수 있다.
>>> calc(10, 20, 30)
60
>>> calc(x=10, y=20, z=30)
60
>>> calc(y=20, x=10, z=30)
60"
Expected JSON:
{
  "blocks": [
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "script",
      "packages": [],
      "setup_code": "NONE",
      "code": "def calc(x, y, z):\\n    return x+y+z",
      "user_input": "NONE",
      "expected_output": "NONE"
    },
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "repl",
      "packages": [],
      "setup_code": "def calc(x, y, z):\\n    return x+y+z",
      "code": "calc(10, 20, 30)",
      "user_input": "NONE",
      "expected_output": "60"
    },
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "repl",
      "packages": [],
      "setup_code": "def calc(x, y, z):\\n    return x+y+z",
      "code": "calc(x=10, y=20, z=30)",
      "user_input": "NONE",
      "expected_output": "60"
    },
    {
      "code_type": "COMPLETE_CODE",
      "execution_mode": "repl",
      "packages": [],
      "setup_code": "def calc(x, y, z):\\n    return x+y+z",
      "code": "calc(y=20, x=10, z=30)",
      "user_input": "NONE",
      "expected_output": "60"
    }
  ]
}
"""


_PYTHON_KEYWORD_LINE_RE = re.compile(
    r"^\s*(?:def|class|import|for|while|if|elif|else|with|try|except|return)\b",
    re.MULTILINE,
)
_PYTHON_FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+\S+\s+import\b",
    re.MULTILINE,
)
_BUILTIN_CALL_RE = re.compile(
    r"\b(?:print|input|open|range|len|int|float|str|list|dict|set)\s*\("
)
_IDENTIFIER_CALL_LINE_RE = re.compile(
    r"^\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\([^)]*\)\s*$",
    re.MULTILINE,
)
_EXPRESSION_OPERAND_PATTERN = (
    r"(?:"
    r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
    r"|\d+(?:\.\d+)?"
    r'|"[^"\\]*(?:\\.[^"\\]*)*"'
    r"|'[^'\\]*(?:\\.[^'\\]*)*'"
    r")"
)
_EXPRESSION_OPERATOR_LINE_RE = re.compile(
    rf"^\s*{_EXPRESSION_OPERAND_PATTERN}"
    r"(?:\s*(?:\*\*|//|==|!=|<=|>=|[+\-*/%<>])\s*"
    rf"{_EXPRESSION_OPERAND_PATTERN})+"
    r"\s*$",
    re.MULTILINE,
)
_CONTAINER_LITERAL_LINE_RE = re.compile(
    r"^\s*(?:"
    r"\[(?=[^\]\n]*(?:,|:|[\"']|-?\d|\bTrue\b|\bFalse\b|\bNone\b))[^\]\n]*\]"
    r"|"
    r"\{(?=[^}\n]*(?:,|:|[\"']|-?\d|\bTrue\b|\bFalse\b|\bNone\b))[^}\n]*\}"
    r"|"
    r"\((?=[^)\n]*,)[^)\n]*\)"
    r")\s*$",
    re.MULTILINE,
)
_SUBSCRIPT_VALUE_PATTERN = (
    r"(?:"
    r"-?\d+"
    r"|[A-Za-z_]\w*"
    r"|'[^'\\]*(?:\\.[^'\\]*)*'"
    r'|"[^"\\]*(?:\\.[^"\\]*)*"'
    r")"
)
_SLICE_VALUE_PATTERN = (
    rf"(?:{_SUBSCRIPT_VALUE_PATTERN})?\s*:\s*"
    rf"(?:{_SUBSCRIPT_VALUE_PATTERN})?"
    rf"(?:\s*:\s*(?:{_SUBSCRIPT_VALUE_PATTERN})?)?"
)
_SUBSCRIPT_OR_SLICE_LINE_RE = re.compile(
    rf"^\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
    rf"(?:\[\s*(?:{_SUBSCRIPT_VALUE_PATTERN}|{_SLICE_VALUE_PATTERN})\s*\])+"
    r"\s*$",
    re.MULTILINE,
)
_FUTURE_CODE_SIGNAL_RE = re.compile(
    r"\b(?:turtle|tkinter|read_csv|read_table|read_excel|read_text|"
    r"read_bytes|loadtxt|genfromtxt)\b"
)
_ASSIGNMENT_LINE_RE = re.compile(
    r"^\s*[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*=\s*(?!=).+",
    re.MULTILINE,
)
_REPL_PROMPT_RE = re.compile(r"^\s*(?:>>>|\.\.\.)", re.MULTILINE)
_INDENTED_LINE_RE = re.compile(r"^(?: {4,}|\t)\S", re.MULTILINE)
_CODE_PUNCTUATION_RE = re.compile(r"[(){}\[\]=:]")
_KOREAN_CODE_WORD_RE = re.compile(r"(?:코드|실행|출력|입력|결과|예제)")


def should_extract_text_page(page_text: str) -> bool:
    stripped_text = page_text.strip()
    if not stripped_text:
        return False

    strong_signal_patterns = (
        _REPL_PROMPT_RE,
        _PYTHON_KEYWORD_LINE_RE,
        _PYTHON_FROM_IMPORT_RE,
        _BUILTIN_CALL_RE,
        _IDENTIFIER_CALL_LINE_RE,
        _EXPRESSION_OPERATOR_LINE_RE,
        _CONTAINER_LITERAL_LINE_RE,
        _SUBSCRIPT_OR_SLICE_LINE_RE,
        _FUTURE_CODE_SIGNAL_RE,
        _ASSIGNMENT_LINE_RE,
    )
    if any(pattern.search(stripped_text) for pattern in strong_signal_patterns):
        return True

    weak_signal_count = sum(
        bool(pattern.search(stripped_text))
        for pattern in (
            _CODE_PUNCTUATION_RE,
            _INDENTED_LINE_RE,
            _KOREAN_CODE_WORD_RE,
        )
    )
    return weak_signal_count >= 2


def extract_text_blocks_to_files(
    text_path: Path,
    output_dir: Path,
    *,
    start_idx: int,
    client,
) -> int:
    if not text_path.exists():
        raise FileNotFoundError(f"Text file does not exist: {text_path}")

    content = text_path.read_text(encoding="utf-8")
    segments = re.split(r"\[page\s*:\s*(\d+)\]", content)
    file_idx = start_idx
    processed_count = 0

    for i in range(1, len(segments), 2):
        page_num = segments[i]
        page_text = segments[i + 1].strip()
        if len(page_text) < 20:
            continue
        if not should_extract_text_page(page_text):
            continue

        extraction = _extract_page_with_retries(client, page_text)
        for block in extraction.get("blocks", []):
            code_text = block.get("code", "").strip()
            if not code_text or code_text == "NONE":
                continue
            packages = block.get("packages", [])
            package_text = "\n".join(packages) if packages else "NONE"
            input_text = str(block.get("user_input", "NONE") or "NONE").strip()
            output_text = str(
                block.get("expected_output", "NONE") or "NONE"
            ).strip()
            setup_text = str(block.get("setup_code", "NONE") or "NONE").strip()
            execution_mode = str(
                block.get("execution_mode", "script") or "script"
            ).strip()
            final_content = (
                f"[META]\npage : {page_num}\n"
                f"source_kind : text\n"
                f"code_type : {block.get('code_type', 'COMPLETE_CODE')}\n"
                f"execution_mode : {execution_mode}\n\n"
                f"[PACKAGES]\n{package_text}\n\n"
                f"[SETUP]\n{setup_text}\n\n"
                f"[CODE]\n{code_text}\n\n"
                f"[INPUT]\n{input_text}\n\n"
                f"[OUTPUT]\n{output_text}"
            )
            (output_dir / f"block_{file_idx}.txt").write_text(
                final_content,
                encoding="utf-8",
            )
            file_idx += 1
            processed_count += 1

    return processed_count


def _extract_page_with_retries(client, page_text: str) -> dict:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=[
                    TEXT_EXTRACTION_PROMPT,
                    f"[TEXT TO ANALYZE]\n{page_text}",
                ],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=PageExtraction,
                ),
            )
            return json.loads(response.text)
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            return {"blocks": []}
