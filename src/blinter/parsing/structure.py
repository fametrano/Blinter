"""Label collection, script structure, and subroutine detection."""

# pylint: disable=too-many-lines

import bisect
from contextvars import ContextVar
import re
from typing import (
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    TypeVar,
)

from blinter.constants import BUILTIN_VARS
from blinter.logging_config import logger
from blinter.models import LintIssue
from blinter.parsing.context import (
    _command_segments,
    _is_blank_or_comment,
    _is_endlocal_command,
    _is_setlocal_command,
)
from blinter.patterns import (
    _COMPILED_SETLOCAL_DISABLE,
)
from blinter.rules.helpers import _add_issue

_LABEL_TARGET_PATTERN = re.compile(
    r"\b(?:call|goto)\s+(:[^\s]+)",
    re.IGNORECASE,
)
# ASCII-only case folding: str.upper() maps ı to I and ſ to S, so a look-alike
# directive would suppress rules that neither a reader nor a search would see.
_SUPPRESSION_DIRECTIVE = re.compile(
    r"^(?:rem\s|::)\s*lint:ignore(-line)?(?=\s|$)(.*)$",
    re.IGNORECASE | re.ASCII,
)
_SUPPRESSION_CODE = re.compile(r"^[A-Za-z]+[0-9]+$", re.ASCII)


def _collect_labels(lines: List[str]) -> Tuple[Dict[str, int], List[LintIssue]]:
    """Collect all labels and detect duplicates."""
    labels: Dict[str, int] = {}
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        stripped_line = line.strip()
        if stripped_line.startswith(":"):
            # Skip comment-style lines that start with :: (double colon)
            if stripped_line.startswith("::"):
                continue

            label = stripped_line.lower()

            # Skip comment-style labels (like :::) that contain no alphanumeric characters
            # These are commonly used as decorative comments and should not be flagged as duplicates
            label_content = label[1:]  # Remove the leading ":"
            if not re.search(r"[a-zA-Z0-9]", label_content):
                # This is a comment-style label like ::::::, skip it
                continue

            if label in labels:
                _add_issue(
                    issues,
                    line_number=i,
                    rule_code="W013",
                    context=f"Label '{label}' already defined on line {labels[label]}",
                )
            else:
                labels[label] = i

    return labels, issues


def _normalize_label_target(raw_target: str) -> str:
    """Normalize CALL/GOTO label targets to match ``labels`` dict keys."""
    target = raw_target.strip().lower()
    if not target.startswith(":"):
        target = f":{target}"
    return target


_target_line_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, Dict[str, int]]]]
] = ContextVar("target_line_cache", default=None)
_sorted_labels_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, List[Tuple[str, int]]]]]
] = ContextVar("sorted_labels_cache", default=None)
_label_block_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, object, List[Optional[Tuple[str, int]]]]]]
] = ContextVar("label_block_cache", default=None)


def _begin_invocation_prefix_pass() -> None:
    """Start per-lint label-target caches for the current execution context."""
    _target_line_cache_var.set({})
    _sorted_labels_cache_var.set({})
    _label_block_cache_var.set({})


def _build_first_target_line(lines: List[str]) -> Dict[str, int]:
    """Map each CALL/GOTO target to the first 0-based line that names it."""
    first_line: Dict[str, int] = {}
    for index, line in enumerate(lines):
        for match in _LABEL_TARGET_PATTERN.finditer(line):
            name = _normalize_label_target(match.group(1))
            if name not in first_line:
                first_line[name] = index
    return first_line


def _first_target_lines_for(lines: List[str]) -> Dict[str, int]:
    """Return cached first-target lines for ``lines`` within a single lint pass."""
    return _identity_cached(
        _target_line_cache_var.get(),
        lines,
        lambda: _build_first_target_line(lines),
    )


def _sorted_labels_for(labels: Dict[str, int]) -> List[Tuple[str, int]]:
    """Return label definitions sorted by line, cached for this lint pass."""
    return _identity_cached(
        _sorted_labels_cache_var.get(),
        labels,
        lambda: sorted(labels.items(), key=_label_sort_key),
    )


def _label_was_targeted_before(
    lines: List[str], before_line: int, label_name: str
) -> bool:
    """Return True when CALL/GOTO names ``label_name`` before ``before_line``."""
    if before_line <= 1:
        return False
    first_line = _first_target_lines_for(lines).get(label_name)
    if first_line is None:
        return False
    return first_line < before_line - 1


def _build_label_block_index(
    sorted_labels: List[Tuple[str, int]], total_lines: int
) -> List[Optional[Tuple[str, int]]]:
    """Map each 1-based line to the label body that contains it.

    Label bodies span from the line after the label until the next label
    (exclusive). The label line itself is not part of the body.
    """
    blocks: List[Optional[Tuple[str, int]]] = [None] * (total_lines + 1)
    for index, (label_name, label_line) in enumerate(sorted_labels):
        next_label_line = (
            sorted_labels[index + 1][1]
            if index + 1 < len(sorted_labels)
            else total_lines + 1
        )
        block = (label_name, label_line)
        for line_number in range(label_line + 1, next_label_line):
            if 1 <= line_number <= total_lines:
                blocks[line_number] = block
    return blocks


