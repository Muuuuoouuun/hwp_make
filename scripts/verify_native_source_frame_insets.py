"""Source-vector frame inset and public edit/save regression."""
# ruff: noqa: E402
import argparse
from copy import deepcopy
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="source_frame_insets_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name
import fitz
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_source_frame_geometry import restore_source_prose_frame_position, source_flow_prose_frame_table
from app.pdf_question_rendering import IDENTITY, _multiply, _transform
from hwpx.oxml import HwpxOxmlParagraph

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SVG = "{http://www.w3.org/2000/svg}"
TEXT = ["A complete measured frame keeps its words.",
        "The next line belongs to the same paragraph.",
        "Its inset must survive an ordinary text edit."]
ADDITION = " More editable words extend this paragraph and grow the frame naturally. " * 7


def compact(value):
    return re.sub(r"\s+", "", value)


def package(path):
    with zipfile.ZipFile(path) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if re.fullmatch(r"Contents/section\d+\.xml", name)]
    return roots, header


def frame(path, prefix):
    roots, header = package(path)
    matches = [(root, table) for root in roots for table in root.iter(HP + "tbl")
               if compact("".join(table.itertext())).startswith(compact(prefix))]
    assert len(matches) == 1, (prefix, len(matches))
    return *matches[0], header


def visible_edges(path, page, x, y, width, height):
    doc = rhwp.parse(str(path))
    svg = etree.fromstring(doc.render_svg(page).encode())
    lines = [tuple(float(node.get(k)) for k in ("x1", "y1", "x2", "y2"))
             for node in svg.iter(SVG + "line") if node.get("stroke") != "none"]
    if y is None:
        tops = [b for a, b, c, d in lines if abs(a - x) < .15 and abs(c - x - width) < .15 and abs(b - d) < .15]
        y = next((top for top in tops if any(abs(other - top - height) < .15 for other in tops)), None)
        assert y is not None, "measured frame rails/height are absent"
    expected = [(x, y, x + width, y), (x, y + height, x + width, y + height),
                (x, y, x, y + height), (x + width, y, x + width, y + height)]
    for edge in expected:
        assert any(max(abs(a - b) for a, b in zip(edge, line)) < .15 for line in lines), (edge, lines[:10])
    return y


def source_bounds(layout, paper_width):
    box = layout["native_tables"][0]["bbox_pt"]
    scale = paper_width / layout["source_page_width_pt"] / 75
    return tuple(v * scale for v in (box[0], box[1], box[2] - box[0], box[3] - box[1]))


