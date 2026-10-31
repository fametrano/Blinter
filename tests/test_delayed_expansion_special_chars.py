"""Tests for delayed expansion detection with special characters in variable names.

This test module verifies that the linter correctly detects delayed expansion
variables that contain special characters like @, -, #, $, etc. which are commonly
used in batch script variable naming conventions.
"""

import pathlib

import pytest

from blinter import lint_batch_file
from blinter.parsing.structure import (
    _delayed_expansion_active_at_line,
    _flow_block_closers,
    _flow_closed_lines,
    _flow_label_line,
    _flow_labels,
    _flow_opens_block,
    _flow_ops,
)


def test_delayed_expand_at_symbol(tmp_path: pathlib.Path) -> None:
    """Test detection of delayed expansion variables with @ symbol."""
    script = tmp_path / "test_at.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @DEBUG_MODE=ON\n"
        "ECHO !@DEBUG_MODE!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 (Unnecessary ENABLEDELAYEDEXPANSION) error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should not flag P004 when using !@variable!"


def test_delayed_expand_hyphen(tmp_path: pathlib.Path) -> None:
    """Test detection of delayed expansion variables with hyphen."""
    script = tmp_path / "test_hyphen.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @CRLF-1=test\n"
        "ECHO !@CRLF-%~1!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should not flag P004 when using !@CRLF-%~1!"


def test_delayed_expand_hash(tmp_path: pathlib.Path) -> None:
    """Test detection of delayed expansion variables with # symbol."""
    script = tmp_path / "test_hash.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @SCRIPT_BEG#=12345\n"
        "ECHO !@SCRIPT_BEG#!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should not flag P004 when using !@SCRIPT_BEG#!"


def test_delayed_expand_dollar(tmp_path: pathlib.Path) -> None:
    """Test detection of delayed expansion variables with $ symbol."""
    script = tmp_path / "test_dollar.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET $CODEPAGE=437\n"
        "ECHO !$CODEPAGE!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should not flag P004 when using !$CODEPAGE!"


def test_no_delayed_expand_needed(tmp_path: pathlib.Path) -> None:
    """Test that P004 is still raised when no delayed expansion variables are used."""
    script = tmp_path / "test_no_delayed.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET MYVAR=test\n"
        "ECHO %MYVAR%\n"  # Using % syntax, not ! syntax
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # SHOULD have P004 error because delayed expansion is not actually used
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert (
        len(p004_issues) == 1
    ), "Should flag P004 when ENABLEDELAYEDEXPANSION is unused"


def test_p008_with_special_chars(tmp_path: pathlib.Path) -> None:
    """Test P008 detection of delayed expansion without ENABLEDELAYEDEXPANSION."""
    script = tmp_path / "test_p008.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL\n"  # No ENABLEDELAYEDEXPANSION
        "SET @DEBUG_MODE=ON\n"
        "ECHO !@DEBUG_MODE!\n"  # Using delayed expansion without enabling it
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # SHOULD have P008 error
    p008_issues = [issue for issue in issues if issue.rule.code == "P008"]
    assert (
        len(p008_issues) >= 1
    ), "Should flag P008 when using !@variable! without ENABLEDELAYEDEXPANSION"


