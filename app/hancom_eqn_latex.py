"""Hancom equation script (HWP/HWPX ``hp:script``) → LaTeX.

Python port of kordoc ``src/hwpx/equation.ts`` (MIT), which itself ports
hml-equation-parser ``hulkEqParser.py`` / ``hulkReplaceMethod.py``
(Copyright 2018 Open Bapul, Apache License 2.0). See
``app/third_party_licenses/NOTICE.md``.

HWP/HWPX imports keep equations as their original Hancom script (``$...$``)
so HWPX export can re-emit them unchanged. Consumers that only read LaTeX —
the DOCX OMML writer — call :func:`hancom_script_to_latex` first; without it
``{1} over {2}`` was written as the literal words ``{1} over {2}``.

The conversion is token based, with the same five rewrite passes as the
original: ``over``/``choose``/``atop`` → ``\\frac``/``\\binom``, ``root .. of``
→ ``\\sqrt[]``, matrices/cases, accents, and over/under braces.
"""
from __future__ import annotations

import re

# Single-token replacements (hml-equation-parser convertMap, via kordoc).
_CONVERT_MAP: dict[str, str] = {
    "TIMES": "\\times", "times": "\\times",
    "LEFT": "\\left", "RIGHT": "\\right",
    "under": "\\underline",
    "SMALLSUM": "\\sum", "sum": "\\sum",
    "SMALLPROD": "\\prod", "prod": "\\prod",
    "SMALLINTER": "\\cap",
    "CUP": "\\cup",
    "OPLUS": "\\oplus", "OMINUS": "\\ominus", "OTIMES": "\\otimes", "ODIV": "\\oslash", "ODOT": "\\odot",
    "LOR": "\\lor", "LAND": "\\land",
    "SUBSET": "\\subset", "SUPERSET": "\\supset", "SUBSETEQ": "\\subseteq", "SUPSETEQ": "\\supseteq",
    "IN": "\\in", "OWNS": "\\owns", "NOTIN": "\\notin",
    "LEQ": "\\leq", "GEQ": "\\geq", "<=": "\\leq", ">=": "\\geq",
    "<<": "\\ll", ">>": "\\gg", "<<<": "\\lll", ">>>": "\\ggg",
    "PREC": "\\prec", "SUCC": "\\succ",
    "UPLUS": "\\uplus",
    "±": "\\pm", "+-": "\\pm", "-+": "\\mp", "÷": "\\div",
    "cdot": "\\cdot",
    "CIRC": "\\circ", "BULLET": "\\bullet", "DEG": "^\\circ",
    "AST": "\\ast", "STAR": "\\bigstar", "BIGCIRC": "\\bigcirc",
    "EMPTYSET": "\\emptyset",
    "THEREFORE": "\\therefore", "BECAUSE": "\\because", "EXIST": "\\exists",
    "!=": "\\neq",
    "SMCOPROD": "\\coprod", "coprod": "\\coprod",
    "SQCAP": "\\sqcap", "SQCUP": "\\sqcup",
    "SQSUBSET": "\\sqsubset", "SQSUBSETEQ": "\\sqsubseteq",
    "BIGSQCUP": "\\bigsqcup",
    "BIGOPLUS": "\\bigoplus", "BIGOTIMES": "\\bigotimes", "BIGODOT": "\\bigodot", "BIGUPLUS": "\\biguplus",
    "inter": "\\bigcap", "union": "\\bigcup",
    "UNDEROVER": "",
    "SIM": "\\sim", "APPROX": "\\approx", "SIMEQ": "\\simeq", "CONG": "\\cong",
    "==": "\\equiv",
    "DIAMOND": "\\diamond", "FORALL": "\\forall",
    "prime": "'", "Partial": "\\partial", "INF": "\\infty", "PROPTO": "\\propto",
    "lim": "\\lim", "Lim": "\\lim",
    "larrow": "\\leftarrow", "->": "\\rightarrow",
    "uparrow": "\\uparrow", "downarrow": "\\downarrow",
    "LARROW": "\\Leftarrow", "RARROW": "\\Rightarrow",
    "UPARROW": "\\Uparrow", "DOWNARROW": "\\Downarrow",
    "udarrow": "\\updownarrow",
    "<->": "\\leftrightarrow",
    "UDARROW": "\\Updownarrow", "LRARROW": "\\Leftrightarrow",
    "NWARROW": "\\nwarrow", "SEARROW": "\\searrow", "NEARROW": "\\nearrow", "SWARROW": "\\swarrow",
    "HOOKLEFT": "\\hookleftarrow", "HOOKRIGHT": "\\hookrightarrow",
    "PVER": "\\|", "MAPSTO": "\\mapsto",
    "CDOTS": "\\cdots", "LDOTS": "\\ldots", "VDOTS": "\\vdots", "DDOTS": "\\ddots",
    "DAGGER": "\\dagger", "DDAGGER": "\\ddagger", "DOTEQ": "\\doteq",
    "image": "\\fallingdotseq", "REIMAGE": "\\risingdotseq",
    "ASYMP": "\\asymp", "ISO": "\\Bumpeq",
    "DSUM": "\\dotplus", "XOR": "\\veebar",
    "TRIANGLE": "\\triangle", "NABLA": "\\nabla",
    "ANGLE": "\\angle", "MSANGLE": "\\measuredangle", "SANGLE": "\\sphericalangle",
    "VDASH": "\\vdash", "DASHV": "\\dashv",
    "BOT": "\\bot", "TOP": "\\top", "MODELS": "\\models",
    "CENTIGRADE": "^{\\circ}C", "FAHRENHEIT": "^{\\circ}F",
    "LSLANT": "\\diagup", "RSLANT": "\\diagdown",
    "sqrt": "\\sqrt",
    "int": "\\int", "dint": "\\iint", "tint": "\\iiint", "oint": "\\oint",
    "alpha": "\\alpha", "beta": "\\beta", "gamma": "\\gamma", "delta": "\\delta",
    "epsilon": "\\epsilon", "zeta": "\\zeta", "eta": "\\eta", "theta": "\\theta",
    "iota": "\\iota", "kappa": "\\kappa", "lambda": "\\lambda", "mu": "\\mu",
    "nu": "\\nu", "xi": "\\xi", "omicron": "o", "pi": "\\pi",
    "rho": "\\rho", "sigma": "\\sigma", "tau": "\\tau", "upsilon": "\\upsilon",
    "phi": "\\phi", "chi": "\\chi", "psi": "\\psi", "omega": "\\omega",
    "ALPHA": "A", "BETA": "B", "GAMMA": "\\Gamma", "DELTA": "\\Delta",
    "EPSILON": "E", "ZETA": "Z", "ETA": "H", "THETA": "\\Theta",
    "IOTA": "I", "KAPPA": "K", "LAMBDA": "\\Lambda", "MU": "M",
    "NU": "N", "XI": "\\Xi", "OMICRON": "O", "PI": "\\Pi",
    "RHO": "P", "SIGMA": "\\Sigma", "TAU": "T", "UPSILON": "\\Upsilon",
    "PHI": "\\Phi", "CHI": "X", "PSI": "\\Psi", "OMEGA": "\\Omega",
    "⌈": "\\lceil", "⌉": "\\rceil", "⌊": "\\lfloor", "⌋": "\\rfloor",
    "∥": "\\|",
    # Tokens this app's own HWPX writer emits (app/hwpx_writer.py) that the
    # upstream map does not list.
    "NEQ": "\\neq", "inf": "\\infty", "approx": "\\approx", "div": "\\div",
    "angle": "\\angle", "triangle": "\\triangle", "parallel": "\\parallel",
    "perp": "\\perp", "because": "\\because", "therefore": "\\therefore",
    "EXISTS": "\\exists", "mod": "\\bmod",
    "rm": "", "it": "", "bold": "",
    **{
        name: "\\" + name
        for name in (
            "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
            "sinh", "cosh", "tanh", "log", "ln", "exp", "max", "min", "det", "gcd", "arg",
        )
    },
}

