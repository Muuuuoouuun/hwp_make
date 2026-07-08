from __future__ import annotations

import unicodedata
import re
from dataclasses import asdict, dataclass
from typing import Any


MATH_OPERATOR = r"(?:->|=>|\\(?:to|le|leq|ge|geq|ne|neq|cdot|times|div|pm|mp|approx|in|notin|cup|cap|subset|supset|subseteq|supseteq|circ|mid|vert)(?![A-Za-z])|[+\-*\/=<>≤≥≠≈×÷±∈∉∪∩⊂⊃⊆⊇∘^!])"
MATH_SYMBOL = r"[√∑∏∫∞≤≥≠≈±×÷∠△∥⊥∈∉∪∩⊂⊃⊆⊇∘′″]"
GREEK_RANGE = "α-ωΑ-Ω"
GREEK_LETTER = rf"[{GREEK_RANGE}]"
IDENTIFIER = rf"[a-zA-Z{GREEK_RANGE}][a-zA-Z0-9{GREEK_RANGE}]*"
SUPERSCRIPT_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ"
SUBSCRIPT_CHARS = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"
VULGAR_FRACTION_CHARS = "¼½¾⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞"
PRIME_CHARS = "'′″"
UNICODE_SUP_SUB_PATTERN = rf"(?<![a-zA-Z0-9{GREEK_RANGE}])[a-zA-Z{GREEK_RANGE}][a-zA-Z0-9{GREEK_RANGE}]*[{SUPERSCRIPT_CHARS}{SUBSCRIPT_CHARS}]+"
VULGAR_FRACTION_PATTERN = rf"[{VULGAR_FRACTION_CHARS}]"
MATH_OPERAND = (
    rf"(?:[+\-]?\d+(?:\.\d+)?(?:\s*\/\s*[+\-]?\d+(?:\.\d+)?)?"
    rf"|[+\-]?\d+(?:\.\d+)?\([^()\n]{{1,120}}\)"
    rf"|[+\-]?\d*(?:\.\d+)?{IDENTIFIER}[{PRIME_CHARS}]*(?:\([^()\n]{{0,120}}\))?(?:[_^](?:\{{[^{{}}\n]{{1,80}}\}}|[a-zA-Z0-9]+))*"
    rf"|{IDENTIFIER}[{PRIME_CHARS}]*\([^()\n]{{0,120}}\)(?:[_^](?:\{{[^{{}}\n]{{1,80}}\}}|[a-zA-Z0-9]+))*"
    rf"|\([^()\n]{{1,120}}\)"
    rf"|{MATH_SYMBOL})"
)
LATEX_GROUP_CONTENT = r"(?:[^{}\n]|\\[A-Za-z]+(?:\{[^{}\n]{0,120}\})?|\{[^{}\n]{0,120}\}){0,180}"
LATEX_WRAPPED_OPERAND = rf"\\(?:mathrm|mathbb|mathbf|text|operatorname)\{{{LATEX_GROUP_CONTENT}\}}"
LATEX_WRAPPED_FUNCTION_PATTERN = rf"{LATEX_WRAPPED_OPERAND}\([^()\n]{{0,120}}\)"
LATEX_LEFT_RIGHT_PATTERN = r"\\left[\s\S]{1,1200}?\\right(?:\\[{}]|\S)?"
LATEX_WRAPPED_LEFT_RIGHT_PATTERN = rf"{LATEX_WRAPPED_OPERAND}\s*{LATEX_LEFT_RIGHT_PATTERN}"
LATEX_WRAPPED_EXPRESSION_PATTERN = rf"(?:{MATH_OPERAND}|{LATEX_WRAPPED_OPERAND})\s*{MATH_OPERATOR}\s*(?:{MATH_OPERAND}|{LATEX_WRAPPED_OPERAND})(?:\s*{MATH_OPERATOR}\s*(?:{MATH_OPERAND}|{LATEX_WRAPPED_OPERAND}))*"
LATEX_FRACTION_PATTERN = rf"\\(?:frac|dfrac|tfrac)\{{{LATEX_GROUP_CONTENT}\}}\{{{LATEX_GROUP_CONTENT}\}}"
LATEX_BINOM_PATTERN = rf"\\(?:binom|dbinom|tbinom)\{{{LATEX_GROUP_CONTENT}\}}\{{{LATEX_GROUP_CONTENT}\}}"
LATEX_SQRT_PATTERN = rf"\\sqrt(?:\[[^\]\n]{{0,80}}\])?\{{{LATEX_GROUP_CONTENT}\}}"
LATEX_SPACE_COMMAND_PATTERN = r"(?:\\[,;:! ]|\\(?:quad|qquad|enspace|thinspace|medspace|thickspace)(?![A-Za-z]))"
ABSOLUTE_VALUE_PATTERN = rf"\|(?=[^|$\n]*[a-zA-Z0-9{GREEK_RANGE}])[^|$\n]{{1,160}}\|"
FUNCTION_CALL_PATTERN = rf"(?<![a-zA-Z0-9{GREEK_RANGE}]){IDENTIFIER}[{PRIME_CHARS}]{{0,3}}\([^()\n]{{1,80}}\)"
LATEX_NARY_BODY_PATTERN = (
    rf"(?:{LATEX_FRACTION_PATTERN}|{LATEX_SQRT_PATTERN}"
    rf"|\([^()\n]{{1,120}}\)|\[[^\[\]\n]{{1,120}}\]"
    rf"|{IDENTIFIER}(?:\([^()\n]{{0,120}}\))?(?:[_^](?:\{{[^{{}}\n]{{1,80}}\}}|[a-zA-Z0-9]+))*(?:d{IDENTIFIER})?"
    r"|\d+(?:\.\d+)?)"
)
RADICAL_PLACEHOLDER_PATTERN = r"[□▢]*"
RADICAL_BODY_PATTERN = rf"(?:{IDENTIFIER}|\([^()\n]{{1,120}}\)|\d+(?:\.\d+)?)"
UNICODE_RADICAL_PATTERN = rf"√\s*{RADICAL_PLACEHOLDER_PATTERN}\s*{RADICAL_BODY_PATTERN}"
HANCOM_RADICAL_PATTERN = rf"(?<![a-zA-Z0-9{GREEK_RANGE}])sqrt\s*{RADICAL_PLACEHOLDER_PATTERN}\s*{RADICAL_BODY_PATTERN}"
UNICODE_NARY_PATTERN = (
    rf"[∑∏∫](?:[_^](?:\{{[^{{}}\n]{{0,120}}\}}|[a-zA-Z0-9]+)){{0,2}}"
    rf"(?:\s*{LATEX_NARY_BODY_PATTERN})?"
)
LATEX_NARY_PATTERN = (
    r"\\(?:sum|prod|int|iint)(?![A-Za-z])"
    r"(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}"
    rf"(?:\s+{LATEX_NARY_BODY_PATTERN})?"
    rf"(?:\s*(?:{LATEX_SPACE_COMMAND_PATTERN}\s*)?d{IDENTIFIER})?"
)
LATEX_FUNCTION_PATTERN = (
    r"\\(?:lim|log|ln|sin|cos|tan|sec|csc|cot)(?![A-Za-z])"
    r"(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}"
    rf"(?:\s*{LATEX_NARY_BODY_PATTERN})?"
    rf"(?:\s*\{{{LATEX_GROUP_CONTENT}\}})?"
)
LATEX_FUNCTION_EXPRESSION_PATTERN = (
    r"\\(?:lim|log|ln)(?![A-Za-z])"
    r"(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}"
    rf"(?:\s*{LATEX_NARY_BODY_PATTERN})?"
    rf"(?:\s*\{{{LATEX_GROUP_CONTENT}\}})?"
    rf"(?:\s*{MATH_OPERATOR}\s*(?:{LATEX_NARY_BODY_PATTERN}|{MATH_OPERAND}))+"
)
LATEX_COMMAND_PATTERN = (
    r"\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|iint|lim|log|ln|sin|cos|tan|sec|csc|cot"
    r"|alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi"
    r"|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon|phi|varphi|chi|psi|omega"
    r"|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega|nabla|le|leq|ge|geq|ne|neq"
    r"|approx|cdot|times|div|pm|mp|infty|overline|underline|overrightarrow|widehat"
    r"|hat|tilde|dot|ddot|check|bar|vec|angle|triangle|parallel|perp|because|therefore"
    r"|binom|dbinom|tbinom|mathrm|mathbb|mathbf|text|operatorname|in|notin|cup|cap"
    r"|subset|supset|subseteq|supseteq|circ|mid|vert|lvert|rvert|lVert|rVert|cdots|ldots)(?![A-Za-z])"
    r"(?:\s*(?:[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)|\{[^{}\n]{0,120}\}|\[[^\]\n]{0,80}\])){0,4}"
)
SUPER_SUB_PATTERN = rf"(?<![a-zA-Z0-9{GREEK_RANGE}])[a-zA-Z{GREEK_RANGE}][a-zA-Z0-9{GREEK_RANGE}]*[{PRIME_CHARS}]*(?:[_^](?:\{{[^{{}}\n]{{1,80}}\}}|[a-zA-Z0-9]+))+"
PREFIXED_SUP_SUB_PATTERN = rf"(?:\{{\}})?(?:[_^](?:\{{[^{{}}\n]{{1,80}}\}}|[a-zA-Z0-9]+))+[a-zA-Z{GREEK_RANGE}][a-zA-Z0-9{GREEK_RANGE}]*(?:[_^](?:\{{[^{{}}\n]{{1,80}}\}}|[a-zA-Z0-9]+))+"
FORMULA_TOKEN_RE = re.compile(
    "|".join(
        [
            r"\$[^$\n]{1,2000}\$",
            r"\\\([^)]{1,2000}\\\)",
            r"\\\[[\s\S]{1,2400}?\\\]",
            r"\\begin\{(?:aligned|matrix|cases|array|pmatrix|bmatrix)\}[\s\S]{1,2400}?\\end\{[a-zA-Z*]+\}",
            LATEX_WRAPPED_LEFT_RIGHT_PATTERN,
            LATEX_LEFT_RIGHT_PATTERN,
            LATEX_WRAPPED_FUNCTION_PATTERN,
            LATEX_WRAPPED_EXPRESSION_PATTERN,
            LATEX_FRACTION_PATTERN,
            LATEX_BINOM_PATTERN,
            LATEX_SQRT_PATTERN,
            LATEX_NARY_PATTERN,
            LATEX_FUNCTION_EXPRESSION_PATTERN,
            LATEX_FUNCTION_PATTERN,
            UNICODE_RADICAL_PATTERN,
            HANCOM_RADICAL_PATTERN,
            UNICODE_NARY_PATTERN,
            LATEX_COMMAND_PATTERN,
            UNICODE_SUP_SUB_PATTERN,
            VULGAR_FRACTION_PATTERN,
            ABSOLUTE_VALUE_PATTERN,
            MATH_SYMBOL,
            FUNCTION_CALL_PATTERN,
            PREFIXED_SUP_SUB_PATTERN,
            rf"{MATH_OPERAND}\s*{MATH_OPERATOR}\s*{MATH_OPERAND}(?:\s*{MATH_OPERATOR}\s*{MATH_OPERAND})*",
            SUPER_SUB_PATTERN,
        ]
    ),
    re.MULTILINE,
)
DATE_LIKE_RE = re.compile(r"^\d{1,4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?$")
NUMERIC_RANGE_RE = re.compile(r"^\d+(?:\.\d+)?\s*[-~]\s*\d+(?:\.\d+)?$")
ALNUM_ID_RE = re.compile(r"^[A-Za-z]+\d+\s*[-/]\s*\d{2,}$")
CURRENCY_SPAN_RE = re.compile(r"^\$\d+(?:\.\d+)?(?:\s+\w+)?\s+\$\d+(?:\.\d+)?$")
CURRENCY_FRAGMENT_RE = re.compile(r"^\$\d+(?:\.\d+)?(?:\s+\w+)?\s*\$$")
MATH_SYMBOL_TOKEN_RE = re.compile(rf"^[√∑∏∫∞≤≥≠≈±×÷∠△∥⊥∈∉∪∩⊂⊃⊆⊇∘′″{VULGAR_FRACTION_CHARS}]$")
HANCOM_MATH_PLACEHOLDER_CHARS = "\u25a1\u25a2"
HANCOM_VECTOR_ACCENT_RE = re.compile(
    rf"[{HANCOM_MATH_PLACEHOLDER_CHARS}\s]*\u20d7\s*([A-Za-zα-ωΑ-Ω]{{1,3}}(?:['′″])?)"
)
HANCOM_RADICAL_FILLER_RE = re.compile(
    rf"(\u221a)\s*[{HANCOM_MATH_PLACEHOLDER_CHARS}]+"
)
HANCOM_SEGMENT_OVERLINE_RE = re.compile(
    rf"[{HANCOM_MATH_PLACEHOLDER_CHARS}]\s*([A-Z]{{1,3}})(?=\b|[\s=:+<>,)\uac00-\ud7a3])"
)
HANCOM_XBAR_RE = re.compile(
    rf"[{HANCOM_MATH_PLACEHOLDER_CHARS}][ \t]*([xX])(?=\b|[\s=+\-<>,)\]\uac00-\ud7a3])"
)
KOREAN_TEXT_RE = re.compile(r"[\uac00-\ud7a3]")
STACKED_LIMIT_RE = re.compile(
    rf"^[A-Za-z{GREEK_RANGE}][A-Za-z0-9{GREEK_RANGE}]*\s*(?:→|->|\\to)\s*[-+∞A-Za-z0-9{GREEK_RANGE}]+[{HANCOM_MATH_PLACEHOLDER_CHARS}]*$"
)
STACKED_FRACTION_DENOMINATOR_RE = re.compile(
    rf"^[A-Za-z0-9{GREEK_RANGE}∞+\-*/^_(){{}}\[\].]+$"
)
STACKED_SIMPLE_FRACTION_LINE_RE = re.compile(
    rf"^(?P<head>.*?)[{HANCOM_MATH_PLACEHOLDER_CHARS}](?P<den>[A-Za-z0-9{GREEK_RANGE}∞+\-.]+)\s*$"
)
STACKED_PREVIOUS_NUMERATOR_LINE_RE = re.compile(
    rf"^(?P<head>.*?)[{HANCOM_MATH_PLACEHOLDER_CHARS}](?P<den>[A-Za-z0-9{GREEK_RANGE}∞+\-.]+)(?P<suffix>.*)$"
)
STACKED_SIMPLE_FRACTION_NUMERATOR_RE = re.compile(
    rf"^(?P<num>[A-Za-z0-9{GREEK_RANGE}∞+\-.]+)(?P<suffix>.*)$"
)
STACKED_EXPONENT_BASE_RE = re.compile(rf"(?:[A-Za-z0-9{GREEK_RANGE}]|\)|\]|\}})$")
STACKED_STANDALONE_EXPONENT_RE = re.compile(
    r"^\s*(?:[+\-]?\d+|[+\-]?\\frac\{[^{}\n]{1,40}\}\{[^{}\n]{1,40}\})\s*$"
)
STACKED_BASE_AFTER_EXPONENT_RE = re.compile(
    rf"^(?P<prefix>\s*[×*]\s*)(?P<base>[A-Za-z0-9{GREEK_RANGE}]+)\s*$"
)
P_OVER_Q_CONTEXT_RE = re.compile(r"p\s*\+\s*q|\bp\s*,\s*q\b|p\s*와\s*q")
P_OVER_Q_PLACEHOLDER_RE = re.compile(rf"[{HANCOM_MATH_PLACEHOLDER_CHARS}]p(?![A-Za-z0-9{GREEK_RANGE}])")
STACKED_FRACTION_HEAD_OPERATORS = set("=+-−*/×÷(<[{,:")
MATH_CONNECTOR_RE = re.compile(
    r"^\s*(?:(?:->|=>)|\\(?:to|leq|geq|neq|approx|times|div|cdot|pm|mp|in|notin|cup|cap|subset|supset|subseteq|supseteq|circ)(?![A-Za-z])|[+\-*\/=<>≤≥≠≈×÷±∈∉∪∩⊂⊃⊆⊇∘^_()[\]{}|!])+\s*$"
)
MATH_TAIL_RE = re.compile(
    rf"^(?:\s*(?:(?:->|=>)|\\(?:to|leq|geq|neq|approx|times|div|cdot|pm|mp|in|notin|cup|cap|subset|supset|subseteq|supseteq|circ)(?![A-Za-z])|[+\-*\/=<>≤≥≠≈×÷±∈∉∪∩⊂⊃⊆⊇∘!])\s*"
    rf"(?:[+\-]?\d+(?:\.\d+)?|{IDENTIFIER}[{PRIME_CHARS}]*(?:[_^](?:\{{[^{{}}\n]{{1,80}}\}}|[a-zA-Z0-9]+))*|\([^()\n]{{1,120}}\)))+\s*$"
)
SUPERSCRIPT_TRANSLATION = str.maketrans(
    {
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
        "⁺": "+",
        "⁻": "-",
        "⁼": "=",
        "⁽": "(",
        "⁾": ")",
        "ⁿ": "n",
    }
)
SUBSCRIPT_TRANSLATION = str.maketrans(
    {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
        "₊": "+",
        "₋": "-",
        "₌": "=",
        "₍": "(",
        "₎": ")",
        "ₐ": "a",
        "ₑ": "e",
        "ₕ": "h",
        "ᵢ": "i",
        "ⱼ": "j",
        "ₖ": "k",
        "ₗ": "l",
        "ₘ": "m",
        "ₙ": "n",
        "ₒ": "o",
        "ₚ": "p",
        "ᵣ": "r",
        "ₛ": "s",
        "ₜ": "t",
        "ᵤ": "u",
        "ᵥ": "v",
        "ₓ": "x",
    }
)
VULGAR_FRACTION_MAP = {
    "¼": r"\frac{1}{4}",
    "½": r"\frac{1}{2}",
    "¾": r"\frac{3}{4}",
    "⅓": r"\frac{1}{3}",
    "⅔": r"\frac{2}{3}",
    "⅕": r"\frac{1}{5}",
    "⅖": r"\frac{2}{5}",
    "⅗": r"\frac{3}{5}",
    "⅘": r"\frac{4}{5}",
    "⅙": r"\frac{1}{6}",
    "⅚": r"\frac{5}{6}",
    "⅛": r"\frac{1}{8}",
    "⅜": r"\frac{3}{8}",
    "⅝": r"\frac{5}{8}",
    "⅞": r"\frac{7}{8}",
}
_RECOGNITION_TRANSLATION = str.maketrans(
    {
        "＋": "+",
        "－": "-",
        "−": "-",
        "﹣": "-",
        "＝": "=",
        "＜": "<",
        "＞": ">",
        "／": "/",
        "∕": "/",
        "⁄": "/",
        "＊": "*",
        "（": "(",
        "）": ")",
        "［": "[",
        "］": "]",
        "｛": "{",
        "｝": "}",
        "，": ",",
        "．": ".",
    }
)


