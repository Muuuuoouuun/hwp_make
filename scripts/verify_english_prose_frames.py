"""Independent source paragraph rails and complete English letter frames."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
from statistics import median
import sys
import tempfile
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="english_prose_frames_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

import fitz
from lxml import etree
import rhwp
from app.pdf_layout_writer import _pdf_output_text, write_pdf_structured_hwpx
from app.pdf_question_rendering import IDENTITY, _bitmap_identity, _bounds, _multiply, _transform
from app.pdf_source_backgrounds import native_background_assets
from scripts.verify_english_layout import verify_cell_glyph_bounds

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
SVG = "{http://www.w3.org/2000/svg}"


def compact(text):
    return re.sub(r"\s+", "", _pdf_output_text(text))


def source_lines(page, bounds):
    rows = {}
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            if bounds.contains(fitz.Rect(line["bbox"])):
                baseline = round(median(span["origin"][1] for span in line["spans"]), 1)
                rows.setdefault(baseline, []).extend(
                    {**span, "text": "".join(char["c"] for char in span["chars"])} for span in line["spans"])
    result = []
    for _, spans in sorted(rows.items()):
        spans.sort(key=lambda span: span["bbox"][0])
        box = fitz.Rect(spans[0]["bbox"])
        for span in spans[1:]:
            box |= fitz.Rect(span["bbox"])
        ink_right = max(char["bbox"][2] for span in spans for char in span["chars"] if char["c"].strip())
        result.append({"spans": spans, "bbox": list(box), "ink_right": ink_right})
    return result


def line_text(line):
    return "".join(span["text"] for span in line["spans"])


def paragraph_text(paragraph):
    return "".join(t.text or "" for run in paragraph.findall(HP + "run") for t in run.findall(HP + "t"))


def package(path):
    with zipfile.ZipFile(path) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if re.fullmatch(r"Contents/section\d+\.xml", name)]
    return roots, header


def verify_painted_wraps(parsed, page_index, lines, source_width):
    root = etree.fromstring(parsed.render_svg(page_index).encode())
    scale = float(root.get("width")) / source_width
    values, positions = [], []
    for node in root.iter(SVG + "text"):
        value = compact("".join(node.itertext()))
        matrix = IDENTITY
        for ancestor in [*reversed(list(node.iterancestors())), node]:
            matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
        point = _bounds(matrix, float(node.get("x", 0)), float(node.get("y", 0)), 0, 0)[:2]
        values.extend(value)
        positions.extend([point] * len(value))
    rendered = "".join(values)
    expected = "".join(compact(line_text(line)) for line in lines)
    assert rendered.count(expected) == 1, "complete source prose was not painted once"
    cursor = rendered.index(expected)
    actual = []
    for line in lines:
        value = compact(line_text(line))
        assert rendered[cursor:cursor + len(value)] == value
        actual.append(positions[cursor])
        cursor += len(value)
    baselines = [median(span["origin"][1] for span in line["spans"] if span["text"].strip()) for line in lines]
    errors = [abs((point[1] - actual[0][1]) - (baseline - baselines[0]) * scale)
              for point, baseline in zip(actual, baselines)]
    assert max(errors) < .4, ("source wraps collapsed or moved between baselines", max(errors))
    left_errors = [abs(point[0] - line["bbox"][0] * scale) for point, line in zip(actual, lines)]
    assert max(left_errors) < 1.5, ("source paragraph rail moved", max(left_errors))
    return {"lines": len(lines), "baseline_delta_error_px": round(max(errors), 4),
            "left_error_px": round(max(left_errors), 4)}


def verify_letter_glyph_bounds(parsed, lines, source_width, bounds, cell, page_width):
    # Bitmap-backed cells have no SVG cell-clip wrapper. Assess their actual
    # emitted PDF font glyphs against the native printable cell width instead.
    with fitz.open(stream=bytes(parsed.render_pdf()), filetype="pdf") as document:
        page = document[1]
        characters = [char for trace in page.get_texttrace() for char in trace["chars"]
                      if not chr(char[0]).isspace()]
        painted = "".join(chr(char[0]) for char in characters)
        expected = compact("".join(map(line_text, lines)))
        assert painted.count(expected) == 1, "complete letter glyph inventory was not painted once"
        first = painted.index(expected)
        margins = cell.find(HP + "cellMargin")
        left = bounds.x0 * page.rect.width / source_width + float(margins.get("left")) / page_width * page.rect.width
        right = bounds.x1 * page.rect.width / source_width - float(margins.get("right")) / page_width * page.rect.width
        tolerance = .3 * page.rect.width / 794
        glyphs = characters[first:first + len(expected)]
        failures = [(chr(char[0]), char[3]) for char in glyphs
                    if char[3][0] < left - tolerance or char[3][2] > right + tolerance]
        assert not failures, ("letter glyph exceeds native printable cell width", failures[:10], left, right)
        return len(glyphs)


def verify_high1(source, output):
    roots, header = package(output)
    parsed = rhwp.parse(str(output))
    assert parsed.page_count == 8
    assert len(roots) == 2
    cells = [cell.get("name", "") for cell in roots[1].iter(HP + "tc")]
    assert any(name in {"source-page-masthead:area", "source-running:subject"} for name in cells)
    # Original four source edges of the [41~42] frame in the named real PDF.
    bounds = fitz.Rect(87.624, 193.116, 411.030, 627.086)
    with fitz.open(source) as document:
        lines = source_lines(document[7], bounds)
        body = lines[:next(index for index, line in enumerate(lines) if line_text(line).lstrip().startswith("*"))]
        assert len(body) == 25 and max(line["bbox"][2] for line in body[:-1]) - min(line["bbox"][2] for line in body[:-1]) < .2
        expected = compact("".join(map(line_text, body)))
        paragraphs = [p for root in roots for p in root.iter(HP + "p") if compact(paragraph_text(p)) == expected]
        assert len(paragraphs) == 1, "the complete source body must remain one editable paragraph"
        paragraph = paragraphs[0]
        styles = {node.get("id"): node for node in header.iter(HH + "paraPr")}
        style = styles[paragraph.get("paraPrIDRef")]
        assert style.find(HH + "align").get("horizontal") == "JUSTIFY", "glossary changed the source body's alignment"
        assert len(paragraph.findall(HP + "linesegarray/" + HP + "lineseg")) == len(body)
        cell = paragraph.getparent().getparent()
        table = cell.getparent().getparent()
        page_width = float(next(root.find(".//" + HP + "pagePr") for root in roots if root.find(".//" + HP + "pagePr") is not None).get("width"))
        scale = page_width / document[7].rect.width
        right = float(cell.find(HP + "cellMargin").get("right")) + float(style.find(".//" + HC + "right").get("value"))
        target = (bounds.x1 - max(line["ink_right"] for line in body[:-1])) * scale
        assert abs(right - target) < 2, ("glossary right edge replaced the body's own rail", right, target)
        assert table.find(HP + "sz") is not None and not paragraph.findall(".//" + HP + "lineBreak")
        wraps = verify_painted_wraps(parsed, 7, body, document[7].rect.width)
    wraps["cell_glyphs"] = verify_cell_glyph_bounds(parsed, 7)
    return wraps


def verify_letter(source, output):
    roots, header = package(output)
    parsed = rhwp.parse(str(output))
    assert parsed.page_count == 16
    assert len(roots) == 4
    assert all(any(cell.get("name") == "source-page-masthead:area" for cell in root.iter(HP + "tc"))
               for root in roots), "source-proven section header was overwritten"
    draw = next(draw for root in roots for draw in root.iter(HP + "drawText") if draw.get("name") == "question:v1:q18")
    table = draw.find(".//" + HP + "tbl")
    paragraphs = table.findall(HP + "tr/" + HP + "tc/" + HP + "subList/" + HP + "p")
    assert len(paragraphs) == 3, "letter salutation/body/signature block were merged"
    bounds = fitz.Rect(447.84, 178.621, 753.96, 414.241)
    with fitz.open(source) as document:
        lines = source_lines(document[1], bounds)
        assert len(lines) == 15 and line_text(lines[0]).strip() == "Dear students,"
        assert [line_text(line).strip() for line in lines[-2:]] == ["Best regards,", "Amanda Clark"]
        assert compact("".join(map(paragraph_text, paragraphs))) == compact("".join(map(line_text, lines)))
        assert [len(p.findall(HP + "linesegarray/" + HP + "lineseg")) for p in paragraphs] == [1, 12, 2]
        wraps = verify_painted_wraps(parsed, 1, lines, document[1].rect.width)
        with zipfile.ZipFile(output) as archive:
            manifest = etree.fromstring(archive.read("Contents/content.hpf"))
            hrefs = {node.get("id"): node.get("href") for node in manifest.iter("{http://www.idpf.org/2007/opf/}item")}
            assets = native_background_assets(table, header, hrefs, archive)
        assert len(assets) == 1
        identity = _bitmap_identity(assets[0][1])
        svg = etree.fromstring(parsed.render_svg(1).encode())
        pictures = []
        for node in svg.iter(SVG + "image"):
            href = node.get("{http://www.w3.org/1999/xlink}href") or node.get("href", "")
            if not href.startswith("data:") or any(a.tag == SVG + "defs" for a in node.iterancestors()):
                continue
            if _bitmap_identity(base64.b64decode(href.split(",", 1)[1])) != identity:
                continue
            matrix = IDENTITY
            for ancestor in [*reversed(list(node.iterancestors())), node]:
                matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
            pictures.append(_bounds(matrix, *[float(node.get(key, 0)) for key in ("x", "y", "width", "height")]))
        assert len(pictures) == 1
        scale = float(svg.get("width")) / document[1].rect.width
        expected = [value * scale for value in bounds]
        error = max(abs(a - b) for a, b in zip(pictures[0], expected))
        assert error < .2, ("complete original letter frame shrank", error, pictures[0], expected)
        wraps["frame_error_px"] = round(error, 4)
        page_width = float(next(root.find(".//" + HP + "pagePr") for root in roots
                                if root.find(".//" + HP + "pagePr") is not None).get("width"))
        wraps["cell_glyphs"] = verify_letter_glyph_bounds(
            parsed, lines, document[1].rect.width, bounds, table.find(HP + "tr/" + HP + "tc"), page_width)
    return wraps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--high1-hwpx", type=Path)
    parser.add_argument("--csat-hwpx", type=Path)
    args = parser.parse_args()
    high1 = ROOT / "data/external_exam_qa/2026_june_high1/english.pdf"
    csat = ROOT / "data/external_exam_qa/2026_csat/문제지/영어/영어.pdf"
    if not high1.is_file() or not csat.is_file():
        print("SKIP: ENGLISH_PROSE_FRAMES requires both real source PDFs")
        return 2
    folder = Path(RUNTIME.name)
    first, second = args.high1_hwpx, args.csat_hwpx
    if first is None:
        first = folder / "high1.hwpx"
        from app.pdf_running_headings import apply_running_heading
        with patch("app.pdf_running_headings.apply_running_heading", wraps=apply_running_heading) as fallback:
            result = write_pdf_structured_hwpx(high1, first, native_math=True)
        assert fallback.call_count == 1 and result["running_heading"]["applied"], "incomplete source headers lost their legacy fallback"
    if second is None:
        second = folder / "csat.hwpx"
        with patch("app.pdf_running_headings.apply_running_heading", side_effect=AssertionError("measured header reached legacy heading")):
            result = write_pdf_structured_hwpx(csat, second, native_math=True, variant_policy="all")
        assert result["running_heading"]["measured_masthead_sections"] == 4
    print("ENGLISH_PROSE_FRAMES_OK: " + json.dumps({"high1": verify_high1(high1, first), "csat": verify_letter(csat, second)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
