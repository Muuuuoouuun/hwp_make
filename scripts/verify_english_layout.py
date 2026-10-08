"""Real English charts/notices, source ownership and booklet pagination."""
# ruff: noqa: E402
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="english_layout_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name

import fitz
from lxml import etree
import rhwp
from app.pdf_editability import inspect_pdf_editability
from app.pdf_figure_labels import include_statistical_chart_labels, statistical_chart_regions
from app.pdf_layout_writer import _iter_text_lines, _item_bbox, _line_text, write_pdf_structured_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_question_rendering import IDENTITY, _bounds, _multiply, _transform, inspect_question_rendering
from app.pdf_source_image_validation import render_source_crop

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SVG = "{http://www.w3.org/2000/svg}"


def verify_choice_rails(parsed, source):
    """A later frame's inset style must not move earlier first choices."""
    root = etree.fromstring(parsed.render_svg(5).encode())
    width = float(root.get("viewBox").split()[2])
    values, starts = [], []
    for node in root.iter(SVG + "text"):
        value = re.sub(r"\s+", "", "".join(node.itertext()))
        matrix = IDENTITY
        for ancestor in [*reversed(list(node.iterancestors())), node]:
            matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
        bounds = _bounds(matrix, float(node.get("x", 0)), float(node.get("y", 0)), 0, 0)
        values.extend(value)
        starts.extend([bounds[0]] * len(value))
    rendered = "".join(values)
    prefixes = ("33. Talking about what something smells like is the most",
                "34. A particularly powerful way in which human beings adapt",
                "① we manage to identify their exact sources",
                "① changing behaviors in light of the consequences")
    with fitz.open(source) as document:
        lines = _iter_text_lines(document[5])
        for prefix in prefixes:
            target = re.sub(r"\s+", "", prefix)
            # Q34's justified first line is emitted as one PDF fragment per
            # word. Its independent question marker still gives the rail.
            source_prefix = "34." if prefix.startswith("34.") else target
            originals = [line for line in lines
                         if re.sub(r"\s+", "", _line_text(line)).startswith(source_prefix)]
            assert len(originals) == 1 and rendered.count(target) == 1, prefix
            expected = _item_bbox(originals[0]).x0 / document[5].rect.width * width
            actual = starts[rendered.index(target)]
            assert abs(actual - expected) < 2, ("question/choice source rail moved", prefix, expected, actual)
    return len(prefixes)


def verify_cell_glyph_bounds(parsed, page):
    """Compare actual SVG glyph advances with the independently emitted clip.

    XML text inventory and SVG presence alone both accept a glyph painted past
    its cell's clipping edge. A per-glyph advance check catches that loss.
    """
    root = etree.fromstring(parsed.render_svg(page).encode())
    clips = {clip.get("id"): clip.find(SVG + "rect") for clip in root.iter(SVG + "clipPath")
             if clip.find(SVG + "rect") is not None}
    pdf_glyphs = None

    def natural_glyph_bounds(value, origin):
        nonlocal pdf_glyphs
        # The renderer leaves natural punctuation/CJK advances out of SVG
        # textLength. Its PDF export contains the actual font glyph metrics;
        # match the same painted character and baseline without guessing an em.
        if pdf_glyphs is None:
            pdf_glyphs = {}
            with fitz.open(stream=bytes(parsed.render_pdf()), filetype="pdf") as document:
                rendered = document[page]
                factor = float(root.get("viewBox").split()[2]) / rendered.rect.width
                for trace in rendered.get_texttrace():
                    for char in trace["chars"]:
                        x, y = (part * factor for part in char[2])
                        pdf_glyphs.setdefault((chr(char[0]), round(x), round(y)), []).append(
                            ((x, y), tuple(part * factor for part in char[3])))
        assert len(value) == 1, ("unassessed natural SVG text run", value)
        x, y = origin
        candidates = [record for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                      for record in pdf_glyphs.get((value, round(x) + dx, round(y) + dy), [])]
        assert candidates, ("missing painted font glyph", value, origin)
        position, bounds = min(candidates, key=lambda record:
                               abs(record[0][0] - x) + abs(record[0][1] - y))
        assert max(abs(a - b) for a, b in zip(position, origin)) < .1, (value, position, origin)
        return bounds

    checked, failures = 0, []
    for node in root.iter(SVG + "text"):
        value = "".join(node.itertext()).strip()
        if not value:
            continue
        ancestors = list(node.iterancestors())
        owners = [match[1] for ancestor in ancestors
                  if (match := re.fullmatch(r"url\(#(cell-clip-[^)]*)\)", ancestor.get("clip-path", "")))]
        if not owners:
            continue
        matrix = IDENTITY
        for ancestor in [*reversed(ancestors), node]:
            matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
        glyph = _bounds(matrix, float(node.get("x", 0)), float(node.get("y", 0)),
                        float(node.get("textLength", 0)), 0)
        if node.get("textLength") is None:
            glyph = natural_glyph_bounds(value, glyph[:2])
        for owner in owners:
            clip = clips[owner]
            left = float(clip.get("x", 0))
            right = left + float(clip.get("width"))
            checked += 1
            if glyph[0] < left - .3 or glyph[2] > right + .3:
                failures.append({"text": value, "glyph_left": glyph[0], "glyph_right": glyph[2],
                                 "cell_left": left, "cell_right": right})
    assert checked > 100, "last-page native text geometry was not assessed"
    assert not failures, ("native text clipped by a cell", failures[:10])
    return checked