def _symbol_pua_map() -> dict[str, str]:
    lower = {
        "a": "α",
        "b": "β",
        "c": "χ",
        "d": "δ",
        "e": "ε",
        "f": "φ",
        "g": "γ",
        "h": "η",
        "i": "ι",
        "j": "φ",
        "k": "κ",
        "l": "λ",
        "m": "μ",
        "n": "ν",
        "o": "ο",
        "p": "π",
        "q": "θ",
        "r": "ρ",
        "s": "σ",
        "t": "τ",
        "u": "υ",
        "v": "ϖ",
        "w": "ω",
        "x": "ξ",
        "y": "ψ",
        "z": "ζ",
    }
    upper = {
        "A": "Α",
        "B": "Β",
        "C": "Χ",
        "D": "Δ",
        "E": "Ε",
        "F": "Φ",
        "G": "Γ",
        "H": "Η",
        "I": "Ι",
        "J": "Θ",
        "K": "Κ",
        "L": "Λ",
        "M": "Μ",
        "N": "Ν",
        "O": "Ο",
        "P": "Π",
        "Q": "Θ",
        "R": "Ρ",
        "S": "Σ",
        "T": "Τ",
        "U": "Υ",
        "V": "Σ",
        "W": "Ω",
        "X": "Ξ",
        "Y": "Ψ",
        "Z": "Ζ",
    }
    mapping = {chr(0xF000 + ord(key)): value for key, value in {**lower, **upper}.items()}
    mapping.update(
        {
            "\uf02b": "+",
            "\uf02d": "-",
            "\uf02f": "/",
            "\uf03c": "<",
            "\uf03d": "=",
            "\uf03e": ">",
            "\uf028": "(",
            "\uf029": ")",
            "\uf05b": "[",
            "\uf05d": "]",
            "\uf0a3": "≤",
            "\uf0b3": "≥",
            "\uf0b9": "≠",
            "\uf0b1": "±",
            "\uf0d7": "×",
            "\uf0f7": "÷",
            "\uf0a5": "∞",
            "\uf0d6": "√",
            "\uf0e5": "∑",
            "\uf0f2": "∫",
        }
    )
    return mapping