def _label_blocks_for(
    lines: List[str], labels: Dict[str, int]
) -> List[Optional[Tuple[str, int]]]:
    """Return the per-line label-body index, cached for this lint pass."""
    sorted_labels = _sorted_labels_for(labels)
    cache = _label_block_cache_var.get()
    if cache is None:
        return _build_label_block_index(sorted_labels, len(lines))
    source_id = id(lines)
    cached = cache.get(source_id)
    if cached is None or cached[0] is not lines or cached[1] is not labels:
        blocks = _build_label_block_index(sorted_labels, len(lines))
        cache[source_id] = (lines, labels, blocks)
        return blocks
    return cached[2]


def _label_sort_key(item: tuple[str, int]) -> int:
    """Sort label entries by line number."""
    return item[1]


def _is_in_subroutine_context(
    lines: List[str], line_number: int, labels: Dict[str, int]
) -> bool:
    """
    Determine if a line is within an invoked subroutine context.

    A line is in subroutine context when it falls inside a label block that was
    reached via an earlier ``CALL :label`` or ``GOTO :label``. Main-line fall-through
    into a label without a prior transfer is not treated as subroutine context.
    """
    if not labels or line_number < 1:
        return False

    blocks = _label_blocks_for(lines, labels)
    block = blocks[line_number] if line_number < len(blocks) else None
    if block is None:
        return False

    label_name, _ = block
    return _label_was_targeted_before(lines, line_number, label_name)


_SET_VAR_NAME = r"[A-Za-z0-9_@]+"
# CALL :label varname — first argument names a variable set via SET "%1=" in :label
_CALL_LABEL_VAR_PATTERN = re.compile(
    rf"\bcall\s+:\w+\s+({_SET_VAR_NAME})\b",
    re.IGNORECASE,
)


def _collect_set_variables(lines: List[str]) -> Set[str]:
    """Collect all variables that are set in the script."""
    set_vars: Set[str] = set()
    vn = _SET_VAR_NAME
    for line in lines:
        # Match different SET patterns, including quoted variable names
        # Use re.search instead of re.match to find SET commands anywhere in the line
        # This handles cases like: if not defined VAR set "VAR=value"
        patterns = [
            rf"\bset\s+({vn})=",  # Regular set: set VAR=value
            rf'\bset\s+"({vn})=',  # Quoted set: set "VAR=value"
            rf"\bset\s+/p\s+({vn})=",  # Set with prompt: set /p VAR=
            rf'\bset\s+/p\s+"({vn})=',  # Quoted set with prompt: set /p "VAR="
            rf"\bset\s+/a\s+({vn})=",  # Arithmetic set: set /a VAR=
            rf'\bset\s+/a\s+"({vn})=',  # Quoted arithmetic set: set /a "VAR="
            rf"\bset\s+/a\s+({vn})[+\-*/%]?=",  # Compound: set /a VAR+=1
            rf'\bset\s+/a\s+"({vn})[+\-*/%]?=',  # Quoted compound set /a
        ]

        stripped_line = line.strip()
        for pattern in patterns:
            for set_match in re.finditer(pattern, stripped_line, re.IGNORECASE):
                var_name_text: str = set_match.group(1)
                set_vars.add(var_name_text.upper())

        for call_match in _CALL_LABEL_VAR_PATTERN.finditer(stripped_line):
            set_vars.add(str(call_match.group(1)).upper())

        # Handle dynamic variable assignments in FOR loops: set "%%~b=value"
        # Example: for %%a in (list) do (set "%%~a=value")
        dynamic_set_match = re.search(
            r'\bset\s+"%%~[a-zA-Z]=', line.strip(), re.IGNORECASE
        )
        if dynamic_set_match:
            # When we see dynamic variable assignment, we need to look for what values
            # the FOR loop might iterate over to determine variable names
            # For now, mark this as a script that uses dynamic variables
            # and be more lenient with undefined variable warnings
            set_vars.add("__DYNAMIC_VARS__")

    set_vars.update(BUILTIN_VARS)

    return set_vars


def _collect_empty_assigned_variables(lines: List[str]) -> Set[str]:
    """Collect variables explicitly assigned an empty value via SET."""
    empty_vars: Set[str] = set()
    vn = _SET_VAR_NAME
    empty_patterns = [
        rf'\bset\s+"?({vn})"?\s*=\s*(?:$|[&|])',
        rf'\bset\s+"({vn})="\s*(?:$|[&|])',
    ]
    for line in lines:
        stripped = line.strip()
        for pattern in empty_patterns:
            for match in re.finditer(pattern, stripped, re.IGNORECASE):
                empty_vars.add(str(match.group(1)).upper())
    return empty_vars


def _suppression_codes(rest: str, line_number: int) -> Set[str]:
    """Return ASCII rule codes from a directive, skipping malformed tokens."""
    codes: Set[str] = set()
    for raw_code in rest.split(","):
        code = raw_code.strip()
        if not code:
            continue
        if _SUPPRESSION_CODE.fullmatch(code) is None:
            logger.debug(
                "Ignoring non-ASCII or malformed suppression code %r on line %d",
                code,
                line_number,
            )
            continue
        codes.add(code.upper())
    return codes


