"""Pin choice-label stripping in the HWPX/DOCX writers (2026-10-03 fix step 5a).

The old CHOICE_PREFIX_RE (``\\d+\\s*[.)]`` or "digit + space") treated numeric
choice values as labels: '0.5'->'5', '3.5'->'5', '2 cm'->'cm', '1 : 2'->': 2',
'12.5%'->'5%'. Only real labels (①~⑨, 1)~9), (1)~(9), 1.~9. not followed by a
digit) may be stripped.

Synthetic only; never SKIPs. Exit codes: 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import html
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory(prefix="hwpmake_choice_prefix_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = _TMP.name

from app import docx_writer, exam_templates, hwpx_writer, hwpx_writer_v2  # noqa: E402

failures: list[str] = []

# (입력 선지, 접두 제거 후 기대값)
CASES = [
    ("① 사과", "사과"),
    ("②사과", "사과"),
    ("1) 사과", "사과"),
    ("1)사과", "사과"),
    ("(1) 사과", "사과"),
    ("( 3 ) 사과", "사과"),
    ("1. 사과", "사과"),
    ("5.사과", "사과"),
    ("0.5", "0.5"),
    ("3.5", "3.5"),
    ("2 cm", "2 cm"),
    ("1 : 2", "1 : 2"),
    ("12.5%", "12.5%"),
    ("3.14", "3.14"),
    ("12) 사과", "12) 사과"),
    ("10. 사과", "10. 사과"),
    ("-1", "-1"),
    ("1.5배", "1.5배"),
    ("사과", "사과"),
]
VALUES = ["0.5", "3.5", "2 cm", "1 : 2", "12.5%"]


def main_check() -> int:
    if hwpx_writer.CHOICE_PREFIX_RE.pattern != docx_writer.CHOICE_PREFIX_RE.pattern:
        failures.append("HWPX and DOCX writers must share one choice-prefix rule")
    for module in (hwpx_writer, docx_writer):
        for raw, expected in CASES:
            got = module.CHOICE_PREFIX_RE.sub("", raw).strip()
            if got != expected:
                failures.append(f"{module.__name__}: {raw!r} -> {got!r}, expected {expected!r}")

    template = exam_templates.get_template("simple")
    for index, value in enumerate(VALUES, start=1):
        formatted = hwpx_writer._format_choice(index, value, template)
        if not formatted.endswith(value):
            failures.append(f"_format_choice({value!r}) lost the value: {formatted!r}")
        relabeled = hwpx_writer._format_choice(index, f"{index}) {value}", template)
        if relabeled != formatted:
            failures.append(f"labelled choice was not normalized: {relabeled!r} vs {formatted!r}")

    problem = {"id": 1, "number": "1", "stem": "1. 값을 고르시오.", "choices": VALUES, "answer": "", "explanation": ""}
    out = Path(_TMP.name)
    hwpx_path, docx_path = out / "choice.hwpx", out / "choice.docx"
    # native_math=False: compare the plain run text, independent of equation conversion.
    hwpx_writer_v2.write_hwpx(hwpx_path, "선지 값 보존", [problem], "simple", native_math=False)
    docx_writer.write_docx(docx_path, "선지 값 보존", [problem], "simple")
    with zipfile.ZipFile(hwpx_path) as archive:
        section = "".join(archive.read(name).decode("utf-8") for name in archive.namelist() if name.startswith("Contents/section"))
    hwpx_text = html.unescape("".join(re.findall(r"<hp:t[^>]*>(.*?)</hp:t>", section, re.S)))
    with zipfile.ZipFile(docx_path) as archive:
        docx_text = html.unescape("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", archive.read("word/document.xml").decode("utf-8"), re.S)))
    for label, text in (("HWPX", hwpx_text), ("DOCX", docx_text)):
        for value in VALUES:
            if value not in text:
                failures.append(f"{label} export lost choice value {value!r}")

    if failures:
        print(f"Choice prefix verification FAILED ({len(failures)} issues)")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"Choice prefix verification PASS ({len(CASES)} cases x 2 writers, HWPX/DOCX export values kept)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main_check())
    finally:
        _TMP.cleanup()
