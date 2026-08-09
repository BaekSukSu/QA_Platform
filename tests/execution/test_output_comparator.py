from qa_platform.execution.output_comparator import OutputComparator


def test_compare_returns_none_when_expected_output_is_empty() -> None:
    assert OutputComparator.compare("", "anything\n") is None


def test_compare_matches_when_only_final_newline_differs() -> None:
    assert OutputComparator.compare("hello\n", "hello") is True
    assert OutputComparator.compare("hello", "hello\n") is True


def test_compare_matches_when_only_line_trailing_spaces_differ() -> None:
    expected_output = "first line\nsecond line\n"
    stdout = "first line   \nsecond line\t \n"

    assert OutputComparator.compare(expected_output, stdout) is True


def test_compare_accepts_pdf_soft_wrap_after_space() -> None:
    expected_output = (
        "반가워요 반가워요 반가워요 반가워요 반가워요 "
        "반가워요 반가워요 반가워요 반가워요 반가워요 \n"
        "반가워요 반가워요 반가워요 반가워요 반가워요 "
        "반가워요 반가워요 반가워요 반가워요 반가워요\n"
    )
    stdout = (
        "반가워요 반가워요 반가워요 반가워요 반가워요 "
        "반가워요 반가워요 반가워요 반가워요 반가워요 "
        "반가워요 반가워요 반가워요 반가워요 반가워요 "
        "반가워요 반가워요 반가워요 반가워요 반가워요 \n"
    )

    assert OutputComparator.compare(expected_output, stdout) is True


def test_compare_preserves_blank_lines_when_normalizing_soft_wraps() -> None:
    assert OutputComparator.compare("\n", "") is False
    assert OutputComparator.compare("a\n\n", "a\n") is False


def test_compare_preserves_carriage_return_blank_lines_when_normalizing_soft_wraps() -> None:
    assert OutputComparator.compare("\r", "") is False
    assert OutputComparator.compare("a\r\r", "a\r") is False


def test_compare_preserves_all_splitlines_blank_lines_when_normalizing_soft_wraps() -> None:
    assert OutputComparator.compare("a\v\v", "a\v") is False
    assert OutputComparator.compare("a\f\f", "a\f") is False
    assert OutputComparator.compare("a\u2028\u2028", "a\u2028") is False


def test_compare_preserves_whitespace_only_lines_when_normalizing_soft_wraps() -> None:
    assert OutputComparator.compare(" hello", " \nhello") is False


def test_compare_preserves_leading_whitespace_without_whole_output_strip() -> None:
    assert OutputComparator.compare("hello", " hello") is False
    assert OutputComparator.compare("hello", "hello ") is True
    assert OutputComparator.compare("\nhello", "hello") is False


def test_compare_ignores_input_prompt_missing_stdin_echo() -> None:
    assert (
        OutputComparator.compare(
            "21\n",
            "몇 번째 항: 21\n",
            code='i = int(input("몇 번째 항: "))\nprint(21)\n',
            stdin="9\n",
        )
        is True
    )


def test_compare_strips_prompt_and_echo_from_expected_transcript() -> None:
    assert (
        OutputComparator.compare(
            "몇 번째 항: 9\n21\n",
            "몇 번째 항: 21\n",
            code='i = int(input("몇 번째 항: "))\nprint(21)\n',
            stdin="9\n",
        )
        is True
    )


def test_compare_strips_input_prompt_when_output_shares_same_line() -> None:
    assert (
        OutputComparator.compare(
            (
                "홍길동 씨, 안녕하세요?\n"
                "파이썬에 오신 것을 환영합니다.\n"
            ),
            (
                "이름을 입력하시오: 홍길동 씨, 안녕하세요?\n"
                "파이썬에 오신 것을 환영합니다.\n"
            ),
            code=(
                'name = input("이름을 입력하시오: ")\n'
                'print(name, "씨, 안녕하세요?")\n'
                'print("파이썬에 오신 것을 환영합니다.")\n'
            ),
            stdin="홍길동\n",
        )
        is True
    )