def _record_suppression(
    suppressions: Dict[int, Set[str]],
    line_number: int,
    same_line: bool,
    rest: str,
) -> None:
    """Record one directive. A code list with no ASCII codes suppresses nothing."""
    target = line_number if same_line else line_number + 1
    if not rest:
        logger.debug(
            "Suppressing all rules on line %d from the directive on line %d",
            target,
            line_number,
        )
        suppressions[target] = set()
        return
    codes = _suppression_codes(rest, line_number)
    if not codes:
        logger.debug(
            "Directive on line %d listed no ASCII rule codes; suppressing nothing",
            line_number,
        )
        return
    logger.debug(
        "Suppressing %s on line %d from the directive on line %d",
        ",".join(sorted(codes)),
        target,
        line_number,
    )
    suppressions.setdefault(target, set()).update(codes)


def _parse_suppression_comments(lines: List[str]) -> Dict[int, Set[str]]:
    """
    Parse inline suppression comments from batch file lines.

    The directive and its rule codes match case-insensitively in ASCII only.
    ``lınt:ıgnore`` and ``ſEC008`` are not directives or codes.

    Supports formats:
    - REM LINT:IGNORE <code> - Suppress code on the next line
    - REM LINT:IGNORE - Suppress all issues on the next line
    - REM LINT:IGNORE-LINE <code> - Suppress code on the same line
    - REM LINT:IGNORE-LINE - Suppress all issues on the same line

    Args:
        lines: List of lines from the batch file

    Returns:
        Dictionary mapping line numbers to set of rule codes to suppress.
        An empty set means suppress all rules for that line.

    Example:
        REM LINT:IGNORE E009
        ECHO '' .... Represents a " character
    """
    suppressions: Dict[int, Set[str]] = {}

    for line_number, line in enumerate(lines, start=1):
        match = _SUPPRESSION_DIRECTIVE.match(line.strip())
        if match is None:
            continue
        rest_raw = match.group(2)
        rest = rest_raw.strip() if isinstance(rest_raw, str) else ""
        _record_suppression(
            suppressions,
            line_number,
            match.group(1) is not None,
            rest,
        )

    return suppressions


_CacheValueT = TypeVar("_CacheValueT")

_PAREN_BLOCK_KEYWORDS = frozenset({"do", "in", "else", "if"})

_paren_depth_cache_var: ContextVar[Optional[Dict[int, tuple[object, List[int]]]]] = (
    ContextVar("paren_depth_cache", default=None)
)
_defined_vars_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, frozenset[str]]]]
] = ContextVar("defined_vars_cache", default=None)
_empty_assigned_vars_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, frozenset[str]]]]
] = ContextVar("empty_assigned_vars_cache", default=None)
_for_block_cache_var: ContextVar[Optional[Dict[int, tuple[object, List[bool]]]]] = (
    ContextVar("for_block_membership", default=None)
)


def _identity_cached(
    cache: Optional[Dict[int, tuple[object, _CacheValueT]]],
    source: object,
    builder: Callable[[], _CacheValueT],
) -> _CacheValueT:
    """Return builder() cached by object identity within a lint pass."""
    if cache is None:
        return builder()
    source_id = id(source)
    cached = cache.get(source_id)
    if cached is None or cached[0] is not source:
        value = builder()
        cache[source_id] = (source, value)
        return value
    return cached[1]


class _ParenScan:  # pylint: disable=too-few-public-methods
    """Mutable cursor for one quote- and caret-aware parenthesis scan."""

    __slots__ = ("delta", "same_line_open", "command", "quote")

    def __init__(self) -> None:
        self.delta = 0
        self.same_line_open = 0
        self.command: List[str] = []
        self.quote = ""


def _is_paren_comment_line(line: str) -> bool:
    """Return True for blank lines and REM/:: comments."""
    return _is_blank_or_comment(line)


def _first_command_token(command: str) -> str:
    """Return the first command token, ignoring a leading @."""
    body = command.strip().lstrip("@").strip()
    if not body:
        return ""
    return body.split(None, 1)[0].lower()


def _paren_opens_block(command: str) -> bool:
    """Return True when '(' opens an IF, FOR, ELSE, or command group."""
    if _first_command_token(command) == "echo":
        return False
    if not command.strip():
        return True
    tokens = {token.lower() for token in command.split()}
    return bool(tokens & _PAREN_BLOCK_KEYWORDS)


def _redir_amp_end(text: str, index: int) -> Optional[int]:
    """Return the index after an ``n>&n`` or ``>&`` redirection."""
    if text[index] in "12" and text.startswith(">&", index + 1):
        end = index + 3
        if end < len(text) and text[end] in "12":
            end += 1
        return end
    if text[index] == ">" and index + 1 < len(text) and text[index + 1] == "&":
        end = index + 2
        if end < len(text) and text[end] in "12":
            end += 1
        return end
    return None


def _separator_span(text: str, index: int) -> int:
    """Return the length of an unquoted command separator at index, or 0."""
    pair = text[index : index + 2]
    if pair in ("&&", "||"):
        return 2
    if text[index] in "&|":
        return 1
    return 0


def _apply_open_paren(scan: _ParenScan) -> None:
    """Count a structural '(' or keep a literal one in the command buffer."""
    if _paren_opens_block("".join(scan.command)):
        scan.delta += 1
        scan.same_line_open += 1
        scan.command = []
        return
    scan.command.append("(")


def _apply_close_paren(scan: _ParenScan) -> None:
    """Count a structural ')' or keep a literal one in the command buffer."""
    if scan.same_line_open > 0:
        scan.same_line_open -= 1
        scan.delta -= 1
        scan.command = []
        return
    if not "".join(scan.command).strip():
        scan.delta -= 1
        scan.command = []
        return
    scan.command.append(")")