def synthetic(folder):
    source, output = folder / "inset.pdf", folder / "inset.hwpx"
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((160, 40), "English source frames")
        page.insert_text((40, 95), "1. Read the measured framed passage.", fontsize=10)
        page.draw_rect(fitz.Rect(50, 120, 265, 190), width=.5)
        for index, text in enumerate(TEXT):
            page.insert_text((60, 140 + index * 15), text, fontsize=10)
        page.insert_text((40, 220), "Following content must move below a growing frame.", fontsize=10)
        page.insert_text((310, 95), "2. Choose another description.", fontsize=10)
        document.save(source)
    write_pdf_structured_hwpx(source, output, native_math=True)
    root, table, header = frame(output, TEXT[0])
    assert source_flow_prose_frame_table(table, root, source)
    position = table.find(HP + "pos")
    assert position.get("treatAsChar") == "0" and position.get("vertRelTo") == "PARA"
    assert position.get("flowWithText") == "1" and position.get("allowOverlap") == "0"
    items, _ = extract_native_content(source)
    layout = next(item["layout"] for item in items if TEXT[0] in str(item.get("tables", [])))
    paper_width = float(root.find(".//" + HP + "pagePr").get("width"))
    x, _, width, height = source_bounds(layout, paper_width)
    rendered_top = visible_edges(output, 0, x, None, width, height)
    # Neither a name nor plausible-looking dimensions authorize a false frame.
    for kind in ("text", "offset", "height", "overlap", "page-anchor"):
        bad = deepcopy(table)
        if kind == "text":
            next(bad.iter(HP + "t")).text += " forged"
        elif kind in ("offset", "height"):
            node, attr = (bad.find(HP + "pos"), "horzOffset") if kind == "offset" else (bad.find(HP + "sz"), "height")
            node.set(attr, str(float(node.get(attr)) + 100))
        else:
            bad.find(HP + "pos").set("allowOverlap" if kind == "overlap" else "vertRelTo", "1" if kind == "overlap" else "PAPER")
        assert not source_flow_prose_frame_table(bad, root, source), kind
    for kind in ("source-text", "native-text", "bounds"):
        bad_layout, bad_table = deepcopy(layout), deepcopy(table)
        if kind == "source-text":
            bad_layout["native_tables"][0]["source_frame_text"] += "forged"
        elif kind == "native-text":
            next(bad_table.iter(HP + "t")).text += "forged"
        else:
            bad_layout["native_tables"][0]["bbox_pt"][2] += 500
        before = etree.tostring(bad_table)
        assert not restore_source_prose_frame_position(bad_table, bad_layout, paper_width, 247 * paper_width / 595)
        assert etree.tostring(bad_table) == before
    # A complete source frame on the column rail needs the same paragraph
    # flow as an inset frame. A subpixel source border overhang is clamped;
    # negative output coordinates and a larger displacement remain invalid.
    source_left = layout["native_tables"][0]["bbox_pt"][0] * paper_width / layout["source_page_width_pt"]
    for delta, expected in ((0, True), (30, True), (60, False)):
        rail_root = deepcopy(root)
        rail_table = next(t for t in rail_root.iter(HP + "tbl")
                          if compact("".join(t.itertext())).startswith(compact(TEXT[0])))
        page = rail_root.find(".//" + HP + "pagePr")
        margin = page.find(HP + "margin")
        margin.set("left", str(source_left + delta))
        gap = float(next(rail_root.iter(HP + "colPr")).get("sameGap"))
        column_width = (paper_width - float(margin.get("left")) - float(margin.get("right")) - gap) / 2
        before = etree.tostring(rail_table)
        assert restore_source_prose_frame_position(rail_table, layout, paper_width, column_width) is expected, delta
        if expected:
            assert rail_table.find(HP + "pos").get("horzOffset") == "0"
            assert source_flow_prose_frame_table(rail_table, rail_root, source)
            negative = deepcopy(rail_table)
            negative.find(HP + "pos").set("horzOffset", "-1")
            assert not source_flow_prose_frame_table(negative, rail_root, source)
            margin.set("left", str(source_left + 100))
            assert not source_flow_prose_frame_table(rail_table, rail_root, source), "forged zero rail"
        else:
            assert etree.tostring(rail_table) == before
    old_size = dict(table.find(HP + "sz").attrib)
    old_offset = position.get("horzOffset")
    p = next(table.iter(HP + "p"))
    doc = HwpxDocument.open(output)
    candidate = next(q for section in doc.sections for q in section.element.iter(HP + "p") if q.get("id") == p.get("id"))
    public = HwpxOxmlParagraph(candidate, doc.sections[0])
    original = public.text
    public.text += ADDITION
    edited = folder / "inset-edited.hwpx"
    doc.save_to_path(edited)
    eroot, etable, _ = frame(edited, TEXT[0])
    assert compact("".join(etable.itertext())) == compact(original + ADDITION)
    assert etable.find(HP + "pos").get("horzOffset") == old_offset
    assert etable.find(HP + "sz").get("width") == old_size["width"]
    assert float(etable.find(HP + "sz").get("height")) > float(old_size["height"])
    painted_svg = etree.fromstring(rhwp.parse(str(edited)).render_svg(0).encode())
    painted = "".join("".join(node.itertext()) for node in painted_svg.iter(SVG + "text"))
    assert compact(original + ADDITION) in compact(painted), "edited frame words are missing in native render"
    visible_edges(edited, 0, x, rendered_top, width, float(etable.find(HP + "sz").get("height")) / 75)
    glyphs, baselines = [], []
    for node in painted_svg.iter(SVG + "text"):
        matrix = IDENTITY
        for ancestor in [*reversed(list(node.iterancestors())), node]:
            matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
        baseline = matrix[1] * float(node.get("x", 0)) + matrix[3] * float(node.get("y", 0)) + matrix[5]
        text = compact("".join(node.itertext()))
        glyphs.extend(text)
        baselines.extend([baseline] * len(text))
    index = "".join(glyphs).index("Followingcontentmustmovebelowagrowingframe.")
    assert baselines[index] > rendered_top + float(etable.find(HP + "sz").get("height")) / 75, "edited frame overlaps following prose"
    again = folder / "inset-edited-reopened.hwpx"
    HwpxDocument.open(edited).save_to_path(again)
    _, twice, _ = frame(again, TEXT[0])
    assert etree.tostring(etable) == etree.tostring(twice), "second save changed source frame flow"
    print("PASS synthetic: source vector inset, full-text/geometry negatives, public edit growth and re-save")


