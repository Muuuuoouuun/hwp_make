"""Actual PDF/native regression for question and shared-passage ownership."""

# ruff: noqa: E402
from pathlib import Path
import sys
import tempfile
import zipfile
from types import SimpleNamespace

import fitz
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import pdf_layout_writer as w
from app.hwpx_writer_v2 import write_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_question_inspection import (
    inspect_question_units,
    _source_regions_from_markers,
    _question_starts,
)

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def run(folder):
    # A stem beside a figure is still the question's first paragraph; numbered
    # survey rows later in a native table must not become exam question starts.
    sub = etree.fromstring(f'''<hp:subList xmlns:hp="{HP[1:-1]}">
      <hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>
       <hp:p><hp:run><hp:t>7. Compare the picture.</hp:t></hp:run></hp:p>
      </hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>
      <hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>
       <hp:p><hp:run><hp:t>1. Survey response.</hp:t></hp:run></hp:p>
      </hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>
    </hp:subList>''')
    assert _question_starts(sub) == ([7], "7. Compare the picture.")
    extra = etree.SubElement(sub, HP + "p")
    etree.SubElement(etree.SubElement(extra, HP + "run"), HP + "t").text = "8. Another question."
    assert _question_starts(sub)[0] == [7, 8]
    source, native = folder / "passage.pdf", folder / "passage.hwpx"
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        for x, y, text in [
            (40, 40, "Reading Test"),
            (40, 90, "1. Choose the first answer."),
            (40, 120, "The first condition remains editable."),
            (40, 180, "[2~3] Read the common passage."),
            (40, 210, "The common river flows north."),
            (40, 280, "2. Which direction does it flow?"),
            (40, 310, "Choose north or south."),
            (310, 90, "3. Compare the two answers."),
        ]:
            page.insert_text((x, y), text, fontsize=10)
        document.save(source)
    items, provenance = extract_native_content(source)
    write_hwpx(
        native,
        "Reading Test",
        items,
        "kice_science",
        native_math=True,
        preserve_source_layout=True,
    )
    report = inspect_question_units(source, native, provenance=provenance)
    assert report["ok"], report
    assert report["source_shared_regions_checked"] == 1, report
    with zipfile.ZipFile(native) as archive:
        root = etree.fromstring(archive.read("Contents/section0.xml"))
        passage = next(
            node
            for node in root.iter(HP + "t")
            if node.text and "common river" in node.text
        )
        assert not any(
            parent.tag == HP + "drawText" for parent in passage.iterancestors()
        )
        passage.text = ""
        changed = folder / "missing_shared.hwpx"
        with zipfile.ZipFile(changed, "w") as output:
            for info in archive.infolist():
                output.writestr(
                    info,
                    etree.tostring(root)
                    if info.filename == "Contents/section0.xml"
                    else archive.read(info.filename),
                )
    failure = inspect_question_units(source, changed, provenance=provenance)
    assert (
        "source_shared_passage_not_preserved_outside_questions" in failure["issues"]
    ), failure
    with zipfile.ZipFile(native) as archive:
        root = etree.fromstring(archive.read("Contents/section0.xml"))
        draw = next(root.iter(HP + "drawText"))
        draw.getparent().find(HP + "sz").set("height", "1")
        draw.find(HP + "subList").set("textHeight", "1")
        collapsed = folder / "collapsed_question.hwpx"
        with zipfile.ZipFile(collapsed, "w") as output:
            for info in archive.infolist():
                output.writestr(
                    info,
                    etree.tostring(root)
                    if info.filename == "Contents/section0.xml"
                    else archive.read(info.filename),
                )
    failure = inspect_question_units(source, collapsed, provenance=provenance)
    assert "question_container_smaller_than_native_content" in failure["issues"], (
        failure
    )
    assert failure["wrong_question_geometry"][0]["shape_height"] == 1

    # A text-only recognizer may stop before a table or picture. The next raw
    # marker, rather than that clipped bottom, determines the actual ownership.
    with fitz.open(source) as document:
        raw = {1: w._iter_text_lines(document[0])}
        problem = SimpleNamespace(
            number=1,
            page_number=1,
            page_width_px=595,
            page_height_px=842,
            box=SimpleNamespace(left=0, top=75, width=297.5, height=25),
        )
        second = SimpleNamespace(
            number=2,
            page_number=1,
            page_width_px=595,
            page_height_px=842,
            box=SimpleNamespace(left=0, top=265, width=297.5, height=25),
        )
        regions = _source_regions_from_markers(
            document, raw, [("q1", problem), ("q2", second)]
        )
        assert regions["q1"][1].y1 > 250
        assert regions["q2"][1].y1 == 842
        # Fraction ink on the first baseline rises above the marker. An
        # unrelated equation above it must remain outside this question.
        raw[1].extend([
            {"bbox": (140, 65, 170, 96), "spans": [{"bbox": (140, 65, 170, 96),
              "text": "x", "font": "HyhwpEQ", "size": 10}]},
            {"bbox": (140, 45, 170, 55), "spans": [{"bbox": (140, 45, 170, 55),
              "text": "y", "font": "HyhwpEQ", "size": 10}]},
        ])
        regions = _source_regions_from_markers(document, raw, [("q1", problem), ("q2", second)])
        assert regions["q1"][1].y0 == 65, regions
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((40, 160), "1. Left question.")
        page.insert_text((315, 160), "2. Right question.")
        for row in range(5):
            page.insert_text(
                (40, 190 + row * 20),
                "This substantial left column passage.",
                fontsize=10,
            )
            page.insert_text(
                (315, 190 + row * 20),
                "This substantial right column passage.",
                fontsize=10,
            )
        raw = {1: w._iter_text_lines(page)}
        questions = [
            (
                f"q{number}",
                SimpleNamespace(
                    number=number,
                    page_number=1,
                    page_width_px=595,
                    page_height_px=842,
                    box=SimpleNamespace(left=0, top=148, width=595, height=400),
                ),
            )
            for number in (1, 2)
        ]
        regions = _source_regions_from_markers(document, raw, questions)
        assert regions["q1"][1].x1 == 297.5
        assert regions["q2"][1].x0 == 297.5
    print(
        "QUESTION_SOURCE_BOUNDARIES_OK: real shared passage preserved outside; missing shared text rejected; clipped recognizer box expanded from raw markers"
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="question_boundaries_") as temporary:
        run(Path(temporary))