# Structure tokens rewritten to markers, then expanded by the later passes.
_MIDDLE_CONVERT_MAP: dict[str, str] = {
    "matrix": "HULKMATRIX", "pmatrix": "HULKPMATRIX", "bmatrix": "HULKBMATRIX",
    "dmatrix": "HULKDMATRIX", "eqalign": "HULKEQALIGN", "cases": "HULKCASE",
    "vec": "HULKVEC", "dyad": "HULKDYAD", "acute": "HULKACUTE", "grave": "HULKGRAVE",
    "dot": "HULKDOT", "ddot": "HULKDDOT", "bar": "HULKBAR", "hat": "HULKHAT",
    "check": "HULKCHECK", "arch": "HULKARCH", "tilde": "HULKTILDE", "BOX": "HULKBOX",
    "OVERBRACE": "HULKOVERBRACE", "UNDERBRACE": "HULKUNDERBRACE",
}

_BAR_CONVERT_MAP: dict[str, str] = {
    "HULKVEC": "\\overrightarrow", "HULKDYAD": "\\overleftrightarrow",
    "HULKACUTE": "\\acute", "HULKGRAVE": "\\grave", "HULKDOT": "\\dot",
    "HULKDDOT": "\\ddot", "HULKBAR": "\\overline", "HULKHAT": "\\widehat",
    "HULKCHECK": "\\check", "HULKARCH": "\\overset{\\frown}", "HULKTILDE": "\\widetilde",
    "HULKBOX": "\\boxed",
}