# 병목 #2: 한컴 수식폰트(HyhwpEQ)의 E0xx PUA 매핑을 병합한다. 평가원 수학/과탐 수식이
# 이미지 폴백 대신 편집 가능한 텍스트로 복원된다(실물 18부 91.8% 커버리지). E0xx는
# _symbol_pua_map(F0xx)과 코드 범위가 겹치지 않아 충돌 없음. (위첨자/분수 등 2D 구조는
# 선형 복원이라 x²→x2로 평탄화 — 구조 복원은 후속 작업.)
from .hancom_pua_map import HANCOM_PUA_MAP as _HANCOM_PUA_MAP  # noqa: E402

SYMBOL_PUA_MAP = {**_symbol_pua_map(), **_HANCOM_PUA_MAP}


def _is_pua_or_bad_control(char: str) -> bool:
    code = ord(char)
    return (0xE000 <= code <= 0xF8FF) or (code < 32 and char not in "\t\n\r")


def is_recoverable_pua_math_char(char: str) -> bool:
    return char in SYMBOL_PUA_MAP


def _normalize_recognition_char(char: str) -> str:
    code = ord(char)
    if char in SYMBOL_PUA_MAP:
        return SYMBOL_PUA_MAP[char]
    if 0x1D400 <= code <= 0x1D7FF or 0xFF01 <= code <= 0xFFEF:
        return unicodedata.normalize("NFKC", char)
    return char.translate(_RECOGNITION_TRANSLATION)