def _block_paren_delta(line: str) -> int:
    """Return the net IF/FOR/group parenthesis change for one line."""
    scan = _ParenScan()
    index = 0
    length = len(line)
    while index < length:
        if scan.quote:
            if line[index] == scan.quote:
                scan.quote = ""
            index += 1
            continue
        if line[index] == "^":
            index += 2 if index + 1 < length else 1
            continue
        if line[index] in '"`':
            scan.quote = line[index]
            index += 1
            continue
        redir_end = _redir_amp_end(line, index)
        if redir_end is not None:
            scan.command.append(line[index:redir_end])
            index = redir_end
            continue
        separator = _separator_span(line, index)
        if separator:
            scan.command = []
            index += separator
            continue
        if line[index] == "(":
            _apply_open_paren(scan)
            index += 1
            continue
        if line[index] == ")":
            _apply_close_paren(scan)
            index += 1
            continue
        scan.command.append(line[index])
        index += 1
    return scan.delta


def _update_paren_depth(line: str, current_depth: int) -> int:
    """Update parentheses depth based on the line content."""
    if _is_paren_comment_line(line):
        return current_depth
    return current_depth + _block_paren_delta(line)


def _begin_paren_depth_pass() -> None:
    """Start a per-lint parenthesis-depth cache for the current context."""
    _paren_depth_cache_var.set({})


def _begin_empty_assigned_vars_pass() -> None:
    """Start a per-lint empty-assigned-vars cache for the current context."""
    _empty_assigned_vars_cache_var.set({})
    _defined_vars_cache_var.set({})


def _begin_for_block_pass() -> None:
    """Start a per-lint FOR-block membership cache for the current context."""
    _for_block_cache_var.set({})


def _begin_structure_cache_pass() -> None:
    """Initialize per-lint caches used by checker modules."""
    _begin_for_block_pass()
    _begin_invocation_prefix_pass()
    _begin_delayed_expansion_pass()
    _begin_paren_depth_pass()
    _begin_empty_assigned_vars_pass()


def _build_paren_depth_before(lines: List[str]) -> List[int]:
    """Return parenthesis block depth before each 1-based line."""
    depth = 0
    result: List[int] = []
    for line in lines:
        result.append(depth)
        depth = max(_update_paren_depth(line.strip(), depth), 0)
    return result


def _paren_depth_before_for_lines(lines: List[str]) -> List[int]:
    """Return cached parenthesis depth-before values within a single lint pass."""
    return _identity_cached(
        _paren_depth_cache_var.get(),
        lines,
        lambda: _build_paren_depth_before(lines),
    )


def _paren_depth_before_line(lines: List[str], line_num: int) -> int:
    """Return parenthesis block depth before processing line_num (1-based)."""
    if line_num < 1:
        return 0
    depths = _paren_depth_before_for_lines(lines)
    if line_num > len(depths):
        return depths[-1] if depths else 0
    return depths[line_num - 1]


_delayed_expansion_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, List[bool]]]]
] = ContextVar("delayed_expansion_cache", default=None)


_delayed_expansion_flow_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, List[bool]]]]
] = ContextVar("delayed_expansion_flow_cache", default=None)


def _begin_delayed_expansion_pass() -> None:
    """Start the per-lint delayed-expansion state caches for the current context."""
    _delayed_expansion_cache_var.set({})
    _delayed_expansion_flow_cache_var.set({})


def _build_delayed_expansion_state(lines: List[str]) -> List[bool]:
    """Return delayed-expansion active state at each 1-based line (after that line)."""
    stack: List[bool] = []
    state: List[bool] = []
    for line in lines:
        if _is_setlocal_command(line):
            stripped = line.strip().lstrip("@").strip().lower()
            if "enabledelayedexpansion" in stripped:
                stack.append(True)
            elif "disabledelayedexpansion" in stripped:
                stack.append(False)
            else:
                stack.append(stack[-1] if stack else False)
        elif _is_endlocal_command(line):
            if stack:
                stack.pop()
        state.append(stack[-1] if stack else False)
    return state


def _delayed_expansion_state_for_lines(lines: List[str]) -> List[bool]:
    """Return cached delayed-expansion state per line within a single lint pass."""
    return _identity_cached(
        _delayed_expansion_cache_var.get(),
        lines,
        lambda: _build_delayed_expansion_state(lines),
    )


# One SETLOCAL scope stack per path. ``None`` is a caller's scope that is not known.
_FlowState = Tuple[Optional[bool], ...]
_FlowOp = Tuple[str, str]

