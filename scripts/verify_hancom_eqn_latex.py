# -*- coding: utf-8 -*-
"""한컴 수식 script → LaTeX 변환(app/hancom_eqn_latex.py)과 DOCX 수식 연결 검증.

HWP/HWPX 가져오기는 수식을 한컴 script 원문($...$)으로 보관한다. DOCX 내보내기의
OMML 변환기는 LaTeX만 읽어 종전에는 `{1} over {2}`가 글자 그대로 들어갔다.
kordoc(src/hwpx/equation.ts, hml-equation-parser 파생) 테스트 사례와 이 앱 writer가
내는 어휘를 고정한다. 종료코드 0=통과, 1=실패.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["HWP_MAKE_DATA_DIR"] = _TMP.name

from app import docx_writer, hwpx_writer  # noqa: E402
from app.hancom_eqn_latex import hancom_script_to_latex  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


# (label, Hancom script, expected LaTeX with whitespace removed)
CASES: tuple[tuple[str, str, str], ...] = (
    ("floor_delimiters", "LEFT ⌊ a+b RIGHT ⌋", r"\left\lfloora+b\right\rfloor"),
    ("single_tokens", "a ± b != c LEQ d", r"a\pmb\neqc\leqd"),
    ("greek", "alpha + PHI", r"\alpha+\Phi"),
    ("literal_braces", "LEFT { x RIGHT }", r"\left\{x\right\}"),
    ("frac", "{a} over {b}", r"\frac{a}{b}"),
    ("nested_frac", "{ { 1 } over { x } } over { y }", r"\frac{\frac{1}{x}}{y}"),
    ("root_of", "root {3} of {x+1}", r"\sqrt[3]{x+1}"),
    ("quoted_over_literal", '{a} over {b} + x _ {"over"}', r"\frac{a}{b}+x_{\text{over}}"),
    ("quoted_profit_literal", '"profit" + root {3} of {x}', r"\text{profit}+\sqrt[3]{x}"),
    ("word_substrings", "groot + cover", "groot+cover"),
    ("vec", "{ vec {AB} }", r"\overrightarrow{AB}"),
    ("hat", "{ hat {x} }", r"\widehat{x}"),
    ("overbrace", "OVERBRACE {x+y} {n}", r"\overbrace{x+y}^{n}"),
    ("arch", "arch {AB}", r"\overset{\frown}{AB}"),
    ("choose", "{n} choose {r}", r"\binom{n}{r}"),
    ("writer_nth_root", "^3sqrt {x^{2}+1}", r"\sqrt[3]{x^{2}+1}"),
    ("glued_scripts", "sum_{k=1}^{n} k", r"\sum_{k=1}^{n}k"),
    ("glued_words", "alpha^{2}+beta_{n}=gamma", r"\alpha^{2}+\beta_{n}=\gamma"),
    ("glued_arrow", "lim _{x->0} {sin x} over {x}", r"\lim_{x\rightarrow0}\frac{\sinx}{x}"),
    ("writer_operators", "a NEQ b approx c therefore d", r"a\neqb\approxc\therefored"),
    ("quoted_text_spacing", 'x=1"이면 "y=2', r"x=1\text{이면}y=2"),
    ("italic_marker_dropped", "{a _{n}it^{2} +5} over {3}", r"\frac{a_{n}^{2}+5}{3}"),
)


def main() -> int:
    for label, script, expected in CASES:
        got = hancom_script_to_latex(script)
        check(label, squash(got) == expected, f"{script!r} -> {got!r}")

    got = hancom_script_to_latex('{ "sum over items" } + {a} over {b}')
    check("multi_word_quote_keeps_over", r"\text{sum over items}" in got and r"\frac{a}{b}" in squash(got), got)

    cases = hancom_script_to_latex(
        "f LEFT ( x RIGHT ) = {cases{``5x+a&&LEFT ( x<`-2 RIGHT )#``x ^{2} -a&&LEFT ( x GEQ `-2 RIGHT )}}"
    )
    check("real_exam_cases", r"\begin{cases}" in cases and r"\end{cases}" in cases and "\\\\" in cases, cases)
    matrix = hancom_script_to_latex("{ matrix {a & b # c & d} }")
    check("matrix", squash(matrix) == r"\begin{matrix}a&b\\c&d\end{matrix}", matrix)
    check("empty", hancom_script_to_latex("") == "" and hancom_script_to_latex("   ") == "")

    source = " ".join(f"{{a{index}}} over {{b{index}}}" for index in range(2000))
    started = time.perf_counter()
    many = hancom_script_to_latex(source)
    elapsed = time.perf_counter() - started
    check("2000_fracs_linear", many.count(r"\frac") == 2000 and elapsed < 2.0, f"{elapsed:.2f}s")

    # Every equation this app's HWPX writer emits must convert without leftovers.
    for latex in (
        r"\left(\frac12\right)^n",
        r"\left\{\begin{array}{ll}x & (x\ge0)\\ -x & (x<0)\end{array}\right.",
        r"\sqrt[3]{x^2+1}",
        r"\binom{n}{r}",
        r"\overbrace{a+b}^{n}",
        r"\overset{\frown}{AB}",
        r"\lim_{x\to\infty}\frac{\sin x}{x}",
    ):
        script = hwpx_writer._hancom_eqn_script(latex)
        back = hancom_script_to_latex(script or "")
        leftovers = re.findall(r"(?<![\\{])\b(?:over|LEFT|RIGHT|HULK\w*|cases|choose|arch|OVERBRACE|sqrt)\b", back)
        check(f"writer_roundtrip {latex}", bool(script) and not leftovers, f"{script!r} -> {back!r}")

    # DOCX: Hancom scripts from HWP/HWPX imports become structured OMML.
    path = Path(_TMP.name) / "eq.docx"
    docx_writer.write_docx(
        path,
        "eq",
        [{"number": 1, "stem": "값 ${1} over {2}$, ${n} choose {r}$, $sqrt {x ^{2} +1}$", "choices": []}],
    )
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    math_text = "".join(re.findall(r"<m:t[^>]*>([^<]*)</m:t>", xml))
    check("docx_structures", "<m:f>" in xml and "<m:rad>" in xml and "<m:d>" in xml, "")
    check("docx_no_script_words", not re.search(r"over|choose|sqrt|\\\\", math_text), math_text)

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("HANCOM_EQN_LATEX_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
