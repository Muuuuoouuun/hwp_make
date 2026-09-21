"""Exercise the public paragraph setter/save path and its actual rendered bounds."""

from pathlib import Path
from collections import Counter
import hashlib, io, re, sys, tempfile, zipfile
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from app.hwpx_writer_v2 import HwpxDocument, write_hwpx
from app.pdf_native_content import annotate_question_groups
from app.pdf_question_geometry import inspect_question_geometry
from hwpx.oxml import HwpxOxmlParagraph
import rhwp

H = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
S = "{http://www.w3.org/2000/svg}"


def state(path):
    with zipfile.ZipFile(path) as z:
        root = etree.Element("sections")
        for name in sorted(z.namelist()):
            if re.fullmatch(r"Contents/section\d+\.xml", name):
                root.append(etree.fromstring(z.read(name)))
        media = Counter(
            hashlib.sha256(z.read(n)).hexdigest()
            for n in z.namelist()
            if n.startswith("BinData/")
        )
    return root, media


def verify(path, folder, sideflow=False, table_cells=False, section_index=None, question_id=None):
    before, images = state(path)
    doc = HwpxDocument.open(path)
    candidates = []
    sections = doc.sections if section_index is None else [doc.sections[section_index]]
    for section, box in ((section, box) for section in sections for box in section.element.iter(H + "drawText")):
        if question_id is not None and box.get("name") != question_id:
            continue
        nodes = box.find(H + "subList").findall(H + "p")
        if table_cells:
            nodes = [p for cell in box.iter(H + "tc")
                     for p in cell.find(H + "subList").findall(H + "p")]
        if sideflow:
            nodes = [
                p
                for cell in box.iter(H + "tc")
                if cell.get("name", "").startswith("source-sideflow:")
                and cell.get("name", "").endswith(":text")
                for p in cell.find(H + "subList").findall(H + "p")
            ]
        for node in nodes:
            p = HwpxOxmlParagraph(node, section)
            if len(p.text) > (20 if sideflow else 60) and not any(
                node.findall(".//" + H + tag) for tag in ("pic", "tbl", "equation")
            ):
                candidates.append((len(p.text), p, box, section))
    _, paragraph, box, section = max(candidates, key=lambda x: x[0])
    identifier = box.get("name")
    page_pr = section.element.find(".//" + H + "pagePr")
    margin = page_pr.find(H + "margin")
    columns = next(c for c in section.element.iter(H + "colPr") if c.get("colCount") == "2")
    page_width = float(page_pr.get("width")) / 75
    left, right, top, bottom = (float(margin.get(edge)) / 75 for edge in ("left", "right", "top", "bottom"))
    top += float(margin.get("header", "0")) / 75
    bottom += float(margin.get("footer", "0")) / 75
    gap = float(columns.get("sameGap")) / 75
    column_width = (page_width - left - right - gap) / 2
    rails = [(left, left + column_width), (left + column_width + gap, page_width - right)]
    middle = (rails[0][1] + rails[1][0]) / 2
    body_bottom = (float(page_pr.get("height")) / 75) - bottom
    before_text = paragraph.text
    cell_width = None
    if sideflow or table_cells:
        cell_width = (
            int(
                paragraph.element.getparent()
                .getparent()
                .find(H + "cellSz")
                .get("width")
            )
            / 75
        )
    old_height = int(box.getparent().find(H + "sz").get("height"))
    addition = (
        " 편집 검증을 위해 조건을 추가합니다. 추가 조건을 읽고 답을 다시 판단하십시오."
        * 3
        + " EDIT_REFLOW_END_QA0"
    )
    paragraph.text = before_text + addition
    target = folder / "edited.hwpx"
    doc.save_to_path(target)
    after, new_images = state(target)
    assert all(inspect_question_geometry(draw)["ok"] for draw in after.iter(H + "drawText")), "edited container is smaller than its native content"
    edited = after.find(f'.//{H}drawText[@name="{identifier}"]')
    assert (
        int(edited.getparent().find(H + "sz").get("height")) > old_height
    ), "question height did not grow"
    assert len(list(before.iter(H + "drawText"))) == len(
        list(after.iter(H + "drawText"))
    ), "question split"
    assert images == new_images, "pictures changed"
    assert [e.text for e in before.iter(H + "script")] == [
        e.text for e in after.iter(H + "script")
    ], "equations changed"
    edited_p = next(
        p
        for p in edited.iter(H + "p")
        if "EDIT_REFLOW_END"
        in "".join(t.text or "" for t in p.findall(H + "run/" + H + "t"))
    )
    assert (
        len(edited_p.findall(H + "linesegarray/" + H + "lineseg")) > 1
    ), "edited paragraph has no wrapping cache"
    assert len(list(before.iter(H + "p"))) == len(
        list(after.iter(H + "p"))
    ), "text was split into more paragraphs"
    render = rhwp.parse(str(target))
    tokens = []
    for page in range(render.page_count):
        root = etree.fromstring(render.render_svg(page).encode())
        for node in root.iter(S + "text"):
            match = re.search(
                r"translate\(([-\d.]+),([-\d.]+)\)", node.get("transform", "")
            )
            if match:
                x, y = map(float, match.groups())
            elif (
                node.get("x")
                and node.get("y")
                and node.getparent().get("transform") is None
            ):
                x, y = float(node.get("x")), float(node.get("y"))
            else:
                continue
            tokens.extend(
                (char, page, x, y)
                for char in "".join(node.itertext())
                if not char.isspace()
            )
    text = "".join(t[0] for t in tokens)
    expected = re.sub(r"\s+", "", before_text + addition)
    position = text.find(expected)
    assert position >= 0, "edited sentence is absent from the renderer"
    used = tokens[position : position + len(expected)]
    assert (
        len({(p, x > middle) for _, p, x, y in used}) == 1
    ), "one question sentence crosses a page/column"
    assert all(
        any(a - 1 <= x <= b + 1 for a, b in rails) and top - 1 <= y <= body_bottom + 1
        for _, p, x, y in used
    ), "edited glyph is outside its printable column"
    if cell_width is not None:
        assert (
            max(t[2] for t in used) - min(t[2] for t in used) < cell_width
        ), "edited prose crossed its figure cell"
    # Re-saving must neither grow the shape again nor erase regenerated caches.
    second = folder / "edited_twice.hwpx"
    doc.save_to_path(second)
    again, _ = state(second)
    assert etree.tostring(after) == etree.tostring(
        again
    ), "second save changes stable layout"
    print(
        f"PASS: {path.name} ({'sideflow' if sideflow else 'body'}): +{len(addition)} chars, one paragraph/box, visible bounded glyphs, images and equations preserved"
    )