_FLOW_SEGMENT_RE = re.compile(r"(?:for\b.*?\bdo\s+\(?\s*)?(.*)", re.IGNORECASE)
# GOTO drops one colon and CALL drops them all. Both end the label at a later
# colon or a redirection, and keep a quote in it, so ``call :x"y"`` looks for
# the label ``x"y"``. A target glued to ``%`` or ``!``, as in ``call%fn%``, is computed.
_FLOW_GOTO_RE = re.compile(
    r"goto(?:[\s,;=]+:?|:|(?=[%!]))[\s,;=]*(:?[^\s,;=+):<>|&]+)", re.IGNORECASE
)
_FLOW_CALL_RE = re.compile(
    r"call[\s,;=]*(?::+[\s,;=]*|(?=[%!]))([^\s,;=+):<>|&]+)", re.IGNORECASE
)
# Redirections before a command, as in ``>nul goto :x`` or ``2> "a b" call :x``.
# A quoted part does not end the target, so in ``>"a b"exit /b`` the target is
# ``"a b"exit`` and the command is ``/b``.
_FLOW_REDIRECT_RE = re.compile(
    r"\A(?:\d?(?:>>?|<)(?:&\d|\s*(?:\"[^\"]*\"|[^\s\"<>&|])+)\s*)*"
)
_FLOW_LABEL_RE = re.compile(r"\s*:([^\s:+&|<>,;=]+)")
_FLOW_CONDITIONAL_RE = re.compile(r"(?:if|for|\)\s*else)\b", re.IGNORECASE)
_FLOW_NESTED_CONDITION_RE = re.compile(
    r"(?:&|\||\()\s*(?:if|for)\b|\)\s*else\s*\(", re.IGNORECASE
)
_FLOW_ELSE_SPLIT_RE = re.compile(r"\)\s*else\s*\(", re.IGNORECASE)
_FLOW_SCOPE_CLOSE_RE = re.compile(
    r"\bendlocal\b|\bdisabledelayedexpansion\b", re.IGNORECASE
)
_FLOW_DELAYED_VAR_RE = re.compile(r"![^!]+!")
_FLOW_CHAIN_RE = re.compile(r"&&|\|\|")
_FLOW_ELSE_OPEN_RE = re.compile(r"\)\s*else\b.*\($", re.IGNORECASE)
_FLOW_ECHO_RE = re.compile(r"@?echo\b", re.IGNORECASE)
_FLOW_ECHO_CLOSE_RE = re.compile(r'(?:[^"^)]|\^.|"[^"]*")*\)')
_FLOW_ELSE_IF_RE = re.compile(r"\)\s*else\s+if\b", re.IGNORECASE)
_FLOW_FOR_RE = re.compile(r"for\b", re.IGNORECASE)
_FLOW_DO_RE = re.compile(r"\bdo\b", re.IGNORECASE)
_FLOW_ELSE_RE = re.compile(r"\)\s*else\b", re.IGNORECASE)
_FLOW_IF_TOKEN = r'(?:"[^"]*"|[^\s"=])+'
# An IF and its condition, up to the command it runs.
_FLOW_IF_RE = re.compile(
    r"if\s+(?:/i\s+)?(?:not\s+)?"
    rf"(?:(?:exist|defined|errorlevel|cmdextversion)\s+{_FLOW_IF_TOKEN}"
    rf"|{_FLOW_IF_TOKEN}\s*==\s*{_FLOW_IF_TOKEN}"
    rf"|{_FLOW_IF_TOKEN}\s+(?:equ|neq|lss|leq|gtr|geq)\s+{_FLOW_IF_TOKEN})",
    re.IGNORECASE,
)
_FLOW_KEYWORD_RE = re.compile(r"(?:if|else|do)\b", re.IGNORECASE)
_FLOW_UNKNOWN_START_RE = re.compile(r'\d?[<>]|[%!^:)"]')
_MAX_FLOW_STATES_PER_LINE = 8


class _FlowLine(NamedTuple):
    """What one line does to the paths through it."""

    ops: Tuple[_FlowOp, ...]
    next_index: int
    skips: Tuple[int, ...]
    conditional: bool
    in_block: bool


def _flow_unescape(text: str) -> str:
    """Return text with the carets cmd.exe removes outside quotes, as ``go^to`` to ``goto``."""
    out: List[str] = []
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "^" and not quoted:
            index += 1
            char = text[index : index + 1]
        elif char == '"':
            quoted = not quoted
        out.append(char)
        index += 1
    return "".join(out)


def _flow_ops(line: str) -> Tuple[_FlowOp, ...]:
    """Return a line's scope and jump operations, up to the one that ends the path."""
    ops: List[_FlowOp] = []
    nested_condition = _FLOW_NESTED_CONDITION_RE.search(line) is not None
    parts = [
        part
        for segment in _command_segments(line)
        for part in _FLOW_ELSE_SPLIT_RE.sub("\0", segment).split("\0")
    ]
    for segment in parts:
        match = _FLOW_SEGMENT_RE.match(segment)
        text = (str(match.group(1)) if match else segment).lstrip("(")
        text = _FLOW_REDIRECT_RE.sub("", text, count=1)
        word = (text.split() or [""])[0].lower()
        unescaped = _flow_unescape(text)
        goto = _FLOW_GOTO_RE.match(unescaped)
        call = _FLOW_CALL_RE.match(unescaped)
        if word == "setlocal":
            lowered = text.lower()
            disable = "disable" if "disabledelayedexpansion" in lowered else ""
            enable = "enabledelayedexpansion" in lowered
            ops.append(("setlocal", "enable" if enable else disable))
        elif word == "endlocal":
            ops.append(("endlocal", ""))
        elif (word == "exit" or word.startswith("exit/")) and not nested_condition:
            ops.append(("end", ""))
            break
        elif goto:
            kind = "call" if nested_condition else "goto"
            ops.append((kind, str(goto.group(1)).lower()))
            if not nested_condition:
                break
        elif call:
            ops.append(("call", str(call.group(1)).lower()))
        elif word[:1] in ("%", "!"):
            # A command read from a variable may be a GOTO or a CALL.
            ops.append(("call", word))
    return tuple(ops)