# name → (begin, end, remove enclosing braces)
_MATRIX_CONVERT_MAP: dict[str, tuple[str, str, bool]] = {
    "HULKMATRIX": ("\\begin{matrix}", "\\end{matrix}", True),
    "HULKPMATRIX": ("\\begin{pmatrix}", "\\end{pmatrix}", True),
    "HULKBMATRIX": ("\\begin{bmatrix}", "\\end{bmatrix}", True),
    "HULKDMATRIX": ("\\begin{vmatrix}", "\\end{vmatrix}", True),
    "HULKCASE": ("\\begin{cases}", "\\end{cases}", True),
    "HULKEQALIGN": ("\\begin{aligned}", "\\end{aligned}", False),
}

_BRACE_CONVERT_MAP: dict[str, str] = {
    "HULKOVERBRACE": "\\overbrace",
    "HULKUNDERBRACE": "\\underbrace",
}

# Infix operators handled like ``over``: numerator/denominator are the
# neighbouring token or brace group.
_INFIX_COMMANDS: dict[str, str] = {"over": "\\frac", "choose": "\\binom", "atop": "\\genfrac{}{}{0pt}{}"}

_MAX_SCRIPT_LENGTH = 200_000


def _find_brackets(value: str, start: int) -> tuple[int, int]:
    """``[start, end)`` of the first balanced ``{...}`` at or after ``start``."""
    open_index = value.find("{", start)
    if open_index < 0:
        raise ValueError("cannot find bracket")
    depth = 1
    for index in range(open_index + 1, len(value)):
        char = value[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return open_index, index + 1
    raise ValueError("cannot find bracket")


def _find_enclosing_brackets(value: str, start: int) -> tuple[int, int] | None:
    """Nearest ``{...}`` group that actually encloses ``start``."""
    depth = 0
    for index in range(start - 1, -1, -1):
        char = value[index]
        if char == "}":
            depth += 1
        elif char == "{":
            if depth > 0:
                depth -= 1
                continue
            try:
                group = _find_brackets(value, index)
            except ValueError:
                return None
            return group if group[0] == index and group[1] > start else None
    return None


def _mask_literals(value: str) -> str:
    """Hide ``"..."`` and ``\\text{...}`` spans (same length) from keyword search."""
    value = re.sub(r'"[^"]*"', lambda match: "\uffff" * len(match.group(0)), value)
    return re.sub(r"\\text\{[^}]*\}", lambda match: "\uffff" * len(match.group(0)), value)


def _keyword_positions(value: str, word: str, start: int = 0) -> list[int]:
    masked = _mask_literals(value)
    positions = []
    index = masked.find(word, start)
    while index >= 0:
        left_ok = index == 0 or masked[index - 1].isspace()
        end = index + len(word)
        right_ok = end == len(masked) or masked[end].isspace()
        if left_ok and right_ok:
            positions.append(index)
        index = masked.find(word, index + 1)
    return positions


def _replace_infix(value: str, keyword: str, command: str) -> str:
    """``{a} over {b}`` → ``\\frac{a}{b}`` in one left-to-right sweep."""
    positions = _keyword_positions(value, keyword)
    if not positions:
        return value
    out: list[str] = []
    pos = 0
    for cursor in positions:
        if cursor < pos:
            continue
        out.extend(value[pos:cursor])
        end = len(out)
        while end > 0 and out[end - 1].isspace():
            end -= 1
        if end > 0 and out[end - 1] == "}":
            depth = 0
            start = end - 1
            while start >= 0:
                if out[start] == "}":
                    depth += 1
                elif out[start] == "{":
                    depth -= 1
                    if depth == 0:
                        break
                start -= 1
            if start < 0:
                return "".join(out) + value[cursor:]
            del out[end:]
            out.insert(start, command)
        else:
            start = end
            while start > 0 and not out[start - 1].isspace():
                start -= 1
            if start == end:
                return "".join(out) + value[cursor:]
            del out[end:]
            out[start:start] = [command, "{"]
            out.append("}")
        pos = cursor + len(keyword)
        # A bare denominator token also needs its own group.
        rest = value[pos:]
        stripped = rest.lstrip()
        if stripped and not stripped.startswith(("{", "\\")):
            lead = len(rest) - len(stripped)
            token = re.match(r"\S+", stripped).group(0)
            out.extend(rest[:lead])
            out.extend("{" + token + "}")
            pos += lead + len(token)
    return "".join(out) + value[pos:]


def _replace_root_of(value: str) -> str:
    while True:
        roots = _keyword_positions(value, "root")
        if not roots:
            return value
        cursor = roots[0]
        try:
            degree = _find_brackets(value, cursor)
            ofs = _keyword_positions(value, "of", degree[1])
            if not ofs:
                return value
            body = _find_brackets(value, ofs[0])
        except ValueError:
            return value
        value = (
            value[:cursor]
            + "\\sqrt["
            + value[degree[0] + 1 : degree[1] - 1]
            + "]{"
            + value[body[0] + 1 : body[1] - 1]
            + "}"
            + value[body[1] :]
        )


def _replace_matrices(value: str) -> str:
    for marker, (begin, end, remove_outer) in _MATRIX_CONVERT_MAP.items():
        while True:
            cursor = value.find(marker)
            if cursor < 0:
                break
            try:
                start, stop = _find_brackets(value, cursor)
            except ValueError:
                break
            inner = value[start + 1 : stop - 1].replace("#", " \\\\ ").replace("&amp;", "&")
            outer = _find_enclosing_brackets(value, cursor) if remove_outer else None
            if outer and outer[1] >= stop:
                value = value[: outer[0]] + begin + inner + end + value[outer[1] :]
            else:
                value = value[:cursor] + begin + inner + end + value[stop:]
    return value


def _replace_accents(value: str) -> str:
    for marker, command in _BAR_CONVERT_MAP.items():
        while True:
            cursor = value.find(marker)
            if cursor < 0:
                break
            try:
                start, stop = _find_brackets(value, cursor)
            except ValueError:
                break
            element = value[start:stop]
            outer = _find_enclosing_brackets(value, cursor)
            replace_start, replace_end = outer if outer and outer[1] >= stop else (cursor, stop)
            value = value[:replace_start] + command + element + value[replace_end:]
    return value


def _replace_braces(value: str) -> str:
    for marker, command in _BRACE_CONVERT_MAP.items():
        while True:
            cursor = value.find(marker)
            if cursor < 0:
                break
            try:
                first = _find_brackets(value, cursor)
                second = _find_brackets(value, first[1])
            except ValueError:
                break
            script = "^" if marker == "HULKOVERBRACE" else "_"
            value = value[:cursor] + command + value[first[0] : first[1]] + script + value[second[0] : second[1]] + value[second[1] :]
    return value


def hancom_script_to_latex(script: str) -> str:
    """Convert a Hancom equation script to LaTeX (without ``$`` delimiters)."""
    value = str(script or "")
    if not value.strip() or len(value) > _MAX_SCRIPT_LENGTH:
        return value.strip()
    # Hancom row separator is '#'; line breaks, tabs and backtick/tilde spacing
    # are layout only.
    value = re.sub(r"[\r\n\t]+", " ", value).replace("`", " ").replace("~", " ")
    # This app's writer emits nth roots as ``^3sqrt {x}``.
    value = re.sub(r"\^\s*\{?\s*([0-9A-Za-z]+)\s*\}?\s*sqrt\s*(?=\{)", r" root {\1} of ", value)
    # Quoted literals may contain spaces; park them as single placeholder tokens.
    literals: list[str] = []

    def park(match: re.Match[str]) -> str:
        literals.append(match.group(1))
        return f" \x00{len(literals) - 1}\x00 "

    value = re.sub(r'"([^"]*)"', park, value)
    value = value.replace("{", " { ").replace("}", " } ").replace("&", " & ")
    # Scripts glue to words (``sum_{k}``, ``it^{2}``); split so the word maps.
    value = value.replace("^", " ^ ").replace("_", " _ ")
    # Multi-character operators are words too, even when glued (``x->0``).
    value = re.sub(r"(<->|<<<|>>>|->|<=|>=|!=|==|\+-|-\+|<<|>>)", r" \1 ", value)
    # Hancom reads a letter run as one word wherever it sits (``+beta``).
    value = re.sub(r"([A-Za-z]+)", r" \1 ", value)
    tokens: list[str] = []
    for token in value.split(" "):
        if not token:
            continue
        parked = re.fullmatch("\x00(\\d+)\x00", token)
        if parked:
            tokens.append(f"\\text{{{literals[int(parked.group(1))]}}}")
            continue
        if token in _CONVERT_MAP:
            token = _CONVERT_MAP[token]
        elif token in _MIDDLE_CONVERT_MAP:
            token = _MIDDLE_CONVERT_MAP[token]
        else:
            quoted = re.fullmatch(r'"(.+)"', token)
            if quoted:
                token = f"\\text{{{quoted.group(1)}}}"
        if token:
            tokens.append(token)
    for index in range(1, len(tokens)):
        if tokens[index] == "{" and tokens[index - 1] == "\\left":
            tokens[index] = "\\{"
        elif tokens[index] == "}" and tokens[index - 1] == "\\right":
            tokens[index] = "\\}"
    out = " ".join(tokens)
    for keyword, command in _INFIX_COMMANDS.items():
        out = _replace_infix(out, keyword, command)
    out = _replace_root_of(out)
    out = _replace_matrices(out)
    out = _replace_accents(out)
    out = _replace_braces(out)
    return _tighten(re.sub(r"\s+", " ", out).strip())


def _tighten(latex: str) -> str:
    """Drop token-separator spaces around groups and scripts (``\\frac{1}{2}``).

    Spaces inside ``\\text{...}`` are content and stay.
    """
    parts = re.split(r"(\\text\{[^}]*\})", latex)
    for index in range(0, len(parts), 2):
        part = re.sub(r"\s*([{}\[\]^_&])\s*", r"\1", parts[index])
        # Keep a separator only where a command would otherwise swallow a letter.
        parts[index] = re.sub(r"(\\[A-Za-z]+) (?![A-Za-z])", r"\1", part)
    return "".join(parts).strip()


def looks_like_hancom_script(expr: str) -> bool:
    """True for math text that is Hancom script rather than LaTeX.

    LaTeX always carries backslash commands; Hancom scripts never do.  Plain
    text math without either (``x^2+1``) converts to itself, so treating it as
    Hancom script is harmless.
    """
    value = str(expr or "")
    return bool(value.strip()) and "\\" not in value