def real(folder, existing=None):
    source = ROOT / "data/external_exam_qa/2026_csat/문제지/영어/영어.pdf"
    if not source.is_file():
        return False
    output = existing or folder / "csat.hwpx"
    if existing is None:
        write_pdf_structured_hwpx(source, output, native_math=True)
    roots, _ = package(output)
    items, _ = extract_native_content(source, area_hint="영어 영역")
    cases = [(item, item["layout"]) for item in items if item.get("source_page") in (7, 15)
             and len(item["layout"].get("native_tables", [])) == 1
             and item["layout"]["native_tables"][0].get("source_prose_frame")]
    assert len(cases) == 10, len(cases)
    document = rhwp.parse(str(output))
    assert document.page_count == 16
    vertical_deltas = []
    for item, layout in cases:
        prefix = compact(layout["native_tables"][0]["source_frame_text"])
        matches = [(root, table) for root in roots for table in root.iter(HP + "tbl")
                   if compact("".join(table.itertext())) == prefix]
        # Identical passages legitimately appear in both odd/even variants.
        assert len(matches) == 2, (prefix[:40], len(matches))
        root, table = matches[0]
        assert all(source_flow_prose_frame_table(t, r, source) for r, t in matches)
        paper_width = float(root.find(".//" + HP + "pagePr").get("width"))
        x, source_y, width, height = source_bounds(layout, paper_width)
        # This regression restores the horizontal source rail. Its vertical
        # location remains ordinary paragraph flow, including after an edit.
        rendered_y = visible_edges(output, item["source_page"] - 1, x, None, width, height)
        vertical_deltas.append(abs(rendered_y - source_y))
    print("PASS real CSAT: both variants Q37/38/39/40 main+summary, ten actual four-rule frame rails, 16 pages; "
          f"observed vertical flow delta max={max(vertical_deltas):.3f}px")
    return True