def _flow_last_command(text: str) -> Optional[str]:
    """Return the command after the last ``&`` or ``|`` outside quotes and carets.

    Returns None when the trailing ``(`` is quoted or escaped, so it is text.
    """
    start = 0
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            quoted = not quoted
        elif quoted:
            pass
        elif char == "^":
            index += 1
            if index == len(text) - 1:
                return None
        elif char in "&|":
            start = index + 1
        index += 1
    return None if quoted else text[start:]


def _flow_opens_block(text: str) -> Optional[bool]:
    """Return whether the ``(`` that ends ``text`` opens a block, or None if unsure.

    It opens one only where a command starts: alone, after ``&`` or ``|``,
    after ``) else``, after an IF condition or after a FOR's DO. After any
    other command, as in ``set x=(`` or ``call :sub (``, it is text.
    """
    command = _flow_last_command(text)
    if command is None:
        return False
    while True:
        command = command.lstrip(" \t,;=")
        command = command[1:].lstrip(" \t,;=") if command[:1] == "@" else command
        if command == "(":
            return True
        else_match = _FLOW_ELSE_RE.match(command)
        if_match = _FLOW_IF_RE.match(command)
        if else_match:
            command = command[else_match.end() :]
        elif if_match and command[if_match.end() :].strip():
            command = command[if_match.end() :]
        elif _FLOW_FOR_RE.match(command):
            dos = list(_FLOW_DO_RE.finditer(command))
            if len(dos) > 1:
                return None
            # Without DO, the ``(`` opens the FOR set that a later ``) do`` closes.
            if not dos:
                return True
            command = command[dos[0].end() :]
        elif (
            command.startswith("(")
            or _FLOW_KEYWORD_RE.match(command)
            or _FLOW_UNKNOWN_START_RE.match(command)
        ):
            return None
        else:
            return False


def _flow_block_closers(lines: List[str]) -> Optional[Dict[int, int]]:
    """Map each line that opens a block to the line that closes it, or None if unbalanced.

    Blocks are read from each line's shape, a trailing ``(`` and a leading ``)``,
    because a FOR set wrapped with ``^`` holds parentheses over several lines.
    A trailing ``(`` opens a block only where ``_flow_opens_block`` says so, so
    in ``set x=(`` it is text, and a ``)`` that closes no block gives None:
    cmd.exe ignores such a line, but it may close a block the walk did not see.
    An ECHO inside a block with a ``)`` outside quotes and carets closes the
    block mid-line, as in ``echo bye) else (``, so it gives None too.
    """
    closers: Dict[int, int] = {}
    open_lines: List[int] = []
    joined = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        text = joined + stripped
        # A line ending in an odd run of carets goes on in the next one.
        carets = len(stripped) - len(stripped.rstrip("^"))
        joined = text[:-1] + " " if carets % 2 else ""
        if (
            _FLOW_ECHO_RE.match(stripped)
            and open_lines
            and _FLOW_ECHO_CLOSE_RE.match(stripped)
        ):
            return None
        if _is_blank_or_comment(stripped) or _FLOW_ECHO_RE.match(stripped):
            continue
        if stripped.startswith(")"):
            if not open_lines:
                return None
            closers[open_lines.pop()] = index
        if stripped.endswith("("):
            opens = _flow_opens_block(text)
            if opens is None:
                return None
            if opens:
                open_lines.append(index)
    return None if open_lines else closers


def _flow_skip_targets(
    lines: List[str], closers: Dict[int, int], opener: int
) -> List[int]:
    """Return where a path goes when the block opened at ``opener`` does not run.

    Where the chain ends without an ELSE, the path skips the closing line too:
    in ``) & exit /b`` the command after ``)`` belongs to the last IF.
    """
    targets: List[int] = []
    closer = closers[opener]
    while closer in closers and _FLOW_ELSE_OPEN_RE.match(lines[closer].strip()):
        targets.append(closer + 1)
        if not _FLOW_ELSE_IF_RE.match(lines[closer].strip()):
            return targets
        closer = closers[closer]
    targets.append(closer + 1)
    return targets


def _flow_chain_end(lines: List[str], closers: Dict[int, int], closer: int) -> int:
    """Return the line after the IF/ELSE chain whose block closes at ``closer``.

    A command after the last ``)`` belongs to the last ELSE, so a path that ran
    an earlier block of the chain skips it.
    """
    while closer in closers and _FLOW_ELSE_OPEN_RE.match(lines[closer].strip()):
        closer = closers[closer]
    return closer + 1


def _flow_expands_after_scope_close(line: str) -> bool:
    """Return True when a ``!VAR!`` follows the line's last ENDLOCAL or DISABLE.

    Such a variable is read with the scope closed whichever way the line's
    condition goes, as in ``if defined VAL endlocal & set "RET=!VAL!"``, or as
    in ``if x setlocal disabledelayedexpansion & echo !A!``.
    """
    ends = list(_FLOW_SCOPE_CLOSE_RE.finditer(line))
    if not ends:
        return False
    return _FLOW_DELAYED_VAR_RE.search(line[ends[-1].end() :]) is not None


