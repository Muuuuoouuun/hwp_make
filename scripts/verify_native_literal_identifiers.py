"""Real PDF identifiers, native paragraph edits, and corrupted-package rejection."""
# ruff: noqa: E402
from pathlib import Path
import argparse
import json
import os
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(folder):
    os.environ["HWP_MAKE_DATA_DIR"] = str(folder / "runtime")
    import fitz
    from lxml import etree
    import rhwp
    from app.math_text import split_math_text
    from app.pdf_layout_writer import write_pdf_structured_hwpx
    from app.pdf_editability import inspect_pdf_editability
    from app.pdf_question_rendering import _visible_svg_text, inspect_question_rendering
    from app.hwpx_writer_v2 import HwpxDocument
    from hwpx.oxml import HwpxOxmlParagraph
    from hwpx.tools.package_validator import validate_package

    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    for text in ("ITEM_01 is plain text.", "Use file_name and output_2026_report.",
                 "Rename USER_02 to USER_03."):
        assert split_math_text(text) == [(text, False)], text
    for formula in ("x_1", "AB_1", "log_2", "$ITEM_01$", r"\alpha_1", r"\beta_2", r"\frac{ITEM_01}{x_1}"):
        assert split_math_text(formula) == [(formula, True)], formula
    assert split_math_text("ITEM_01 + x_1") == [("ITEM_01 + ", False), ("x_1", True)]

    source, native = folder / "source.pdf", folder / "native.hwpx"
    lines = ["1. Keep ITEM_01 and file_name in this paragraph.",
             "The output_2026_report has the original values.",
             "Every word on these lines remains fully editable.",
             "They belong to one continuous native paragraph."]
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((145, 38), "Literal identifier paragraph")
        for i, text in enumerate(lines):
            page.insert_text((40, 110 + 14 * i), text, fontsize=10)
        page.insert_text((40, 185), "The second ITEM_01 occurrence must remain.", fontsize=10)
        page.insert_text((310, 110), "2. Another ordinary paragraph.", fontsize=10)
        pdf.save(source)
    stats = write_pdf_structured_hwpx(source, native, native_math=True)
    audit = inspect_pdf_editability(source, native, stats["image_provenance"], require_question_boxes=True)
    assert audit["ok"], audit
    assert audit["literal_identifiers"]["source_identifiers"] == {
        "ITEM_01": 2, "file_name": 1, "output_2026_report": 1,
    }, audit["literal_identifiers"]
    assert audit["paragraph_flow"]["source_wrap_pairs_checked"] >= 2, audit["paragraph_flow"]

    def visible(path):
        rendered = rhwp.parse(str(path))
        return "".join(_visible_svg_text(rendered.render_svg(i))[0] for i in range(rendered.page_count))

    def check(path, expected):
        assert inspect_question_rendering(path, rhwp)["ok"]
        package = validate_package(path)
        assert package.ok, package
        text = visible(path)
        assert all(name in text for name in expected), (expected, text)
        with zipfile.ZipFile(path) as archive:
            root = etree.fromstring(archive.read("Contents/section0.xml"))
        assert not list(root.iter(hp + "equation")), "literal became an equation"
        return root

    before = check(native, audit["literal_identifiers"]["source_identifiers"])
    paragraphs = [p for p in before.iter(hp + "p")
                  if lines[0] in "".join(t.text or "" for t in p.findall(hp + "run/" + hp + "t"))]
    assert len(paragraphs) == 1
    assert all(line in "".join(paragraphs[0].itertext()) for line in lines)
    assert not list(paragraphs[0].iter(hp + "lineBreak"))
    assert len(paragraphs[0].findall(hp + "linesegarray/" + hp + "lineseg")) >= 3

    doc = HwpxDocument.open(native)
    section = doc.sections[0]
    node = next(p for p in section.element.iter(hp + "p")
                if lines[0] in "".join(t.text or "" for t in p.findall(hp + "run/" + hp + "t")))
    paragraph = HwpxOxmlParagraph(node, section)
    paragraph.text = paragraph.text.replace("ITEM_01", "ITEM_02") + " An additional sentence extends this editable paragraph." * 3
    edited = folder / "edited.hwpx"
    doc.save_to_path(edited)
    after = check(edited, ["ITEM_02", "ITEM_01", "file_name", "output_2026_report"])
    assert len(list(before.iter(hp + "p"))) == len(list(after.iter(hp + "p")))
    changed = next(p for p in after.iter(hp + "p")
                   if "ITEM_02" in "".join(t.text or "" for t in p.findall(hp + "run/" + hp + "t")))
    assert not list(changed.iter(hp + "lineBreak"))
    assert len(changed.findall(hp + "linesegarray/" + hp + "lineseg")) > len(paragraphs[0].findall(hp + "linesegarray/" + hp + "lineseg"))
    resaved = folder / "resaved.hwpx"
    HwpxDocument.open(edited).save_to_path(resaved)
    check(resaved, ["ITEM_02", "ITEM_01", "file_name", "output_2026_report"])
    assert visible(resaved) == visible(edited)

    rejected = {}
    for corruption in ("delete_underscore", "change_suffix", "equation_instead_of_text", "delete_second_occurrence"):
        mutant = folder / (corruption + ".hwpx")
        with zipfile.ZipFile(native) as archive, zipfile.ZipFile(mutant, "w") as output:
            root = etree.fromstring(archive.read("Contents/section0.xml"))
            candidates = [t for t in root.iter(hp + "t") if "ITEM_01" in (t.text or "")]
            t = candidates[-1 if corruption == "delete_second_occurrence" else 0]
            if corruption == "equation_instead_of_text":
                leading, trailing = t.text.split("ITEM_01", 1)
                t.text = leading
                equation = etree.Element(hp + "equation")
                etree.SubElement(equation, hp + "script").text = "ITEM_01"
                t.addnext(equation)
                tail = etree.Element(hp + "t")
                tail.text = trailing
                equation.addnext(tail)
            else:
                replacement = {"delete_underscore": "ITEM01", "change_suffix": "ITEM_99", "delete_second_occurrence": ""}[corruption]
                t.text = t.text.replace("ITEM_01", replacement, 1)
            for info in archive.infolist():
                output.writestr(info, etree.tostring(root) if info.filename == "Contents/section0.xml" else archive.read(info.filename))
        bad = inspect_pdf_editability(source, mutant, stats["image_provenance"], require_question_boxes=True)
        assert not bad["ok"] and "native_source_literal_identifier_missing" in bad["issues"], (corruption, bad)
        rejected[corruption] = bad["literal_identifiers"]
    report = {"ok": True, "literal_audit": audit["literal_identifiers"],
              "source_wrap_pairs": audit["paragraph_flow"]["source_wrap_pairs_checked"],
              "paragraph_edit_and_resave": True, "rejected_corruptions": rejected}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("NATIVE_LITERAL_IDENTIFIERS_OK: " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        verify(args.output_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="native_literal_identifiers_") as temporary:
            verify(Path(temporary))
