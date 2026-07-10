from __future__ import annotations

import html
import mimetypes
import re
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from .exam_templates import (
    ANSWER_SHEET_TITLE,
    ExamTemplate,
    answer_blank_text,
    explanation_entries,
    format_answer,
    get_template,
    needs_answer_blank,
    quick_answer_lines,
    resolve_export_title,
)
from . import storage
from .math_text import normalize_math_token, split_math_text, strip_math_delimiters


SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
PARA_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HEAD_NS = "http://www.hancom.co.kr/hwpml/2011/head"
CORE_NS = "http://www.hancom.co.kr/hwpml/2011/core"


# XML 1.0에서 허용되지 않는 문자(제어문자·lone surrogate 등). PDF/HWP에서 추출한
# 텍스트에 섞여 들어오면 남겨둘 경우 한글이 파일 열기를 거부하므로 제거한다.
_XML_ILLEGAL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _esc(value: Any) -> str:
    text = _XML_ILLEGAL_RE.sub("", str(value or ""))
    return html.escape(text, quote=True)


def _read_command(source: str, index: int) -> tuple[str, int] | None:
    if index >= len(source) or source[index] != "\\":
        return None
    cursor = index + 1
    while cursor < len(source) and source[cursor].isalpha():
        cursor += 1
    if cursor == index + 1:
        return source[index + 1 : index + 2], min(len(source), index + 2)
    return source[index + 1 : cursor], cursor


def _read_braced(source: str, index: int) -> tuple[str, int] | None:
    if index >= len(source) or source[index] != "{":
        return None
    depth = 0
    start = index + 1
    cursor = index
    while cursor < len(source):
        char = source[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:cursor], cursor + 1
        cursor += 1
    return None


def _read_bracketed(source: str, index: int) -> tuple[str, int] | None:
    if index >= len(source) or source[index] != "[":
        return None
    depth = 0
    start = index + 1
    cursor = index
    while cursor < len(source):
        char = source[cursor]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return source[start:cursor], cursor + 1
        cursor += 1
    return None


def _read_parenthesized(source: str, index: int) -> tuple[str, int] | None:
    if index >= len(source) or source[index] != "(":
        return None
    depth = 0
    start = index + 1
    cursor = index
    while cursor < len(source):
        char = source[cursor]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[start:cursor], cursor + 1
        cursor += 1
    return None


def _skip_spaces(source: str, index: int) -> int:
    cursor = index
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    return cursor


def _read_latex_arg(source: str, index: int) -> tuple[str, int] | None:
    cursor = _skip_spaces(source, index)
    braced = _read_braced(source, cursor)
    if braced is not None:
        return braced
    command = _read_command(source, cursor)
    if command is not None:
        return source[cursor : command[1]], command[1]
    if cursor < len(source):
        return source[cursor : cursor + 1], cursor + 1
    return None


def _read_latex_delimiter(source: str, index: int) -> tuple[str, int] | None:
    cursor = _skip_spaces(source, index)
    if cursor >= len(source):
        return None
    named = {
        r"\{": "{",
        r"\}": "}",
        r"\langle": "〈",
        r"\rangle": "〉",
        r"\lceil": "⌈",
        r"\rceil": "⌉",
        r"\lfloor": "⌊",
        r"\rfloor": "⌋",
        r"\lvert": "|",
        r"\rvert": "|",
        r"\lVert": "∥",
        r"\rVert": "∥",
        r"\|": "∥",
    }
    for token, value in named.items():
        if source.startswith(token, cursor):
            return value, cursor + len(token)
    if source[cursor] == "\\" and cursor + 1 < len(source):
        return source[cursor + 1], cursor + 2
    return source[cursor], cursor + 1


def _read_left_right(source: str, index: int) -> tuple[str, str, str, int] | None:
    command = _read_command(source, index)
    if command is None or command[0] != "left":
        return None
    begin = _read_latex_delimiter(source, command[1])
    if begin is None:
        return None
    begin_token, body_start = begin
    depth = 1
    cursor = body_start
    while cursor < len(source):
        nested = _read_command(source, cursor)
        if nested is not None and nested[0] == "left":
            depth += 1
            cursor = nested[1]
            continue
        if nested is not None and nested[0] == "right":
            depth -= 1
            if depth == 0:
                end = _read_latex_delimiter(source, nested[1])
                if end is None:
                    return None
                end_token, end_cursor = end
                return begin_token, source[body_start:cursor], end_token, end_cursor
            cursor = nested[1]
            continue
        cursor += 1
    return None


def _read_environment(source: str, index: int) -> tuple[str, str, int] | None:
    command = _read_command(source, index)
    if command is None or command[0] != "begin":
        return None
    env = _read_braced(source, command[1])
    if env is None:
        return None
    env_name, body_start = env
    end_token = rf"\end{{{env_name}}}"
    end_index = source.find(end_token, body_start)
    if end_index < 0:
        return None
    return env_name, source[body_start:end_index], end_index + len(end_token)