def normalize_recognized_math_text(text: str) -> str:
    """Recover common OCR/PDF math glyph variants before math detection/export."""
    out: list[str] = []
    prev_unknown_pua = False
    for char in str(text or ""):
        if _is_pua_or_bad_control(char) and char not in SYMBOL_PUA_MAP:
            if not prev_unknown_pua:
                out.append("□")
                prev_unknown_pua = True
            continue
        out.append(_normalize_recognition_char(char))
        prev_unknown_pua = False
    value = "".join(out)
    value = HANCOM_RADICAL_FILLER_RE.sub(r"\1", value)
    value = HANCOM_VECTOR_ACCENT_RE.sub(r"\\vec{\1}", value)
    value = HANCOM_XBAR_RE.sub(r"\\overline{\1}", value)
    return HANCOM_SEGMENT_OVERLINE_RE.sub(r"\\overline{\1}", value)


def _normalize_limit_script(value: str) -> str:
    cleaned = str(value or "").strip().strip(HANCOM_MATH_PLACEHOLDER_CHARS)
    cleaned = cleaned.replace("→", r"\to")
    return re.sub(r"\s+", "", cleaned)


def _split_math_suffix(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    for marker in ("의 값은?", "의 값을", "의"):
        index = text.find(marker)
        if index > 0:
            return text[:index].strip(), text[index:].strip()
    return text, ""


def _looks_like_stacked_fraction_denominator(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped or len(stripped) > 80 or KOREAN_TEXT_RE.search(stripped):
        return False
    return bool(STACKED_FRACTION_DENOMINATOR_RE.match(stripped))


def _repair_stacked_limit_fractions(value: str) -> str:
    lines = str(value or "").splitlines()
    if len(lines) < 4:
        return str(value or "")

    repaired: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index].rstrip()
        if (
            current.endswith("lim")
            and index + 3 < len(lines)
            and STACKED_LIMIT_RE.match(lines[index + 1].strip())
            and _looks_like_stacked_fraction_denominator(lines[index + 3].strip())
        ):
            numerator, suffix = _split_math_suffix(lines[index + 2])
            denominator = lines[index + 3].strip()
            if numerator and not KOREAN_TEXT_RE.search(numerator):
                prefix = current[:-3].rstrip()
                limit_script = _normalize_limit_script(lines[index + 1])
                formula = rf"\lim_{{{limit_script}}}\frac{{{numerator}}}{{{denominator}}}"
                repaired.append(f"{prefix} {formula}{suffix}".strip())
                index += 4
                continue
        repaired.append(lines[index])
        index += 1
    return "\n".join(repaired)


def _case_context(lines: list[str], index: int) -> bool:
    nearby = "\n".join(lines[max(0, index - 8) : index + 1])
    return "{" in nearby and bool(re.search(r"[A-Za-z]\(x\)\s*=", nearby))


def _can_repair_simple_fraction_head(head: str) -> bool:
    stripped = str(head or "").rstrip()
    if not stripped:
        return True
    return stripped[-1] in STACKED_FRACTION_HEAD_OPERATORS


def _looks_like_stacked_fraction_numerator(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped or len(stripped) > 80 or KOREAN_TEXT_RE.search(stripped):
        return False
    if stripped[:1] in "①②③④⑤":
        return False
    return bool(STACKED_FRACTION_DENOMINATOR_RE.match(stripped))


def _can_repair_stacked_fraction_exponent_head(head: str) -> bool:
    stripped = str(head or "").rstrip()
    if not stripped or KOREAN_TEXT_RE.search(stripped):
        return False
    if _can_repair_simple_fraction_head(stripped):
        return False
    return bool(STACKED_EXPONENT_BASE_RE.search(stripped))


def _looks_like_stacked_fraction_exponent_parts(numerator: str, denominator: str) -> bool:
    numerator = str(numerator or "").strip()
    denominator = str(denominator or "").strip()
    if not denominator.isdigit() or len(denominator) > 3:
        return False
    if not _looks_like_stacked_fraction_numerator(numerator):
        return False
    return True


def _stacked_fraction_exponent(numerator: str, denominator: str) -> str:
    return f"^{{\\frac{{{numerator.strip()}}}{{{denominator.strip()}}}}}"


def _repair_stacked_fraction_exponents(value: str) -> str:
    lines = str(value or "").splitlines()
    if not lines:
        return str(value or "")

    repaired: list[str] = []
    index = 0
    while index < len(lines):
        if repaired:
            previous = repaired[-1].strip()
            current_match = STACKED_PREVIOUS_NUMERATOR_LINE_RE.match(lines[index].rstrip())
            if current_match:
                head = current_match.group("head")
                denominator = current_match.group("den")
                suffix = current_match.group("suffix")
                if (
                    not suffix.strip()
                    and _can_repair_stacked_fraction_exponent_head(head)
                    and _looks_like_stacked_fraction_exponent_parts(previous, denominator)
                ):
                    repaired[-1] = f"{head}{_stacked_fraction_exponent(previous, denominator)}".rstrip()
                    index += 1
                    continue

        if index + 1 < len(lines):
            line_match = STACKED_SIMPLE_FRACTION_LINE_RE.match(lines[index].rstrip())
            numerator_match = STACKED_SIMPLE_FRACTION_NUMERATOR_RE.match(lines[index + 1].strip())
            if line_match and numerator_match:
                head = line_match.group("head")
                denominator = line_match.group("den")
                numerator = numerator_match.group("num")
                suffix = numerator_match.group("suffix")
                if (
                    not suffix.strip()
                    and _can_repair_stacked_fraction_exponent_head(head)
                    and _looks_like_stacked_fraction_exponent_parts(numerator, denominator)
                ):
                    repaired.append(f"{head}{_stacked_fraction_exponent(numerator, denominator)}".rstrip())
                    index += 2
                    continue

        if index + 1 < len(lines):
            exponent = lines[index].strip()
            base_match = STACKED_BASE_AFTER_EXPONENT_RE.match(lines[index + 1].rstrip())
            if base_match and STACKED_STANDALONE_EXPONENT_RE.match(exponent):
                repaired.append(f"{base_match.group('prefix')}{base_match.group('base')}^{{{exponent}}}".rstrip())
                index += 2
                continue

        repaired.append(lines[index])
        index += 1
    return "\n".join(repaired)


def _repair_stacked_simple_fractions_and_cases(value: str) -> str:
    lines = str(value or "").splitlines()
    if not lines:
        return str(value or "")

    repaired: list[str] = []
    has_p_over_q_context = bool(P_OVER_Q_CONTEXT_RE.search(str(value or "")))
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and all(ch in HANCOM_MATH_PLACEHOLDER_CHARS for ch in stripped) and _case_context(lines, index):
            index += 1
            continue

        if repaired:
            previous = repaired[-1].strip()
            current_match = STACKED_PREVIOUS_NUMERATOR_LINE_RE.match(lines[index].rstrip())
            if current_match:
                head = current_match.group("head")
                denominator = current_match.group("den")
                suffix = current_match.group("suffix")
                if (
                    _can_repair_simple_fraction_head(head)
                    and not KOREAN_TEXT_RE.search(head)
                    and _looks_like_stacked_fraction_numerator(previous)
                    and denominator
                    and not (has_p_over_q_context and denominator == "p")
                ):
                    repaired[-1] = f"{head}\\frac{{{previous}}}{{{denominator}}}{suffix}".rstrip()
                    index += 1
                    continue

        if index + 1 < len(lines):
            line_match = STACKED_SIMPLE_FRACTION_LINE_RE.match(lines[index].rstrip())
            numerator_match = STACKED_SIMPLE_FRACTION_NUMERATOR_RE.match(lines[index + 1].strip())
            if line_match and numerator_match and _can_repair_simple_fraction_head(line_match.group("head")):
                head = line_match.group("head")
                denominator = line_match.group("den")
                numerator = numerator_match.group("num")
                suffix = numerator_match.group("suffix")
                if (
                    numerator
                    and denominator
                    and not KOREAN_TEXT_RE.search(numerator)
                    and not (has_p_over_q_context and denominator == "p")
                ):
                    repaired.append(f"{head}\\frac{{{numerator}}}{{{denominator}}}{suffix}".rstrip())
                    index += 2
                    continue

        repaired.append(lines[index])
        index += 1
    return "\n".join(repaired)


def _repair_p_over_q_placeholders(value: str) -> str:
    text = str(value or "")
    if "\uc11c\ub85c\uc18c" not in text or not P_OVER_Q_CONTEXT_RE.search(text):
        return text

    def replace(match: re.Match[str]) -> str:
        previous = text[max(0, match.start() - 80) : match.start()]
        if any(marker in previous for marker in ("q√", r"q\sqrt", "qπ", r"q\pi")):
            return match.group(0)
        return r"\frac{p}{q}"

    return P_OVER_Q_PLACEHOLDER_RE.sub(replace, text)


def normalize_recognized_math_layout_text(text: str) -> str:
    """Recover known glyphs plus simple PDF line-layout math structures."""
    value = _repair_stacked_limit_fractions(normalize_recognized_math_text(text))
    value = _repair_stacked_fraction_exponents(value)
    value = _repair_stacked_simple_fractions_and_cases(value)
    return _repair_p_over_q_placeholders(value)


@dataclass(slots=True)
class MathSpan:
    text: str
    start: int
    end: int
    kind: str
    normalized: str = ""
    field: str = ""
    index: int | None = None
    table: int | None = None
    row: int | None = None
    col: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in ("", None)}


def _span_kind(token: str) -> str:
    stripped = token.strip()
    if stripped.startswith(("$", r"\(", r"\[", r"\begin")):
        return "latex-block" if "\n" in stripped or stripped.startswith((r"\[", r"\begin")) else "latex-inline"
    if stripped.startswith("\\"):
        return "latex-command"
    if any(symbol in stripped for symbol in "√∑∏∫∞≤≥≠≈±×÷∠△∥⊥"):
        return "math-symbol"
    return "math-expression"


def strip_math_delimiters(token: str) -> str:
    value = str(token or "").strip()
    if len(value) >= 2 and value.startswith("$") and value.endswith("$"):
        return value[1:-1].strip()
    if value.startswith(r"\(") and value.endswith(r"\)"):
        return value[2:-2].strip()
    if value.startswith(r"\[") and value.endswith(r"\]"):
        return value[2:-2].strip()
    return value


def normalize_math_token(token: str) -> str:
    value = normalize_recognized_math_text(strip_math_delimiters(token))
    if not value:
        return ""
    if value in VULGAR_FRACTION_MAP:
        return VULGAR_FRACTION_MAP[value]

    value = "".join(VULGAR_FRACTION_MAP.get(char, char) for char in value)

    def replace_scripts(match: re.Match[str]) -> str:
        source = match.group(0)
        base = source.rstrip(SUPERSCRIPT_CHARS + SUBSCRIPT_CHARS)
        rest = source[len(base) :]
        output = base
        cursor = 0
        while cursor < len(rest):
            char = rest[cursor]
            script_chars = SUPERSCRIPT_CHARS if char in SUPERSCRIPT_CHARS else SUBSCRIPT_CHARS
            marker = "^" if char in SUPERSCRIPT_CHARS else "_"
            end = cursor + 1
            while end < len(rest) and rest[end] in script_chars:
                end += 1
            chunk = rest[cursor:end]
            translation = SUPERSCRIPT_TRANSLATION if marker == "^" else SUBSCRIPT_TRANSLATION
            output += f"{marker}" + "{" + chunk.translate(translation) + "}"
            cursor = end
        return output

    return re.sub(UNICODE_SUP_SUB_PATTERN, replace_scripts, value)


def extract_math_spans(text: str) -> list[MathSpan]:
    value = str(text or "")
    spans: list[MathSpan] = []
    last_end = 0
    for match in FORMULA_TOKEN_RE.finditer(value):
        token = match.group(0).strip()
        if (
            len(token) <= 1
            and not MATH_SYMBOL_TOKEN_RE.match(token)
        ) or DATE_LIKE_RE.match(token) or NUMERIC_RANGE_RE.match(token) or ALNUM_ID_RE.match(token) or CURRENCY_SPAN_RE.match(token) or CURRENCY_FRAGMENT_RE.match(token):
            continue
        if match.start() < last_end:
            continue
        spans.append(
            MathSpan(
                text=token,
                start=match.start(),
                end=match.end(),
                kind=_span_kind(token),
                normalized=normalize_math_token(token),
            )
        )
        last_end = match.end()
    return spans


def _is_explicit_math_token(token: str) -> bool:
    stripped = str(token or "").strip()
    return (
        (len(stripped) >= 2 and stripped.startswith("$") and stripped.endswith("$"))
        or (stripped.startswith(r"\(") and stripped.endswith(r"\)"))
        or (stripped.startswith(r"\[") and stripped.endswith(r"\]"))
        or stripped.startswith(r"\begin")
    )


def split_math_text(text: str) -> list[tuple[str, bool]]:
    value = str(text or "")
    if not value:
        return []
    spans = extract_math_spans(value)
    if not spans:
        return [(value, False)]
    ranges: list[tuple[int, int]] = []
    current_start = spans[0].start
    current_end = spans[0].end
    current_explicit = _is_explicit_math_token(spans[0].text)
    for span in spans[1:]:
        next_explicit = _is_explicit_math_token(span.text)
        separator = value[current_end : span.start]
        if not current_explicit and not next_explicit and MATH_CONNECTOR_RE.match(separator):
            current_end = span.end
            continue
        tail = value[current_end : span.start]
        if not current_explicit and MATH_TAIL_RE.match(tail):
            current_end = span.start
        ranges.append((current_start, current_end))
        current_start = span.start
        current_end = span.end
        current_explicit = next_explicit
    final_tail = value[current_end:]
    if not current_explicit and MATH_TAIL_RE.match(final_tail):
        current_end = len(value)
    ranges.append((current_start, current_end))

    parts: list[tuple[str, bool]] = []
    cursor = 0
    for start, end in ranges:
        if start > cursor:
            parts.append((value[cursor:start], False))
        parts.append((value[start:end], True))
        cursor = end
    if cursor < len(value):
        parts.append((value[cursor:], False))
    return parts or [(value, False)]


def _field_spans(field: str, text: str, **meta: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for span in extract_math_spans(text):
        span.field = field
        for key, value in meta.items():
            setattr(span, key, value)
        results.append(span.to_dict())
    return results


def analyze_problem_math(problem: dict[str, Any]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    spans.extend(_field_spans("stem", str(problem.get("stem") or "")))
    for index, choice in enumerate(problem.get("choices") or []):
        spans.extend(_field_spans("choices", str(choice or ""), index=index))
    spans.extend(_field_spans("answer", str(problem.get("answer") or "")))
    spans.extend(_field_spans("explanation", str(problem.get("explanation") or "")))
    for table_index, table in enumerate(problem.get("tables") or []):
        if not isinstance(table, list):
            continue
        for row_index, row in enumerate(table):
            if not isinstance(row, list):
                continue
            for col_index, cell in enumerate(row):
                spans.extend(
                    _field_spans(
                        "tables",
                        str(cell or ""),
                        table=table_index,
                        row=row_index,
                        col=col_index,
                    )
                )
    return spans


def math_summary(problem: dict[str, Any]) -> dict[str, Any]:
    spans = analyze_problem_math(problem)
    fields = sorted({str(span.get("field") or "") for span in spans if span.get("field")})
    return {
        "count": len(spans),
        "fields": fields,
        "has_latex": any(str(span.get("kind", "")).startswith("latex") for span in spans),
        "has_symbolic": any(span.get("kind") == "math-symbol" for span in spans),
    }
