"""Annotated source figures: exact inset/size, real crop, and paragraph reflow."""
# ruff: noqa: E402
from copy import deepcopy
import argparse
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(folder):
    os.environ["HWP_MAKE_DATA_DIR"] = str(folder / "runtime")
    import fitz
    import rhwp
    from lxml import etree
    from PIL import Image, ImageDraw
    from app.pdf_layout_writer import write_pdf_structured_hwpx, _iter_text_lines
    from app.pdf_editability import inspect_pdf_editability
    from app.pdf_figure_labels import include_diagram_labels
    from app.pdf_floating_geometry import inspect_floating_picture
    from app.pdf_question_rendering import inspect_question_rendering, _bounds, _multiply, _transform, IDENTITY
    from app.hwpx_writer_v2 import HwpxDocument
    from hwpx.oxml import HwpxOxmlParagraph
    from hwpx.tools.package_validator import validate_package

    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    sg = "{http://www.w3.org/2000/svg}"
    source, target = folder / "source.pdf", folder / "native.hwpx"
    image = Image.new("RGB", (520, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(3, 3), (3, 356), (516, 356), (3, 3)], fill="black", width=3)
    draw.line([(3, 356), (132, 91), (260, 356)], fill="black", width=3)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    original = fitz.Rect(100, 180, 230, 270)
    prose = ["1. Explain this source diagram and its labels.",
             "This sentence remains editable as a paragraph.",
             "Use all information when solving the problem."]
    positions = {"A": (92, 185), "H": (127, 201), "M": (90, 231),
                 "B": (92, 272), "C": (232, 272), "N": (164, 280)}
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((155, 38), "Annotated source illustration")
        for i, text in enumerate(prose):
            page.insert_text((40, 110 + i * 14), text, fontsize=10)
        page.insert_text((310, 110), "2. Keep this next question editable.", fontsize=10)
        page.insert_image(original, stream=buffer.getvalue())
        for label, position in positions.items():
            page.insert_text(position, label, fontsize=10)
        doc.save(source)

    with fitz.open(source) as doc:
        page = doc[0]
        lines = _iter_text_lines(page)
        figure = {"bbox": original}
        retained = include_diagram_labels(page, [figure], lines)
        assert len(retained) == 6, retained
        expected_region = fitz.Rect(original)
        for line in lines:
            if id(line) in retained:
                expected_region.include_rect(fitz.Rect(line["bbox"]))
        assert figure["bbox"] == expected_region
        for obstruction in ("An editable sentence.", "x+1=2", "1. solve", "① answer"):
            extra = deepcopy(next(line for line in lines if id(line) in retained))
            extra["bbox"] = fitz.Rect(91, 220, 99, 229)
            extra["spans"][0]["text"] = obstruction
            fig = {"bbox": fitz.Rect(original)}
            assert not include_diagram_labels(page, [fig], lines + [extra]), obstruction
            assert fig["bbox"] == original
        assert not include_diagram_labels(page, [{"bbox": original}, {"bbox": original}], lines), "ambiguous figure ownership"
        assert not include_diagram_labels(page, [{"bbox": original}], lines, [expected_region]), "table ownership"

    stats = write_pdf_structured_hwpx(source, target, native_math=True)
    audit = inspect_pdf_editability(source, target, stats["image_provenance"], require_question_boxes=True)
    assert audit["ok"], audit
    assert len(stats["image_provenance"]) == 1 and audit["images"] == 1
    assert not audit["rasterized_prose"]

    def state(path):
        with zipfile.ZipFile(path) as package:
            header = etree.fromstring(package.read("Contents/header.xml"))
            roots = [etree.fromstring(package.read(n)) for n in package.namelist()
                     if n.startswith("Contents/section") and n.endswith(".xml")]
            media = {n: package.read(n) for n in package.namelist() if n.startswith("BinData/")}
        paragraphs = [p for root in roots for p in root.iter(hp + "p")]
        text = lambda p: "".join(t.text or "" for t in p.findall(hp + "run/" + hp + "t"))
        assert not any(text(p).strip() in positions for p in paragraphs), "duplicated label paragraph"
        p = next(p for p in paragraphs if prose[0] in text(p))
        assert all(sentence in text(p) for sentence in prose), "printed lines became separate paragraphs"
        assert not list(p.iter(hp + "lineBreak"))
        picture = next(pic for root in roots for pic in root.iter(hp + "pic"))
        assert inspect_floating_picture(picture, header)["ok"]
        assert inspect_question_rendering(path, rhwp)["ok"]
        package_check = validate_package(path)
        assert package_check.ok and not package_check.warnings, package_check
        rendered = rhwp.parse(str(path))
        boxes = []
        for i in range(rendered.page_count):
            svg = etree.fromstring(rendered.render_svg(i).encode())
            for image in svg.iter(sg + "image"):
                matrix = IDENTITY
                for ancestor in [*reversed(list(image.iterancestors())), image]:
                    matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
                boxes.append(_bounds(matrix, *[float(image.get(k, "0")) for k in ("x", "y", "width", "height")]))
        assert len(boxes) == 1, boxes
        return roots, header, picture, p, boxes[0], media

    roots, header, picture, paragraph, before, media = state(target)
    page_width = float(roots[0].find(".//" + hp + "pagePr").get("width")) / 75
    scale = page_width / 595
    errors = {"x_px": before[0] - expected_region.x0 * scale,
              "width_px": before[2] - before[0] - expected_region.width * scale,
              "height_px": before[3] - before[1] - expected_region.height * scale}
    assert max(map(abs, errors.values())) <= .1, errors
    original_paragraphs = sum(len(list(root.iter(hp + "p"))) for root in roots)
    doc = HwpxDocument.open(target)
    section = doc.sections[0]
    node = next(p for p in section.element.iter(hp + "p") if prose[0] in "".join(t.text or "" for t in p.findall(hp + "run/" + hp + "t")))
    editable = HwpxOxmlParagraph(node, section)
    editable.add_run(" Added evidence extends the same paragraph without splitting its text box." * 3)
    edited = folder / "edited.hwpx"
    doc.save_to_path(edited)
    roots2, _, _, _, after, media2 = state(edited)
    assert after[1] > before[1] + 10, (before, after)
    assert abs(after[0] - before[0]) <= .1 and media2 == media
    assert sum(len(list(root.iter(hp + "p"))) for root in roots2) == original_paragraphs
    resaved = folder / "resaved.hwpx"
    HwpxDocument.open(edited).save_to_path(resaved)
    assert state(resaved)[4:] == (after, media2)

    rejected = {}
    for corruption in ("outside_column", "overlap", "absolute_page_anchor", "no_flow_height", "add_prose"):
        clone = deepcopy(picture.getparent().getparent())
        pic = clone.find(hp + "run/" + hp + "pic")
        pos = pic.find(hp + "pos")
        # Retain the actual containing flow so column width is independently available.
        parent = picture.getparent().getparent().getparent()
        parent.append(clone)
        if corruption == "outside_column": pos.set("horzOffset", "999999")
        elif corruption == "overlap": pos.set("allowOverlap", "1")
        elif corruption == "absolute_page_anchor": pos.set("vertRelTo", "PAGE")
        elif corruption == "no_flow_height": clone.find(hp + "linesegarray/" + hp + "lineseg").set("vertsize", "1")
        else: etree.SubElement(clone.find(hp + "run"), hp + "t").text = "This is native prose."
        bad = inspect_floating_picture(pic, header)
        assert not bad["ok"], corruption
        rejected[corruption] = bad["issues"]
        parent.remove(clone)
    report = {"ok": True, "labels_in_source_figure": sorted(positions), "figure_label_editability": "part of the original figure crop, not separate editable text",
              "source_bbox_pt": list(expected_region), "rendered_bbox_px": before,
              "geometry_errors": errors, "absolute_source_y_error_px": before[1] - expected_region.y0 * scale,
              "absolute_source_y_within_0_1px": abs(before[1] - expected_region.y0 * scale) <= .1,
              "edited_figure_shift_y_px": after[1] - before[1],
              "source_crop_verified": audit["source_images"]["ok"], "rejected_corruptions": rejected}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("NATIVE_DIAGRAM_PARAGRAPHS_OK: " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        verify(args.output_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="native_diagram_paragraphs_") as temporary:
            verify(Path(temporary))