def package_roots(path):
    with zipfile.ZipFile(path) as package:
        header = etree.fromstring(package.read("Contents/header.xml"))
        for kind in ("paraProperties", "charProperties"):
            identifiers = [node.get("id") for node in header.find(".//" + HH + kind)]
            assert len(identifiers) == len(set(identifiers)), ("duplicate native style IDs", kind)
        roots = [etree.fromstring(package.read(name)) for name in package.namelist()
                 if re.fullmatch(r"Contents/section\d+\.xml", name)]
        assets = [hashlib.sha256(package.read(name)).hexdigest()
                  for name in package.namelist() if name.startswith("BinData/")]
    return roots, assets


def verify_repeated_background_frames(output, source, provenance, folder):
    from app.pdf_background_geometry import source_flow_background_table
    from app.pdf_source_backgrounds import native_background_assets

    with zipfile.ZipFile(output) as package:
        header = etree.fromstring(package.read("Contents/header.xml"))
        manifest = etree.fromstring(package.read("Contents/content.hpf"))
        hrefs = {node.get("id"): node.get("href")
                 for node in manifest.iter("{http://www.idpf.org/2007/opf/}item")}
        owners = []
        for name in package.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            root = etree.fromstring(package.read(name))
            owners.extend((root, draw.find(".//" + HP + "tbl"))
                          for draw in root.iter(HP + "drawText")
                          if draw.get("name") in {"question:v1:q27", "question:v2:q27"})
        assert len(owners) == 2
        for root, table in owners:
            assert source_flow_background_table(table, root, header, hrefs, package, source, provenance)
        root, table = owners[0]
        asset = native_background_assets(etree.Element(table.tag, dict(table.attrib)), header, hrefs, package)
        records = [record for record in provenance
                   if record.get("role") == "source_background_frame" and record.get("sha256") == asset[0][0]]
        assert len(records) == 2 and records[0]["bbox_px"] == records[1]["bbox_px"]
        for mutation in ("duplicate_page", "geometry"):
            changed = deepcopy(provenance)
            matches = [record for record in changed
                       if record.get("role") == "source_background_frame" and record.get("sha256") == asset[0][0]]
            if mutation == "duplicate_page":
                matches[1]["page"] = matches[0]["page"]
            else:
                matches[1]["bbox_px"][0] += 1
            assert not source_flow_background_table(table, root, header, hrefs, package, source, changed), mutation
        # The original bitmap and its bounds stay unchanged while the repeated
        # page's independent native prose changes. A hash alone cannot pass.
        changed_source = folder / "repeated-frame-different-prose.pdf"
        with fitz.open(source) as document:
            x, y, _, _ = records[1]["bbox_px"]
            document[int(records[1]["page"]) - 1].insert_text((x + 20, y + 40), "Changed source prose", fontsize=8)
            document.save(changed_source)
        assert not source_flow_background_table(table, root, header, hrefs, package, changed_source, provenance)
    return {"positive": 2, "negative": 3}