def main():
    with tempfile.TemporaryDirectory(prefix="native_edit_reflow_") as temp:
        folder = Path(temp)
        if sys.argv[1:]:
            paths = [Path(p) for p in sys.argv[1:]]
        else:
            item = {
                "stem": "1. "
                + "문장의 조건을 읽고 자료와 비교하여 답을 판단하십시오. " * 5,
                "source_page": 1,
                "layout": {
                    "source_content": True,
                    "source_page_width_pt": 842,
                    "source_column": 1,
                    "source_typography": {
                        "font_size_pt": 11.21,
                        "font_name": "HY신명조",
                        "line_spacing_pt": 16.7,
                        "source_column_width_pt": 320,
                    },
                },
            }
            items = [item]
            annotate_question_groups(items)
            path = folder / "fixture.hwpx"
            write_hwpx(
                path,
                "Edit verification",
                items,
                "kice_science",
                native_math=True,
                preserve_source_layout=True,
            )
            paths = [path]
        for i, path in enumerate(paths):
            case = folder / str(i)
            case.mkdir()
            verify(path, case)
            root, _ = state(path)
            if any(
                c.get("name", "").startswith("source-sideflow:")
                for c in root.iter(H + "tc")
            ):
                side = folder / f"{i}_sideflow"
                side.mkdir()
                verify(path, side, sideflow=True)
    print("NATIVE_QUESTION_EDIT_REFLOW_OK")


if __name__ == "__main__":
    main()
