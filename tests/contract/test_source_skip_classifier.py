from qa_platform.contract.models import PackageSpec
from qa_platform.contract.source_skip_classifier import (
    META_ENVIRONMENT_MODULES_KEY,
    META_MISSING_REQUIRED_FILES_KEY,
    META_RUN_SKIP_REASON_KEY,
    RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT,
    RUN_SKIP_REASON_MISSING_REQUIRED_FILE,
    detect_source_skip,
    source_skip_metadata,
)


def test_detect_source_skip_finds_external_file_read() -> None:
    decision = detect_source_skip(
        setup_code="",
        code="print(open('weather.csv').read())\n",
        stdin="",
        packages=[],
    )
    assert decision is not None
    assert decision.reason == RUN_SKIP_REASON_MISSING_REQUIRED_FILE
    assert decision.missing_required_files == ("weather.csv",)
    assert decision.environment_modules == ()


def test_detect_source_skip_finds_input_filename() -> None:
    decision = detect_source_skip(
        setup_code="",
        code="filename = input('파일명: ')\nprint(open(filename).read())\n",
        stdin="input.txt\n",
        packages=[],
    )
    assert decision is not None
    assert decision.reason == RUN_SKIP_REASON_MISSING_REQUIRED_FILE
    assert decision.missing_required_files == ("input.txt",)


def test_detect_source_skip_finds_environment_module_import() -> None:
    decision = detect_source_skip(
        setup_code="",
        code="import turtle\nturtle.forward(100)\n",
        stdin="",
        packages=[],
    )
    assert decision is not None
    assert decision.reason == RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT
    assert decision.environment_modules == ("turtle",)
    assert decision.missing_required_files == ()


def test_detect_source_skip_finds_declared_environment_package() -> None:
    decision = detect_source_skip(
        setup_code="",
        code="print('ready')\n",
        stdin="",
        packages=[PackageSpec(name="tkinter", specifier="", raw="tkinter")],
    )
    assert decision is not None
    assert decision.reason == RUN_SKIP_REASON_ENVIRONMENT_DEPENDENT
    assert decision.environment_modules == ("tkinter",)


def test_detect_source_skip_ignores_self_created_file() -> None:
    decision = detect_source_skip(
        setup_code="",
        code=(
            "with open('created.txt', 'w') as file:\n"
            "    file.write('hello')\n"
            "print(open('created.txt').read())\n"
        ),
        stdin="",
        packages=[],
    )
    assert decision is None


def test_source_skip_metadata_renders_stable_values() -> None:
    decision = detect_source_skip(
        setup_code="",
        code="import turtle\nprint(open('data.csv').read())\n",
        stdin="",
        packages=[],
    )
    assert decision is not None
    assert source_skip_metadata(decision) == {
        META_RUN_SKIP_REASON_KEY: RUN_SKIP_REASON_MISSING_REQUIRED_FILE,
        META_MISSING_REQUIRED_FILES_KEY: "data.csv",
    }