def verify_high1(folder, source):
    items, provenance = extract_native_content(source)
    with fitz.open(source) as document:
        page = document[3]
        charts = statistical_chart_regions(page)
        assert len(charts) == 1, "the plot's complete frame was not recognized"
        chart = charts[0]
        assert chart.width < page.rect.width * .48 and chart.height < page.rect.height * .35
        # Numeric data and a surrounding rectangle cannot authorize prose or
        # an unordered value row as a chart. Exercise the complete source page.
        lines = _iter_text_lines(page)
        plot = fitz.Rect(122.027, 252.849, 400.602, 381.553)
        for mutation in ("prose", "axis"):
            changed = deepcopy(lines)
            if mutation == "prose":
                line = next(line for line in changed if _line_text(line).strip() == "34")
                line["spans"][0]["text"] = "An ordinary paragraph must stay editable in the document."
            else:
                line = next(line for line in changed if _line_text(line).strip() == "40"
                            and _item_bbox(line).y0 >= plot.y1 - 1)
                line["spans"][0]["text"] = "10"
            figures = [{"type": "image", "bbox": plot}]
            assert not include_statistical_chart_labels(page, figures, changed), mutation
        assert not statistical_chart_regions(document[1]), "a prose letter became a chart"
    q25 = [item for item in items if item["layout"].get("question_number") == 25]
    pictures = [item for item in q25 if item["image_paths"]]
    assert len(pictures) == 1 and pictures[0]["layout"]["source_bbox_pt"] == list(chart)
    assert not any(item["tables"] for item in q25), "chart labels leaked into prose boxes"
    assert any("The graph above shows" in item["stem"] for item in q25), "chart prose was rasterized"
    q28 = [item for item in items if item["layout"].get("question_number") == 28]
    notices = [item for item in q28 if item["tables"]]
    assert len(notices) == 1 and not any(item["image_paths"] for item in q28), "notice was split around its illustration"
    notice = notices[0]
    text = str(notice["tables"])
    assert text.count("Food Truck Festival") == text.count("Parking is available for free.") == 1
    assert "www.emtontruckfest.com." in text and text.count("∙") == 7
    geometry = notice["layout"]["native_tables"][0]
    background = next(record for record in provenance
                      if record["role"] == "source_background_frame" and record["page"] == 4
                      and record["bbox_px"][1] > 600)
    assert len(background["source_image_numbers"]) == 10, "original notice rim/truck bitmap inventory changed"
    assert geometry["background_source_text"], "notice prose must stay native"

    output = folder / "high1.hwpx"
    stats = write_pdf_structured_hwpx(source, output, native_math=True)
    parsed = rhwp.parse(str(output))
    assert parsed.page_count == 8 and stats["output_problem_count"] == 45
    assert stats["full_page_images"] == 0
    roots, assets = package_roots(output)
    digest = hashlib.sha256(render_source_crop(source, 3, chart)).hexdigest()
    assert assets.count(digest) == 1, "complete original chart pixels must occur exactly once"
    draw = next(draw for root in roots for draw in root.iter(HP + "drawText")
                if draw.get("name") == "question:v1:q28")
    assert len(draw.findall(".//" + HP + "tbl")) == 1 and not draw.findall(".//" + HP + "pic")
    native = "".join(draw.itertext())
    assert native.count("Parking is available for free.") == 1 and "www.emtontruckfest.com." in native
    audit = inspect_pdf_editability(source, output, stats["image_provenance"], require_question_boxes=True)
    assert audit["ok"], audit["issues"]
    paint = inspect_question_rendering(output, rhwp)
    assert paint["ok"], paint
    glyphs = verify_cell_glyph_bounds(parsed, 7)
    choices = verify_choice_rails(parsed, source)
    (folder / "high1_page4.png").write_bytes(bytes(parsed.render_png(3)))
    return {"pages": parsed.page_count, "questions": stats["output_problem_count"],
            "editability": audit["ok"], "rendering": paint["ok"], "cell_glyphs": glyphs,
            "source_choice_rails": choices}


def verify_csat(folder, source):
    output = folder / "csat.hwpx"
    stats = write_pdf_structured_hwpx(source, output, native_math=True, variant_policy="all")
    parsed = rhwp.parse(str(output))
    assert parsed.page_count == 16, "a source-fitting last question shifted later booklet columns"
    assert stats["output_problem_count"] == 90 and stats["question_grouping"]["inventory_matches"]
    assert stats["full_page_images"] == 0
    audit = inspect_pdf_editability(source, output, stats["image_provenance"], require_question_boxes=True)
    assert audit["ok"], audit["issues"]
    repeated_frames = verify_repeated_background_frames(output, source, stats["image_provenance"], folder)
    paint = inspect_question_rendering(output, rhwp)
    assert paint["ok"], paint
    glyphs = verify_cell_glyph_bounds(parsed, 15)
    (folder / "csat_page16.png").write_bytes(bytes(parsed.render_png(15)))
    return {"pages": parsed.page_count, "questions": stats["output_problem_count"],
            "editability": audit["ok"], "rendering": paint["ok"], "cell_glyphs": glyphs,
            "repeated_frame_proofs": repeated_frames}


def run():
    folder = Path(runtime.name)
    cases = [("high1", ROOT / "data/external_exam_qa/2026_june_high1/english.pdf", verify_high1),
             ("csat", ROOT / "data/external_exam_qa/2026_csat/문제지/영어/영어.pdf", verify_csat)]
    results = {}
    for name, source, verify in cases:
        if source.exists():
            results[name] = verify(folder, source)
        else:
            results[name] = {"skipped": "local source PDF unavailable"}
    skipped = any("skipped" in result for result in results.values())
    print(("SKIP: ENGLISH_LAYOUT " if skipped else "ENGLISH_LAYOUT_OK: ")
          + json.dumps(results, ensure_ascii=False))
    return 2 if skipped else 0


if __name__ == "__main__":
    raise SystemExit(run())
