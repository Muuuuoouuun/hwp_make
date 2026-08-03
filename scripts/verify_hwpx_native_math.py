# -*- coding: utf-8 -*-
"""HWPX native equation QA for math-heavy PDF samples.

Usage:
  python scripts/verify_hwpx_native_math.py
  python scripts/verify_hwpx_native_math.py data/uploads/sample.pdf

The built-in corpus verifies the writer path end to end:
  math text -> Hancom EQN script -> HWPX hp:equation -> re-importable script.
Optional PDF paths are scanned for text-layer math candidates so sample PDFs can
be compared against the equation corpus while the PDF extraction path evolves.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HWP_MAKE_DATA_DIR", str(ROOT / "data"))

from app import hwpx_writer, hwpx_writer_v2, importers, math_text, storage  # noqa: E402
from hwpx.tools.package_validator import validate_package  # noqa: E402
from scripts import qa_hwp_math_samples as layout_qa  # noqa: E402

HP_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
OUT_DIR = ROOT / "data" / "exports" / "native_math_qa"


@dataclass(frozen=True)
class FormulaCase:
    label: str
    source: str
    expected_script: str


LONG_HANCOM_EQN = (
    "lim _{x ``->`` 2} {} {g LEFT (x-1 RIGHT )} over "
    "{f LEFT (x RIGHT )-g LEFT (x RIGHT )} TIMES "
    "lim _{x ``->`` INF } {} {LEFT { f LEFT (x RIGHT ) it RIGHT } ^{2}} over "
    "{g LEFT (x RIGHT )} =k"
)


FORMULA_CASES: tuple[FormulaCase, ...] = (
    FormulaCase("fraction", r"\frac{1}{2}", "{1} over {2}"),
    FormulaCase("unbraced_fraction", r"$\frac12$", "{1} over {2}"),
    FormulaCase("nested_fraction_sqrt", r"\frac{\sqrt{x}}{2}", "{sqrt {x}} over {2}"),
    FormulaCase("unicode_fraction", "½", "{1} over {2}"),
    FormulaCase("subscript_superscript", r"x_{n+1}=\frac{1}{2}", "x_{n+1}={1} over {2}"),
    FormulaCase("unicode_scripts", "α²+βₙ=γ", "alpha^{2}+beta_{n}=gamma"),
    FormulaCase("greek_latex_extended", r"\phi+\varphi+\epsilon+\varepsilon", "phi+phi+epsilon+epsilon"),
    FormulaCase("greek_latex_uppercase", r"\Gamma+\Theta+\Omega", "GAMMA+THETA+OMEGA"),
    FormulaCase("greek_unicode_expression", "θ+Ω=π", "theta+OMEGA=pi"),
    FormulaCase("sqrt_atom", "√x", "sqrt {x}"),
    FormulaCase("sqrt_group", "√(x+1)", "sqrt {x+1}"),
    FormulaCase("latex_sqrt_unbraced", r"$\sqrt x$", "sqrt {x}"),
    FormulaCase("latex_sqrt", r"\sqrt{x^2+1}", "sqrt {x^{2}+1}"),
    FormulaCase("hancom_sqrt_digit_atom", "$sqrt5$", "sqrt {5}"),
    FormulaCase("hancom_sqrt_square_placeholder", "$sqrt□5$", "sqrt {5}"),
    FormulaCase("unicode_sqrt_square_placeholder", "√□5", "sqrt {5}"),
    FormulaCase("hancom_sqrt_missing_arg", "$sqrt□$", "sqrt {□}"),
    FormulaCase("unicode_sqrt_missing_arg", "√□", "sqrt {□}"),
    FormulaCase("hancom_sqrt_number_atom", "$sqrt43$", "sqrt {43}"),
    FormulaCase("hancom_sqrt_braced_no_space", "$sqrt{10}$", "sqrt {10}"),
    FormulaCase("hancom_sqrt_parenthesized", "$sqrt(n)$", "sqrt {n}"),
    FormulaCase("hancom_sqrt_nested_script", "$sqrt{a_{n} it ^ {2}+n}$", "sqrt {a_{n} it ^ {2}+n}"),
    FormulaCase(
        "hancom_sqrt_nested_fraction",
        "$sqrt{{x+1} over {x left(x+ ln `x  right)}}$",
        "sqrt {{x+1} over {x left(x+ ln `x  right)}}",
    ),
    FormulaCase("hancom_sqrt_inline_choice", "$18+15 sqrt3$", "18+15 sqrt {3}"),
    FormulaCase("sum_limits", r"\sum_{k=1}^{n} k", "sum_{k=1}^{n} k"),
    FormulaCase("integral_limits", r"\int_{0}^{1} dx", "int_{0}^{1} dx"),
    FormulaCase("integral_thinspace_dx", r"\int_{0}^{1} x^2\,dx", "int_{0}^{1} x^{2} dx"),
    FormulaCase("double_integral", r"$\iint_D f(x,y)\,dxdy$", "dint_{D} f(x,y) dxdy"),
    FormulaCase("triple_integral", r"$\iiint_V f(x,y,z)\,dV$", "tint_{V} f(x,y,z) dV"),
    FormulaCase("contour_integral", r"$\oint_C x\,dy-y\,dx$", "oint_{C} x dy-y dx"),
    FormulaCase("limit_fraction", r"\lim_{x\to0}\frac{\sin x}{x}", "lim_{x->0}{sin x} over {x}"),
    FormulaCase("limit_greek_fraction", r"\lim_{\theta\to0}\frac{\sin\theta}{\theta}", "lim_{theta->0}{sin theta} over {theta}"),
    FormulaCase("trig_identity", r"\sin x+\cos x=1", "sin x+cos x=1"),
    FormulaCase("trig_squared_identity", r"\sin^{2} x+\cos^{2} x=1", "sin^{2} x+cos^{2} x=1"),
    FormulaCase("min_function", r"\min_{x\in A} f(x)", "min_{x∈ A} f(x)"),
    FormulaCase("max_function", r"\max_{0\le x\le 1} x^2", "max_{0 LEQ x LEQ 1} x^{2}"),
    FormulaCase("inverse_trig", r"\arctan x", "arctan x"),
    FormulaCase("overline", r"\overline{x}", "bar {x}"),
    FormulaCase("underline", r"\underline{x}", "under {x}"),
    FormulaCase("vector", r"\vec{v}", "vec {v}"),
    FormulaCase("left_right", r"\left(x+1\right)", "(x+1)"),
    FormulaCase("matrix", r"\begin{matrix}a & b \\ c & d\end{matrix}", "matrix{a & b # c & d}"),
    FormulaCase("pmatrix", r"\begin{pmatrix}a & b \\ c & d\end{pmatrix}", "pmatrix{a & b # c & d}"),
    FormulaCase("bmatrix", r"\begin{bmatrix}a & b \\ c & d\end{bmatrix}", "bmatrix{a & b # c & d}"),
    FormulaCase("cases", r"\begin{cases}2x+y=4 \\ 3x-4y=-1\end{cases}", "cases{2x+y=4 # 3x-4y=-1}"),
    FormulaCase("inequality_latex", r"a\leq b", "a LEQ b"),
    FormulaCase("neq_latex", r"a\neq0", "a NEQ 0"),
    FormulaCase("log_base", r"\log_2 x", "log_{2} x"),
    FormulaCase("log_braced_argument", r"\log_{2}{x}", "log_{2}x"),
    FormulaCase("le_ge_aliases", r"a\le b\leq c \ne d \ge e", "a LEQ b LEQ c NEQ d GEQ e"),
    FormulaCase("relation_operators", r"$x\sim y\simeq z\cong w\equiv q\propto r$", "x SIM y SIMEQ z CONG w== q PROPTO r"),
    FormulaCase("order_operators", r"$a\ll b\gg c\prec d\succ e$", "a<< b>> c PREC d SUCC e"),
    FormulaCase("absolute_value", r"\left|x-1\right|", "|x-1|"),
    FormulaCase("ceiling_delimiter", r"\left\lceil x\right\rceil", "⌈x⌉"),
    FormulaCase("floor_delimiter", r"\left\lfloor x\right\rfloor", "⌊x⌋"),
    FormulaCase("set_builder_mid", r"\left\{x\mid x>0\right\}", "{x| x>0}"),
    FormulaCase("interval_bracket", r"\left[0,1\right]", "[0,1]"),
    FormulaCase("nth_root", r"\sqrt[3]{x^2+1}", "^3sqrt {x^{2}+1}"),
    FormulaCase("binomial", r"\binom{n}{r}", "{n} choose {r}"),
    FormulaCase("unbraced_binomial", r"$\binom nr$", "{n} choose {r}"),
    FormulaCase("combination_symbol", r"{}_{n}C_{r}", "{}_{n}C_{r}"),
    FormulaCase("derivative_prime", "f'(1)=3", "f'(1)=3"),
    FormulaCase("composition", r"g\circ f", "g∘ f"),
    FormulaCase("set_membership", r"x\in A", "x∈ A"),
    FormulaCase("set_not_membership", r"x\notin A", "x∉ A"),
    FormulaCase("set_union", r"A\cup B", "A∪ B"),
    FormulaCase("set_intersection", r"A\cap B", "A∩ B"),
    FormulaCase("set_subseteq", r"A\subseteq B", "A⊆ B"),
    FormulaCase("set_supseteq", r"A\supseteq B", "A⊇ B"),
    FormulaCase("quantifiers", r"$\forall x\in A, \exists y\notin B$", "FORALL x∈ A, EXIST y∉ B"),
    FormulaCase("emptyset_subset", r"$\emptyset \subset A$", "EMPTYSET ⊂ A"),
    FormulaCase("varnothing_subseteq", r"$\varnothing\subseteq A$", "EMPTYSET ⊆ A"),
    FormulaCase("logic_operators", r"$A\oplus B\land C\lor D$", "A OPLUS B LAND C LOR D"),
    FormulaCase("partial_derivative", r"$\partial f/\partial x$", "Partial f/Partial x"),
    FormulaCase("arrows", r"$A\Rightarrow B\Leftrightarrow C$", "A RARROW B LRARROW C"),
    FormulaCase("arrow_variants", r"$x\leftarrow y\leftrightarrow z\mapsto w$", "x larrow y <-> z MAPSTO w"),
    FormulaCase("vector_segment", r"\overrightarrow{AB}", "vec {AB}"),
    FormulaCase("hat_angle", r"\widehat{ABC}", "hat {ABC}"),
    FormulaCase("extended_accents", r"$\widetilde{x}+\acute{y}+\grave{z}+\overleftrightarrow{AB}$", "tilde {x}+acute {y}+grave {z}+dyad {AB}"),
    FormulaCase("boxed_expression", r"$\boxed{x+1}$", "BOX {x+1}"),
    FormulaCase("brace_accents", r"$\overbrace{x+y}+\underbrace{z}$", "OVERBRACE {x+y}+UNDERBRACE {z}"),
    FormulaCase("mathbb_real", r"x\in\mathbb{R}", "x∈ℝ"),
    FormulaCase("math_font_wrappers", r"$\mathcal{L}+\mathsf{A}+\mathtt{B}+\boldsymbol{x}$", "L+A+B+x"),
    FormulaCase("probability_wrapper", r"\mathrm{P}(A)", "P(A)"),
    FormulaCase("probability_command", r"\Pr(A)=\frac{1}{2}", "Pr(A)={1} over {2}"),
    FormulaCase("probability_intersection", r"\mathrm{P}\left(A\cap B\right)", "P(A∩ B)"),
    FormulaCase("aligned", r"\begin{aligned}x+y&=1 \\ x-y&=3\end{aligned}", "eqalign{x+y & =1 # x-y & =3}"),
    FormulaCase("align_environment", r"$\begin{align}x&=1\\y&=2\end{align}$", "eqalign{x & =1 # y & =2}"),
    FormulaCase("array_alignment", r"\begin{array}{cc}a&b\\c&d\end{array}", "matrix{a & b # c & d}"),
    FormulaCase("vmatrix_environment", r"$\begin{vmatrix}a&b\\c&d\end{vmatrix}$", "dmatrix{a & b # c & d}"),
    FormulaCase("pmod_expression", r"$a\equiv b\pmod{n}$", "a== b mod n"),
    FormulaCase("long_hancom_eqn", f"${LONG_HANCOM_EQN}$", LONG_HANCOM_EQN),
)


def _problem_for_cases() -> dict[str, object]:
    return {
        "number": "1",
        "title": "네이티브 수식 QA",
        "stem": "\n".join(
            f"Case {index:02d} {case.label.replace('_', ' ')}: {case.source}"
            for index, case in enumerate(FORMULA_CASES, start=1)
        ),
        "choices": [
            r"\frac{a}{b}",
            r"\sqrt{x}",
            r"\sum_{k=1}^{n} k",
            r"\begin{cases}x=1 \\ y=2\end{cases}",
            r"\int_{0}^{1}x^2 dx",
            r"$sqrt5$",
            r"\frac{\sqrt{x+1}}{3}",
        ],
        "answer": "1",
        "explanation": "\n".join(
            [
                r"\lim_{x\to0}\frac{\sin x}{x}",
                r"\frac{\sqrt{x}}{2}+\int_{0}^{1}x^2 dx",
                r"\sum_{k=1}^{n}k=\frac{n(n+1)}{2}",
            ]
        ),
        "tables": [
            [
                ["case", "formula"],
                ["fraction", r"\frac{1}{2}"],
                ["matrix", r"\begin{matrix}a & b \\ c & d\end{matrix}"],
            ]
        ],
        "image_paths": [],
    }


def _equation_scripts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("Contents/section0.xml"))
    return [
        "".join(node.text or "" for node in equation.iter(f"{HP_NS}script")).strip()
        for equation in root.iter(f"{HP_NS}equation")
    ]


def _equation_object_issues(path: Path) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    with zipfile.ZipFile(path) as archive:
        section_names = sorted(
            name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)
        )
        ids: list[str] = []
        zorders: list[str] = []
        for section_name in section_names:
            root = ET.fromstring(archive.read(section_name))
            for index, equation in enumerate(root.iter(f"{HP_NS}equation"), start=1):
                script = "".join(node.text or "" for node in equation.iter(f"{HP_NS}script")).strip()
                reasons: list[str] = []
                for attr, expected in (
                    ("numberingType", "EQUATION"),
                    ("lineMode", "CHAR"),
                    ("font", "HancomEQN"),
                ):
                    if equation.get(attr) != expected:
                        reasons.append(f"{attr}={equation.get(attr)!r}")
                if equation.get("id"):
                    ids.append(str(equation.get("id")))
                else:
                    reasons.append("missing id")
                if equation.get("zOrder"):
                    zorders.append(str(equation.get("zOrder")))
                else:
                    reasons.append("missing zOrder")
                if not equation.get("version"):
                    reasons.append("missing version")
                if not script:
                    reasons.append("missing script")
                sz = equation.find(f"{HP_NS}sz")
                if sz is None:
                    reasons.append("missing sz")
                else:
                    if sz.get("widthRelTo") != "ABSOLUTE":
                        reasons.append(f"sz.widthRelTo={sz.get('widthRelTo')!r}")
                    if sz.get("heightRelTo") != "ABSOLUTE":
                        reasons.append(f"sz.heightRelTo={sz.get('heightRelTo')!r}")
                pos = equation.find(f"{HP_NS}pos")
                if pos is None:
                    reasons.append("missing pos")
                else:
                    for attr, expected in (
                        ("treatAsChar", "1"),
                        ("flowWithText", "1"),
                        ("allowOverlap", "0"),
                    ):
                        if pos.get(attr) != expected:
                            reasons.append(f"pos.{attr}={pos.get(attr)!r}")
                if equation.find(f"{HP_NS}script") is None:
                    reasons.append("missing script node")
                if reasons:
                    issues.append(
                        {
                            "section": section_name,
                            "equation": index,
                            "id": equation.get("id"),
                            "zOrder": equation.get("zOrder"),
                            "script": script[:120],
                            "reasons": reasons,
                        }
                    )
        for label, values in (("duplicate id", ids), ("duplicate zOrder", zorders)):
            counts: dict[str, int] = {}
            for value in values:
                counts[value] = counts.get(value, 0) + 1
            for value, count in counts.items():
                if count > 1:
                    issues.append({"reason": label, "value": value, "count": count})
    return issues


def _equation_texts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("Contents/section0.xml"))
    return [importers._hwpx_equation_text(equation) for equation in root.iter(f"{HP_NS}equation")]


def _validate_with_rhwp(path: Path) -> dict[str, object]:
    try:
        import rhwp
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        document = rhwp.parse(str(path))
        rendered = bytes(document.render_png(0))
        render_path = path.with_suffix(".page1.png")
        render_path.write_bytes(rendered)
        return {
            "available": True,
            "page_count": int(document.page_count),
            "render_bytes": len(rendered),
            "render_path": str(render_path),
        }
    except Exception as exc:
        return {"available": True, "error": f"{type(exc).__name__}: {exc}"}


def _blank_equation_scripts(path: Path) -> Path:
    control_path = path.with_name(f"{path.stem}_blank_equations{path.suffix}")
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}

    updates: dict[str, bytes] = {}
    for name, data in payloads.items():
        if not re.fullmatch(r"Contents/section\d+\.xml", name):
            continue
        root = ET.fromstring(data)
        changed = False
        for script in root.iter(f"{HP_NS}script"):
            if script.text:
                script.text = ""
                changed = True
        if changed:
            updates[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    with zipfile.ZipFile(control_path, "w") as out:
        for info in infos:
            out.writestr(info, updates.get(info.filename, payloads[info.filename]))
    return control_path


def _native_math_visibility(path: Path) -> dict[str, object]:
    control_path = _blank_equation_scripts(path)
    code = r"""