def test_compare_preserves_same_line_output_equal_to_stdin_after_prompt() -> None:
    assert (
        OutputComparator.compare(
            "Alice\n",
            "Name: Alice\n",
            code='name = input("Name: ")\nprint(name)\n',
            stdin="Alice\n",
        )
        is True
    )


def test_compare_does_not_strip_prompt_text_inside_real_output() -> None:
    assert (
        OutputComparator.compare(
            "prompt was Label: \n",
            "prompt was \n",
            code='value = input("Label: ")\nprint("prompt was Label: ")\n',
            stdin="x\n",
        )
        is False
    )


def test_compare_does_not_strip_later_real_output_starting_with_prompt() -> None:
    assert (
        OutputComparator.compare(
            "first\ndone\n",
            "Label: first\nLabel: done\n",
            code='value = input("Label: ")\nprint("first")\nprint("Label: done")\n',
            stdin="x\n",
        )
        is False
    )


def test_compare_preserves_prompt_prefixed_output_before_input_prompt() -> None:
    assert (
        OutputComparator.compare(
            "Label: first\ndone\n",
            "Label: first\nLabel: done\n",
            code='print("Label: first")\nvalue = input("Label: ")\nprint("done")\n',
            stdin="x\n",
        )
        is True
    )


def test_compare_strips_prompt_after_known_one_line_variable_print() -> None:
    assert (
        OutputComparator.compare(
            "hello\nAlice\n",
            "hello\nName: Alice\n",
            code='message = "hello"\nprint(message)\nname = input("Name: ")\nprint(name)\n',
            stdin="Alice\n",
        )
        is True
    )


def test_compare_strips_prompt_after_unexecuted_function_body_print() -> None:
    assert (
        OutputComparator.compare(
            "Alice\n",
            "Name: Alice\n",
            code='def greet():\n    print("hi")\nname = input("Name: ")\nprint(name)\n',
            stdin="Alice\n",
        )
        is True
    )


def test_compare_does_not_strip_prompt_from_unexecuted_function_body_input() -> None:
    assert (
        OutputComparator.compare(
            "real\n",
            "Label: real\n",
            code='def ask():\n    input("Label: ")\nprint("Label: real")\n',
            stdin="",
        )
        is False
    )


def test_compare_strips_consecutive_input_prompts_before_output() -> None:
    expected_output = (
        "===========================================\n"
        "오늘 서울 에서 야구 경기가 열렸습니다.\n"
        "삼성 과 LG 은 치열한 공방전을 펼쳤습니다.\n"
        "홍길동 이 맹활약을 하였습니다.\n"
        "결국 삼성 가 LG 를  8:7 로 이겼습니다.\n"
        "===========================================\n"
    )
    stdout = (
        "경기장은 어디입니까?이긴팀은 어디입니까진팀은 어디입니까?"
        "우수선수는 누구입니까?스코어는 몇대몇입니까?\n"
        "===========================================\n"
        "오늘 서울 에서 야구 경기가 열렸습니다.\n"
        "삼성 과 LG 은 치열한 공방전을 펼쳤습니다.\n"
        "홍길동 이 맹활약을 하였습니다.\n"
        "결국 삼성 가 LG 를  8:7 로 이겼습니다.\n"
        "===========================================\n"
    )

    assert (
        OutputComparator.compare(
            expected_output,
            stdout,
            code=(
                'stadium = input("경기장은 어디입니까?")\n'
                'winner = input("이긴팀은 어디입니까")\n'
                'loser = input("진팀은 어디입니까?")\n'
                'vip = input("우수선수는 누구입니까?")\n'
                'score = input("스코어는 몇대몇입니까?")\n'
                'print("")\n'
                'print("===========================================")\n'
                'print("오늘", stadium, "에서 야구 경기가 열렸습니다.")\n'
                'print(winner, "과", loser, "은 치열한 공방전을 펼쳤습니다.")\n'
                'print(vip, "이 맹활약을 하였습니다.")\n'
                'print("결국", winner, "가", loser, "를 ", score, "로 이겼습니다.")\n'
                'print("===========================================")\n'
            ),
            stdin="서울\n삼성\nLG\n홍길동\n8:7\n",
        )
        is True
    )