def shared_rail(folder):
    """A shared frame on the rail keeps its real before-gap and native flow."""
    from app.pdf_source_spacing import _complete_source_flow_frame, apply_source_flow_spacing
    from hwpx.tools.paragraph_spacing import paragraph_spacing

    source, output = folder / "zero-shared-english.pdf", folder / "zero-shared.hwpx"
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((160, 40), "2026학년도 시험 문제지", fontname="korea", fontsize=16)
        page.insert_text((240, 75), "영어 영역", fontname="korea", fontsize=20)
        page.draw_line((40, 100), (555, 100), width=.5)
        page.insert_text((40, 140), "[1~2] Read the shared framed passage.", fontsize=10)
        page.draw_rect(fitz.Rect(40, 165, 265, 235), width=.5)
        for index, text in enumerate(TEXT):
            page.insert_text((50, 185 + index * 15), text, fontsize=10)
        page.insert_text((40, 265), "1. Following content stays below this shared frame.", fontsize=10)
        page.insert_text((310, 140), "2. Choose another description.", fontsize=10)
        document.save(source)
    write_pdf_structured_hwpx(source, output, native_math=True)
    root, table, header = frame(output, TEXT[0])
    assert table.find(HP + "pos").get("horzOffset") == "0"
    assert source_flow_prose_frame_table(table, root, source)
    items, _ = extract_native_content(source)
    layout = next(item["layout"] for item in items if TEXT[0] in str(item.get("tables", [])))
    owner = table.getparent().getparent()
    preceding = owner.getprevious()
    layout = {**layout, "source_page": 1}
    assert _complete_source_flow_frame(owner, [layout])
    styles = {p.get("id"): p for p in header.iter(HH + "paraPr")}
    assert paragraph_spacing(owner, styles)[0] == 0
    assert paragraph_spacing(preceding, styles)[1] > 0, "table before-gap was not placed after preceding prose"
    page_width = float(root.find(".//" + HP + "pagePr").get("width"))
    x, y, width, height = source_bounds(layout, page_width)
    rendered_y = visible_edges(output, 0, x, None, width, height)
    # Reverse only the gap's location to reproduce the old paint-anchor bug.
    # Both packages reserve the same total flow, while the source-derived gap
    # must move the painted frame by exactly that amount.
    from app.pdf_source_spacing import set_space_before, set_space_after
    old_root, old_header = deepcopy(root), deepcopy(header)
    old_owner = next(p for p in old_root.findall(HP + "p") if p.get("id") == owner.get("id"))
    gap = paragraph_spacing(preceding, styles)[1]
    set_space_after(old_owner.getprevious(), old_header, 0)
    set_space_before(old_owner, old_header, gap)
    old_output = folder / "zero-shared-old-gap.hwpx"
    with zipfile.ZipFile(output) as original, zipfile.ZipFile(old_output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in original.namelist():
            content = (etree.tostring(old_header) if name == "Contents/header.xml" else
                       etree.tostring(old_root) if name == "Contents/section0.xml" else original.read(name))
            archive.writestr(name, content)
    old_y = visible_edges(old_output, 0, x, None, width, height)
    assert abs(rendered_y - old_y - gap / 75) < .15, "source gap was reserved but omitted from the painted frame anchor"
    from app.pdf_native_typography import _flow_height
    old_styles = {p.get("id"): p for p in old_header.iter(HH + "paraPr")}
    assert sum(_flow_height(p) + sum(paragraph_spacing(p, styles)) for p in (preceding, owner)) == sum(
        _flow_height(p) + sum(paragraph_spacing(p, old_styles)) for p in (old_owner.getprevious(), old_owner)
    ), "relocating the gap changed the total flow height"
    # A second spacing pass uses newly allocated style IDs without adding the
    # same gap again. The whole flow sum and the original gap remain stable.
    prefix_layout = next(item["layout"] for item in items if str(item.get("stem", "")).startswith("[1~2]"))
    prefix_layout = {**prefix_layout, "source_page": 1}
    def total():
        styles = {p.get("id"): p for p in header.iter(HH + "paraPr")}
        return sum(_flow_height(p) + sum(paragraph_spacing(p, styles)) for p in (preceding, owner))
    # The final writer has already changed section margins for its masthead.
    # Establish this section's current origin before checking repeated passes.
    apply_source_flow_spacing(root, [preceding, owner], [[prefix_layout], [layout]], header)
    before = total()
    apply_source_flow_spacing(root, [preceding, owner], [[prefix_layout], [layout]], header)
    assert abs(total() - before) < 1, "a repeated spacing pass changed the total source flow"
    assert paragraph_spacing(owner, {p.get("id"): p for p in header.iter(HH + "paraPr")})[0] == 0
    for field in ("source_frame_text", "source_prose_frame"):
        bad = deepcopy(layout)
        bad["native_tables"][0][field] = "forged" if field == "source_frame_text" else False
        assert not _complete_source_flow_frame(owner, [bad]), field
    assert not _complete_source_flow_frame(owner, [layout, layout]), "wrapped questions must keep their own spacing"
    print("PASS synthetic zero rail: actual shared-frame gap, independent vector proof, repeated style-ID spacing, ordinary-table/fulltext negatives")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--csat-hwpx", type=Path)
    args = parser.parse_args()
    folder = Path(RUNTIME.name)
    synthetic(folder)
    shared_rail(folder)
    if not args.synthetic_only and not real(folder, args.csat_hwpx):
        print("MISSING_SOURCE: actual CSAT English PDF required")
        return 2
    print("NATIVE_SOURCE_FRAME_INSETS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
