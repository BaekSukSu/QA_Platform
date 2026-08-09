import json

from qa_platform.contract.models import (
    BlockSpec,
    ExecutionResult,
    PackageSpec,
    ParseError,
    ParseResult,
)
from qa_platform.shared.json_io import (
    read_json,
    write_json,
)


def test_package_spec_round_trips_to_json_dict() -> None:
    package = PackageSpec(name="numpy", specifier="==1.26.4", raw="numpy==1.26.4")

    data = package.to_dict()

    assert data == {
        "name": "numpy",
        "specifier": "==1.26.4",
        "raw": "numpy==1.26.4",
    }
    assert PackageSpec.from_dict(data) == package


def test_parse_error_uses_type_key_in_json_dict() -> None:
    error = ParseError(
        error_type="missing_section",
        message="Missing [CODE] section.",
        line=3,
    )

    data = error.to_dict()

    assert data == {
        "type": "missing_section",
        "message": "Missing [CODE] section.",
        "line": 3,
    }
    assert ParseError.from_dict(data) == error


def test_parse_result_success_round_trips_with_block_spec() -> None:
    spec = BlockSpec(
        code="print('안녕')\n",
        stdin="",
        packages=[PackageSpec(name="numpy", specifier=">=1.26", raw="numpy>=1.26")],
        expected_output="안녕\n",
        meta={"input_source": "textbook"},
    )
    result = ParseResult(parse_success=True, block_id="block_001", spec=spec)

    data = result.to_dict()

    assert data == {
        "parse_success": True,
        "block_id": "block_001",
        "spec": {
            "code": "print('안녕')\n",
            "stdin": "",
            "packages": [
                {
                    "name": "numpy",
                    "specifier": ">=1.26",
                    "raw": "numpy>=1.26",
                }
            ],
            "expected_output": "안녕\n",
            "meta": {"input_source": "textbook"},
            "setup_code": "",
        },
    }
    assert ParseResult.from_dict(data) == result


def test_block_spec_round_trips_setup_code() -> None:
    spec = BlockSpec(
        setup_code="def greet(name, msg):\n    print(name, msg)\n",
        code='greet("영희")\n',
        stdin="",
        expected_output=(
            "TypeError: greet() missing 1 required positional argument: "
            "'msg'\n"
        ),
        meta={"execution_mode": "repl"},
    )

    restored = BlockSpec.from_dict(spec.to_dict())

    assert restored == spec
    assert restored.to_dict()["setup_code"] == (
        "def greet(name, msg):\n    print(name, msg)\n"
    )


def test_parse_result_failure_round_trips_with_error() -> None:
    error = ParseError(error_type="empty_code", message="[CODE] is empty.")
    result = ParseResult(parse_success=False, block_id="block_002", error=error)

    data = result.to_dict()

    assert data == {
        "parse_success": False,
        "block_id": "block_002",
        "error": {
            "type": "empty_code",
            "message": "[CODE] is empty.",
            "line": None,
        },
    }
    assert ParseResult.from_dict(data) == result


def test_execution_result_serializes_result_json_shape() -> None:
    result = ExecutionResult(
        block_id="block_001",
        status="passed",
        category=None,
        exit_code=0,
        duration_ms=42,
        stdout="안녕\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error_type=None,
        error_message=None,
        expected_output="안녕\n",
        output_matched=True,
        meta={"output_source": "generated_sample"},
    )

    assert result.to_dict() == {
        "block_id": "block_001",
        "status": "passed",
        "category": None,
        "exit_code": 0,
        "duration_ms": 42,
        "stdout": "안녕\n",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "error_type": None,
        "error_message": None,
        "expected_output": "안녕\n",
        "output_matched": True,
        "meta": {"output_source": "generated_sample"},
    }


def test_execution_result_round_trips_from_json_dict() -> None:
    data = {
        "block_id": "block_002",
        "status": "failed",
        "category": "name_error",
        "exit_code": 1,
        "duration_ms": 87,
        "stdout": "",
        "stderr": "NameError: name 'missing' is not defined\n",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "error_type": "NameError",
        "error_message": "name 'missing' is not defined",
        "expected_output": "hello\n",
        "output_matched": None,
        "meta": {"page": "12"},
    }

    result = ExecutionResult.from_dict(data)

    assert result.to_dict() == data


def test_write_json_uses_utf8_pretty_json(tmp_path) -> None:
    output_path = tmp_path / "block.json"

    write_json(output_path, {"message": "안녕", "items": [1, 2]})

    raw_text = output_path.read_text(encoding="utf-8")
    assert raw_text == '{\n  "message": "안녕",\n  "items": [\n    1,\n    2\n  ]\n}\n'
    assert json.loads(raw_text) == {"message": "안녕", "items": [1, 2]}
    assert read_json(output_path) == {"message": "안녕", "items": [1, 2]}