def test_compare_accepts_textbook_simplified_type_display() -> None:
    assert (
        OutputComparator.compare(
            "float\n",
            "<class 'float'>\n",
            code="weight = 78.2\ntype(weight)\n",
            stdin="",
        )
        is True
    )
    assert (
        OutputComparator.compare(
            "int\n",
            "<class 'int'>\n",
            code="salary = 250\ntype(salary)\n",
            stdin="",
        )
        is True
    )
    assert (
        OutputComparator.compare(
            "str\n",
            "<class 'str'>\n",
            code='address = "서울시 종로구 1번지"\ntype(address)\n',
            stdin="",
        )
        is True
    )
    assert (
        OutputComparator.compare(
            "bool\n",
            "<class 'bool'>\n",
            code="b = True\ntype(b)\n",
            stdin="",
        )
        is True
    )


def test_compare_accepts_textbook_string_echo_without_repr_quotes() -> None:
    assert (
        OutputComparator.compare(
            "2356\n",
            "'2356'\n",
            code="'23' + '56'\n",
            stdin="",
        )
        is True
    )


def test_compare_accepts_repl_display_after_unexecuted_function_body_print() -> None:
    assert (
        OutputComparator.compare(
            "float\n",
            "<class 'float'>\n",
            code='def greet():\n    print("hi")\ntype(1.0)\n',
            stdin="",
        )
        is True
    )


def test_compare_does_not_simplify_printed_type_line_when_expression_follows() -> None:
    assert (
        OutputComparator.compare(
            "float\n1\n",
            "<class 'float'>\n1\n",
            code="print(type(1.0))\n1\n",
            stdin="",
        )
        is False
    )


def test_compare_does_not_simplify_printed_quoted_string_when_expression_follows() -> None:
    assert (
        OutputComparator.compare(
            "2356\n1\n",
            "'2356'\n1\n",
            code="print('2356')\n1\n",
            stdin="",
        )
        is False
    )


def test_compare_does_not_simplify_after_side_effecting_assignment() -> None:
    assert (
        OutputComparator.compare(
            "float\n1\n",
            "<class 'float'>\n1\n",
            code="x = print(type(1.0))\n1\n",
            stdin="",
        )
        is False
    )


def test_compare_does_not_simplify_after_expression_with_unknown_display_output() -> None:
    assert (
        OutputComparator.compare(
            "float\n1\n",
            "<class 'float'>\n1\n",
            code="def f():\n    return None\nf()\nprint(type(1.0))\n1\n",
            stdin="",
        )
        is False
    )


def test_compare_does_not_simplify_side_effecting_supported_expression() -> None:
    assert (
        OutputComparator.compare(
            "float\n<class 'NoneType'>\n",
            "<class 'float'>\n<class 'NoneType'>\n",
            code="type(print(\"<class 'float'>\"))\n",
            stdin="",
        )
        is False
    )


def test_compare_does_not_simplify_after_dynamic_multiline_print() -> None:
    assert (
        OutputComparator.compare(
            "hello\nfloat\n<class 'float'>\n",
            "hello\n<class 'float'>\n<class 'float'>\n",
            code='s = "hello\\n<class \'float\'>"\nprint(s)\ntype(1.0)\n',
            stdin="",
        )
        is False
    )


def test_compare_accepts_pandas_series_footer_when_package_declared() -> None:
    assert (
        OutputComparator.compare(
            "0    10\n1    20\n2    30\n",
            "0    10\n1    20\n2    30\nName: points, dtype: int64\n",
            packages=("pandas",),
        )
        is True
    )


def test_compare_accepts_pandas_dataframe_alignment_when_package_declared() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n1 Bob 88\n",
            "    name  score\n0  Alice     95\n1    Bob     88\n",
            packages=("pandas",),
        )
        is True
    )