def _split_latex_rows(body: str) -> list[str]:
    rows: list[str] = []
    start = 0
    depth = 0
    cursor = 0
    while cursor < len(body):
        char = body[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "\\" and cursor + 1 < len(body) and body[cursor + 1] == "\\" and depth == 0:
            rows.append(body[start:cursor].strip())
            cursor += 2
            start = cursor
            continue
        cursor += 1
    rows.append(body[start:].strip())
    return [row for row in rows if row]


def _split_latex_columns(row: str) -> list[str]:
    columns: list[str] = []
    start = 0
    depth = 0
    cursor = 0
    while cursor < len(row):
        char = row[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "&" and depth == 0:
            columns.append(row[start:cursor].strip())
            start = cursor + 1
        cursor += 1
    columns.append(row[start:].strip())
    return columns


def _display_delimiter(token: str) -> str:
    return "" if token == "." else token


def _strip_array_alignment(env: str, body: str) -> str:
    if env != "array":
        return body
    cursor = 0
    while cursor < len(body) and body[cursor].isspace():
        cursor += 1
    alignment = _read_braced(body, cursor)
    if alignment is None:
        return body
    return body[alignment[1] :].lstrip()


def _hancom_environment_script(env_name: str, body: str) -> str | None:
    env = env_name.rstrip("*")
    command = {
        "matrix": "matrix",
        "array": "matrix",
        "pmatrix": "pmatrix",
        "bmatrix": "bmatrix",
        "vmatrix": "dmatrix",
        "Vmatrix": "dmatrix",
        "cases": "cases",
        "aligned": "eqalign",
        "align": "eqalign",
        "gathered": "eqalign",
        "split": "eqalign",
    }.get(env)
    if command is None:
        return None
    body = _strip_array_alignment(env, body)
    row_scripts: list[str] = []
    for row in _split_latex_rows(body):
        cell_scripts = []
        for cell in _split_latex_columns(row):
            cell_scripts.append(_hancom_eqn_script(cell) or cell.strip())
        row_scripts.append(" & ".join(cell_scripts))
    if not row_scripts:
        return None
    return f"{command}{{" + " # ".join(row_scripts) + "}"


_RADICAL_ATOM_RE = re.compile(
    r"[a-zA-Zα-ωΑ-Ω][a-zA-Z0-9α-ωΑ-Ω]*(?:[_^](?:\{[^{}\n]{1,80}\}|[a-zA-Z0-9]+))*"
    r"|[+\-]?\d+(?:\.\d+)?"
)


def _read_radical_arg(source: str, index: int) -> tuple[str, int] | None:
    cursor = index
    while cursor < len(source) and (source[cursor].isspace() or source[cursor] in {"□", "▢"}):
        cursor += 1
    braced = _read_braced(source, cursor)
    if braced is not None:
        return braced
    parenthesized = _read_parenthesized(source, cursor)
    if parenthesized is not None:
        return parenthesized
    match = _RADICAL_ATOM_RE.match(source, cursor)
    if match:
        return match.group(0), match.end()
    return None


def _skip_radical_fillers(source: str, index: int) -> int:
    cursor = index
    while cursor < len(source) and (source[cursor].isspace() or source[cursor] in {"□", "▢"}):
        cursor += 1
    return cursor


def _read_script_arg(source: str, index: int) -> tuple[str, int]:
    braced = _read_braced(source, index)
    if braced is not None:
        return braced
    command = _read_command(source, index)
    if command is not None:
        name, end = command
        return _EQN_COMMANDS.get(name, "\\" + name), end
    return source[index : index + 1], min(len(source), index + 1)


_GREEK_EQN_COMMANDS = {
    "alpha": "alpha",
    "beta": "beta",
    "gamma": "gamma",
    "delta": "delta",
    "epsilon": "epsilon",
    "varepsilon": "epsilon",
    "zeta": "zeta",
    "eta": "eta",
    "theta": "theta",
    "vartheta": "theta",
    "iota": "iota",
    "kappa": "kappa",
    "lambda": "lambda",
    "mu": "mu",
    "nu": "nu",
    "xi": "xi",
    "pi": "pi",
    "varpi": "pi",
    "rho": "rho",
    "varrho": "rho",
    "sigma": "sigma",
    "varsigma": "sigma",
    "tau": "tau",
    "upsilon": "upsilon",
    "phi": "phi",
    "varphi": "phi",
    "chi": "chi",
    "psi": "psi",
    "omega": "omega",
    "Gamma": "GAMMA",
    "Delta": "DELTA",
    "Theta": "THETA",
    "Lambda": "LAMBDA",
    "Xi": "XI",
    "Pi": "PI",
    "Sigma": "SIGMA",
    "Upsilon": "UPSILON",
    "Phi": "PHI",
    "Psi": "PSI",
    "Omega": "OMEGA",
}


_UNICODE_GREEK_EQN = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "ϵ": "epsilon",
    "ζ": "zeta",
    "η": "eta",
    "θ": "theta",
    "ϑ": "theta",
    "ι": "iota",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "ξ": "xi",
    "π": "pi",
    "ϖ": "pi",
    "ρ": "rho",
    "ϱ": "rho",
    "σ": "sigma",
    "ς": "sigma",
    "τ": "tau",
    "υ": "upsilon",
    "φ": "phi",
    "ϕ": "phi",
    "χ": "chi",
    "ψ": "psi",
    "ω": "omega",
    "Α": "ALPHA",
    "Β": "BETA",
    "Γ": "GAMMA",
    "Δ": "DELTA",
    "Ε": "EPSILON",
    "Ζ": "ZETA",
    "Η": "ETA",
    "Θ": "THETA",
    "Ι": "IOTA",
    "Κ": "KAPPA",
    "Λ": "LAMBDA",
    "Μ": "MU",
    "Ν": "NU",
    "Ξ": "XI",
    "Ο": "OMICRON",
    "Π": "PI",
    "Ρ": "RHO",
    "Σ": "SIGMA",
    "Τ": "TAU",
    "Υ": "UPSILON",
    "Φ": "PHI",
    "Χ": "CHI",
    "Ψ": "PSI",
    "Ω": "OMEGA",
}


_EQN_COMMANDS = {
    **_GREEK_EQN_COMMANDS,
    "nabla": "nabla",
    "partial": "Partial",
    "le": "<=",
    "leq": "<=",
    "ge": ">=",
    "geq": ">=",
    "ne": "!=",
    "neq": "!=",
    "approx": "approx",
    "sim": "SIM",
    "simeq": "SIMEQ",
    "cong": "CONG",
    "equiv": "==",
    "propto": "PROPTO",
    "asymp": "ASYMP",
    "ll": "<<",
    "gg": ">>",
    "lll": "<<<",
    "ggg": ">>>",
    "prec": "PREC",
    "succ": "SUCC",
    "times": "times",
    "cdot": "cdot",
    "div": "div",
    "pm": "+-",
    "mp": "-+",
    "infty": "inf",
    "infinity": "inf",
    "emptyset": "EMPTYSET",
    "varnothing": "EMPTYSET",
    "forall": "FORALL",
    "exists": "EXIST",
    "in": "∈",
    "notin": "∉",
    "cup": "∪",
    "cap": "∩",
    "oplus": "OPLUS",
    "ominus": "OMINUS",
    "otimes": "OTIMES",
    "oslash": "ODIV",
    "odot": "ODOT",
    "lor": "LOR",
    "land": "LAND",
    "subset": "⊂",
    "supset": "⊃",
    "subseteq": "⊆",
    "supseteq": "⊇",
    "circ": "∘",
    "mid": "|",
    "vert": "|",
    "lvert": "|",
    "rvert": "|",
    "lVert": "||",
    "rVert": "||",
    "cdots": "⋯",
    "ldots": "…",
    "angle": "angle",
    "triangle": "triangle",
    "parallel": "parallel",
    "perp": "perp",
    "because": "because",
    "therefore": "therefore",
    "to": "->",
    "rightarrow": "->",
    "longrightarrow": "->",
    "leftarrow": "larrow",
    "longleftarrow": "larrow",
    "leftrightarrow": "<->",
    "longleftrightarrow": "<->",
    "Rightarrow": "RARROW",
    "Longrightarrow": "RARROW",
    "Leftarrow": "LARROW",
    "Longleftarrow": "LARROW",
    "Leftrightarrow": "LRARROW",
    "Longleftrightarrow": "LRARROW",
    "uparrow": "uparrow",
    "downarrow": "downarrow",
    "Uparrow": "UPARROW",
    "Downarrow": "DOWNARROW",
    "updownarrow": "udarrow",
    "Updownarrow": "UDARROW",
    "mapsto": "MAPSTO",
    "hookleftarrow": "HOOKLEFT",
    "hookrightarrow": "HOOKRIGHT",
    "nearrow": "NEARROW",
    "nwarrow": "NWARROW",
    "searrow": "SEARROW",
    "swarrow": "SWARROW",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "arcsin": "arcsin",
    "arccos": "arccos",
    "arctan": "arctan",
    "sinh": "sinh",
    "cosh": "cosh",
    "tanh": "tanh",
    "sec": "sec",
    "csc": "csc",
    "cot": "cot",
    "log": "log",
    "ln": "ln",
    "lim": "lim",
    "min": "min",
    "max": "max",
    "arg": "arg",
    "argmin": "argmin",
    "argmax": "argmax",
    "exp": "exp",
    "det": "det",
    "gcd": "gcd",
    "lcm": "lcm",
    "Pr": "Pr",
    "lceil": "⌈",
    "rceil": "⌉",
    "lfloor": "⌊",
    "rfloor": "⌋",
    "langle": "〈",
    "rangle": "〉",
}


_NARY_EQN = {
    "sum": "sum",
    "prod": "prod",
    "int": "int",
    "iint": "dint",
    "iiint": "tint",
    "oint": "oint",
}
_FUNCTION_COMMANDS = {
    "sin",
    "cos",
    "tan",
    "arcsin",
    "arccos",
    "arctan",
    "sinh",
    "cosh",
    "tanh",
    "sec",
    "csc",
    "cot",
    "log",
    "ln",
    "min",
    "max",
    "arg",
    "argmin",
    "argmax",
    "exp",
    "det",
    "gcd",
    "lcm",
    "Pr",
}
_LATEX_SPACING_COMMANDS = {
    ",",
    ":",
    ";",
    " ",
    "quad",
    "qquad",
    "enspace",
    "thinspace",
    "medspace",
    "thickspace",
}
_LATEX_NEGATIVE_SPACING_COMMANDS = {"!"}
_LATEX_IGNORED_COMMANDS = {
    "limits",
    "nolimits",
    "displaystyle",
    "textstyle",
    "scriptstyle",
    "scriptscriptstyle",
}
_LATEX_DELIMITER_SIZE_COMMANDS = {
    "big",
    "Big",
    "bigg",
    "Bigg",
    "bigl",
    "bigr",
    "Bigl",
    "Bigr",
    "biggl",
    "biggr",
    "Biggl",
    "Biggr",
}
_NEGATED_COMMANDS = {
    "in": "∉",
    "subset": "⊄",
    "supset": "⊅",
    "subseteq": "⊈",
    "supseteq": "⊉",
    "=": "!=",
}
_ACCENT_EQN = {
    "overline": "bar",
    "bar": "bar",
    "underline": "under",
    "vec": "vec",
    "overrightarrow": "vec",
    "overleftrightarrow": "dyad",
    "widehat": "hat",
    "hat": "hat",
    "widetilde": "tilde",
    "tilde": "tilde",
    "acute": "acute",
    "grave": "grave",
    "dot": "dot",
    "ddot": "ddot",
    "check": "check",
}
_TEXT_WRAPPER_COMMANDS = {
    "mathrm",
    "mathbf",
    "text",
    "operatorname",
    "mathcal",
    "mathsf",
    "mathtt",
    "mathit",
    "mathnormal",
    "boldsymbol",
}
_MATHBB_MAP = str.maketrans(
    {
        "N": "ℕ",
        "Z": "ℤ",
        "Q": "ℚ",
        "R": "ℝ",
        "C": "ℂ",
    }
)
_EQN_SPACED_TOKENS = {
    "SIM",
    "SIMEQ",
    "CONG",
    "PROPTO",
    "ASYMP",
    "PREC",
    "SUCC",
    "OPLUS",
    "OMINUS",
    "OTIMES",
    "ODIV",
    "ODOT",
    "LOR",
    "LAND",
    "FORALL",
    "EXIST",
    "EMPTYSET",
    "larrow",
    "<->",
    "RARROW",
    "LARROW",
    "LRARROW",
    "uparrow",
    "downarrow",
    "UPARROW",
    "DOWNARROW",
    "udarrow",
    "UDARROW",
    "MAPSTO",
    "HOOKLEFT",
    "HOOKRIGHT",
    "NEARROW",
    "NWARROW",
    "SEARROW",
    "SWARROW",
    "times",
    "cdot",
    "div",
    "approx",
    "angle",
    "triangle",
    "parallel",
    "perp",
    "because",
    "therefore",
}


def _append_eqn_token(output: list[str], token: str, source: str, next_cursor: int) -> None:
    if token not in _EQN_SPACED_TOKENS:
        output.append(token)
        return
    if output:
        previous = output[-1]
        if previous and not previous.endswith((" ", "(", "[", "{")) and previous[-1] not in "+-*/=<>^_":
            output.append(" ")
    output.append(token)
    if next_cursor < len(source):
        next_char = source[next_cursor]
        if not next_char.isspace() and next_char not in ".,;:)]}+-*/=<>^_":
            output.append(" ")


def _normalize_hancom_eqn_script(script: str) -> str:
    value = str(script or "").strip()
    if not value:
        return value
    output: list[str] = []
    cursor = 0
    while cursor < len(value):
        if value.startswith("sqrt", cursor) and (
            cursor == 0 or not value[cursor - 1].isalpha()
        ):
            base = _read_radical_arg(value, cursor + 4)
            if base is not None:
                output.append(f"sqrt {{{base[0].strip()}}}")
                cursor = base[1]
                continue
            output.append("sqrt {□}")
            cursor = _skip_radical_fillers(value, cursor + 4)
            continue
        output.append(value[cursor])
        cursor += 1
    return "".join(output)


def _is_hancom_eqn_script(expr: str) -> bool:
    value = str(expr or "").strip()
    if not value or "\\" in value:
        return False
    markers = (
        "`",
        " LEFT ",
        " RIGHT ",
        " left",
        " right",
        "over",
        "root",
        "sqrt",
        " of ",
        "cases{",
        "eqalign{",
        "matrix{",
        "pmatrix{",
        "bmatrix{",
        "rm ",
        "rm{",
        "prime",
        "rarrow",
        "GEQ",
        "LEQ",
        "INF",
        "TIMES",
    )
    return any(marker in value for marker in markers)


def _hancom_eqn_script(source: str) -> str | None:
    expr = normalize_math_token(strip_math_delimiters(source)).strip()
    if not expr:
        return None
    if _is_hancom_eqn_script(expr):
        return _normalize_hancom_eqn_script(expr)
    output: list[str] = []
    cursor = 0
    while cursor < len(expr):
        char = expr[cursor]
        if char.isspace():
            output.append(" ")
            cursor += 1
            continue
        command = _read_command(expr, cursor)
        if command is not None:
            name, next_cursor = command
            if name in _LATEX_SPACING_COMMANDS:
                if output and not output[-1].endswith(" "):
                    output.append(" ")
                cursor = next_cursor
                continue
            if name in _LATEX_NEGATIVE_SPACING_COMMANDS or name in _LATEX_IGNORED_COMMANDS:
                cursor = next_cursor
                continue
            if name in _LATEX_DELIMITER_SIZE_COMMANDS:
                delimiter = _read_latex_delimiter(expr, next_cursor)
                if delimiter is None:
                    return None
                token, cursor = delimiter
                output.append(_display_delimiter(token))
                continue
            if name == "not":
                lookahead = _skip_spaces(expr, next_cursor)
                negated = _read_command(expr, lookahead)
                if negated is not None and negated[0] in _NEGATED_COMMANDS:
                    output.append(_NEGATED_COMMANDS[negated[0]])
                    cursor = negated[1]
                    continue
                if lookahead < len(expr) and expr[lookahead] in _NEGATED_COMMANDS:
                    output.append(_NEGATED_COMMANDS[expr[lookahead]])
                    cursor = lookahead + 1
                    continue
                output.append("not")
                cursor = next_cursor
                continue
            if name in {"pmod", "pod"}:
                modulus = _read_latex_arg(expr, next_cursor)
                if modulus is None:
                    return None
                body = _hancom_eqn_script(modulus[0]) or modulus[0].strip()
                output.append(f" mod {body}")
                cursor = modulus[1]
                continue
            if name == "bmod":
                output.append(" mod ")
                cursor = next_cursor
                continue
            if name == "begin":
                environment = _read_environment(expr, cursor)
                if environment is None:
                    return None
                env_name, body, cursor = environment
                script = _hancom_environment_script(env_name, body)
                if script is None:
                    return None
                output.append(script)
                continue
            if name == "left":
                wrapped = _read_left_right(expr, cursor)
                if wrapped is None:
                    return None
                begin_token, body, end_token, cursor = wrapped
                body_script = _hancom_eqn_script(body)
                if body_script is None:
                    return None
                output.append(f"{_display_delimiter(begin_token)}{body_script}{_display_delimiter(end_token)}")
                continue
            if name in {"frac", "dfrac", "tfrac"}:
                numerator = _read_latex_arg(expr, next_cursor)
                if numerator is None:
                    return None
                denominator = _read_latex_arg(expr, numerator[1])
                if denominator is None:
                    return None
                num = _hancom_eqn_script(numerator[0])
                den = _hancom_eqn_script(denominator[0])
                if num is None or den is None:
                    return None
                output.append(f"{{{num}}} over {{{den}}}")
                cursor = denominator[1]
                continue
            if name == "sqrt":
                bracketed = _read_bracketed(expr, next_cursor)
                if bracketed is not None:
                    base = _read_braced(expr, bracketed[1])
                    if base is None:
                        return None
                    degree = _hancom_eqn_script(bracketed[0]) or bracketed[0].strip()
                    body = _hancom_eqn_script(base[0])
                    if body is None:
                        return None
                    output.append(f"^{degree}sqrt {{{body}}}")
                    cursor = base[1]
                    continue
                base = _read_braced(expr, next_cursor) or _read_radical_arg(expr, next_cursor)
                if base is None:
                    return None
                body = _hancom_eqn_script(base[0])
                if body is None:
                    return None
                output.append(f"sqrt {{{body}}}")
                cursor = base[1]
                continue
            if name in {"binom", "dbinom", "tbinom"}:
                top = _read_latex_arg(expr, next_cursor)
                if top is None:
                    return None
                bottom = _read_latex_arg(expr, top[1])
                if bottom is None:
                    return None
                upper = _hancom_eqn_script(top[0]) or top[0].strip()
                lower = _hancom_eqn_script(bottom[0]) or bottom[0].strip()
                output.append(f"{{{upper}}} choose {{{lower}}}")
                cursor = bottom[1]
                continue
            if name in {"boxed", "fbox"}:
                base = _read_braced(expr, next_cursor)
                if base is None:
                    return None
                body = _hancom_eqn_script(base[0])
                output.append(f"BOX {{{body}}}" if body is not None else f"BOX {{{base[0].strip()}}}")
                cursor = base[1]
                continue
            if name in {"overbrace", "underbrace"}:
                base = _read_braced(expr, next_cursor)
                if base is None:
                    return None
                body = _hancom_eqn_script(base[0])
                command_name = "OVERBRACE" if name == "overbrace" else "UNDERBRACE"
                output.append(
                    f"{command_name} {{{body}}}" if body is not None else f"{command_name} {{{base[0].strip()}}}"
                )
                cursor = base[1]
                continue
            if name in _ACCENT_EQN:
                base = _read_braced(expr, next_cursor)
                if base is None:
                    return None
                body = _hancom_eqn_script(base[0])
                command_name = _ACCENT_EQN[name]
                output.append(f"{command_name} {{{body}}}" if body is not None else f"{command_name} {{{base[0]}}}")
                cursor = base[1]
                continue
            if name in _TEXT_WRAPPER_COMMANDS:
                base = _read_braced(expr, next_cursor)
                if base is None:
                    return None
                body = _hancom_eqn_script(base[0])
                output.append(body if body is not None else base[0].strip())
                cursor = base[1]
                continue
            if name == "mathbb":
                base = _read_braced(expr, next_cursor)
                if base is None:
                    return None
                output.append(base[0].translate(_MATHBB_MAP))
                cursor = base[1]
                continue
            if name in _NARY_EQN:
                output.append(_NARY_EQN[name])
                cursor = next_cursor
                continue
            if name in _EQN_COMMANDS:
                _append_eqn_token(output, _EQN_COMMANDS[name], expr, next_cursor)
                if name in _FUNCTION_COMMANDS and next_cursor < len(expr) and expr[next_cursor] == "\\":
                    output.append(" ")
                cursor = next_cursor
                continue
            return None
        if char == "{":
            braced = _read_braced(expr, cursor)
            if braced is not None:
                if not braced[0].strip():
                    output.append("{}")
                else:
                    body = _hancom_eqn_script(braced[0])
                    output.append(body if body is not None else braced[0].strip())
                cursor = braced[1]
                continue
        if char in "^_":
            value, cursor = _read_script_arg(expr, cursor + 1)
            body = _hancom_eqn_script(value) or value
            output.append(("^" if char == "^" else "_") + "{" + body + "}")
            continue
        if char == "√":
            base = _read_radical_arg(expr, cursor + 1)
            if base is None:
                output.append("sqrt {□}")
                cursor = _skip_radical_fillers(expr, cursor + 1)
                continue
            body = _hancom_eqn_script(base[0]) or base[0]
            output.append(f"sqrt {{{body}}}")
            cursor = base[1]
            continue
        mapped = {
            "≤": "<=",
            "≥": ">=",
            "≠": "!=",
            "×": "times",
            "÷": "div",
            "±": "+-",
            "∓": "-+",
            "∈": "∈",
            "∉": "∉",
            "∪": "∪",
            "∩": "∩",
            "⊂": "⊂",
            "⊃": "⊃",
            "⊆": "⊆",
            "⊇": "⊇",
            "∘": "∘",
            "∑": "sum",
            "∏": "prod",
            "∫": "int",
            "∞": "inf",
            "≈": "approx",
            "∠": "angle",
            "△": "triangle",
            "∥": "parallel",
            "⊥": "perp",
            "∵": "because",
            "∴": "therefore",
            **_UNICODE_GREEK_EQN,
        }.get(char)
        output.append(mapped if mapped is not None else char)
        cursor += 1
    return _normalize_hancom_eqn_script("".join(output).strip())


_EQN_WORD_OPERATORS = {
    "TIMES": "*",
    "LEQ": "<=",
    "GEQ": ">=",
    "NEQ": "!=",
    "APPROX": "~",
}


def _equation_visual_units(script: str) -> int:
    text = str(script or "")
    text = text.replace("`", "").replace("~", " ")
    text = re.sub(r"\b(?:LEFT|RIGHT|left|right)\b\s*", "", text)
    text = re.sub(r"\b(?:rm|it)\b\s*", "", text)
    for word, operator in _EQN_WORD_OPERATORS.items():
        text = re.sub(rf"\b{word}\b", operator, text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\{\s*([^{}]+?)\s*\}\s+over\s+\{\s*([^{}]+?)\s*\}", r"\1/\2", text)
        text = re.sub(r"sqrt\s*\{\s*([^{}]+?)\s*\}", r"√\1", text)
    text = re.sub(r"\^\{\s*([^{}]+?)\s*\}", r"^\1", text)
    text = re.sub(r"_\{\s*([^{}]+?)\s*\}", r"_\1", text)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\s+", "", text)
    return max(1, len(text))


def _equation_size(script: str) -> tuple[int, int]:
    text = str(script or "")
    width = max(900, min(24000, 800 + _equation_visual_units(text) * 600))
    height = 1300
    if " over " in text or "sqrt" in text or "choose" in text:
        height = 2100
    if any(token in text for token in ("int", "dint", "tint", "oint", "sum", "prod", "lim")):
        height = max(height, 2300)
    if any(token in text for token in ("int_", "dint_", "tint_", "oint_", "sum_", "prod_", "lim_")) or ("^{" in text and "_" in text):
        height = max(height, 2700)
    if len(text) > 90:
        height = max(height, 1900)
    if any(token in text for token in ("matrix{", "pmatrix{", "bmatrix{", "cases{", "eqalign{")):
        row_count = max(2, text.count("#") + 1)
        height = max(height, 1500 + row_count * 1050)
    return width, min(height, 6200)


def _equation_placeholder(script: str) -> str:
    width, _ = _equation_size(script)
    return " " * max(2, min(36, width // 550))


def _native_math_height(text: str) -> int:
    height = 0
    for segment, is_math in split_math_text(text):
        if not is_math:
            continue
        script = _hancom_eqn_script(segment)
        if script:
            height = max(height, _equation_size(script)[1])
    return height


def _equation_xml(script: str, instance: int) -> str:
    placeholder = _equation_placeholder(script)
    return f"""<hp:equation id="{1000000000 + instance}" zOrder="{instance}" numberingType="EQUATION" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" version="Equation Version 60" baseLine="0" textColor="#000000" baseUnit="1000" lineMode="CHAR" font="HancomEQN">
        <hp:sz width="0" widthRelTo="ABSOLUTE" height="0" heightRelTo="ABSOLUTE" protect="0"/>
        <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
        <hp:outMargin left="56" right="56" top="0" bottom="0"/>
        <hp:shapeComment>수식입니다.</hp:shapeComment>
        <hp:script>{_esc(script)}</hp:script>
      </hp:equation><hp:t xml:space="preserve">{placeholder}</hp:t>"""


def _text_runs(
    text: str,
    char_pr: int = 0,
    *,
    native_math: bool = False,
    equation_counter: list[int] | None = None,
) -> list[str]:
    runs: list[str] = []
    for segment, is_math in split_math_text(text):
        if native_math and is_math and equation_counter is not None:
            script = _hancom_eqn_script(segment)
            if script:
                equation_counter[0] += 1
                runs.append(f'<hp:run charPrIDRef="{char_pr}">{_equation_xml(script, equation_counter[0])}</hp:run>')
                continue
        run_char_pr = MATH_CHAR_PR if is_math and char_pr in {0, 3, 4} else char_pr
        runs.append(
            f'<hp:run charPrIDRef="{run_char_pr}"><hp:t xml:space="preserve">{_esc(segment)}</hp:t></hp:run>'
        )
    return runs


# header.xml의 charPr id별 글자 크기 (lineseg 계산용)
MATH_CHAR_PR = 5
CHAR_HEIGHTS = {0: 1000, 1: 1600, 2: 1150, 3: 1250, 4: 900, MATH_CHAR_PR: 1000}


def _paragraph(
    text: str,
    pid: int,
    char_pr: int = 0,
    para_pr: int = 0,
    extra_run: str = "",
    page_break: bool = False,
    native_math: bool = False,
    equation_counter: list[int] | None = None,
) -> str:
    raw_text = _XML_ILLEGAL_RE.sub("", str(text or "")) or " "
    height = CHAR_HEIGHTS.get(char_pr, 1000)
    if native_math:
        height = max(height, _native_math_height(raw_text))
    # extra_run: 첫 문단 run에 들어가는 secPr/colPr 컨트롤 (OWPML 표준 위치)
    run_parts = [f"<hp:run charPrIDRef=\"{char_pr}\">{extra_run}</hp:run>"] if extra_run else []
    run_parts.extend(
        _text_runs(raw_text, char_pr, native_math=native_math, equation_counter=equation_counter)
    )
    runs = "\n    ".join(run_parts)
    return f"""  <hp:p id="{pid}" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="{1 if page_break else 0}" columnBreak="0" merged="0">
    {runs}
    <hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="{height}" textheight="{height}" baseline="{int(height * 0.85)}" spacing="{int(height * 0.6)}" horzpos="0" horzsize="42520" flags="393216"/></hp:linesegarray>
  </hp:p>"""


# 본문 폭: 용지 59528 - 좌우 여백 8504*2 (HWPUNIT, 1/7200인치)
MAX_IMAGE_WIDTH = 42520
COLUMN_GAP = 1200
PX_TO_HWPUNIT = 75  # 96dpi 기준: px / 96 * 7200
CIRCLED_NUMBERS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")
QUESTION_PREFIX_RE = re.compile(r"^\s*(?:문제\s*)?(\d{1,3})\s*[\.\)]\s*")
CHOICE_PREFIX_RE = re.compile(r"^\s*(?:[①②③④⑤⑥⑦⑧⑨]|\d+\s*[\.\)]|[1-9](?=\s))\s*")
SOURCE_MARKER_RE = re.compile(r"^\s*\[\d{1,2}\s*점\]\s*\[[^\]]+\]\s*$")


def _pic_paragraph(pid: int, item: dict[str, Any], instance: int) -> str:
    """실제 한컴 출력(hwpxlib SimplePicture.hwpx)과 동일한 구조의 인라인 이미지 문단."""
    width, height = item["width"], item["height"]
    return f"""  <hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:pic id="{1000000000 + instance}" zOrder="{instance}" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{2000000000 + instance}" reverse="0">
        <hp:offset x="0" y="0"/>
        <hp:orgSz width="{width}" height="{height}"/>
        <hp:curSz width="{width}" height="{height}"/>
        <hp:flip horizontal="0" vertical="0"/>
        <hp:rotationInfo angle="0" centerX="{width // 2}" centerY="{height // 2}" rotateimage="1"/>
        <hp:renderingInfo>
          <hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>
          <hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>
          <hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>
        </hp:renderingInfo>
        <hp:imgRect>
          <hc:pt0 x="0" y="0"/>
          <hc:pt1 x="{width}" y="0"/>
          <hc:pt2 x="{width}" y="{height}"/>
          <hc:pt3 x="0" y="{height}"/>
        </hp:imgRect>
        <hp:imgClip left="0" right="{width}" top="0" bottom="{height}"/>
        <hp:inMargin left="0" right="0" top="0" bottom="0"/>
        <hp:imgDim dimwidth="{width}" dimheight="{height}"/>
        <hc:img binaryItemIDRef="{item['id']}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>
        <hp:effects/>
        <hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/>
        <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
        <hp:outMargin left="0" right="0" top="0" bottom="0"/>
        <hp:shapeComment/>
      </hp:pic>
      <hp:t/>
    </hp:run>
    <hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="{height}" textheight="{height}" baseline="{int(height * 0.85)}" spacing="600" horzpos="0" horzsize="42520" flags="393216"/></hp:linesegarray>
  </hp:p>"""


# 표(hp:tbl) 설정. 셀 테두리는 header.xml의 borderFill id=1(SOLID) 사용.
TABLE_BORDER_FILL = 1
TABLE_ROW_HEIGHT = 2400  # 셀 기본 높이(HWPUNIT)
CELL_MARGIN = (510, 510, 141, 141)  # left, right, top, bottom


def _cell_paragraph(
    text: str,
    cell_id: int,
    text_width: int,
    native_math: bool = False,
    equation_counter: list[int] | None = None,
) -> str:
    """표 셀(hp:subList) 안에 들어가는 문단."""
    raw_text = _XML_ILLEGAL_RE.sub("", str(text or "")) or " "
    line_height = max(1000, _native_math_height(raw_text) if native_math else 1000)
    runs = "\n            ".join(
        _text_runs(raw_text, 0, native_math=native_math, equation_counter=equation_counter)
    )
    return f"""<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">
          <hp:p id="{cell_id}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
            {runs}
            <hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="{line_height}" textheight="{line_height}" baseline="{int(line_height * 0.85)}" spacing="600" horzpos="0" horzsize="{max(text_width, 1000)}" flags="393216"/></hp:linesegarray>
          </hp:p>
        </hp:subList>"""


def _table_paragraph(
    pid: int,
    instance: int,
    rows: list[list[str]],
    total_width: int,
    native_math: bool = False,
    equation_counter: list[int] | None = None,
) -> str:
    """2차원 문자열 배열을 실제 한컴 호환 hp:tbl 인라인 표로 직렬화한다."""
    row_cnt = len(rows)
    col_cnt = max(len(row) for row in rows)
    col_width = max(total_width // col_cnt, 1000)
    table_width = col_width * col_cnt
    left, right, top, bottom = CELL_MARGIN
    cell_text_width = col_width - left - right
    row_heights: list[int] = []
    for row in rows:
        content_height = 1000
        if native_math:
            content_height = max(
                [_native_math_height(str(value or "")) for value in row] or [1000]
            )
        row_heights.append(max(TABLE_ROW_HEIGHT, content_height + top + bottom + 400))
    table_height = sum(row_heights)

    tr_parts: list[str] = []
    for r, row in enumerate(rows):
        tc_parts: list[str] = []
        row_height = row_heights[r]
        for c in range(col_cnt):
            value = row[c] if c < len(row) else ""
            cell_id = 1500000000 + instance * 10000 + r * col_cnt + c
            sublist = _cell_paragraph(
                value,
                cell_id,
                cell_text_width,
                native_math=native_math,
                equation_counter=equation_counter,
            )
            tc_parts.append(f"""<hp:tc name="" header="0" hasMargin="1" protect="0" editable="0" dirty="0" borderFillIDRef="{TABLE_BORDER_FILL}">
        {sublist}
        <hp:cellAddr colAddr="{c}" rowAddr="{r}"/>
        <hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:cellSz width="{col_width}" height="{row_height}"/>
        <hp:cellMargin left="{left}" right="{right}" top="{top}" bottom="{bottom}"/>
      </hp:tc>""")
        tr_parts.append("<hp:tr>\n      " + "\n      ".join(tc_parts) + "\n    </hp:tr>")
    rows_xml = "\n    ".join(tr_parts)

    return f"""  <hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:tbl id="{1000000000 + instance}" zOrder="{instance}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" rowCnt="{row_cnt}" colCnt="{col_cnt}" cellSpacing="0" borderFillIDRef="{TABLE_BORDER_FILL}" noAdjust="0">
        <hp:sz width="{table_width}" widthRelTo="ABSOLUTE" height="{table_height}" heightRelTo="ABSOLUTE" protect="0"/>
        <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
        <hp:outMargin left="0" right="0" top="0" bottom="0"/>
        <hp:inMargin left="0" right="0" top="0" bottom="0"/>
    {rows_xml}
      </hp:tbl>
      <hp:t/>
    </hp:run>
    <hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="{table_height}" textheight="{table_height}" baseline="{int(table_height * 0.85)}" spacing="600" horzpos="0" horzsize="{table_width}" flags="393216"/></hp:linesegarray>
  </hp:p>"""


def _strip_question_prefix(text: str, label: str) -> str:
    match = QUESTION_PREFIX_RE.match(text)
    if match and match.group(1) == str(label):
        return text[match.end() :].lstrip()
    return text


def _choice_label(index: int, template: ExamTemplate) -> str:
    if template.choice_style == "bare_number":
        return str(index)
    if template.circled_choices and index <= len(CIRCLED_NUMBERS):
        return CIRCLED_NUMBERS[index - 1]
    return f"{index})"


def _format_choice(index: int, choice: str, template: ExamTemplate) -> str:
    clean = CHOICE_PREFIX_RE.sub("", choice or "").strip()
    return f"{_choice_label(index, template)} {clean}".rstrip()


def _add_masthead(add_text, title: str, template: ExamTemplate) -> None:
    if template.key == "basic":
        add_text(title, 1, 1)
        add_text("")
        return

    add_text(title or template.masthead_title, 1, 1)
    meta = "   ".join(
        part for part in (template.area, template.period, template.variant) if part
    )
    if meta:
        add_text(meta, 3, 1)
    if template.show_student_fields:
        add_text("성명 ____________     수험 번호 ____________     " + template.selection, 4, 1)
    elif template.selection:
        add_text(template.selection, 4, 1)
    for direction in template.directions:
        add_text(direction, 4, 0)
    add_text("")


def _build_body(
    title: str,
    problems: list[dict[str, Any]],
    image_items: dict[str, dict[str, Any]],
    template: ExamTemplate,
    section_controls: str = "",
    include_answer_sheet: bool = False,
    content_width: int = MAX_IMAGE_WIDTH,
    native_math: bool = False,
) -> str:
    paragraphs: list[str] = []
    pid = 0
    instance = 0
    equation_counter = [0]

    def add_text(text: str, char_pr: int = 0, para_pr: int = 0, page_break: bool = False) -> None:
        nonlocal pid
        pid += 1
        # 섹션 설정(secPr/colPr)은 문서 첫 문단의 run에 한 번만 싣는다.
        extra = section_controls if pid == 1 else ""
        paragraphs.append(
            _paragraph(
                text,
                pid,
                char_pr,
                para_pr,
                extra_run=extra,
                page_break=page_break,
                native_math=native_math,
                equation_counter=equation_counter,
            )
        )

    def add_image(image_path: str) -> None:
        nonlocal pid, instance
        item = image_items.get(image_path)
        if item is None:
            add_text(f"[첨부 이미지: {Path(image_path).name}]")
            return
        pid += 1
        instance += 1
        paragraphs.append(_pic_paragraph(pid, item, instance))

    def add_table(rows: list[list[str]]) -> None:
        nonlocal pid, instance
        if not rows or not any(rows):
            return
        pid += 1
        instance += 1
        paragraphs.append(
            _table_paragraph(
                pid,
                instance,
                rows,
                content_width,
                native_math=native_math,
                equation_counter=equation_counter,
            )
        )

    _add_masthead(add_text, title, template)
    for index, problem in enumerate(problems, start=1):
        label = problem.get("number") or str(index)
        subject = problem.get("subject") or ""
        unit = problem.get("unit") or ""
        source_marker = unit if SOURCE_MARKER_RE.match(str(unit)) else ""
        meta_unit = "" if source_marker else unit
        meta = " / ".join(part for part in [subject, meta_unit] if part)

        stem_lines = (problem.get("stem") or "").splitlines()
        if template.merge_question_number:
            first_line = _strip_question_prefix(stem_lines[0], label) if stem_lines else ""
            heading = f"{label}. {first_line or problem.get('title') or '문제'}"
            add_text(heading, 2, 3 if template.compact else 0)
            for line in stem_lines[1:]:
                add_text(line, 0, 3 if template.compact else 0)
            if meta:
                add_text(f"[{meta}]", 4, 3 if template.compact else 0)
        else:
            heading = f"{label}. {problem.get('title') or '문제'}"
            if meta:
                heading += f" [{meta}]"
            add_text(heading, 2, 0)
            for line in stem_lines or [""]:
                add_text(line)

        for table in problem.get("tables") or []:
            add_table(table)

        for image_path in problem.get("image_paths") or []:
            add_image(image_path)

        if source_marker:
            add_text(source_marker, 4, 2)

        choices = [
            _format_choice(choice_index, choice, template)
            for choice_index, choice in enumerate(problem.get("choices") or [], start=1)
        ]
        if choices and template.inline_short_choices and sum(len(choice) for choice in choices) <= 90:
            add_text("    ".join(choices), 0, 3 if template.compact else 0)
        else:
            for choice in choices:
                add_text(choice, 0, 3 if template.compact else 0)
        if needs_answer_blank(problem, template):
            add_text(answer_blank_text(template), 0, 3 if template.compact else 0)

        if template.include_answers and problem.get("answer"):
            add_text(f"정답: {format_answer(problem, template)}")
        if template.include_explanations and problem.get("explanation"):
            add_text(f"해설: {problem['explanation']}")
        add_text("")

    if include_answer_sheet:
        add_text(ANSWER_SHEET_TITLE, 1, 1, page_break=True)
        add_text("")
        add_text("빠른 정답", 2)
        for line in quick_answer_lines(problems, template):
            add_text(line, 0, 3 if template.compact else 0)
        entries = explanation_entries(problems, template)
        if entries:
            add_text("")
            add_text("해설", 2)
            for heading, lines in entries:
                add_text(heading, 3, 3 if template.compact else 0)
                for line in lines:
                    add_text(line, 0, 3 if template.compact else 0)
                add_text("")
    return "\n".join(paragraphs)


def _header_xml(title: str) -> str:
    # 실제 한컴 출력 기준으로 이미지(BinData)는 content.hpf 매니페스트에만 등록한다.
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hh:head xmlns:hh="{HEAD_NS}" xmlns:hc="{CORE_NS}" version="1.0">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList>
    <hh:fontfaces itemCnt="7">
      <hh:fontface lang="KO" fontCnt="1"><hh:font id="0" face="맑은 고딕" type="TTF"/></hh:fontface>
      <hh:fontface lang="EN" fontCnt="1"><hh:font id="0" face="Arial" type="TTF"/></hh:fontface>
      <hh:fontface lang="CN" fontCnt="1"><hh:font id="0" face="SimSun" type="TTF"/></hh:fontface>
      <hh:fontface lang="JP" fontCnt="1"><hh:font id="0" face="Yu Gothic" type="TTF"/></hh:fontface>
      <hh:fontface lang="OTHER" fontCnt="1"><hh:font id="0" face="Arial" type="TTF"/></hh:fontface>
      <hh:fontface lang="SYMBOL" fontCnt="1"><hh:font id="0" face="Symbol" type="TTF"/></hh:fontface>
      <hh:fontface lang="USER" fontCnt="1"><hh:font id="0" face="Arial" type="TTF"/></hh:fontface>
    </hh:fontfaces>
    <hh:borderFills itemCnt="2">
      <hh:borderFill id="0" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
        <hh:slash type="NONE" Crooked="0" isCounter="0"/>
        <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
        <hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:topBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:diagonal type="NONE" width="0.1 mm" color="#000000"/>
        <hh:fillBrush><hc:winBrush faceColor="#FFFFFF" hatchColor="#000000" alpha="0"/></hh:fillBrush>
      </hh:borderFill>
      <hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
        <hh:slash type="NONE" Crooked="0" isCounter="0"/>
        <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
        <hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:diagonal type="NONE" width="0.1 mm" color="#000000"/>
        <hh:fillBrush><hc:winBrush faceColor="none" hatchColor="#000000" alpha="0"/></hh:fillBrush>
      </hh:borderFill>
    </hh:borderFills>
    <hh:charProperties itemCnt="6">
      <hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="1" height="1600" textColor="#111111" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="2" height="1150" textColor="#111111" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="3" height="1250" textColor="#111111" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="4" height="900" textColor="#333333" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="5" height="1000" textColor="#111111" shadeColor="none" useFontSpace="0" useKerning="1" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="100" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
    </hh:charProperties>
    <hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="1" autoTabRight="1"/></hh:tabProperties>
    <hh:numberings itemCnt="1"><hh:numbering id="1" start="1"/></hh:numberings>
    <hh:paraProperties itemCnt="4">
      <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="LEFT" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin><hc:intent value="0"/><hc:left value="0"/><hc:right value="0"/><hc:prev value="0"/><hc:next value="0"/></hh:margin>
      </hh:paraPr>
      <hh:paraPr id="1" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="CENTER" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin><hc:intent value="0"/><hc:left value="0"/><hc:right value="0"/><hc:prev value="0"/><hc:next value="0"/></hh:margin>
      </hh:paraPr>
      <hh:paraPr id="2" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="RIGHT" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin><hc:intent value="0"/><hc:left value="0"/><hc:right value="0"/><hc:prev value="0"/><hc:next value="0"/></hh:margin>
      </hh:paraPr>
      <hh:paraPr id="3" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="LEFT" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:lineSpacing type="PERCENT" value="125" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin><hc:intent value="0"/><hc:left value="0"/><hc:right value="0"/><hc:prev value="0"/><hc:next value="0"/></hh:margin>
      </hh:paraPr>
    </hh:paraProperties>
    <hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>
  </hh:refList>
  <hh:docOption><hh:linkinfo path=""/></hh:docOption>
  <hh:trackchagesConfig flags="0"/>
</hh:head>"""


def _section_xml(
    title: str,
    problems: list[dict[str, Any]],
    image_items: dict[str, dict[str, Any]],
    template: ExamTemplate,
    include_answer_sheet: bool = False,
    native_math: bool = False,
) -> str:
    columns = max(1, min(template.columns, 2))
    content_width = (
        (MAX_IMAGE_WIDTH - COLUMN_GAP * (columns - 1)) // columns
        if columns > 1
        else MAX_IMAGE_WIDTH
    )
    # OWPML 표준: secPr와 단 설정(ctrl/colPr)은 첫 문단의 run 안에 들어간다.
    section_controls = f"""<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">
        <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0" strtnum="0"/>
        <hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>
        <hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>
        <hp:pagePr landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY">
          <hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/>
        </hp:pagePr>
      </hp:secPr><hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="{columns}" sameSz="1" sameGap="{COLUMN_GAP}"><hp:colLine type="SOLID" width="0.12 mm" color="#000000"/></hp:colPr></hp:ctrl>"""
    body = _build_body(
        title,
        problems,
        image_items,
        template,
        section_controls=section_controls,
        include_answer_sheet=include_answer_sheet,
        content_width=content_width,
        native_math=native_math,
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hs:sec xmlns:hs="{SECTION_NS}" xmlns:hp="{PARA_NS}" xmlns:hc="{CORE_NS}" xmlns:hh="{HEAD_NS}">
{body}
</hs:sec>"""


def _content_hpf(title: str, image_items: dict[str, dict[str, Any]]) -> str:
    lines = "\n".join(
        f'    <opf:item id="{item["id"]}" href="BinData/{_esc(item["name"])}" media-type="{_esc(item["media"])}" isEmbeded="1"/>'
        for item in image_items.values()
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="1.0" unique-identifier="uid">
  <opf:metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{_esc(title or "문항 모음")}</dc:title>
    <dc:creator>HWP Make</dc:creator>
    <dc:language>ko-KR</dc:language>
  </opf:metadata>
  <opf:manifest>
    <opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
    <opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
{lines}
  </opf:manifest>
  <opf:spine>
    <opf:itemref idref="section0"/>
  </opf:spine>
</opf:package>"""


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
  </rootfiles>
</container>"""


def _manifest_xml(image_items: dict[str, dict[str, Any]]) -> str:
    entries = [
        '  <manifest:file-entry manifest:media-type="application/hwp+zip" manifest:full-path="/"/>',
        '  <manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/content.hpf"/>',
        '  <manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/header.xml"/>',
        '  <manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/section0.xml"/>',
    ]
    for item in image_items.values():
        entries.append(
            f'  <manifest:file-entry manifest:media-type="{_esc(item["media"])}" manifest:full-path="BinData/{_esc(item["name"])}"/>'
        )
    return """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest">
""" + "\n".join(entries) + "\n</manifest:manifest>"


def _preview_text(title: str, problems: list[dict[str, Any]]) -> str:
    chunks = [title or "문항 모음", ""]
    for index, problem in enumerate(problems, start=1):
        chunks.append(f"{problem.get('number') or index}. {problem.get('title') or '문제'}")
        chunks.append(problem.get("stem") or "")
        chunks.append("")
    return "\n".join(chunks)


def _collect_image_items(
    problems: list[dict[str, Any]], columns: int = 1
) -> dict[str, dict[str, Any]]:
    """문제들이 참조하는 이미지의 매니페스트 정보(id, 보관 이름, 크기)를 모은다."""
    # 다단 레이아웃에서는 단 폭을 넘으면 안 된다.
    max_width = (MAX_IMAGE_WIDTH - COLUMN_GAP * (columns - 1)) // columns if columns > 1 else MAX_IMAGE_WIDTH
    items: dict[str, dict[str, Any]] = {}
    index = 0
    for problem in problems:
        for image_path in problem.get("image_paths") or []:
            if image_path in items:
                continue
            full_path = storage.DATA_DIR / image_path
            if not full_path.exists():
                continue
            try:
                with Image.open(full_path) as image:
                    px_width, px_height = image.size
            except Exception:
                continue
            width = px_width * PX_TO_HWPUNIT
            height = px_height * PX_TO_HWPUNIT
            if width > max_width:
                height = int(height * max_width / width)
                width = max_width
            index += 1
            extension = full_path.suffix.lower() or ".bin"
            items[image_path] = {
                "id": f"image{index}",
                "name": f"image{index}{extension}",
                "media": mimetypes.guess_type(full_path.name)[0] or "application/octet-stream",
                "width": width,
                "height": height,
            }
    return items


def write_hwpx(
    path: Path,
    title: str,
    problems: list[dict[str, Any]],
    template_key: str = "basic",
    include_answer_sheet: bool = False,
    native_math: bool = False,
) -> None:
    template = get_template(template_key)
    title = resolve_export_title(title, template)
    image_items = _collect_image_items(problems, columns=max(1, min(template.columns, 2)))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _container_xml())
        archive.writestr("META-INF/manifest.xml", _manifest_xml(image_items))
        archive.writestr("version.xml", '<?xml version="1.0" encoding="UTF-8"?><version app="HWP Make" ver="1.0"/>')
        archive.writestr("Contents/content.hpf", _content_hpf(title, image_items))
        archive.writestr("Contents/header.xml", _header_xml(title))
        archive.writestr(
            "Contents/section0.xml",
            _section_xml(
                title,
                problems,
                image_items,
                template,
                include_answer_sheet=include_answer_sheet,
                native_math=native_math,
            ),
        )
        archive.writestr("Preview/PrvText.txt", _preview_text(title, problems))
        for image_path, item in image_items.items():
            archive.write(storage.DATA_DIR / image_path, f"BinData/{item['name']}")
