from qa_platform.contract.constants import (
    CATEGORY_ENVIRONMENT_DEPENDENT,
    CATEGORY_INPUT_REQUIRED_OR_INVALID,
    CATEGORY_MISSING_REQUIRED_FILE,
    CATEGORY_MODULE_NOT_FOUND,
    CATEGORY_NAME_ERROR,
    CATEGORY_RUNTIME_ERROR,
    CATEGORY_SYNTAX_ERROR,
    CATEGORY_TIMEOUT,
)
from qa_platform.execution.result_classifier import ResultClassifier


def test_classify_timeout_takes_priority() -> None:
    category, error_type, error_message = ResultClassifier.classify(
        exit_code=None,
        stderr="Traceback says NameError",
        timed_out=True,
    )

    assert category == CATEGORY_TIMEOUT
    assert error_type == "TimeoutError"
    assert error_message == "Execution timed out."


def test_classify_syntax_error_from_traceback() -> None:
    stderr = """  File "normalized.py", line 1
    print(
         ^
SyntaxError: '(' was never closed
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_SYNTAX_ERROR
    assert error_type == "SyntaxError"
    assert error_message == "'(' was never closed"


def test_classify_name_error_from_traceback() -> None:
    stderr = """Traceback (most recent call last):
  File "normalized.py", line 1, in <module>
    print(answer)
          ^^^^^^
NameError: name 'answer' is not defined
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_NAME_ERROR
    assert error_type == "NameError"
    assert error_message == "name 'answer' is not defined"


def test_classify_module_not_found_error_from_traceback() -> None:
    stderr = """Traceback (most recent call last):
  File "normalized.py", line 1, in <module>
    import missing_package
ModuleNotFoundError: No module named 'missing_package'
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_MODULE_NOT_FOUND
    assert error_type == "ModuleNotFoundError"
    assert error_message == "No module named 'missing_package'"


def test_classify_missing_tk_shared_library_as_environment_dependent() -> None:
    stderr = """Traceback (most recent call last):
  File "normalized.py", line 1, in <module>
    import turtle
  File "/usr/local/lib/python3.12/turtle.py", line 107, in <module>
    import tkinter as TK
  File "/usr/local/lib/python3.12/tkinter/__init__.py", line 38, in <module>
    import _tkinter
ImportError: libtk8.6.so: cannot open shared object file: No such file or directory
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_ENVIRONMENT_DEPENDENT
    assert error_type == "ImportError"
    assert "libtk8.6.so" in error_message


def test_classify_missing_tkinter_module_as_environment_dependent() -> None:
    stderr = """Traceback (most recent call last):
  File "normalized.py", line 1, in <module>
    import turtle
  File "/usr/local/lib/python3.12/turtle.py", line 107, in <module>
    import tkinter as TK
  File "/usr/local/lib/python3.12/tkinter/__init__.py", line 38, in <module>
    import _tkinter
ModuleNotFoundError: No module named '_tkinter'
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_ENVIRONMENT_DEPENDENT
    assert error_type == "ModuleNotFoundError"
    assert "_tkinter" in error_message


def test_classify_missing_display_as_environment_dependent() -> None:
    stderr = """Traceback (most recent call last):
  File "normalized.py", line 2, in <module>
    turtle.Screen()
  File "/usr/local/lib/python3.12/turtle.py", line 3680, in Screen
    Turtle._screen = _Screen()
  File "/usr/local/lib/python3.12/turtle.py", line 3696, in __init__
    _Screen._root = self._root = _Root()
  File "/usr/local/lib/python3.12/turtle.py", line 436, in __init__
    TK.Tk.__init__(self)
  File "/usr/local/lib/python3.12/tkinter/__init__.py", line 2345, in __init__
    self.tk = _tkinter.create(screenName, baseName, className, interactive, wantobjects, useTk, sync, use)
_tkinter.TclError: no display name and no $DISPLAY environment variable
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_ENVIRONMENT_DEPENDENT
    assert error_type == "TclError"
    assert "DISPLAY" in error_message


def test_classify_file_not_found_error_from_traceback() -> None:
    stderr = """Traceback (most recent call last):
  File "normalized.py", line 1, in <module>
    open("data.txt")
FileNotFoundError: [Errno 2] No such file or directory: 'data.txt'
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_MISSING_REQUIRED_FILE
    assert error_type == "FileNotFoundError"
    assert error_message == "[Errno 2] No such file or directory: 'data.txt'"


def test_classify_eof_error_from_traceback() -> None:
    stderr = """Traceback (most recent call last):
  File "normalized.py", line 1, in <module>
    input()
EOFError: EOF when reading a line
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_INPUT_REQUIRED_OR_INVALID
    assert error_type == "EOFError"
    assert error_message == "EOF when reading a line"


def test_classify_unknown_nonzero_exit_as_runtime_error() -> None:
    stderr = """Traceback (most recent call last):
  File "normalized.py", line 1, in <module>
    raise ValueError("bad value")
ValueError: bad value
"""

    category, error_type, error_message = ResultClassifier.classify(
        exit_code=1,
        stderr=stderr,
        timed_out=False,
    )

    assert category == CATEGORY_RUNTIME_ERROR
    assert error_type == "ValueError"
    assert error_message == "bad value"