import json
import sys
from io import BytesIO
from pathlib import Path

try:
    import rhwp
    from PIL import Image, ImageChops
except Exception as exc:
    print(json.dumps({"available": False, "error": f"{type(exc).__name__}: {exc}"}))
    raise SystemExit(0)

actual_path = Path(sys.argv[1])
control_path = Path(sys.argv[2])
try:
    actual = rhwp.parse(str(actual_path))
    control = rhwp.parse(str(control_path))
    page_count = min(int(actual.page_count), int(control.page_count))
    page_diffs = []
    changed_total = 0
    pixel_total = 0
    for page_index in range(page_count):
        actual_png = bytes(actual.render_png(page_index))
        control_png = bytes(control.render_png(page_index))
        actual_image = Image.open(BytesIO(actual_png)).convert("L")
        control_image = Image.open(BytesIO(control_png)).convert("L")
        if actual_image.size != control_image.size:
            control_image = control_image.resize(actual_image.size)
        diff = ImageChops.difference(actual_image, control_image)
        hist = diff.histogram()
        changed = sum(count for value, count in enumerate(hist) if value > 30)
        total = actual_image.width * actual_image.height
        changed_total += changed
        pixel_total += total
        page_diffs.append({
            "page": page_index + 1,
            "changed_pixels": changed,
            "total_pixels": total,
            "changed_ratio": round(changed / total, 6) if total else 0,
        })
    print(json.dumps({
        "available": True,
        "page_count": page_count,
        "actual_page_count": int(actual.page_count),
        "control_page_count": int(control.page_count),
        "changed_pixels": changed_total,
        "total_pixels": pixel_total,
        "changed_ratio": round(changed_total / pixel_total, 6) if pixel_total else 0,
        "page_diffs": page_diffs,
    }, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"available": True, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
    raise
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(path), str(control_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    json_lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if not json_lines:
        return {
            "available": False,
            "control_path": str(control_path),
            "error": f"visibility subprocess produced no JSON (exit {completed.returncode})",
            "log_tail": (completed.stdout + completed.stderr).splitlines()[-20:],
        }
    try:
        result = json.loads(json_lines[-1])
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "control_path": str(control_path),
            "error": f"visibility subprocess JSON parse failed: {exc}",
            "log_tail": (completed.stdout + completed.stderr).splitlines()[-20:],
        }
    result["control_path"] = str(control_path)
    result["log_tail"] = (completed.stdout + completed.stderr).splitlines()[-20:]
    if completed.returncode != 0 and not result.get("error"):
        result["error"] = f"visibility subprocess exited {completed.returncode}"
    return result


def _pdf_math_candidates(path: Path) -> dict[str, object]:
    try:
        import fitz
    except Exception as exc:
        return {"path": str(path), "available": False, "error": f"PyMuPDF unavailable: {exc}"}

    pages: list[dict[str, object]] = []
    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        return {"path": str(path), "available": True, "error": f"open failed: {type(exc).__name__}: {exc}"}
    try:
        for index in range(doc.page_count):
            text = doc.load_page(index).get_text("text") or ""
            normalized = math_text.normalize_recognized_math_text(text)
            spans = [span.to_dict() for span in math_text.extract_math_spans(normalized)]
            pages.append(
                {
                    "page": index + 1,
                    "text_chars": len(text),
                    "math_count": len(spans),
                    "math_spans": spans[:80],
                    "truncated": len(spans) > 80,
                }
            )
    finally:
        doc.close()
    return {"path": str(path), "available": True, "pages": pages}


def run(pdf_paths: list[Path]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    storage.ensure_dirs()

    direct_cases = []
    failures: list[str] = []
    for case in FORMULA_CASES:
        actual = hwpx_writer._hancom_eqn_script(case.source)
        ok = actual == case.expected_script
        direct_cases.append({**asdict(case), "actual_script": actual, "ok": ok})
        if not ok:
            failures.append(f"{case.label}: expected {case.expected_script!r}, got {actual!r}")

    width_cases = {
        "inline_function": ("f left(x  right)`", 2600, 4200),
        "inline_condition": ("a  ~ LEFT ( a != 3 sqrt {5}  RIGHT )`", 5200, 7600),
        "short_fraction": ("{37} over {4}", 2600, 4200),
        "short_radical_choice": ("18+15  sqrt{3}", 4200, 6200),
        "display_cases": (
            "g LEFT ( x RIGHT ) = {cases{``x ^{3} +ax ^{2} +15x+7&&LEFT ( x LEQ 0 RIGHT )#"
            "``f LEFT ( x RIGHT )&&LEFT ( x>0 RIGHT )}}",
            20000,
            24000,
        ),
    }
    width_report = {}
    for label, (script, lower, upper) in width_cases.items():
        width, height = hwpx_writer._equation_size(script)
        width_report[label] = {"script": script, "width": width, "height": height, "range": [lower, upper]}
        if width < lower or width > upper:
            failures.append(f"{label}: equation width {width} outside expected range {lower}..{upper}")

    hwpx_path = OUT_DIR / "native_math_corpus.hwpx"
    # Exercise the same writer used by /api/export.  Keeping this QA on the
    # legacy string-template writer allowed the production HWPX path to drift
    # without this high-value native-equation/render gate noticing.
    hwpx_writer_v2.write_hwpx(
        hwpx_path,
        "네이티브 수식 QA",
        [_problem_for_cases()],
        template_key="school_exam",
        native_math=True,
    )
    package_report = validate_package(hwpx_path)
    package_issues = [
        {
            "level": issue.level,
            "part_name": issue.part_name,
            "message": issue.message,
        }
        for issue in package_report.issues
    ]
    blocking_package_issues = [
        issue
        for issue in package_issues
        if issue["level"] == "error" or "version part" in issue["message"]
    ]
    if blocking_package_issues:
        failures.append(f"HWPX package validity issues: {blocking_package_issues[:8]}")
    scripts = _equation_scripts(hwpx_path)
    object_issues = _equation_object_issues(hwpx_path)
    if object_issues:
        failures.append(f"native equation object integrity issues: {object_issues[:8]}")
    for case in FORMULA_CASES:
        if case.expected_script not in scripts:
            failures.append(f"{case.label}: HWPX script missing {case.expected_script!r}")

    imported_texts = _equation_texts(hwpx_path)
    imported_text = "\n".join(imported_texts)
    for expected in ("over", "sqrt", "matrix", "cases", "lim"):
        if expected not in imported_text:
            failures.append(f"roundtrip import missing {expected!r} in equation text")

    visibility = _native_math_visibility(hwpx_path)
    if visibility.get("available") and visibility.get("error"):
        failures.append(f"native equation render visibility check failed: {visibility['error']}")
    elif visibility.get("available"):
        changed_pixels = int(visibility.get("changed_pixels") or 0)
        changed_ratio = float(visibility.get("changed_ratio") or 0)
        if changed_pixels < 4000 or changed_ratio < 0.001:
            failures.append(
                "native equation render visibility is too weak versus blank-script control: "
                f"changed_pixels={changed_pixels}, changed_ratio={changed_ratio}"
            )
        weak_pages = [
            page
            for page in visibility.get("page_diffs") or []
            if isinstance(page, dict)
            and (
                int(page.get("changed_pixels") or 0) < 700
                or float(page.get("changed_ratio") or 0) < 0.0008
            )
        ]
        if weak_pages:
            failures.append(f"native equation render visibility is weak on pages: {weak_pages[:8]}")

    # Render every page in a subprocess so rhwp's LAYOUT_OVERFLOW diagnostics
    # are captured and promoted to a hard failure.  The former first-page
    # smoke check printed those diagnostics but still returned success.
    layout_render = layout_qa._render_hwpx(hwpx_path, OUT_DIR / "renders", 0)
    if layout_render.get("error"):
        failures.append(f"rhwp full-document render failed: {layout_render['error']}")
    if layout_render.get("overflow_count"):
        failures.append(
            "rhwp full-document layout overflow count: "
            f"{layout_render['overflow_count']} ({layout_render.get('overflow_lines', [])[:8]})"
        )

    pdf_reports = [_pdf_math_candidates(path) for path in pdf_paths]
    report = {
        "ok": not failures,
        "hwpx_path": str(hwpx_path),
        "equation_count": len(scripts),
        "package_issues": package_issues,
        "scripts": scripts,
        "equation_object_issue_count": len(object_issues),
        "equation_object_issues": object_issues[:20],
        "direct_cases": direct_cases,
        "width_cases": width_report,
        "roundtrip_equation_texts": imported_texts,
        "rhwp": _validate_with_rhwp(hwpx_path),
        "layout_render": {
            "page_count": layout_render.get("page_count"),
            "overflow_count": layout_render.get("overflow_count"),
            "overflow_lines": layout_render.get("overflow_lines") or [],
            "render_bytes": layout_render.get("render_bytes") or [],
            "error": layout_render.get("error"),
        },
        "render_visibility": visibility,
        "pdfs": pdf_reports,
        "failures": failures,
    }
    report_path = OUT_DIR / "native_math_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"HWPX: {hwpx_path}")
    print(f"Report: {report_path}")
    print(f"Equation scripts: {len(scripts)}")
    if visibility.get("available"):
        print(
            "Render visibility: "
            f"changed_pixels={visibility.get('changed_pixels')}, "
            f"changed_ratio={visibility.get('changed_ratio')}"
        )
    for pdf in pdf_reports:
        page_counts = [int(page.get("math_count") or 0) for page in pdf.get("pages", [])] if isinstance(pdf.get("pages"), list) else []
        print(f"PDF: {pdf.get('path')} math candidates={sum(page_counts)}")
    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Native HWPX math QA OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify HWPX native math equation output.")
    parser.add_argument("pdf", nargs="*", type=Path, help="Optional sample PDF path(s) to scan for math candidates.")
    args = parser.parse_args()
    return run(args.pdf)


if __name__ == "__main__":
    raise SystemExit(main())
