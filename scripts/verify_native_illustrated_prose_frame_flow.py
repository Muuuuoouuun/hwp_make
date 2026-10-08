"""Independent Q28 source/frame/pixel oracle and ordinary edit/save flow proof."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import re
from statistics import median
import sys
import tempfile
import unicodedata
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="illustrated_frame_oracle_")
os.environ["HWP_MAKE_DATA_DIR"] = str(Path(RUNTIME.name) / "engine")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402
from lxml import etree  # noqa: E402
from PIL import Image  # noqa: E402
import rhwp  # noqa: E402
from app.hwpx_writer_v2 import HwpxDocument  # noqa: E402
from app.pdf_question_geometry import inspect_question_geometry  # noqa: E402
from app.pdf_question_rendering import IDENTITY, _bounds, _multiply, _transform, _visible_svg_images, _expose_painted_dot_leaders  # noqa: E402
from hwpx.oxml import HwpxOxmlParagraph  # noqa: E402
from hwpx.tools.package_validator import validate_package  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SVG = "{http://www.w3.org/2000/svg}"
SOURCE = ROOT / "data/external_exam_qa/2026_september_high2/english.pdf"


def compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).replace("\xad", "-").replace("•", "∙"))


def check(condition, message):
    assert condition, message
    print("PASS:", message, flush=True)


def pixels(payload):
    with Image.open(io.BytesIO(payload)) as image:
        image = image.convert("RGBA")
        canvas = Image.new("RGBA", image.size, "white")
        canvas.alpha_composite(image)
        rgb = canvas.convert("RGB")
        return f"{rgb.width}x{rgb.height}:" + hashlib.sha256(rgb.tobytes()).hexdigest()


def source_rules(page):
    result = []
    for drawing in page.get_drawings():
        if (not drawing.get("color") or max(drawing["color"]) > .3
            or drawing.get("stroke_opacity", 1) < .999
            or drawing.get("width", 0) <= 0 or drawing.get("dashes") not in (None, "", "[] 0")):
            continue
        for part in drawing.get("items", []):
            if part[0] == "l":
                a, b = part[1:3]
                result.append((a.x, a.y, b.x, b.y))
            elif part[0] == "re":
                b = fitz.Rect(part[1])
                result.extend(((b.x0, b.y0, b.x1, b.y0), (b.x0, b.y1, b.x1, b.y1),
                               (b.x0, b.y0, b.x0, b.y1), (b.x1, b.y0, b.x1, b.y1)))
    return list(dict.fromkeys(tuple(round(v, 4) for v in line) for line in result))


def source_oracle(source):
    """Freeze expectations from raw PDF glyphs/rules/images, before app use."""
    with fitz.open(source) as document:
        page = document[3]
        raw = page.get_text("rawdict")
        lines = []
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                chars = [char for span in line["spans"] for char in span.get("chars", [])]
                lines.append({"text": "".join(char["c"] for char in chars), "bbox": list(line["bbox"]),
                              "baseline": median(span["origin"][1] for span in line["spans"]),
                              "chars": chars})
        prompts = [line for line in lines if line["text"].startswith("28.")]
        check(len(prompts) == 1, "source Q28 is independently identified by its printed question number")
        prompt = prompts[0]
        images = [block for block in page.get_text("dict")["blocks"] if block.get("type") == 1]
        rules = source_rules(page)
        horizontal = [(min(a, c), b, max(a, c)) for a, b, c, d in rules if abs(b-d) < .01 and abs(c-a) > 200]
        vertical = [(a, min(b, d), max(b, d)) for a, b, c, d in rules if abs(a-c) < .01]
        candidates = []
        for left, top, right in horizontal:
            if top <= prompt["bbox"][3] or left < page.rect.width / 2:
                continue
            for other_left, bottom, other_right in horizontal:
                if bottom <= top or max(abs(left-other_left), abs(right-other_right)) > .3:
                    continue
                if not all(any(abs(x-edge) < .3 and a <= top+.1 and b >= bottom-.1
                               for x, a, b in vertical) for edge in (left, right)):
                    continue
                bounds = fitz.Rect(left, top, right, bottom)
                rows = sorted([line for line in lines if bounds.contains(fitz.Rect(line["bbox"]))],
                              key=lambda line: (line["baseline"], line["bbox"][0]))
                pictures = [image for image in images if bounds.contains(fitz.Rect(image["bbox"]))]
                if rows and compact(rows[0]["text"]) in compact(prompt["text"]) and len(pictures) == 2:
                    candidates.append((bounds, rows, pictures))
        check(len(candidates) == 1, "one complete four-rule source frame owns the Q28 caption and two illustrations")
        frame, rows, pictures = candidates[0]
        check(len(rows) == 18 and len({round(row["baseline"], 2) for row in rows}) == 18,
              "source independently contains 18 complete prose baselines")
        check(all(not (fitz.Rect(image["bbox"]) & fitz.Rect(row["bbox"])).get_area() > .1
                  for image in pictures for row in rows), "source illustrations do not cover any original prose glyph row")
        pictures.sort(key=lambda image: image["bbox"][1])
        following = next(line["text"] for line in lines
                         if line["text"].startswith("①") and line["bbox"][0] > page.rect.width / 2
                         and line["bbox"][1] > frame.y1)
        width, height = page.rect.width, page.rect.height
    frozen_images = []
    for image in pictures:
        # Isolated source image clips contain no text (proved above). Only
        # source figure pixels are rasterized; no prose/frame/page raster.
        with fitz.open(source) as independent:
            payload = independent[3].get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(image["bbox"]), alpha=False).tobytes("png")
        frozen_images.append({"bbox": list(image["bbox"]), "pixels": pixels(payload), "payload": payload})
    return {"source": str(source), "page": 3, "page_width": width, "page_height": height,
            "frame": list(frame), "rows": rows, "images": frozen_images,
            "text": "".join(row["text"] for row in rows), "rules": rules, "following": following}


def package(path):
    with zipfile.ZipFile(path) as archive:
        data = {name: archive.read(name) for name in archive.namelist()}
    roots = {name: etree.fromstring(payload) for name, payload in data.items()
             if re.fullmatch(r"Contents/section\d+\.xml", name)}
    manifest = etree.fromstring(data["Contents/content.hpf"])
    refs = {node.get("id"): node.get("href") for node in manifest.iter("{http://www.idpf.org/2007/opf/}item")}
    owners = [(name, root, draw) for name, root in roots.items() for draw in root.iter(HP + "drawText")
              if draw.get("name") == "question:v1:q28"]
    check(len(owners) == 1, "one native question owns Q28")
    name, root, draw = owners[0]
    tables = draw.find(HP + "subList").findall(HP + "p/" + HP + "run/" + HP + "tbl")
    return data, roots, refs, name, root, draw, tables


def audit_native(oracle, draw, tables, refs, data):
    issues = []
    if len(tables) != 1:
        return ["not_one_native_outer_frame"]
    table = tables[0]
    page = draw.getroottree().getroot().find(".//" + HP + "pagePr")
    paper_width = float(page.get("width")) if page is not None else oracle.get("native_page_width", 59528)
    expected_width = (oracle["frame"][2] - oracle["frame"][0]) * paper_width / oracle["page_width"]
    if abs(float(table.find(HP + "sz").get("width")) - expected_width) > 2:
        issues.append("source_frame_width")
    if compact("".join(t.text or "" for t in table.iter(HP + "t"))) != compact(oracle["text"]):
        issues.append("source_prose_inventory")
    # The raw source has one full-width prose region followed by two
    # illustration/text relationships. Cells represent these regions, never
    # individual printed rows. Column cuts come from the two visible images.
    cells = table.findall(HP + "tr/" + HP + "tc")
    regions = []
    cuts = [oracle["frame"][0], oracle["images"][1]["bbox"][0],
            oracle["images"][0]["bbox"][0], oracle["frame"][2]]
    for cell in cells:
        address, span, size = (cell.find(HP + tag) for tag in ("cellAddr", "cellSpan", "cellSz"))
        if address is None or span is None or size is None:
            issues.append("invalid_source_region_cell"); continue
        row, col = int(address.get("rowAddr")), int(address.get("colAddr"))
        rowspan, colspan = int(span.get("rowSpan")), int(span.get("colSpan"))
        regions.append((row, col, rowspan, colspan))
        if not 0 <= col < col + colspan <= 3:
            issues.append("invalid_source_region_cell"); continue
        width = (cuts[col + colspan] - cuts[col]) * paper_width / oracle["page_width"]
        if abs(float(size.get("width")) - width) > 2:
            issues.append("source_region_width")
    if (table.get("rowCnt"), table.get("colCnt")) != ("3", "3") or sorted(regions) != [
        (0, 0, 1, 3), (1, 0, 1, 2), (1, 2, 2, 1), (2, 0, 1, 1), (2, 1, 1, 1)
    ]:
        issues.append("source_semantic_region_topology")
    if not inspect_question_geometry(draw)["ok"]:
        issues.append("native_question_content_bounds")
    pictures = table.findall(".//" + HP + "pic")
    identities = []
    for picture in pictures:
        image = picture.find(".//" + HC + "img")
        ref = refs.get(image.get("binaryItemIDRef")) if image is not None else None
        if ref not in data:
            issues.append("unresolved_picture"); continue
        identities.append(pixels(data[ref]))
        position = picture.find(HP + "pos")
        owner = next((node for node in picture.iterancestors() if node.tag == HP + "p"), None)
        if position is None or (position.get("treatAsChar") != "1" and position.get("vertRelTo") in ("PAGE", "PAPER")):
            issues.append("fixed_page_picture")
        if position is None or position.get("flowWithText") != "1":
            issues.append("picture_does_not_follow_text")
        if picture.get("textWrap") in ("IN_FRONT_OF_TEXT", "BEHIND_TEXT") or position.get("allowOverlap") == "1":
            issues.append("overlapping_picture_anchor")
        if owner is None or not any(node.tag == HP + "tc" for node in picture.iterancestors()):
            issues.append("picture_outside_native_frame_cell")
    if Counter(identities) != Counter(image["pixels"] for image in oracle["images"]):
        issues.append("source_picture_pixel_inventory")
    # Native adjacent cells preserve the source's same-row relationship.
    # A fixed floating offset inside a cell is insufficient ownership proof.
    if len(pictures) == 2 and len(identities) == 2:
        small_id = oracle["images"][1]["pixels"]
        small = pictures[identities.index(small_id)] if small_id in identities else None
        if small is not None:
            owner_cell = next(node for node in small.iterancestors() if node.tag == HP + "tc")
            registration = [cell for cell in table.findall(HP + "tr/" + HP + "tc")
                            if "Pre-registration" in unicodedata.normalize("NFKC", "".join(cell.itertext())).replace("\xad", "-")]
            if (len(registration) != 1 or registration[0] is owner_cell
                or owner_cell.find(HP + "cellAddr").get("rowAddr") != registration[0].find(HP + "cellAddr").get("rowAddr")
                or int(owner_cell.find(HP + "cellAddr").get("colAddr")) != int(registration[0].find(HP + "cellAddr").get("colAddr")) + 1):
                issues.append("small_picture_lost_adjacent_source_row")
    return issues


def painted(path):
    parsed = rhwp.parse(str(path))
    values, images, lines = [], [], []
    for page in range(parsed.page_count):
        svg_text = parsed.render_svg(page)
        svg = etree.fromstring(svg_text.encode())
        _expose_painted_dot_leaders(svg)
        for node in svg.iter():
            if any(ancestor.tag == SVG + "defs" for ancestor in node.iterancestors()):
                continue
            matrix = IDENTITY
            for ancestor in [*reversed(list(node.iterancestors())), node]:
                matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
            if node.tag == SVG + "text":
                xy = _bounds(matrix, float(node.get("x", 0)), float(node.get("y", 0)), 0, 0)[:2]
                values.extend((char, page, *xy) for char in compact("".join(node.itertext())))
            elif node.tag == SVG + "image":
                href = node.get("href") or node.get("{http://www.w3.org/1999/xlink}href", "")
                if href.startswith("data:image/"):
                    payload = base64.b64decode(href.split(",", 1)[1])
                    box = _bounds(matrix, float(node.get("x", 0)), float(node.get("y", 0)),
                                  float(node.get("width", 0)), float(node.get("height", 0)))
                    images.append((pixels(payload), page, box))
            elif node.tag == SVG + "line" and node.get("stroke") not in (None, "none", "#ffffff"):
                a = _bounds(matrix, float(node.get("x1", 0)), float(node.get("y1", 0)), 0, 0)[:2]
                b = _bounds(matrix, float(node.get("x2", 0)), float(node.get("y2", 0)), 0, 0)[:2]
                lines.append((page, (*a, *b)))
        visible = _visible_svg_images(svg_text)
        for identity, count in visible.items():
            check(sum(value[0] == identity and value[1] == page for value in images) >= count,
                  "visible source image geometry is independently available")
    return parsed, values, images, lines


def locate(values, text):
    joined, target = "".join(value[0] for value in values), compact(text)
    check(joined.count(target) == 1, "complete expected SVG text inventory exists once")
    start = joined.index(target)
    return values[start:start + len(target)]


def union_covers(intervals, start, end, tolerance=.4):
    cursor = start
    for left, right in sorted(intervals):
        if cursor >= end - tolerance:
            return True
        if right < start - tolerance:
            continue
        if left > cursor + tolerance:
            return False
        cursor = max(cursor, right)
    return cursor >= end - tolerance


def visible_frame(oracle, data, images, lines):
    ids = [image["pixels"] for image in oracle["images"]]
    found = [next((record for record in images if record[0] == identity), None) for identity in ids]
    check(all(found), "both original source illustrations paint in the output")
    check(len({record[1] for record in found}) == 1, "both illustrations remain in one source frame page")
    page = found[0][1]
    root = etree.fromstring(data[f"Contents/section{0 if page == 0 else 1}.xml"])
    paper_width = float(root.find(".//" + HP + "pagePr").get("width")) / 75
    scale = paper_width / oracle["page_width"]
    left, top, right, bottom = [value * scale for value in oracle["frame"]]
    failures = []

    def geometry_check(condition, message):
        if condition:
            check(True, message)
        else:
            failures.append(message)
            print("FAIL:", message, flush=True)

    # Source-relative y is checked on the unedited document. Four continuous
    # rails may consist of several row-border segments in an editable table.
    edge_lines = [line for index, line in lines if index == page]
    for y in (top, bottom):
        parts = [(min(a, c), max(a, c)) for a, b, c, d in edge_lines if max(abs(b-y), abs(d-y)) < .5]
        geometry_check(union_covers(parts, left, right), f"native frame retains source horizontal rule y={y:.4f}px")
    for x in (left, right):
        parts = [(min(b, d), max(b, d)) for a, b, c, d in edge_lines if max(abs(a-x), abs(c-x)) < .5]
        geometry_check(union_covers(parts, top, bottom), f"native frame retains source vertical rule x={x:.4f}px")
    for record, source in zip(found, oracle["images"]):
        expected = [value * scale for value in source["bbox"]]
        delta = [round(a-b, 4) for a, b in zip(record[2], expected)]
        geometry_check(max(abs(value) for value in delta) < .6,
                       f"source illustration retains independent display bounds; delta_px={delta}")
    return page, scale, found, failures


def negative_tests(oracle, draw, tables, refs, data):
    cases = ("partialtext", "replacementimage", "fixedpage", "overlap", "invalidframe", "framewidth", "regiontopology")
    for case in cases:
        altered = deepcopy(draw)
        altered_tables = altered.find(HP + "subList").findall(HP + "p/" + HP + "run/" + HP + "tbl")
        payloads = dict(data)
        if case == "partialtext":
            next(altered_tables[0].iter(HP + "t")).text = "Missing original text"
        elif case == "replacementimage":
            picture = next(altered_tables[0].iter(HP + "pic"))
            href = refs[picture.find(".//" + HC + "img").get("binaryItemIDRef")]
            with Image.open(io.BytesIO(payloads[href])) as image:
                changed = Image.new("RGB", image.size, "white")
            buf = io.BytesIO(); changed.save(buf, format="PNG"); payloads[href] = buf.getvalue()
        elif case in ("fixedpage", "overlap"):
            picture = next(altered_tables[0].iter(HP + "pic"))
            picture.find(HP + "pos").set("treatAsChar", "0")
            picture.find(HP + "pos").set("vertRelTo" if case == "fixedpage" else "allowOverlap", "PAGE" if case == "fixedpage" else "1")
            if case == "overlap":
                picture.set("textWrap", "IN_FRONT_OF_TEXT")
        elif case == "invalidframe":
            altered_tables.append(deepcopy(altered_tables[0]))
        elif case == "framewidth":
            altered_tables[0].find(HP + "sz").set("width", "100")
        else:
            altered_tables[0].find(HP + "tr/" + HP + "tc/" + HP + "cellSpan").set("colSpan", "1")
        check(bool(audit_native(oracle, altered, altered_tables, refs, payloads)), f"independent oracle rejects {case}")


def source_proof_negative_tests(oracle, path, data, root, refs):
    """Exercise the real source-proof exception using independent XML mutants."""
    from app.pdf_illustrated_prose_frames import source_flow_illustrated_frame_table
    HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
    cases = ("positive", "partialtext", "replacementimage", "outerborder", "width",
             "rowownership", "pageanchor", "oversizedcontent", "oversizedwidth", "badbaseline", "nonfinitecache")
    for case in cases:
        changed, header, payloads = deepcopy(root), etree.fromstring(data["Contents/header.xml"]), dict(data)
        draw = next(node for node in changed.iter(HP + "drawText") if node.get("name") == "question:v1:q28")
        table = next(draw.iter(HP + "tbl"))
        if case == "partialtext":
            next(table.iter(HP + "t")).text = "Missing original source prose"
        elif case == "replacementimage":
            picture = next(table.iter(HP + "pic"))
            href = refs[picture.find(".//" + HC + "img").get("binaryItemIDRef")]
            with Image.open(io.BytesIO(payloads[href])) as image:
                replacement = Image.new("RGB", image.size, "white")
            output = io.BytesIO(); replacement.save(output, format="PNG"); payloads[href] = output.getvalue()
        elif case == "outerborder":
            identifier = table.find(HP + "tr/" + HP + "tc").get("borderFillIDRef")
            fill = next(node for node in header.iter(HH + "borderFill") if node.get("id") == identifier)
            fill.find(HH + "leftBorder").set("type", "NONE")
        elif case == "width":
            table.find(HP + "sz").set("width", "100")
        elif case == "rowownership":
            picture = next(table.iter(HP + "pic"))
            cell = next(node for node in picture.iterancestors() if node.tag == HP + "tc")
            cell.find(HP + "cellAddr").set("rowAddr", "0")
        elif case == "pageanchor":
            position = next(table.iter(HP + "pic")).find(HP + "pos")
            position.set("treatAsChar", "0"); position.set("vertRelTo", "PAGE")
        elif case == "oversizedcontent":
            segment = next(table.iter(HP + "lineseg"))
            segment.set("vertsize", "200000"); segment.set("textheight", "200000")
        elif case in ("oversizedwidth", "badbaseline", "nonfinitecache"):
            segment = next(table.iter(HP + "lineseg"))
            key, value = {"oversizedwidth": ("horzsize", "200000"),
                          "badbaseline": ("baseline", segment.get("textheight")),
                          "nonfinitecache": ("vertsize", "NaN")}[case]
            segment.set(key, value)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, payload in payloads.items():
                archive.writestr(name, payload)
        with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
            result = source_flow_illustrated_frame_table(table, changed, header, refs, archive, Path(oracle["source"]))
        check(result == (case == "positive"), f"real source proof {'accepts' if case == 'positive' else 'rejects'} {case}")


def direct_text(paragraph):
    return "".join(t.text or "" for t in paragraph.findall(HP + "run/" + HP + "t"))


def field_oracle(oracle):
    """Infer repeated labels and their continuation ink from raw source glyphs."""
    rows = oracle["rows"]
    labels = [(index, re.match(r"^([A-Za-z][A-Za-z -]{1,30}):\s+\S", row["text"]))
              for index, row in enumerate(rows)]
    labels = [(index, match.group(1)) for index, match in labels if match]
    check(len(labels) >= 3, "source raw glyphs independently prove repeated labeled fields")
    result = []
    for position, (index, label) in enumerate(labels):
        stop = labels[position + 1][0] if position + 1 < len(labels) else index + 1
        group = rows[index:stop]
        nonspace = [[char for char in row["chars"] if not char["c"].isspace()] for row in group]
        result.append({"label": label, "rows": group,
                       "text": " ".join(row["text"].strip() for row in group),
                       "first_x": nonspace[0][0]["origin"][0],
                       "continuation_x": nonspace[1][0]["origin"][0] if len(group) > 1 else None})
    return result


def paragraph_margin(header, paragraph, name):
    styles = {node.get("id"): node for node in header.iter(HH + "paraPr")}
    style = styles[paragraph.get("paraPrIDRef")]
    values = [float(node.get("value")) for node in style.iter(HC + name)]
    check(values and max(values) == min(values), f"native {name} margin is consistent in both HWPX branches")
    return values[0]


def source_field_issues(oracle, table, header, scale):
    fields = field_oracle(oracle)
    paragraphs = list(table.iter(HP + "p"))
    issues, selected = [], []
    for field in fields:
        candidates = [p for p in paragraphs if compact(direct_text(p)).startswith(field["label"] + ":")]
        if len(candidates) != 1 or compact(direct_text(candidates[0])) != compact(field["text"]):
            issues.append(f"{field['label']} is not one complete independent semantic paragraph")
            continue
        paragraph = candidates[0]
        selected.append(paragraph)
        lines = paragraph.findall(HP + "linesegarray/" + HP + "lineseg")
        if len(lines) != len(field["rows"]):
            issues.append(f"{field['label']} source rows changed")
        if field["continuation_x"] is not None:
            expected = (field["continuation_x"] - field["first_x"]) * scale * 75
            # Native HWP semantics: left + max(0, -intent) is the
            # continuation rail, while a negative intent leaves line 1 at left.
            if abs(paragraph_margin(header, paragraph, "left")) > 2:
                issues.append("source first field rail gained an unsupported left margin")
            if abs(paragraph_margin(header, paragraph, "intent") + expected) > 2:
                issues.append("source first-line negative indent differs from independent source ink")
    return issues, selected


def styled_inventory(table, header):
    """Compare actual resolved charPr content, never trust retained style IDs."""
    def signature(node):
        return (etree.QName(node).localname,
                tuple(sorted((key, value) for key, value in node.attrib.items() if key != "id")),
                node.text, tuple(signature(child) for child in node))
    styles = {node.get("id"): signature(node) for node in header.iter(HH + "charPr")}
    return [(char, styles[run.get("charPrIDRef")]) for paragraph in table.iter(HP + "p")
            for run in paragraph.findall(HP + "run") for text in run.findall(HP + "t")
            for char in text.text or "" if not char.isspace()]


def field_group_height(table, header):
    paragraphs = [p for p in table.iter(HP + "p") if direct_text(p)]
    first = next(index for index, p in enumerate(paragraphs) if direct_text(p).startswith("When:"))
    last = next(index for index, p in enumerate(paragraphs) if "Workshop Schedule" in direct_text(p))
    return sum(sum(float(line.get("vertsize")) + float(line.get("spacing"))
                   for line in paragraph.findall(HP + "linesegarray/" + HP + "lineseg"))
               + paragraph_margin(header, paragraph, "prev") + paragraph_margin(header, paragraph, "next")
               for paragraph in paragraphs[first:last + 1])


def verify_source_fields(oracle, path, data, table, values, scale, before_path=None):
    header = etree.fromstring(data["Contents/header.xml"])
    issues, paragraphs = source_field_issues(oracle, table, header, scale)
    check(not issues, f"raw source labels, whole semantic paragraphs and hanging indent are restored: {issues}")
    selected = locate(values, oracle["text"])
    cursor = 0
    positions = []
    for row in oracle["rows"]:
        portion = selected[cursor:cursor + len(compact(row["text"]))]
        ink = [record for record in portion if record[0] != "∙"]
        positions.append(ink)
        cursor += len(portion)
    when = next(field for field in field_oracle(oracle) if len(field["rows"]) > 1)
    row_index = oracle["rows"].index(when["rows"][1])
    continuation = positions[row_index][0]
    check(abs(continuation[2] - when["continuation_x"] * scale) < .15,
          "native When continuation first ink matches independently measured source rail")
    # Actual-mutant tests exercise the independent consumer oracle, not flags.
    cases = ("merged-fields", "partial-field", "split-continuation", "wrong-left", "wrong-intent")
    for case in cases:
        changed, changed_header = deepcopy(table), deepcopy(header)
        targets = [p for p in changed.iter(HP + "p") if direct_text(p).startswith("When:")]
        target = targets[0]
        if case == "merged-fields":
            adjacent = next(p for p in changed.iter(HP + "p") if direct_text(p).startswith("Where:"))
            for run in adjacent.findall(HP + "run"):
                target.insert(len(target.findall(HP + "run")), deepcopy(run))
            adjacent.getparent().remove(adjacent)
        elif case == "partial-field":
            next(target.iter(HP + "t")).text = "When: omitted source condition"
        elif case == "split-continuation":
            target.remove(target.find(HP + "linesegarray"))
        else:
            style = next(p for p in changed_header.iter(HH + "paraPr") if p.get("id") == target.get("paraPrIDRef"))
            for node in style.iter(HC + ("left" if case == "wrong-left" else "intent")):
                node.set("value", "500" if case == "wrong-left" else "0")
        mutant_issues, _ = source_field_issues(oracle, changed, changed_header, scale)
        check(bool(mutant_issues), f"independent source field oracle rejects actual {case} mutant")
    summary = {"labels": [field["label"] for field in field_oracle(oracle)],
               "when_source_rows": len(when["rows"]), "continuation_x": continuation[2],
               "source_continuation_x": when["continuation_x"] * scale,
               "combined_field_heading_flow": field_group_height(table, header), "negative_cases": len(cases)}
    if before_path:
        before = package(before_path)
        before_header = etree.fromstring(before[0]["Contents/header.xml"])
        check(styled_inventory(before[6][0], before_header) == styled_inventory(table, header),
              "field restoration preserves every source character and resolved run style")
        check(field_group_height(before[6][0], before_header) == summary["combined_field_heading_flow"],
              "field semantic split preserves the combined original five-row flow height")
        check(before[5].getparent().find(HP + "sz").get("height") == package(path)[5].getparent().find(HP + "sz").get("height"),
              "field restoration leaves the owning question height unchanged")
        _, before_values, _, _ = painted(before_path)
        prior = locate(before_values, oracle["text"])
        continuation_start = sum(len(compact(row["text"])) for row in oracle["rows"][:row_index])
        continuation_stop = continuation_start + len(compact(oracle["rows"][row_index]["text"]))
        unaffected = [(a, b) for index, (a, b) in enumerate(zip(prior, selected))
                      if not continuation_start <= index < continuation_stop]
        check(all(a[0:2] == b[0:2] and max(abs(a[2]-b[2]), abs(a[3]-b[3])) < .05 for a, b in unaffected),
              "all other original glyph rails and baselines stay unchanged by field restoration")
        summary["unchanged_resolved_run_styles_height_other_glyphs"] = True
    return summary


def actual(oracle, path, folder, before_path=None):
    data, roots, refs, name, root, draw, tables = package(path)
    issues = audit_native(oracle, draw, tables, refs, data)
    check(not issues, f"native frame passes independent source text/pixel/flow proof: {issues}")
    negative_tests(oracle, draw, tables, refs, data)
    source_proof_negative_tests(oracle, path, data, root, refs)
    validation = validate_package(path)
    check(validation.ok and not validation.warnings, "native package references and schema controls remain valid")
    parsed, values, images, lines = painted(path)
    print("ACTUAL_RENDERED_PAGE_COUNT:", parsed.page_count, flush=True)
    page, scale, original_images, geometry_failures = visible_frame(oracle, data, images, lines)
    source_text = locate(values, oracle["text"])
    offset = 0
    rows = []
    for row in oracle["rows"]:
        count = len(compact(row["text"]))
        portion = source_text[offset:offset + count]
        prose = [record for record in portion if record[0] != "∙"]
        check(len({p for _, p, _, _ in prose}) == 1 and max(record[3] for record in prose) - min(record[3] for record in prose) < .15,
              "one original source line stays on one native baseline")
        rows.append(prose[0]); offset += count
    check(max(abs((value[3] - rows[0][3]) - (row["baseline"] - oracle["rows"][0]["baseline"]) * scale)
              for value, row in zip(rows, oracle["rows"])) < .5,
          "all 18 source baselines preserve their measured relative spacing")
    fields = verify_source_fields(oracle, path, data, tables[0], values, scale, before_path)
    native_text = "".join(t.text or "" for t in tables[0].iter(HP + "t"))
    cell_regions = source_cell_regions(tables[0], page, lines, original_images)
    original_glyphs, missing_visible, cell_failures = edited_glyph_bounds(
        path, native_text, original_images, root, values, native_cells=cell_regions, source_oracle=oracle)
    edit_cases = edit_flow(oracle, path, folder, values, original_images)
    if parsed.page_count == 8:
        check(True, "actual high2 retains the source eight-page booklet")
    else:
        geometry_failures.append(f"source eight-page booklet became {parsed.page_count} pages")
        print("FAIL:", geometry_failures[-1], flush=True)
    success = not (geometry_failures or cell_failures or missing_visible)
    report = {"ok": success, "source": oracle["source"], "hwpx": str(path),
              "pages": parsed.page_count, "source_rows": len(oracle["rows"]), "source_pictures": len(oracle["images"]),
              "native_text_source_image_flow_proof": True, "negative_cases": 17,
              "original_source_glyphs": original_glyphs,
              "missing_source_visible_glyph": missing_visible,
              "missing_source_visible_glyph_backend": "rhwp.render_pdf (usvg/rustybuzz); PNG painting is separate",
              "source_native_cell_glyph_bounds_failures": cell_failures,
              "source_native_cell_glyph_bounds_backend": "rhwp.render_pdf; PNG clipping is not inferred",
              "relative_source_baselines": True, "edit_growth_reopen_glyph_bounds": True,
              "source_labeled_fields": fields,
              "total_negative_cases": 17 + fields["negative_cases"], "edit_cases": edit_cases,
              "absolute_source_geometry_failures": geometry_failures}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ILLUSTRATED_FRAME_FLOW_" + ("OK" if success else "FAIL"), json.dumps(report, ensure_ascii=False))
    return 0 if success else 1


def question_text(draw):
    return "".join(t.text or "" for t in draw.iter(HP + "t"))


def source_cell_regions(table, page, lines, pictures):
    """Locate actual four SVG rails, then resolve ordinary native cell geometry."""
    width, height = (float(table.find(HP + "sz").get(key)) / 75 for key in ("width", "height"))
    visible = [line for index, line in lines if index == page]
    horizontal = [(min(a, c), b, max(a, c)) for a, b, c, d in visible if abs(b-d) < .05]
    frames = []
    for left, top, right in horizontal:
        if abs(right-left-width) >= .1:
            continue
        bottom = top + height
        if not union_covers([(a,c) for a,b,c in horizontal if abs(b-bottom) < .1], left, right, .1):
            continue
        if not all(union_covers([(min(b, d), max(b, d)) for a, b, c, d in visible
                                 if max(abs(a-x), abs(c-x)) < .1], top, bottom, .1) for x in (left, right)):
            continue
        frame = fitz.Rect(left, top, right, bottom)
        if all(frame.contains(fitz.Rect(record[2])) for record in pictures):
            frames.append(frame)
    check(len(frames) == 1, "actual SVG four-rule frame independently locates its native cells")
    frame = frames[0]
    cells = table.findall(HP + "tr/" + HP + "tc")
    widths, heights = {}, {}
    for cell in cells:
        address, span, size = (cell.find(HP + tag) for tag in ("cellAddr", "cellSpan", "cellSz"))
        if span.get("colSpan") == "1": widths[int(address.get("colAddr"))] = float(size.get("width")) / 75
        if span.get("rowSpan") == "1": heights[int(address.get("rowAddr"))] = float(size.get("height")) / 75
    regions = []
    for cell in cells:
        address = cell.find(HP + "cellAddr")
        row, col = int(address.get("rowAddr")), int(address.get("colAddr"))
        x, y = frame.x0 + sum(widths[i] for i in range(col)), frame.y0 + sum(heights[i] for i in range(row))
        w, h = float(cell.find(HP + "cellSz").get("width")) / 75, float(cell.find(HP + "cellSz").get("height")) / 75
        # Source-derived text margins are placement rails, not SVG clipping
        # regions. Natural font ink may enter them while staying inside the
        # physical editable cell. Compare actual ink with those cell edges.
        box = fitz.Rect(x, y, x+w, y+h)
        text = "".join(t.text or "" for t in cell.iter(HP + "t"))
        regions.append((text, box))
    return regions


def edited_glyph_bounds(path, expected, picture_records, root, painted_values, *, native_cells=None, source_oracle=None):
    parsed = rhwp.parse(str(path))
    page_pr = root.find(".//" + HP + "pagePr")
    margin = page_pr.find(HP + "margin")
    left, right = float(margin.get("left")) / 100, (float(page_pr.get("width")) - float(margin.get("right"))) / 100
    top = (float(margin.get("top")) + float(margin.get("header", "0"))) / 100
    bottom = (float(page_pr.get("height")) - float(margin.get("bottom"))) / 100
    with fitz.open(stream=bytes(parsed.render_pdf()), filetype="pdf") as pdf:
        glyphs = [(page_index, char) for page_index, page in enumerate(pdf)
                  for trace in page.get_texttrace() for char in trace["chars"] if not chr(char[0]).isspace()]
        values, mapped = [], []
        for record in glyphs:
            value = compact(chr(record[1][0])).replace("∙", "")
            values.extend(value); mapped.extend([record] * len(value))
        # Actual font bounds are distinct from XML/SVG text inventory. A
        # vector bullet has separate painted-circle proof. Missing visible
        # source soft hyphens are explicitly reported below, never passed.
        locate(painted_values, expected)
        sequence = "".join(values)
        target = compact(expected.replace("\xad", "")).replace("∙", "")
        check(sequence.count(target) == 1, "expected native font glyph inventory exists (visible source hyphens audited separately)")
        selected = mapped[sequence.index(target):sequence.index(target) + len(target)]
        outside, overlaps = [], []
        clipped = []
        for page_index, char in selected:
            box = char[3]
            if not (left - .3 <= box[0] < box[2] <= right + .3 and top - .3 <= box[1] < box[3] <= bottom + .3):
                outside.append((chr(char[0]), box))
            for _, image_page, image_box in picture_records:
                if image_page == page_index:
                    picture = fitz.Rect(*(value * .75 for value in image_box))
                    if (picture & fitz.Rect(box)).get_area() > .1:
                        overlaps.append((chr(char[0]), box, list(picture)))
        check(not outside, f"{len(selected)} edited glyph ink bounds and positive descenders remain printable: {outside[:3]}")
        check(not overlaps, f"edited glyphs do not overlap source illustrations: {overlaps[:3]}")
        failures, missing_visible = [], []
        if native_cells is not None:
            cursor = 0
            for cell_text, cell in native_cells:
                count = len(compact(cell_text.replace("\xad", "")).replace("∙", ""))
                for _, char in selected[cursor:cursor+count]:
                    glyph = fitz.Rect(*(value / .75 for value in char[3]))
                    if not (cell.x0-.3 <= glyph.x0 < glyph.x1 <= cell.x1+.3 and cell.y0-.3 <= glyph.y0 < glyph.y1 <= cell.y1+.3):
                        clipped.append((chr(char[0]), list(glyph), list(cell)))
                cursor += count
            check(cursor == len(selected), "all source font glyphs have independent native cell ownership")
            if clipped:
                failures.append(f"source_native_cell_glyph_bounds: {clipped[:8]}")
                print("FAIL:", failures[-1], flush=True)
            else:
                check(True, f"all {len(selected)} source font glyphs fit actual native cell edges")
        if source_oracle is not None:
            native = locate(painted_values, source_oracle["text"])
            with fitz.open(source_oracle["source"]) as source:
                traces = [char for trace in source[source_oracle["page"]].get_texttrace()
                          if trace.get("type") == 0 and trace.get("opacity", 1) > .99 for char in trace["chars"]]
            cursor = 0
            for row in source_oracle["rows"]:
                for char in row["chars"]:
                    if char["c"] == "\xad":
                        painted_source = [value for value in traces if value[0] == 173 and value[1] > 0
                                          and max(abs(a-b) for a, b in zip(value[2], char["origin"])) < .1]
                        check(bool(painted_source), "source soft hyphen is an actual painted font glyph")
                        _, page_index, x, y = native[cursor]
                        matched = [value for glyph_page, value in glyphs if glyph_page == page_index
                                   and compact(chr(value[0])) == "-"
                                   and max(abs(a/.75-b) for a, b in zip(value[2], (x, y))) < .15]
                        if not matched:
                            missing_visible.append({"char": "U+00AD", "paint_backend": "rhwp.render_pdf",
                                                    "source_bbox_pt": char["bbox"], "native_svg_origin": [x,y]})
                    cursor += len(compact(char["c"]))
            if missing_visible: print("FAIL: native PDF missing_source_visible_glyph:", missing_visible, flush=True)
            else: check(True, "all actually painted source hyphens have native font glyphs")
    return (len(selected), missing_visible, failures) if native_cells is not None else len(selected)


def edit_flow(oracle, path, folder, initial_values, original_images):
    previous = path
    expected = compact(oracle["text"])
    prior_values, prior_images = initial_values, original_images
    summaries = []
    for label, prefix, addition in (
        ("main-body-grown", "The 2026 Footnote Dance Program",
         " Extra practice develops careful movement and confidence for every young participant." * 3),
        ("registration-row-grown", "• Pre", " Please submit the completed registration form before attending the program." * 2),
        ("when-field-grown", "When:",
         " Participants may request an additional practice session after discussing their plans with the instructor." * 2),
    ):
        stage_details = {}
        document = HwpxDocument.open(previous)
        section, draw = next((section, draw) for section in document.sections for draw in section.element.iter(HP + "drawText")
                             if draw.get("name") == "question:v1:q28")
        candidates = [p for p in next(draw.iter(HP + "tbl")).iter(HP + "p")
                      if compact("".join(t.text or "" for t in p.findall(HP + "run/" + HP + "t"))).startswith(compact(prefix))]
        check(len(candidates) == 1, "one semantic source paragraph owns the edited condition")
        public = HwpxOxmlParagraph(candidates[0], section)
        original = public.text
        old_header = etree.fromstring(package(previous)[0]["Contents/header.xml"])
        old_styles = styled_inventory(candidates[0], old_header)
        old_margins = {key: paragraph_margin(old_header, candidates[0], key) for key in ("left", "intent")}
        old_question_height = float(draw.getparent().find(HP + "sz").get("height"))
        before_paragraphs = sum(1 for _ in draw.iter(HP + "p"))
        # The caption is also printed in the question prompt. Locate it within
        # the complete, unique frame inventory rather than selecting globally.
        old_start = locate(prior_values, expected)[0]
        old_following = locate(prior_values, oracle["following"])[0]
        if label == "when-field-grown":
            # Public add_run preserves the source's mixed character styles and
            # invalidates the native cache, exercising actual edit-time reflow.
            last_run = next(run for run in reversed(public.runs) if run.text)
            public.add_run(addition, char_pr_id_ref=last_run.element.get("charPrIDRef"))
            check(candidates[0].find(HP + "linesegarray") is None, "public When edit invalidates the source layout cache")
        else:
            public.text = original + addition
        expected = expected.replace(compact(original), compact(original + addition), 1)
        target = folder / f"{label}.hwpx"
        document.save_to_path(target)
        data, roots, refs, _, root, updated, tables = package(target)
        changed_oracle = {**oracle, "text": expected, "native_page_width":
                          float(root.find(".//" + HP + "pagePr").get("width"))}
        check(not audit_native(changed_oracle, updated, tables, refs, data),
              "edited prose retains the native frame, both source figures and their flow ownership")
        check(sum(1 for _ in updated.iter(HP + "p")) == before_paragraphs,
              "editing keeps semantic paragraphs instead of splitting them into printed rows")
        check(float(updated.getparent().find(HP + "sz").get("height")) > old_question_height,
              "growing a frame paragraph enlarges its owning native question")
        parsed, values, images, _ = painted(target)
        locate(values, original + addition)
        new_start = locate(values, expected)[0]
        new_following = locate(values, oracle["following"])[0]
        check(new_following[3] - new_start[3] > old_following[3] - old_start[3] + .5,
              "the following native choice moves below the growing frame")
        selected_images = [next(record for record in images if record[0] == image["pixels"]) for image in oracle["images"]]
        if label == "main-body-grown":
            for before, after in zip(prior_images, selected_images):
                check(after[2][1] - new_start[3] > before[2][1] - old_start[3] + .5,
                      "each lower illustration follows the grown main-body row")
        elif label == "registration-row-grown":
            small = selected_images[1]
            prefix_start = locate(values, original)[0]
            check(small[1] == prefix_start[1] and abs(small[2][1] - prefix_start[3]) < 20,
                  "adjacent-cell illustration follows the edited registration row")
        else:
            grown = next(p for p in tables[0].iter(HP + "p") if direct_text(p).startswith(prefix))
            grown_header = etree.fromstring(data["Contents/header.xml"])
            check(all(paragraph_margin(grown_header, grown, key) == value for key, value in old_margins.items()),
                  "public When edit/save preserves native left and negative first-line indent")
            check(styled_inventory(grown, grown_header)[:len(old_styles)] == old_styles,
                  "public When append preserves all original resolved run styles")
            field = next(field for field in field_oracle(oracle) if field["label"] == "When")
            scale = float(root.find(".//" + HP + "pagePr").get("width")) / 75 / oracle["page_width"]
            portion = locate(values, original + addition)
            baselines = {}
            for value in portion:
                baselines.setdefault((value[1], round(value[3], 3)), value)
            first_inks = list(baselines.values())
            check(len(first_inks) > len(field["rows"]), "meaningful public When append grows its hanging paragraph")
            expected_first = locate(prior_values, original)[0][2] + new_start[2] - old_start[2]
            expected_continuation = expected_first + (field["continuation_x"] - field["first_x"]) * scale
            check(abs(first_inks[0][2] - expected_first) < .15
                  and all(abs(value[2] - expected_continuation) < .15 for value in first_inks[1:]),
                  "all edit-time When continuation rows retain the independently measured hanging rail")
            stage_details = {"native_margins": old_margins,
                             "first_row_x": first_inks[0][2], "expected_first_row_x": expected_first,
                             "continuation_row_x": [value[2] for value in first_inks[1:]],
                             "expected_continuation_x": expected_continuation,
                             "original_resolved_run_styles_preserved": True}
            for neighbor in ("Where:", "Cost:"):
                before_field, after_field = locate(prior_values, neighbor)[0], locate(values, neighbor)[0]
                check(after_field[3] - new_start[3] > before_field[3] - old_start[3] + .5,
                      f"following semantic {neighbor} paragraph moves after the grown When field")
            for before, after in zip(prior_images, selected_images):
                check(after[2][1] - new_start[3] > before[2][1] - old_start[3] + .5,
                      "lower source illustration follows the grown hanging field")
        page_root = list(roots.values())[0 if new_start[1] == 0 else 1]
        glyph_count = edited_glyph_bounds(target, original + addition, selected_images, page_root, values)
        validation = validate_package(target)
        check(validation.ok and not validation.warnings, "edited native package remains valid")
        reopened = folder / f"{label}-reopened.hwpx"
        HwpxDocument.open(target).save_to_path(reopened)
        again = package(reopened)
        check([etree.tostring(node) for node in again[1].values()] == [etree.tostring(node) for node in roots.values()],
              "reopening and resaving preserves stable native frame XML")
        _, again_values, again_images, _ = painted(reopened)
        check(values == again_values and images == again_images, "reopened native text and picture painting is stable")
        (folder / f"{label}-p{new_start[1]+1}.png").write_bytes(bytes(parsed.render_png(new_start[1])))
        summaries.append({"case": label, "pages": parsed.page_count, "glyphs": glyph_count,
                          "old_question_height": old_question_height,
                          "new_question_height": float(updated.getparent().find(HP + "sz").get("height")),
                          **stage_details})
        previous, prior_values, prior_images = reopened, values, selected_images
    (folder / "edit-summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    return summaries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--hwpx", type=Path)
    parser.add_argument("--before-hwpx", type=Path, help="independent pre-field-split output for exact style/height/baseline comparison")
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    if (not args.source.is_file() or (args.hwpx and not args.hwpx.is_file())
        or (args.before_hwpx and not args.before_hwpx.is_file())):
        print("MISSING: source or requested HWPX"); return 2
    folder = args.artifacts or Path(RUNTIME.name)
    folder.mkdir(parents=True, exist_ok=True)
    oracle = source_oracle(args.source)
    frozen = {**oracle, "images": [{key: value for key, value in image.items() if key != "payload"} for image in oracle["images"]]}
    (folder / "source-oracle.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    return actual(oracle, args.hwpx, folder, args.before_hwpx) if args.hwpx else 0


if __name__ == "__main__":
    raise SystemExit(main())