def _flow_spans_lines(stripped: str, conditional: bool, is_for: bool) -> bool:
    """Return True when a command goes on past its line in a way the walk does not read.

    Any line ending in an odd run of carets goes on: cmd.exe usually joins the
    next line to it, so ``echo ^`` above ``exit /b`` runs no EXIT. It does not
    after ``rem x ^`` or inside quotes, and the walk gives up on those too. A FOR
    line does not count: the line after it is read as part of the FOR. An IF, FOR or
    ``&&``/``||`` command also goes on through a block that does not close on a
    line of its own, as in ``if x (echo bye`` followed by ``exit /b 1)``. The
    walk reads a block from a trailing ``(`` and a leading ``)``, so it gives up
    on these. An IF after ``&``, ``|`` or ``(`` counts too, and so does any
    block it opens, since its skip edges are not known.
    """
    if (len(stripped) - len(stripped.rstrip("^"))) % 2:
        return not is_for
    nested = _FLOW_NESTED_CONDITION_RE.search(stripped) is not None
    if not (conditional or nested):
        return False
    if nested and stripped.endswith("(") and not _FLOW_ELSE_OPEN_RE.match(stripped):
        return True
    body = stripped.lstrip(")")
    return body.count("(") > body.count(")") and not stripped.endswith("(")


def _flow_lines(lines: List[str]) -> Optional[List[_FlowLine]]:
    """Return each line's operations and edges, or None if its blocks are unbalanced."""
    closers = _flow_block_closers(lines)
    if closers is None:
        return None
    # A FOR line ending in ``^`` goes on over the line that follows it.
    for_lines: Set[int] = set()
    for index, line in enumerate(lines):
        stripped = line.strip().lstrip("@").strip()
        if _FLOW_FOR_RE.match(stripped) or (
            index - 1 in for_lines and lines[index - 1].rstrip().endswith("^")
        ):
            for_lines.add(index)
    loop_backs = {closers[index]: index + 1 for index in closers if index in for_lines}
    depth = [0] * (len(lines) + 1)
    for opener, closer in closers.items():
        depth[opener + 1] += 1
        depth[closer] -= 1
    for index in range(1, len(lines)):
        depth[index] += depth[index - 1]
    flow: List[_FlowLine] = []
    for index, line in enumerate(lines):
        stripped = line.strip().lstrip("@").strip()
        branches = (
            _FLOW_CONDITIONAL_RE.match(stripped) is not None or index in for_lines
        )
        conditional = branches or _FLOW_CHAIN_RE.search(stripped) is not None
        if _flow_spans_lines(stripped, conditional, index in for_lines):
            return None
        is_else_open = (
            index in closers and _FLOW_ELSE_OPEN_RE.match(stripped) is not None
        )
        skips: List[int] = []
        if index in closers and branches and not is_else_open:
            skips = _flow_skip_targets(lines, closers, index)
        elif index in closers and conditional and not is_else_open:
            # ``ver || (`` skips its block, and a command after its ``)`` still runs.
            skips = [closers[index]]
        elif conditional and index not in closers:
            skips = [index + 1]
        if index in loop_backs:
            skips.append(loop_backs[index])
        flow.append(
            _FlowLine(
                _flow_ops(line),
                (
                    _flow_chain_end(lines, closers, closers[index])
                    if is_else_open and index in closers
                    else index + 1
                ),
                tuple(skips),
                conditional and not _flow_expands_after_scope_close(line),
                depth[index] > 0,
            )
        )
    return flow


def _flow_apply_scope(state: _FlowState, ops: Tuple[_FlowOp, ...]) -> _FlowState:
    """Return the scope stack after a line's SETLOCAL and ENDLOCAL operations."""
    for kind, mode in ops:
        if kind == "setlocal":
            inherited: Optional[bool] = state[-1] if state else False
            value = {"enable": True, "disable": False}.get(mode, inherited)
            state = (*state, value)
        elif kind == "endlocal" and state and state[-1] is not None:
            state = state[:-1]
    return state


def _flow_is_closed(state: _FlowState) -> bool:
    """Return True when delayed expansion is known to be off in this scope stack."""
    return not state or state[-1] is False


def _flow_label_line(labels: Dict[str, List[int]], target: str, index: int) -> int:
    """Return the line a jump from ``index`` to ``target`` reaches, or -1 if none.

    cmd.exe searches for the label forward from the jump, then from the top of
    the file, so with a label defined twice the first one below the jump wins.
    """
    found = labels.get(target)
    if not found:
        return -1
    after = bisect.bisect_right(found, index)
    return found[after] if after < len(found) else found[0]


def _flow_targets(
    ops: Tuple[_FlowOp, ...], labels: Dict[str, List[int]], index: int
) -> Tuple[List[int], bool, bool]:
    """Return the labels a line jumps to, whether a jump is computed, and if the path ends."""
    targets: List[int] = []
    computed = False
    ended = False
    for kind, target in ops:
        if kind in ("goto", "call"):
            if "%" in target or "!" in target:
                computed = True
            elif _flow_label_line(labels, target, index) >= 0:
                targets.append(_flow_label_line(labels, target, index))
            ended = ended or kind == "goto"
        ended = ended or kind == "end"
    return targets, computed, ended


def _flow_labels(lines: List[str]) -> Dict[str, List[int]]:
    """Map each label to the lines that define it, in order."""
    labels: Dict[str, List[int]] = {}
    for index, line in enumerate(lines):
        match = _FLOW_LABEL_RE.match(line)
        if match:
            labels.setdefault(str(match.group(1)).lower(), []).append(index)
    return labels


