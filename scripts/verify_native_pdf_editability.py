"""Native PDF output contract, including forged statistics and tiled crops."""

# ruff: noqa: E402 -- isolate the engine database before importing the app.
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
RUNTIME = tempfile.TemporaryDirectory(
    prefix="native_editability_", ignore_cleanup_errors=True
)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

import fitz
from lxml import etree
from fastapi.testclient import TestClient
from app import main, pdf_layout_writer as w, hwpx_writer_v2
from app.pdf_editability import inspect_pdf_editability
from app.pdf_native_content import source_margin_label_indices, _anchor_question_figures
from hwpx import HwpxDocument

HP = w.HP
HH = "http://www.hancom.co.kr/hwpml/2011/head"


def check(ok, message):
    if not ok:
        raise AssertionError(message)
    print("PASS:", message)


def paragraph_text(paragraph):
    """Do not mistake a wrapper's descendant text for one actual paragraph."""
    return "".join(t.text or "" for t in paragraph.findall(f"./{{{HP}}}run/{{{HP}}}t"))


def rewrite(source, output, modify):
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(output, "w") as result:
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename == "Contents/section0.xml":
                root = etree.fromstring(data)
                modify(root)
                data = etree.tostring(root, encoding="utf-8", xml_declaration=True)
            result.writestr(info, data)