def test_compare_accepts_pandas_dataframe_alignment_when_imported_in_code() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n1 Bob 88\n",
            "    name  score\n0  Alice     95\n1    Bob     88\n",
            code="import pandas as pd\ndf = pd.DataFrame()\ndf\n",
        )
        is True
    )


def test_compare_keeps_pandas_row_mismatch_failed() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n1 Bob 88\n",
            "    name  score\n0  Alice     95\n2    Bob     88\n",
            packages=("pandas",),
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_without_pandas_display_signal() -> None:
    assert (
        OutputComparator.compare(
            "value one\n",
            "value   one\n",
            packages=("pandas",),
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_without_pandas_usage() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n1 Bob 88\n",
            "    name  score\n0  Alice     95\n1    Bob     88\n",
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_to_indented_plain_text() -> None:
    assert (
        OutputComparator.compare(
            "  header\nvalue\n",
            "header\nvalue\n",
            code="import pandas as pd\n",
        )
        is False
    )


def test_compare_detects_pandas_package_case_insensitively() -> None:
    assert (
        OutputComparator.compare(
            "0    10\n",
            "0    10\nName: points, dtype: int64\n",
            packages=("Pandas",),
        )
        is True
    )


def test_compare_detects_pandas_requirement_string() -> None:
    assert (
        OutputComparator.compare(
            "0    10\n",
            "0    10\nName: points, dtype: int64\n",
            packages=("pandas>=2",),
        )
        is True
    )


def test_compare_does_not_apply_pandas_alignment_to_manual_printed_table() -> None:
    assert (
        OutputComparator.compare(
            "name score\nAlice 95\nBob 88\n",
            "name  score\nAlice   95\nBob     88\n",
            code=(
                "import pandas as pd\n"
                "print('name  score')\n"
                "print('Alice   95')\n"
                "print('Bob     88')\n"
            ),
        )
        is False
    )


def test_compare_accepts_pandas_dataframe_alignment_for_printed_dataframe() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n1 Bob 88\n",
            "    name  score\n0  Alice     95\n1    Bob     88\n",
            code="import pandas as pd\ndf = pd.DataFrame()\nprint(df)\n",
        )
        is True
    )


def test_compare_accepts_unnamed_pandas_series_footer() -> None:
    assert (
        OutputComparator.compare(
            "0    10\n1    20\n",
            "0    10\n1    20\ndtype: int64\n",
            packages=("pandas",),
        )
        is True
    )


def test_compare_does_not_apply_series_footer_to_plain_text_without_pandas_source() -> None:
    assert (
        OutputComparator.compare(
            "value one\ndtype: int64\n",
            "value   one\ndtype: int64\n",
            code="import pandas as pd\n",
        )
        is False
    )


def test_compare_accepts_one_row_printed_pandas_dataframe_alignment() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n",
            "    name  score\n0  Alice     95\n",
            code="import pandas as pd\ndf = pd.DataFrame()\nprint(df)\n",
        )
        is True
    )


def test_compare_accepts_one_row_repl_pandas_dataframe_alignment() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n",
            "    name  score\n0  Alice     95\n",
            code="import pandas as pd\ndf = pd.DataFrame()\ndf\n",
        )
        is True
    )


def test_compare_accepts_series_alignment_for_static_pandas_aggregation_spec() -> None:
    assert (
        OutputComparator.compare(
            "score 95\ndtype: int64\n",
            "score    95\ndtype: int64\n",
            code=(
                "import pandas as pd\n"
                "df = pd.DataFrame({'score': [95]})\n"
                "print(df.agg({'score': 'sum'}))\n"
            ),
        )
        is True
    )


def test_compare_does_not_apply_pandas_alignment_to_mixed_plain_print_and_dataframe() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   name  score\n0 Alice 95\n",
            "value   one\n    name  score\n0  Alice     95\n",
            code=(
                "import pandas as pd\n"
                "df = pd.DataFrame()\n"
                "print('value   one')\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_still_accepts_dataframe_alignment_with_assignments_only_before_output() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n",
            "    name  score\n0  Alice     95\n",
            code=(
                "import pandas as pd\n"
                "df = pd.DataFrame()\n"
                "df['score'] = [95]\n"
                "print(df)\n"
            ),
        )
        is True
    )