def _flow_closed_lines(lines: List[str]) -> Optional[List[Optional[bool]]]:
    """Return, per line, whether some path runs it with delayed expansion off.

    A line no path reaches is None. A computed jump reaches every label with the
    scope of the path that jumps. A CALL returns with the caller's scope
    unchanged. Returns None for unbalanced blocks, too many scope states on a
    line or at computed jumps, or a jump to a label inside a block.
    """
    flow = _flow_lines(lines)
    if flow is None:
        return None
    labels = _flow_labels(lines)
    block_labels = {
        line for found in labels.values() for line in found if flow[line].in_block
    }
    seen: List[Set[_FlowState]] = [set() for _ in lines]
    closed = [False] * len(lines)
    computed_states: Set[_FlowState] = set()
    pending: List[Tuple[int, _FlowState]] = [(0, ())]
    while pending:
        index, state = pending.pop()
        if index >= len(lines) or state in seen[index]:
            continue
        seen[index].add(state)
        if len(seen[index]) > _MAX_FLOW_STATES_PER_LINE:
            return None
        entry = flow[index]
        after = _flow_apply_scope(state, entry.ops)
        closed[index] = closed[index] or (
            _flow_is_closed(after) and (not entry.conditional or _flow_is_closed(state))
        )
        targets, computed, ended = _flow_targets(entry.ops, labels, index)
        if block_labels.intersection(targets) or (computed and block_labels):
            # cmd.exe runs what follows such a label in ways the walk does not model.
            return None
        pending.extend((target, after) for target in targets)
        pending.extend((skip, state) for skip in entry.skips)
        if computed and after not in computed_states:
            # A computed jump may reach any label, once per scope state.
            computed_states.add(after)
            if len(computed_states) > _MAX_FLOW_STATES_PER_LINE:
                return None
            pending.extend(
                (target, after) for found in labels.values() for target in found
            )
        if not ended:
            pending.append((entry.next_index, after))
    return [
        is_closed if states else None
        for is_closed, states in zip(closed, seen, strict=True)
    ]


def _delayed_expansion_closed_for_lines(lines: List[str]) -> List[bool]:
    """Return, per line, whether delayed expansion is off for P008, cached per lint pass.

    A line is closed where the linear state says so, unless the walk reaches the
    line and finds no path that runs it with delayed expansion off. So following
    the paths can remove a finding but never add one, and a line the walk never
    reaches, or a file it gives up on, keeps the linear state.
    """

    def build() -> List[bool]:
        linear = _build_delayed_expansion_state(lines)
        walked = _flow_closed_lines(lines)
        if walked is None:
            return [not active for active in linear]
        return [
            not active and on_path is not False
            for on_path, active in zip(walked, linear, strict=True)
        ]

    return _identity_cached(_delayed_expansion_flow_cache_var.get(), lines, build)


def _delayed_expansion_active_at_line(lines: List[str], line_num: int) -> bool:
    """Return whether P008 should treat delayed expansion as on at a 1-based line."""
    if line_num < 1 or line_num > len(lines):
        return False
    return not _delayed_expansion_closed_for_lines(lines)[line_num - 1]


def _analyze_script_structure(
    lines: List[str],
) -> Tuple[bool, bool, bool, bool, bool, bool, bool]:
    """Analyze script structure for context-aware checking.

    Returns:
        Tuple of (has_setlocal, has_set_commands, has_delayed_expansion, uses_delayed_vars,
                  has_disable_delayed_expansion, has_literal_exclamations, disable_expansion_lines)
    """
    has_setlocal = any(_is_setlocal_command(line) for line in lines)
    has_set_commands = any(
        re.match(r"\s*set\s+[^=]+=.*", line, re.IGNORECASE) for line in lines
    )
    has_delayed_expansion = any(
        _is_setlocal_command(line) and "enabledelayedexpansion" in line.lower()
        for line in lines
    )
    # Match any content between exclamation marks, including special chars like @, -, #, $, etc.
    # that are commonly used in batch variable names (e.g., !@DEBUG_MODE!, !@CRLF-%~1!)
    uses_delayed_vars = any(re.search(r"![^!]+!", line) for line in lines)

    # Check for SETLOCAL DISABLEDELAYEDEXPANSION usage
    has_disable_delayed_expansion = any(
        _COMPILED_SETLOCAL_DISABLE.search(line) for line in lines
    )

    # Check for literal ! characters in strings (not delayed expansion variables)
    # Look for ! characters that are NOT part of delayed expansion !var! patterns
    # Use negative lookbehind (?<![^\s]) and negative lookahead (?![^\s!]) to match standalone !
    has_literal_exclamations = False
    for line in lines:
        # Remove all delayed expansion patterns first
        cleaned = re.sub(r"![^!\s]+!", "", line)
        # Now check if there are any remaining ! characters in echo/set statements
        if re.search(r"(echo|set\s+\w+=).*!", cleaned, re.IGNORECASE):
            has_literal_exclamations = True
            break

    # Track whether any line uses disabledelayedexpansion
    has_disable_expansion_lines = any(
        _COMPILED_SETLOCAL_DISABLE.search(line) for line in lines
    )

    return (
        has_setlocal,
        has_set_commands,
        has_delayed_expansion,
        uses_delayed_vars,
        has_disable_delayed_expansion,
        has_literal_exclamations,
        has_disable_expansion_lines,
    )