def test_comment_is_not_delayed_expansion(tmp_path: pathlib.Path) -> None:
    """A !VAR! in a comment gives no P008, W022 or E006, with no SETLOCAL at all.

    cmd.exe still expands %VAR% in a comment, so E006 reports %NOPE% there.
    """
    script = tmp_path / "test_comment.bat"
    script.write_text(
        '@echo off\nREM A "!VAR!" in prose.\n:: A "!VAR!" in prose.\n'
        "REM A %NOPE% in prose.\n:: A %NOPE% in prose.\nexit /b 0\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    codes = {issue.rule.code for issue in issues}
    assert not codes & {"P008", "W022"}
    assert [i.line_number for i in issues if i.rule.code == "E006"] == [4, 5]


def test_setaccounts_regression(tmp_path: pathlib.Path) -> None:
    """Test the specific case from SetAccounts.BAT that caused the bug report."""
    script = tmp_path / "test_setaccounts.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @DEBUG_MODE=ON\n"
        "SET @CRLF-TEST=value\n"
        "SET @CUSTOM_TITLE=MyScript\n"
        "REM Simulating the ShowStatus subroutine\n"
        "TITLE %@CUSTOM_TITLE% [%USERDOMAIN%\\%USERNAME%]   !@DEBUG_MODE!\n"
        "ECHO !@CRLF-%~1!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error - this is the regression test for the bug
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert (
        len(p004_issues) == 0
    ), "Regression: Should not flag P004 for SetAccounts.BAT pattern with !@DEBUG_MODE!"


def test_complex_delayed_exprs(tmp_path: pathlib.Path) -> None:
    """Test detection of complex delayed expansion expressions."""
    script = tmp_path / "test_complex.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET arr[0]=value1\n"
        "SET arr[1]=value2\n"
        "ECHO !arr[0]!\n"
        "ECHO !arr[1]!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert (
        len(p004_issues) == 0
    ), "Should detect delayed expansion in array syntax !arr[0]!"


def test_nested_delayed_expansion(tmp_path: pathlib.Path) -> None:
    """Test detection of nested/complex delayed expansion patterns."""
    script = tmp_path / "test_nested.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET var1=test\n"
        "SET var2=var1\n"
        "ECHO !!var2!!\n"  # Double delayed expansion
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should detect nested delayed expansion !!var2!!"


def test_multi_special_chars_var(tmp_path: pathlib.Path) -> None:
    """Test variables with multiple special characters."""
    script = tmp_path / "test_multiple.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @VAR_NAME-123#=test\n"
        "ECHO !@VAR_NAME-123#!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert (
        len(p004_issues) == 0
    ), "Should detect !@VAR_NAME-123#! with multiple special chars"


def test_p008_loop_back_closing_the_scope_stays_silent() -> None:
    """The linear state has the last word: following paths never adds a finding."""
    lines = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        ":again",
        "echo !A!",
        "endlocal",
        'if "%~1"=="1" goto :again',
        "exit /b 0",
    ]
    assert _delayed_expansion_active_at_line(lines, 4)


def test_p008_flow_gives_up_on_too_many_states() -> None:
    """A path walk over its bound falls back to the linear state."""
    lines = ["@echo off", ":again"]
    lines += ["setlocal enabledelayedexpansion", 'if "%~1"=="1" goto :again']
    lines += ["endlocal", "endlocal", "echo !A!", "exit /b 0"]
    closed = _flow_closed_lines(lines)
    assert closed is None
    assert _delayed_expansion_active_at_line(lines, 7) is False


def test_p008_flow_unbalanced_block_falls_back_to_linear() -> None:
    """Unbalanced blocks give no paths to follow."""
    lines = ["@echo off", "exit /b 0", ")", "echo !A!"]
    assert _flow_closed_lines(lines) is None
    assert _delayed_expansion_active_at_line(lines, 4) is False


def test_p008_flow_on_many_jumps_is_bounded() -> None:
    """Thousands of labels and jumps stay within _MAX_FLOW_STATES_PER_LINE."""
    lines = ["@echo off"]
    for index in range(5000):
        lines += [f"goto :l{index}", f":l{index}"]
    lines.append("echo !A!")
    assert _flow_closed_lines(lines) is not None
    assert _delayed_expansion_active_at_line(lines, len(lines)) is False


_CLOSED_SCOPE = ["@echo off", "setlocal enabledelayedexpansion", "set A=1", "endlocal"]


