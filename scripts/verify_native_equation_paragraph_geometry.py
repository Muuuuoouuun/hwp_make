"""Reject false math matches; measure rendered paragraph gaps and edited boxes."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import zipfile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pdf_equation_measurements import joined_equation_metrics
from app.pdf_source_line_cache import apply_source_line_cache
from app.hwpx_writer_v2 import write_hwpx
from app.pdf_native_content import annotate_question_groups
from app.pdf_question_geometry import inspect_question_geometry
from scripts.verify_native_equation_source_font import span
from scripts.verify_native_question_edit_reflow import verify as verify_edit
import rhwp

H = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
S = "{http://www.w3.org/2000/svg}"


def split_formula(x=120, y=100):
    result = []
    for text, width in [("(", 4), ("4+i", 19), (")", 4), ("+", 8),
                        ("(", 4), ("1-2i", 25), (")", 4)]:
        result.append(span(text, x, y, 10, "HyhwpEQ", width))
        x += width
    return result


def verify_matches_and_cache():
    formula = "(4+i)+(1-2i)"
    pieces = split_formula()
    assert joined_equation_metrics([{"spans": pieces}], {formula})[formula] == [(10, 68)]
    for kind in ("gap", "prose", "operator", "missing", "unsupported"):
        bad = deepcopy(pieces)
        if kind == "gap":
            bad[3]["bbox"] = (220, 90, 228, 102)
        elif kind == "prose":
            bad[3]["font"] = "Helvetica"
        elif kind == "operator":
            bad[3]["text"] = "-"
        elif kind == "missing":
            bad.pop(3)
        else:
            bad[1]["text"] = r"\frac{"
        assert formula not in joined_equation_metrics([{"spans": bad}], {formula}), kind

    p = etree.Element(H + "p")
    run = etree.SubElement(p, H + "run")
    etree.SubElement(run, H + "t").text = "가😀 "
    eq = etree.SubElement(run, H + "equation")
    etree.SubElement(eq, H + "script").text = formula
    etree.SubElement(run, H + "t").text = "의 값 다음 문장"
    first_spans = [span("가😀 ", 40, 100, 10, "Helvetica", 80), *pieces,
                   span("의 값", 190, 100, 10, "Helvetica", 20)]
    layout = {"source_page_width_pt": 595.28, "column_left_pt": 40,
              "source_typography": {"font_size_pt": 10, "lines": [
                  {"text": "", "baseline_pt": 100, "bbox_pt": [40, 89, 210, 104], "spans": first_spans},
                  {"text": "다음 문장", "baseline_pt": 117, "bbox_pt": [40, 108, 90, 120],
                   "spans": [span("다음 문장", 40, 117, 10, "Helvetica", 50)]},
              ]}}
    assert apply_source_line_cache(p, layout, 25000)
    lines = p.findall(H + "linesegarray/" + H + "lineseg")
    assert [int(n.get("textpos")) for n in lines] == [0, 16], "UTF-16 plus eight-unit equation anchor"
    assert [int(n.get("vertpos")) + int(n.get("baseline")) for n in lines] == [1100, 2800]
    assert len(list(p.iter(H + "p"))) == 1 and not list(p.iter(H + "lineBreak"))
    saved = etree.tostring(p)
    for kind in ("operator", "unsupported", "split_equation", "overlap"):
        bad = deepcopy(layout)
        records = bad["source_typography"]["lines"]
        if kind == "operator":
            records[0]["spans"][4]["text"] = "-"
        elif kind == "unsupported":
            records[0]["spans"][2]["text"] = r"\frac{"
        elif kind == "split_equation":
            records[1]["spans"] = records[0]["spans"][4:] + records[1]["spans"]
            records[0]["spans"] = records[0]["spans"][:4]
        else:
            records[1]["bbox_pt"][1] = 100
        assert not apply_source_line_cache(p, bad, 25000), kind
        assert etree.tostring(p) == saved, "rejected evidence mutated the paragraph"
    braces = deepcopy(p)
    braces.find(".//" + H + "script").text = "x^{a+b}"
    bad = deepcopy(layout)
    bad["source_typography"]["lines"][0]["spans"] = [first_spans[0],
        span("x^{a}+b", 120, 100, 10, "HyhwpEQ", 68), first_spans[-1]]
    assert not apply_source_line_cache(braces, bad, 25000), "grouping braces carry meaning"
    print("PASS: exact complete equations, UTF-16 boundaries, varying ascenders; mismatched evidence rejected")


def metadata(lines):
    records = []
    for spans in lines:
        records.append({"text": "".join(s["text"] for s in spans), "spans": spans,
                        "baseline_pt": spans[0]["origin"][1],
                        "bbox_pt": [min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
                                    max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans)]})
    return {"font_name": "Helvetica", "font_size_pt": 10, "alignment": "LEFT",
            "line_spacing_pt": 14, "lines": records,
            "source_bbox_pt": [40, records[0]["bbox_pt"][1], 270, records[-1]["bbox_pt"][3]]}


def verify_rendered_spacing():
    first = "1. Evaluate $(4+i)+(1-2i)$."
    body = ["Read all the conditions before choosing an answer.",
            "Keep this complete paragraph editable after saving."]
    metas = [metadata([[span("1. Evaluate ", 40, 100, 10, "Helvetica", 80), *split_formula(),
                       span(".", 188, 100, 10, "Helvetica", 3)]]),
             metadata([[span(text, 40, 160 + i * 14, 10, "Helvetica", 230)] for i, text in enumerate(body)])]
    items = [{"stem": stem, "source_page": 1,
              "layout": {"source_content": True, "source_column": 1,
                         "column_left_pt": 40, "source_page_width_pt": 595.28,
                         "source_typography": meta}}
             for stem, meta in zip([first, " ".join(body)], metas)]
    annotate_question_groups(items)
    with tempfile.TemporaryDirectory(prefix="equation_paragraph_geometry_") as directory:
        folder = Path(directory)
        path = folder / "paragraphs.hwpx"
        write_hwpx(path, "Math geometry", items, "kice_math", native_math=True, preserve_source_layout=True)
        with zipfile.ZipFile(path) as z:
            root = etree.fromstring(z.read("Contents/section0.xml"))
        draw = root.find(".//" + H + "drawText")
        assert len(draw.find(H + "subList").findall(H + "p")) == 2
        eq = draw.find(".//" + H + "equation")
        scale = float(root.find(".//" + H + "pagePr").get("width")) / 595.28
        assert abs(int(eq.find(H + "sz").get("width")) - 68 * scale) <= 1
        render = rhwp.parse(str(path))
        svg = etree.fromstring(render.render_svg(0).encode())
        text = [n for n in svg.iter(S + "text") if n.text and n.get("y")]
        # The renderer may emit justified words as individual glyph nodes.
        start = next(n for n in text if n.text.startswith("1"))
        following = next(n for n in text if n.text.startswith("R"))
        gap = float(following.get("y")) - float(start.get("y"))
        assert abs(gap - 60 * scale / 75) < .2, (gap, 60 * scale / 75)
        assert inspect_question_geometry(draw)["ok"]
        broken = deepcopy(draw.getparent())
        broken.find(H + "sz").set("height", "3500")
        broken.find(H + "drawText/" + H + "subList").set("textHeight", "3500")
        assert not inspect_question_geometry(broken.find(H + "drawText"))["ok"], "blank spacing must fit too"
        edit_folder = folder / "edit"
        edit_folder.mkdir()
        verify_edit(path, edit_folder)
        print(f"PASS: rendered baseline gap {gap:.3f}px; full paragraphs, growing box and +155-character re-save")


if __name__ == "__main__":
    verify_matches_and_cache()
    verify_rendered_spacing()
    print("NATIVE_EQUATION_PARAGRAPH_GEOMETRY_OK")