def main_test():
    directory = Path(RUNTIME.name)
    figure = {
        "stem": "",
        "image_paths": ["figure.png"],
        "source_page": 1,
        "layout": {"source_column": 1, "source_bbox_pt": [200, 100, 280, 190]},
    }
    question = {
        "stem": "20. Read the following observation.",
        "source_page": 1,
        "layout": {
            "source_column": 1,
            "source_typography": {"source_bbox_pt": [50, 102, 190, 135]},
        },
    }
    continuation = {
        "stem": "This text continues beside the same figure.",
        "source_page": 1,
        "layout": {
            "source_column": 1,
            "source_typography": {"source_bbox_pt": [50, 145, 190, 180]},
        },
    }
    below = {
        "stem": "Choose the correct statement.",
        "source_page": 1,
        "layout": {
            "source_column": 1,
            "source_typography": {"source_bbox_pt": [50, 210, 280, 230]},
        },
    }
    check(
        _anchor_question_figures([figure, question, continuation, below])
        == [question, continuation, figure, below],
        "a figure beside a question follows that question's opening text in editable reading order",
    )
    unchanged_cases = []
    for key, value in (
        ("above", [200, 30, 280, 90]),
        ("overlapping_text", [50, 100, 180, 190]),
    ):
        changed = deepcopy(figure)
        changed["layout"]["source_bbox_pt"] = value
        unchanged_cases.append((key, [changed, question]))
    other_column = deepcopy(figure)
    other_column["layout"]["source_column"] = 0
    unchanged_cases.append(("other_column", [other_column, question]))
    other_page = deepcopy(figure)
    other_page["source_page"] = 2
    unchanged_cases.append(("other_page", [other_page, question]))
    unchanged_cases.append(("unnumbered_text", [figure, continuation]))
    check(
        all(_anchor_question_figures(items) == items for _, items in unchanged_cases),
        "figure anchoring preserves above-text, overlapping, other-column, other-page and unnumbered cases",
    )
    side_table = {
        "stem": "",
        "tables": [[["Mass", "Value"], ["A", "1"]]],
        "source_page": 1,
        "layout": {
            "source_column": 1,
            "source_typography": {"source_bbox_pt": [200, 100, 280, 165]},
        },
    }
    table_question = {
        "stem": "3. Read the table beside the question. The final line extends below it.",
        "source_page": 1,
        "layout": {
            "source_column": 1,
            "source_typography": {
                "source_bbox_pt": [50, 102, 280, 190],
                "lines": [
                    {"bbox_pt": [50, 102, 190, 125]},
                    {"bbox_pt": [50, 140, 190, 155]},
                    {"bbox_pt": [50, 175, 280, 190]},
                ],
            },
        },
    }
    check(
        _anchor_question_figures([side_table, table_question])
        == [table_question, side_table],
        "a side table belongs after its question even when a later prose line spans beneath it",
    )
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((150, 50), "지구과학 영역", fontname="korea", fontsize=12)
        page.draw_line(fitz.Point(40, 80), fitz.Point(555, 80))
        for x, text, top in (
            (12, "지구과학", 140),
            (100, "지구과학", 240),
            (12, "광물학", 340),
            (12, "지구", 440),
        ):
            for index, char in enumerate(text):
                page.insert_text(
                    (x, top + index * 16), char, fontname="korea", fontsize=10
                )
        lines = w._iter_text_lines(page)
        excluded = source_margin_label_indices(page, lines)
        excluded_text = "".join(
            w._line_text(lines[index]) for index in sorted(excluded)
        )
        check(
            excluded_text == "지구과학" and len(excluded) == 4,
            "only a duplicated header in the outer margin is classified as a running label",
        )
        check(
            not any(
                index in excluded
                for index, line in enumerate(lines)
                if w._item_bbox(line).x0 > 90 or w._item_bbox(line).y0 > 300
            ),
            "interior vertical text, unrelated margin text and two-glyph labels are preserved",
        )
    source = directory / "science.pdf"
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((45, 60), "Science examination", fontsize=15)
        page.insert_text(
            (45, 145), "1. Read the following scientific observation.", fontsize=9
        )
        page.insert_text(
            (45, 166), "Water changes its temperature when energy", fontsize=9
        )
        page.insert_text(
            (45, 179), "is transferred between the two objects.", fontsize=9
        )
        page.draw_rect(fitz.Rect(45, 205, 270, 266))
        page.insert_text(
            (55, 224), "The boxed explanation must remain editable.", fontsize=9
        )
        page.insert_text(
            (55, 241), "It must never disappear behind an image when", fontsize=9
        )
        page.insert_text((55, 254), "the surrounding text is edited.", fontsize=9)
        page.insert_text(
            (320, 145), "2. Compare the temperature measurements.", fontsize=9
        )
        page.draw_rect(fitz.Rect(45, 350, 270, 420))
        page.insert_text((55, 374), "A=", fontsize=10)
        page.insert_text((80, 365), "1", fontsize=10)
        page.insert_text((80, 380), "2", fontsize=10)
        page.draw_line(fitz.Point(78, 369), fitz.Point(91, 369))
        page.insert_text((55, 404), "is the measured ratio.", fontsize=10)
        # A genuine source figure has a known bounded image region.
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 50), False)
        pix.clear_with(170)
        page.insert_image(fitz.Rect(330, 185, 390, 235), pixmap=pix)
        pix.clear_with(80)
        page.insert_image(fitz.Rect(405, 185, 465, 235), pixmap=pix)
        pix.clear_with(220)
        page.insert_image(fitz.Rect(330, 255, 390, 305), pixmap=pix)
        page.insert_text(
            (320, 328), "Use the lower diagram to complete question two.", fontsize=9
        )
        document.save(source)
    output = directory / "native.hwpx"
    stats = w.write_pdf_structured_hwpx(source, output, high_fidelity_math=True)
    audit = inspect_pdf_editability(source, output, stats["image_provenance"])
    check(audit["ok"], f"native package is editable: {audit}")
    check(
        audit["images"] == stats["images"] == len(stats["image_provenance"]) == 3,
        "both paired source figures and the separate single figure survive as actual pictures",
    )
    check(stats["template_key"] == "kice_science", "science has a science template")
    check(
        audit["source_fractions"] == 1 and not audit["missing_native_fractions"],
        "a source stacked fraction becomes the correct native fraction",
    )
    check(
        stats["layout_mode"] == "structured" and stats["draw_text_boxes"] == 2,
        "legacy high-fidelity flag creates only two complete question containers",
    )
    plain = w._structured_hwpx_plain_text(output)
    check(
        "Theboxedexplanationmustremaineditable." in plain,
        "boxed source prose survives recognition exclusions",
    )
    with zipfile.ZipFile(output) as package:
        xml = package.read("Contents/section0.xml")
        root = etree.fromstring(xml)
        question_boxes = root.findall(f".//{{{HP}}}drawText")
        check(
            len(question_boxes) == 2
            and {box.get("name") for box in question_boxes}
            == {"question:v1:q01", "question:v1:q02"},
            "only complete named question text boxes are emitted, with no boxes per line",
        )
        check(
            any(
                len(p.findall(f"./{{{HP}}}run/{{{HP}}}pic")) == 2
                for p in root.findall(f".//{{{HP}}}p")
            ),
            "adjacent source figures share one native flow paragraph as two genuine pictures",
        )
        header = etree.fromstring(package.read("Contents/header.xml"))
        source_paragraph = next(
            p
            for p in root.findall(f".//{{{HP}}}p")
            if "Read the following scientific observation." in paragraph_text(p)
        )
        source_run = next(
            run
            for run in source_paragraph.findall(f"{{{HP}}}run")
            if "Read the following" in "".join(run.itertext())
        )
        char_style = header.find(
            f".//{{{HH}}}charPr[@id='{source_run.get('charPrIDRef')}']"
        )
        check(
            abs(int(char_style.get("height")) - 900) <= 5,
            "native body typography uses the measured 9-point source size, not a fixed template size",
        )
        latin_font_id = char_style.find(f"{{{HH}}}fontRef").get("latin")
        latin_font = header.find(
            f".//{{{HH}}}fontface[@lang='LATIN']/{{{HH}}}font[@id='{latin_font_id}']"
        )
        check(
            latin_font is not None and latin_font.get("face") == "Helvetica",
            "native body text references the source Helvetica face in the header",
        )
        flowing_paragraph = next(
            p
            for p in root.findall(f".//{{{HP}}}p")
            if "Waterchangesitstemperaturewhenenergyistransferred"
            in paragraph_text(p).replace(" ", "")
        )
        source_lines = flowing_paragraph.findall(
            f"{{{HP}}}linesegarray/{{{HP}}}lineseg"
        )
        check(
            len(source_lines) >= 2
            and abs(
                int(source_lines[0].get("vertsize"))
                + int(source_lines[0].get("spacing"))
                - 1300
            )
            <= 5,
            "wrapped native prose retains the measured 13-point source baseline spacing",
        )
        check(
            not any(
                marker in xml
                for marker in (
                    b"nativeParagraphGroup",
                    b"nativeParagraphWidth",
                    b"nativeSourceItem",
                )
            ),
            "temporary paragraph grouping and source metadata is removed",
        )
        check(
            any(
                "Waterchangesitstemperaturewhenenergyistransferred"
                in paragraph_text(p).replace(" ", "")
                for p in root.findall(f".//{{{HP}}}p")
            ),
            "wrapped prose remains a single editable paragraph",
        )
        check(
            any(
                "Itmustneverdisappearbehindanimagewhenthesurroundingtextisedited."
                in paragraph_text(p).replace(" ", "")
                for p in root.findall(f".//{{{HP}}}tc/{{{HP}}}subList/{{{HP}}}p")
            ),
            "a source box wraps within one editable paragraph, not one paragraph per line",
        )
        check(
            any(
                "is the measured ratio." in paragraph_text(p)
                and p.find(f"./{{{HP}}}run/{{{HP}}}equation") is not None
                for p in root.findall(f".//{{{HP}}}tc/{{{HP}}}subList/{{{HP}}}p")
            ),
            "a tall source fraction and its next-line sentence ending share one paragraph",
        )
    stripped = directory / "without_images.hwpx"

    def remove_images(root):
        for picture in root.findall(f".//{{{HP}}}pic"):
            picture.getparent().remove(picture)

    rewrite(output, stripped, remove_images)
    check(
        w._structured_hwpx_plain_text(stripped) == plain,
        "deleting every picture preserves the complete native text",
    )
    check(
        "source_figure_missing_from_output"
        in inspect_pdf_editability(source, stripped, stats["image_provenance"])[
            "issues"
        ],
        "preserved native text cannot conceal a missing declared source figure",
    )
    wrong_fraction = directory / "wrong_fraction.hwpx"

    def corrupt_fraction(root):
        for script in root.findall(f".//{{{HP}}}equation/{{{HP}}}script"):
            if "over" in (script.text or ""):
                script.text = (script.text or "").replace("2", "3")

    rewrite(output, wrong_fraction, corrupt_fraction)
    check(
        "native_source_fraction_missing"
        in inspect_pdf_editability(source, wrong_fraction, stats["image_provenance"])[
            "issues"
        ],
        "the same equation count cannot conceal a changed denominator",
    )

    # Provenance alone cannot bless two narrow screenshots of the source prose.
    tiled = directory / "tiled.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("Editable text beneath a forged visual layer")
    provenance = []
    with fitz.open(source) as pdf:
        for region in (fitz.Rect(40, 150, 150, 185), fitz.Rect(150, 150, 280, 185)):
            data = pdf[0].get_pixmap(clip=region).tobytes("png")
            identifier = doc.add_image(data, "png")
            doc.add_paragraph("").add_picture(identifier, width=11000, height=3500)
            provenance.append(
                {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "role": "source_figure",
                    "page": 1,
                    "bbox_px": [region.x0, region.y0, region.width, region.height],
                    "page_width_px": 595,
                    "page_height_px": 842,
                }
            )
    w._prepare_hancom_compatibility(doc)
    w._save_hancom_compatible_document(doc, tiled)
    result = inspect_pdf_editability(source, tiled, provenance)
    check(
        "source_prose_in_picture_union" in result["issues"],
        "multiple small crops cannot rasterize prose as a group",
    )
    check(
        "unproven_or_duplicate_picture"
        in inspect_pdf_editability(source, tiled, [])["issues"],
        "untraceable picture assets are rejected",
    )

    word_fraction = directory / "word_fraction.hwpx"
    long_cell_paragraph = (
        "첫째 항목은 긴 문장을 편집하는 동안 자동 줄바꿈이 여러 번 발생하더라도 "
        "문단 경계를 새로 만들지 않고 같은 문단 안에서 이어져야 한다. "
        "또한 글자를 추가하거나 지울 때 다음 줄과 자연스럽게 연결되어야 한다."
    )
    second_cell_paragraph = "둘째 항목은 별도의 문단 경계를 유지한다."
    hwpx_writer_v2.write_hwpx(
        word_fraction,
        "한글 분수",
        [
            {
                "stem": r"현재 $\frac{A에 포함된 X의 함량}{B에 포함된 Y의 함량}$ 은 8이다.",
                "tables": [[[long_cell_paragraph + "\n" + second_cell_paragraph]]],
                "layout": {"source_content": True},
            }
        ],
        "kice_science",
        native_math=True,
        preserve_source_layout=True,
    )
    with zipfile.ZipFile(word_fraction) as package:
        xml = package.read("Contents/section0.xml")
        root = etree.fromstring(xml)
        check(
            not any(
                marker in xml
                for marker in (
                    b"nativeParagraphGroup",
                    b"nativeParagraphWidth",
                    b"nativeSourceItem",
                )
            ),
            "direct native writer removes temporary grouping and source metadata",
        )
        table = root.find(f".//{{{HP}}}tbl[@rowCnt='2'][@colCnt='1']")
        check(
            table is not None and not root.findall(f".//{{{HP}}}pic"),
            "Hangul word fractions use editable text cells instead of raster or broken equation glyphs",
        )
        paragraph = table.getparent().getparent()
        line = paragraph.find(f"{{{HP}}}linesegarray/{{{HP}}}lineseg")
        check(
            int(line.get("vertsize")) >= int(table.find(f"{{{HP}}}sz").get("height")),
            "word fraction line reserves the full native table height",
        )
        check(
            "A에 포함된 X의 함량" in "".join(root.itertext())
            and "B에 포함된 Y의 함량" in "".join(root.itertext()),
            "both word-fraction operands remain real text",
        )
        prose_table = root.find(f".//{{{HP}}}tbl[@rowCnt='1'][@colCnt='1']")
        cell_paragraphs = prose_table.findall(
            f".//{{{HP}}}tc/{{{HP}}}subList/{{{HP}}}p"
        )
        check(
            len(cell_paragraphs) == 2
            and "".join(cell_paragraphs[0].itertext()).replace(" ", "")
            == long_cell_paragraph.replace(" ", "")
            and "".join(cell_paragraphs[1].itertext()).replace(" ", "")
            == second_cell_paragraph.replace(" ", ""),
            "cell wrapping preserves two semantic paragraphs instead of splitting every line",
        )
        check(
            len(cell_paragraphs[0].findall(f"{{{HP}}}linesegarray/{{{HP}}}lineseg"))
            > 1,
            "a long editable cell paragraph retains multiple visual cache lines",
        )

    forged = directory / "forged.hwpx"

    def add_box(root):
        paragraph = root.find(f"{{{HP}}}p")
        run = etree.SubElement(paragraph, f"{{{HP}}}run", charPrIDRef="0")
        etree.SubElement(run, f"{{{HP}}}drawText")

    rewrite(output, forged, add_box)

    def bad_writer(_source, target, **_kwargs):
        Path(target).write_bytes(forged.read_bytes())
        return {
            **stats,
            "draw_text_boxes": 0,
            "images": 0,
            "editable_text_coverage_ratio": 1.0,
        }

    body = {
        "filename": source.name,
        "data_base64": base64.b64encode(source.read_bytes()).decode(),
        "math_ai_recognition": False,
    }
    with (
        TestClient(main.app) as client,
        patch.object(w, "write_pdf_structured_hwpx", bad_writer),
    ):
        for mode in ("structured", "coordinate"):
            response = client.post(
                "/api/pdf-layout-export", json={**body, "layout_mode": mode}
            )
            check(
                response.status_code == 422,
                f"{mode} API rejects an extra unidentified text box despite forged perfect stats",
            )
    check(
        not list((directory / "exports").rglob("*.hwpx")),
        "rejected API output is cleaned up",
    )


if __name__ == "__main__":
    main_test()