@pytest.mark.parametrize(
    "body",
    [
        ['find "x" f.txt || (', "  exit /b 1", ")"],
        ["pushd x && (", "  exit /b 1", ")"],
        ["(", "  ver", ") || (", "  exit /b 1", ")"],
        ['if "%~1"=="x" (echo bye', "  exit /b 1)"],
        ["(if exist x exit /b)"],
        ['if "%~1"=="x" ^', "exit /b 1"],
        ['if "%~1"=="x" (', "  echo then", ") & exit /b"],
        ['set "fn=:sub"', "call %fn%", "exit /b", ":sub"],
        ['goto "end"', ":end"],
    ],
)
def test_p008_reports_after_a_path_the_walk_misses(
    tmp_path: pathlib.Path, body: list[str]
) -> None:
    """A line the walk never reaches keeps the line-by-line state.

    In cmd.exe each of these prints ``[!A!]`` (``goto "end"`` stops the script
    instead, since GOTO keeps the quotes).
    """
    lines = [*_CLOSED_SCOPE, *body, "echo [!A!]"]
    script = tmp_path / "missed.bat"
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    issues = lint_batch_file(str(script))
    assert [issue.line_number for issue in issues if issue.rule.code == "P008"] == [
        len(lines)
    ]


def test_p008_flow_goto_searches_forward_then_wraps() -> None:
    """A label defined twice: the first one below the jump wins, else the first."""
    lines = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        "goto :main",
        ":x",
        "echo FIRST !A!",
        "exit /b 0",
        ":main",
        "endlocal",
        "goto :x",
        "echo unreachable",
        ":x",
        "echo SECOND !A!",
        "goto :x",
    ]
    labels = _flow_labels(lines)
    assert _flow_label_line(labels, "x", 8) == 10
    assert _flow_label_line(labels, "x", 12) == 3
    assert _flow_label_line(labels, "missing", 0) == -1
    closed = _flow_closed_lines(lines)
    assert closed is not None
    assert closed[11] is True
    assert not _delayed_expansion_active_at_line(lines, 12)


@pytest.mark.parametrize(
    "body",
    [
        ["ver >nul || (", "exit /b 1", ")"],
        ['if "x"=="y" (echo bye', "exit /b 1)"],
        ['if "x"=="y" ^', "exit /b 1"],
        ["ver >nul && (", "ver >nul", ") || (", "exit /b 1", ")"],
    ],
)
def test_p008_reports_a_label_also_reached_with_the_scope_closed(
    tmp_path: pathlib.Path, body: list[str]
) -> None:
    """A CALL reaches ``:tail`` with the scope open, but the fall-through does not.

    In cmd.exe each of these goes on past ``body`` and prints ``[!A!]``.
    """
    lines = [
        *_CLOSED_SCOPE[:3],
        "call :tail",
        "endlocal",
        *body,
        ":tail",
        "echo [!A!]",
        "exit /b 0",
    ]
    script = tmp_path / "tail.bat"
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    issues = lint_batch_file(str(script))
    assert [issue.line_number for issue in issues if issue.rule.code == "P008"] == [
        len(lines) - 1
    ]


def test_p008_computed_goto_keeps_the_scope_of_the_jump(
    tmp_path: pathlib.Path,
) -> None:
    """A computed GOTO after ENDLOCAL reaches its label with the scope closed."""
    lines = [
        *_CLOSED_SCOPE,
        'set "t=next"',
        "goto %t%",
        ":next",
        "echo [!A!]",
        "exit /b 0",
    ]
    script = tmp_path / "computed.bat"
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    issues = lint_batch_file(str(script))
    assert [issue.line_number for issue in issues if issue.rule.code == "P008"] == [8]


def test_p008_flow_gives_up_on_too_many_computed_jump_states() -> None:
    """Computed jumps from more scope states than the bound fall back to linear."""
    lines = ["@echo off"]
    for _ in range(9):
        lines += ["setlocal enabledelayedexpansion", 'if "%~1"=="x" goto %t%']
    lines += [":l", "echo !A!"]
    assert _flow_closed_lines(lines) is None
    assert _flow_closed_lines(lines[:-4] + lines[-2:]) is not None


_OPEN_TO_SHOW = [
    "@echo off",
    "setlocal enabledelayedexpansion",
    "set A=1",
    'if "%~1"=="y" goto :show',
]


