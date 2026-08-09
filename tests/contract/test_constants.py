from qa_platform.contract import constants


def test_constants_define_parser_sections_and_errors() -> None:
    assert constants.ALLOWED_SECTIONS == {
        "CODE",
        "INPUT",
        "PACKAGES",
        "OUTPUT",
        "META",
        "SETUP",
    }
    assert constants.PARSER_ERROR_TYPES == {
        "missing_section",
        "duplicate_section",
        "content_before_header",
        "empty_code",
        "invalid_meta",
        "unknown_section",
        "read_error",
    }


def test_constants_keep_parse_success_separate_from_result_status() -> None:
    assert constants.RESULT_STATUSES == {"passed", "failed", "skipped"}
    assert "parse_success" not in constants.RESULT_STATUSES


def test_constants_define_all_mvp_failure_categories() -> None:
    assert constants.RESULT_CATEGORIES == {
        "parse_error",
        "syntax_error",
        "name_error",
        "module_not_found",
        "missing_required_file",
        "input_required_or_invalid",
        "timeout",
        "output_mismatch",
        "runtime_error",
        "unsupported_package",
        "environment_dependent",
        "executor_input_error",
        "incomplete_snippet",
        "error_finding",
        "runner_error",
    }
    assert constants.CATEGORY_RUNNER_ERROR == "runner_error"


def test_constants_define_execution_policy_meta_values() -> None:
    assert constants.META_OUTPUT_DETERMINISM_KEY == "output_determinism"
    assert constants.META_OUTPUT_DETERMINISM_VALUES == {
        "deterministic",
        "nondeterministic",
    }
    assert constants.DEFAULT_META_OUTPUT_DETERMINISM == "deterministic"
    assert constants.META_ENUM_VALUES["output_determinism"] == {
        "deterministic",
        "nondeterministic",
    }
    assert constants.META_STDIN_EXHAUSTION_KEY == "stdin_exhaustion"
    assert constants.META_STDIN_EXHAUSTION_VALUES == {"deny", "accept"}
    assert constants.DEFAULT_META_STDIN_EXHAUSTION == "deny"
    assert constants.META_CODE_TYPE_KEY == "code_type"
    assert constants.META_CODE_TYPE_VALUES == {
        "COMPLETE_CODE",
        "INCOMPLETE_SNIPPET",
        "ERROR_FINDING",
    }
    assert constants.DEFAULT_META_CODE_TYPE == "COMPLETE_CODE"


def test_constants_define_execution_mode_meta_values() -> None:
    assert constants.META_EXECUTION_MODE_KEY == "execution_mode"
    assert constants.EXECUTION_MODE_SCRIPT == "script"
    assert constants.EXECUTION_MODE_REPL == "repl"
    assert constants.EXECUTION_MODE_VALUES == {
        "script",
        "repl",
    }
    assert constants.META_ENUM_VALUES["execution_mode"] == {
        "script",
        "repl",
    }
