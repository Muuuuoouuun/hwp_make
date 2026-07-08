# -*- coding: utf-8 -*-
"""Verify KICE template typography in generated HWPX.

This guard checks the writer-level contract derived from real HWP samples:
KICE templates must emit exam-like font faces, 11pt body text, 165% line
spacing, 95% character ratio, -5 spacing, and native Hancom equation fonts.
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HWP_MAKE_DATA_DIR", str(ROOT / "data" / "kice_typography"))
sys.path.insert(0, str(ROOT))

from app import hwpx_writer_v2, storage  # noqa: E402

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _font_faces(header: ET.Element) -> dict[str, dict[str, str]]:
    faces: dict[str, dict[str, str]] = {}
    for fontface in header.findall(f".//{HH}fontface"):
        lang = (fontface.get("lang") or "").lower()
        faces[lang] = {
            str(font.get("id")): str(font.get("face") or "")
            for font in fontface.findall(f"{HH}font")
            if font.get("id") is not None
        }
    return faces


def _char_props(header: ET.Element, faces: dict[str, dict[str, str]]) -> dict[str, dict[str, object]]:
    props: dict[str, dict[str, object]] = {}
    for char_pr in header.findall(f".//{HH}charPr"):
        char_id = char_pr.get("id")
        if char_id is None:
            continue
        font_ref = char_pr.find(f"{HH}fontRef")
        ratio = char_pr.find(f"{HH}ratio")
        spacing = char_pr.find(f"{HH}spacing")
        font_faces = {}
        if font_ref is not None:
            for attr, font_id in font_ref.attrib.items():
                lang = {
                    "hangul": "hangul",
                    "latin": "latin",
                    "hanja": "hanja",
                    "japanese": "japanese",
                    "other": "other",
                    "symbol": "symbol",
                    "user": "user",
                }.get(attr, attr)
                font_faces[attr] = faces.get(lang, {}).get(font_id, f"#{font_id}")
        props[char_id] = {
            "height": char_pr.get("height"),
            "size_pt": int(char_pr.get("height") or 0) / 100,
            "font_faces": font_faces,
            "ratio": dict(ratio.attrib) if ratio is not None else {},
            "spacing": dict(spacing.attrib) if spacing is not None else {},
            "bold": char_pr.find(f"{HH}bold") is not None,
            "italic": char_pr.find(f"{HH}italic") is not None,
        }
    return props


def _para_props(header: ET.Element) -> dict[str, dict[str, str]]:
    props: dict[str, dict[str, str]] = {}
    for para_pr in header.findall(f".//{HH}paraPr"):
        para_id = para_pr.get("id")
        if para_id is None:
            continue
        spacing = para_pr.find(f".//{HH}lineSpacing")
        props[para_id] = dict(spacing.attrib) if spacing is not None else {}
    return props


def _text_of(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{HP}t"))


def _inspect(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        header = ET.fromstring(archive.read("Contents/header.xml"))
        section = ET.fromstring(archive.read("Contents/section0.xml"))
    faces = _font_faces(header)
    chars = _char_props(header, faces)
    paras = _para_props(header)
    runs = []
    for paragraph in section.iter(f"{HP}p"):
        text = _text_of(paragraph)
        for run in paragraph.findall(f"{HP}run"):
            run_text = _text_of(run)
            runs.append(
                {
                    "text": run_text or text,
                    "char_pr": run.get("charPrIDRef"),
                    "para_pr": paragraph.get("paraPrIDRef"),
                }
            )
    equations = list(section.iter(f"{HP}equation"))
    return {"faces": faces, "chars": chars, "paras": paras, "runs": runs, "equations": equations}


def _write_sample(path: Path, *, template_key: str) -> None:
    items = [
        {
            "number": "1",
            "unit": "[2점][typography 01]",
            "stem": "함수 $f(x)=x^2+1$ 에 대하여 다음 값을 구하시오.\nEnglish passage value should keep the body font.",
            "choices": [r"$1$", r"$2$", r"$3$", r"$4$", r"$5$"],
            "tables": [],
            "image_paths": [],
        }
    ]
    hwpx_writer_v2.write_hwpx(
        path,
        "KICE typography QA",
        items,
        template_key=template_key,
        native_math=True,
    )


def _has_face(faces: dict[str, dict[str, str]], face: str) -> bool:
    return any(face in fonts.values() for fonts in faces.values())


def _has_style(
    chars: dict[str, dict[str, object]],
    *,
    face: str,
    size_pt: float,
    ratio: str = "95",
    spacing: str = "-5",
    bold: bool | None = None,
) -> bool:
    for style in chars.values():
        font_faces = style.get("font_faces") or {}
        if face not in set(font_faces.values()):
            continue
        if abs(float(style.get("size_pt") or 0) - size_pt) > 0.01:
            continue
        style_ratio = style.get("ratio") or {}
        style_spacing = style.get("spacing") or {}
        if style_ratio.get("hangul") != ratio or style_ratio.get("latin") != ratio:
            continue
        if style_spacing.get("hangul") != spacing or style_spacing.get("latin") != spacing:
            continue
        if bold is not None and bool(style.get("bold")) != bold:
            continue
        return True
    return False


def _run_uses_face(report: dict[str, object], text_part: str, face: str) -> bool:
    chars = report["chars"]
    for run in report["runs"]:
        if text_part not in str(run.get("text") or ""):
            continue
        char_pr = str(run.get("char_pr") or "")
        style = chars.get(char_pr) if isinstance(chars, dict) else None
        if style and face in set((style.get("font_faces") or {}).values()):
            return True
    return False


def _all_nonempty_runs_use_165_line_spacing(report: dict[str, object]) -> bool:
    paras = report["paras"]
    for run in report["runs"]:
        if not str(run.get("text") or "").strip():
            continue
        para_pr = str(run.get("para_pr") or "")
        spacing = paras.get(para_pr) if isinstance(paras, dict) else None
        if not spacing or spacing.get("type") != "PERCENT" or spacing.get("value") != "165":
            return False
    return True


def main() -> int:
    storage.ensure_dirs()
    out_dir = ROOT / "data" / "kice_typography"
    out_dir.mkdir(parents=True, exist_ok=True)
    math_path = out_dir / "kice_math_typography.hwpx"
    english_path = out_dir / "kice_english_typography.hwpx"
    _write_sample(math_path, template_key="kice_math")
    _write_sample(english_path, template_key="kice_english")

    math_report = _inspect(math_path)
    english_report = _inspect(english_path)
    failures: list[str] = []

    for face in ("신명 중명조", "Times New Roman", "돋움", "HancomEQN"):
        if not _has_face(math_report["faces"], face):
            failures.append(f"kice_math header missing font face: {face}")
    if not _has_style(math_report["chars"], face="신명 중명조", size_pt=11.0):
        failures.append("kice_math missing 11pt 신명 중명조 body charPr with ratio=95 and spacing=-5")
    if not _has_style(math_report["chars"], face="돋움", size_pt=11.0, bold=True):
        failures.append("kice_math missing 11pt bold 돋움 heading charPr")
    if not _all_nonempty_runs_use_165_line_spacing(math_report):
        failures.append("kice_math nonempty paragraphs are not all using 165% line spacing")
    if not all(equation.get("font") == "HancomEQN" for equation in math_report["equations"]):
        failures.append("kice_math native equation objects are not using HancomEQN")

    if not _has_style(english_report["chars"], face="Times New Roman", size_pt=11.0):
        failures.append("kice_english missing 11pt Times New Roman body charPr")
    if not _run_uses_face(english_report, "English passage", "Times New Roman"):
        failures.append("kice_english body run does not use Times New Roman")
    if not _all_nonempty_runs_use_165_line_spacing(english_report):
        failures.append("kice_english nonempty paragraphs are not all using 165% line spacing")

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("PASS KICE typography: fonts, ratio/spacing, 165% line spacing, native equation font")
    print(f"math={math_path}")
    print(f"english={english_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