@pytest.mark.parametrize(
    ("body", "gives_up"),
    [
        pytest.param(
            ['if "%~1"=="x" (', "endlocal", ") else (", "echo else", ") & exit /b"],
            False,
            id="else-trailing-command",
        ),
        pytest.param(
            [
                "endlocal",
                'if "%~1"=="x" (',
                "echo x",
                ') else if "%~1"=="z" (',
                "echo z",
                ") & exit /b",
            ],
            False,
            id="else-if-without-else",
        ),
        pytest.param(
            ["endlocal", 'ver >nul & if "%~1"=="x" (', "goto :eof", ")"],
            True,
            id="if-after-ampersand",
        ),
        pytest.param(
            ["endlocal", '(if "%~1"=="x" goto :eof)'], False, id="if-after-paren"
        ),
        pytest.param(
            ['if "%~1"=="x" (', "endlocal", ") else (echo leaving", "exit /b 1)"],
            True,
            id="else-open-text",
        ),
        pytest.param(
            ['if "%~1"=="x" (', "endlocal", "echo bye) else (", "exit /b 1", ")"],
            True,
            id="echo-closes-block",
        ),
        pytest.param(
            ['set "fn=:show"', "call :show", "endlocal", "call %fn%", "exit /b"],
            False,
            id="call-through-variable",
        ),
        pytest.param(
            ["endlocal", "for %%i in (%~2) do ^", "goto :eof"],
            False,
            id="for-continued-with-caret",
        ),
        pytest.param(["endlocal", "echo ^", "exit /b"], True, id="echo-caret-exit"),
        pytest.param(["endlocal", "echo ^", "goto :eof"], True, id="echo-caret-goto"),
        pytest.param(["endlocal", "echo ^^^", "exit /b"], True, id="echo-odd-carets"),
        pytest.param(
            ["endlocal", "call prog.exe --flag ^", "exit"], True, id="call-caret-arg"
        ),
        pytest.param(
            ["endlocal", 'for %%i in (1) do if "%~1"=="x" (echo bye', "exit /b 1)"],
            True,
            id="for-if-open-text",
        ),
        pytest.param(
            ["endlocal", "for %%i in (%~2) do (echo bye", "exit /b 1)"],
            True,
            id="for-open-text",
        ),
        pytest.param(
            [
                "endlocal",
                "for %%i in (1) do ^",
                'if "%~1"=="x" (echo bye',
                "exit /b 1)",
            ],
            True,
            id="for-caret-if-open-text",
        ),
        pytest.param(["endlocal", "goto,show", "exit /b"], False, id="goto-comma"),
        pytest.param(["endlocal", "goto;show", "exit /b"], False, id="goto-semicolon"),
        pytest.param(["endlocal", "goto=show", "exit /b"], False, id="goto-equals"),
        pytest.param(
            ["endlocal", "goto :show,x", "exit /b"], False, id="goto-label-comma"
        ),
        pytest.param(
            ["endlocal", "goto :show;", "exit /b"], False, id="goto-label-semicolon"
        ),
        pytest.param(
            ["endlocal", "call ,:show", "exit /b"], False, id="call-comma-colon"
        ),
        pytest.param(
            ["endlocal", "call :show,x", "exit /b"], False, id="call-label-comma"
        ),
        pytest.param(
            ["endlocal", "goto :show+x", "exit /b"], False, id="goto-label-plus"
        ),
        pytest.param(
            ["endlocal", "call :show:x", "exit /b"], False, id="call-label-colon"
        ),
        pytest.param(
            ["endlocal", "call :show>nul", "exit /b"], False, id="call-label-redirect"
        ),
        pytest.param(
            ["endlocal", "goto :show<nul", "exit /b"], False, id="goto-label-redirect"
        ),
        pytest.param(
            ["endlocal", ">nul goto :show", "exit /b"], False, id="redirect-before-goto"
        ),
        pytest.param(
            ["endlocal", "2> nul call :show", "exit /b"],
            False,
            id="redirect-before-call",
        ),
        pytest.param(
            ['set "fn=:show"', "endlocal", "call%fn%", "exit /b"],
            False,
            id="call-glued-variable",
        ),
        pytest.param(
            [
                "goto :inside",
                'if "x"=="x" (',
                ":inside",
                "echo in",
                ") else (",
                "endlocal",
                ")",
            ],
            True,
            id="label-in-then-block",
        ),
        pytest.param(
            [
                "endlocal",
                "goto :inside",
                'if "x"=="y" (',
                ":inside",
                "echo in",
                ") & exit /b",
            ],
            True,
            id="label-in-if-block",
        ),
        pytest.param(
            ["endlocal", '>"a b"exit /b'], False, id="redirect-quote-glued-exit"
        ),
        pytest.param(
            ["endlocal", '>"a b"goto :eof'], False, id="redirect-quote-glued-goto"
        ),
        pytest.param(
            ["endlocal", '2>"a"exit /b'], False, id="redirect-2-quote-glued-exit"
        ),
        pytest.param(
            ["endlocal", "set x=(", ") & exit /b"], True, id="paren-after-set-exit"
        ),
        pytest.param(
            ["endlocal", "set x=(", ") & goto :eof"], True, id="paren-after-set-goto"
        ),
        pytest.param(
            ["endlocal", "call :sub (", ") & exit /b"], True, id="paren-after-call"
        ),
    ],
)
def test_p008_flow_keeps_a_path_cmd_takes(body: list[str], gives_up: bool) -> None:
    """A path cmd.exe takes to ``echo [!A!]`` with the scope closed is kept.

    ``goto :show`` reaches the line with the scope open, so the finding stays
    only where the walk also finds the closed path, or gives up.
    """
    lines = [*_OPEN_TO_SHOW, *body, ":show", "echo [!A!]"]
    target = len(lines) - 1
    closed = _flow_closed_lines(lines)
    if gives_up:
        assert closed is None
    else:
        assert closed is not None
        assert closed[target] is True
    assert _delayed_expansion_active_at_line(lines, target + 1) is False