def test_compare_still_accepts_repl_dataframe_expression_after_assignments() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n",
            "    name  score\n0  Alice     95\n",
            code=(
                "import pandas as pd\n"
                "df = pd.DataFrame()\n"
                "df['score'] = [95]\n"
                "df\n"
            ),
        )
        is True
    )


def test_compare_still_accepts_dataframe_alignment_after_file_setup_blocks() -> None:
    assert (
        OutputComparator.compare(
            "   name  score\n0 Alice 95\n",
            "    name  score\n0  Alice     95\n",
            code=(
                "with open('scores.csv', 'w') as f:\n"
                "    f.write('name,score\\n')\n"
                "import pandas as pd\n"
                "df = pd.DataFrame()\n"
                "print(df)\n"
            ),
        )
        is True
    )


def test_compare_does_not_apply_pandas_alignment_after_print_assignment() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   name  score\n0 Alice 95\n",
            "value   one\n    name  score\n0  Alice     95\n",
            code=(
                "import pandas as pd\n"
                "df = pd.DataFrame()\n"
                "x = print('value   one')\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_after_unknown_assignment_call() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   name  score\n0 Alice 95\n",
            "value   one\n    name  score\n0  Alice     95\n",
            code=(
                "import pandas as pd\n"
                "def noisy():\n"
                "    print('value   one')\n"
                "df = pd.DataFrame()\n"
                "x = noisy()\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_after_nested_print_in_pandas_assignment() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0    95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "df = pd.DataFrame(print('value   one') or {'score': [95]})\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_after_unknown_call_in_pandas_constructor() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0    95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "def noisy():\n"
                "    print('value   one')\n"
                "    return {'score': [95]}\n"
                "df = pd.DataFrame(noisy())\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_after_print_inside_file_write() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0    95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "with open('tmp.csv', 'w') as f:\n"
                "    f.write(print('value   one') or 'x')\n"
                "df = pd.DataFrame({'score': [95]})\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_to_direct_constructor_with_unknown_call() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0    95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "def noisy():\n"
                "    print('value   one')\n"
                "    return {'score': [95]}\n"
                "print(pd.DataFrame(noisy()))\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_to_repl_constructor_with_unknown_call() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0    95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "def noisy():\n"
                "    print('value   one')\n"
                "    return {'score': [95]}\n"
                "pd.DataFrame(noisy())\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_series_footer_to_string_value_whitespace_mismatch() -> None:
    assert (
        OutputComparator.compare(
            "0    New York\n",
            "0    New    York\ndtype: object\n",
            packages=("pandas",),
        )
        is False
    )


def test_compare_does_not_apply_dataframe_alignment_to_string_value_whitespace_mismatch() -> None:
    assert (
        OutputComparator.compare(
            "       city  count\n0  New York      1\n",
            "       city  count\n0  New    York      1\n",
            code="import pandas as pd\ndf = pd.DataFrame()\nprint(df)\n",
        )
        is False
    )


def test_compare_does_not_apply_dataframe_alignment_to_index_free_string_value_whitespace_mismatch() -> None:
    assert (
        OutputComparator.compare(
            "   city  count\nNew York      1\n",
            "   city  count\nNew    York      1\n",
            code="import pandas as pd\ndf = pd.DataFrame()\nprint(df.to_string(index=False))\n",
        )
        is False
    )


def test_compare_does_not_apply_dataframe_alignment_to_index_free_label_whitespace_mismatch() -> None:
    assert (
        OutputComparator.compare(
            "   region  count\nLA County      1\n",
            "   region  count\nLA    County      1\n",
            code="import pandas as pd\ndf = pd.DataFrame()\nprint(df.to_string(index=False))\n",
        )
        is False
    )


def test_compare_does_not_apply_dataframe_alignment_to_index_free_lowercase_string_whitespace_mismatch() -> None:
    assert (
        OutputComparator.compare(
            "   city  count\nnew york      1\n",
            "   city  count\nnew    york      1\n",
            code="import pandas as pd\ndf = pd.DataFrame()\nprint(df.to_string(index=False))\n",
        )
        is False
    )


def test_compare_does_not_apply_pandas_alignment_when_apply_callable_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0    95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "df = pd.DataFrame({'score': [95]})\n"
                "def noisy(row):\n"
                "    print('value   one')\n"
                "    return row\n"
                "df = df.apply(noisy, axis=1)\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_series_footer_when_apply_builtin_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n0 None\ndtype: object\n",
            "value   one\n0    None\ndtype: object\n",
            code=(
                "import pandas as pd\n"
                "s = pd.Series(['value   one'])\n"
                "print(s.apply(print))\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_series_footer_when_apply_print_alias_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n0 None\ndtype: object\n",
            "value   one\n0    None\ndtype: object\n",
            code=(
                "import pandas as pd\n"
                "noisy = print\n"
                "s = pd.Series(['value   one'])\n"
                "print(s.apply(noisy))\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_series_footer_when_apply_local_function_alias_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n0 None\ndtype: object\n",
            "value   one\n0    None\ndtype: object\n",
            code=(
                "import pandas as pd\n"
                "def noisy(value):\n"
                "    print('value   one')\n"
                "    return None\n"
                "alias = noisy\n"
                "s = pd.Series(['value   one'])\n"
                "print(s.apply(alias))\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_series_footer_when_apply_tuple_unpacked_function_alias_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n0 None\ndtype: object\n",
            "value   one\n0    None\ndtype: object\n",
            code=(
                "import pandas as pd\n"
                "def noisy(value):\n"
                "    print('value   one')\n"
                "    return None\n"
                "alias, other = noisy, None\n"
                "s = pd.Series(['value   one'])\n"
                "print(s.apply(alias))\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_series_footer_when_apply_opaque_function_alias_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n0 None\ndtype: object\n",
            "value   one\n0    None\ndtype: object\n",
            code=(
                "import pandas as pd\n"
                "def noisy(value):\n"
                "    print('value   one')\n"
                "    return None\n"
                "alias = [noisy][0]\n"
                "s = pd.Series(['value   one'])\n"
                "print(s.apply(alias))\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_dataframe_alignment_when_rename_callable_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   None\n0 95\n",
            "value   one\n   None\n0    95\n",
            code=(
                "import pandas as pd\n"
                "def noisy(column):\n"
                "    print('value   one')\n"
                "    return None\n"
                "df = pd.DataFrame({'score': [95]})\n"
                "alias = [noisy][0]\n"
                "print(df.rename(columns=alias))\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_dataframe_alignment_when_reader_converter_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0 95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "def noisy(value):\n"
                "    print('value   one')\n"
                "    return value\n"
                "alias = [noisy][0]\n"
                "df = pd.read_csv('scores.csv', converters={'score': alias})\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_dataframe_alignment_when_reader_usecols_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0 95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "def noisy(column):\n"
                "    print('value   one')\n"
                "    return True\n"
                "alias = [noisy][0]\n"
                "df = pd.read_csv('scores.csv', usecols=alias)\n"
                "print(df)\n"
            ),
        )
        is False
    )


def test_compare_does_not_apply_dataframe_alignment_when_to_string_formatter_prints() -> None:
    assert (
        OutputComparator.compare(
            "value one\n   score\n0 95\n",
            "value   one\n   score\n0    95\n",
            code=(
                "import pandas as pd\n"
                "def noisy(value):\n"
                "    print('value   one')\n"
                "    return value\n"
                "alias = [noisy][0]\n"
                "df = pd.DataFrame({'score': [95]})\n"
                "print(df.to_string(formatters={'score': alias}))\n"
            ),
        )
        is False
    )


def test_compare_returns_false_for_different_content() -> None:
    assert OutputComparator.compare("hello\n", "goodbye\n") is False