def test_p008_flow_gives_up_on_a_computed_jump_with_a_label_in_a_block() -> None:
    """A computed jump may reach a label inside a block, so the walk gives up."""
    body = ["endlocal", "goto %t%", 'if "x"=="y" (', ":inside", "echo in", ")"]
    assert _flow_closed_lines([*_OPEN_TO_SHOW, *body, ":show", "echo [!A!]"]) is None
    assert _flow_closed_lines([*_OPEN_TO_SHOW, *body[:2], ":show", "echo [!A!]"])


@pytest.mark.parametrize(
    ("command", "target"),
    [
        ("goto :eof", "eof"),
        ("goto:eof", "eof"),
        ("@goto :eof", "eof"),
        ('goto "end"', '"end"'),
        ("goto,end", "end"),
        ("goto;end", "end"),
        ("goto=end", "end"),
        ("goto , :end", "end"),
        ("goto ::end", ":end"),
        ("goto :end:x", "end"),
        ("goto :end=x", "end"),
        ("goto ^:end", "end"),
        ("goto ^end", "end"),
        ("goto :e^nd", "end"),
        ("go^to :end", "end"),
        ('goto "e^nd"', '"e^nd"'),
        ("goto :end>nul", "end"),
        ("goto :end<nul", "end"),
        (">nul goto :end", "end"),
        ("goto%t%", "%t%"),
    ],
)
def test_p008_flow_reads_the_goto_target(command: str, target: str) -> None:
    """GOTO takes a space, comma, semicolon or ``=`` before its label, as in cmd.exe.

    One colon is dropped: cmd.exe does not find ``:end`` for ``goto ::end``.
    A later colon, ``=`` or redirection ends the label. Carets outside quotes
    and redirections before GOTO are dropped first.
    """
    assert _flow_ops(command) == (("goto", target),)


@pytest.mark.parametrize(
    ("command", "target"),
    [
        ("call ,:sub", "sub"),
        ("call :sub,x", "sub"),
        ("call :sub;x", "sub"),
        ("call :sub=x", "sub"),
        ("call :sub+x", "sub"),
        ("call ::sub", "sub"),
        ("call ^:sub", "sub"),
        ("call :s^ub", "sub"),
        ("call :sub:x", "sub"),
        ("call :sub>nul", "sub"),
        ("call :sub>>log.txt", "sub"),
        ('2>"a b" call :sub', "sub"),
        ("call :sub|more", "sub"),
        ('call :sub"x"', 'sub"x"'),
        ("call%fn%", "%fn%"),
    ],
)
def test_p008_flow_reads_the_call_target(command: str, target: str) -> None:
    """CALL drops every colon before its label, as ``call ::sub`` reaches ``:sub``.

    The label ends at a comma, semicolon, ``=``, ``+``, a later colon, a
    redirection or a pipe, and keeps a quote, as GOTO does. Carets and
    redirections before CALL are dropped first.
    """
    assert _flow_ops(command) == (("call", target),)


def test_p008_flow_call_label_with_a_quote_reaches_no_label() -> None:
    """``call :sub"x"`` looks for the label ``sub"x"``, so ``:sub`` stays unreached.

    cmd.exe reports that it cannot find the label ``sub"x"`` and goes on.
    """
    lines = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        "set A=1",
        'call :sub"x"',
        "exit /b",
        ":sub",
        "echo [!A!]",
    ]
    closed = _flow_closed_lines(lines)
    assert closed is not None
    assert closed[6] is None


def test_p008_flow_conditional_disable_closes_the_rest_of_the_line() -> None:
    """``setlocal disabledelayedexpansion`` closes the scope for what follows it."""
    lines = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        "set A=1",
        'if "%~1"=="x" setlocal disabledelayedexpansion & echo [!A!]',
    ]
    closed = _flow_closed_lines(lines)
    assert closed is not None
    assert closed[3] is True
    assert _delayed_expansion_active_at_line(lines, 4) is False


@pytest.mark.parametrize(
    ("command", "ops"),
    [
        ('>"a b" exit /b', (("end", ""),)),
        ('>"a b"exit /b', ()),
        ('2>"a"exit /b', ()),
        ('>"a b"goto :eof', ()),
    ],
)
def test_p008_flow_quoted_redirect_target_goes_on(
    command: str, ops: tuple[tuple[str, str], ...]
) -> None:
    """A quoted redirection target goes on up to whitespace, as in cmd.exe.

    For ``>"a b"exit /b`` the target is ``"a b"exit`` and the command is
    ``/b``, so the script goes on.
    """
    assert _flow_ops(command) == ops


@pytest.mark.parametrize(
    ("line", "opens"),
    [
        ("(", True),
        ("@(", True),
        ("if 1==1 (", True),
        ('if /i not "%~1"=="" (', True),
        ("if %a% equ 1 (", True),
        (") else (", True),
        (") else if x==y (", True),
        ("ver || (", True),
        ("echo a & (", True),
        ("for %%a in (x) do (", True),
        ("if x==y for %%a in (x) do (", True),
        ("set x=(", False),
        ('set "x=(', False),
        ("set x=^(", False),
        ("call :sub (", False),
        ("if x==y set a=(", False),
        (") else set x=(", False),
        ("if 1==1(", None),
        ("(set x=(", None),
        (">nul (", None),
        ("%cmd% (", None),
        ("for /f %%a in ('do') do (", None),
    ],
)
def test_p008_flow_reads_a_block_opener(line: str, opens: bool | None) -> None:
    """A trailing ``(`` opens a block only where a command starts; None is unsure."""
    assert _flow_opens_block(line) is opens


def test_p008_flow_paren_line_outside_a_block_gives_up() -> None:
    """``set x=(`` opens no block, so the ``)`` line below it closes none.

    cmd.exe ignores such a line, ``& exit /b`` included, and goes on. The walk
    gives up instead, since it may close a block opened in a way it did not
    read. A real IF block is still read.
    """
    lines = [*_OPEN_TO_SHOW, "endlocal", "set x=(", ") & exit /b", ":show", "echo !A!"]
    assert _flow_block_closers(lines) is None
    block = [*_OPEN_TO_SHOW, "endlocal", "if 1==1 (", "exit /b", ")", ":show"]
    assert _flow_block_closers(block) == {5: 7}
    assert _flow_closed_lines([*block, "echo !A!"]) is not None
