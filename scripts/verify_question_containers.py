"""Verify whole-question native containers, content conservation and forged splits.

Uses an isolated synthetic PDF by default. Optional --real-folder reads the
three-source audit.json produced by the local visual audit; --baseline-folder
also checks that adding containers preserves the prior native content exactly.
"""

# ruff: noqa: E402 -- isolate engine data before importing the application.
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
RUNTIME = tempfile.TemporaryDirectory(
    prefix="question_containers_", ignore_cleanup_errors=True
)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

import fitz
from lxml import etree
from app import pdf_layout_writer as w, hwpx_writer_v2
from app.pdf_editability import inspect_pdf_editability, _native_text_fraction_scripts
from app.pdf_native_content import annotate_question_groups
from app.pdf_question_markers import QUESTION_START
from scripts.verify_pdf_layout_hwpx import _verify_no_draw_text_equations

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
OPF = "{http://www.idpf.org/2007/opf/}"
QUESTION = QUESTION_START


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def native_state(path):
    texts, scripts, pictures = [], [], Counter()
    with zipfile.ZipFile(path) as package:
        manifest = etree.fromstring(package.read("Contents/content.hpf"))
        hrefs = {
            node.get("id"): node.get("href") for node in manifest.iter(f"{OPF}item")
        }
        for name in sorted(package.namelist()):
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            root = etree.fromstring(package.read(name))
            texts.extend(node.text for node in root.iter(f"{HP}t") if node.text)
            scripts.extend(node.text for node in root.iter(f"{HP}script") if node.text)
            for picture in root.iter(f"{HP}pic"):
                image = picture.find(f".//{HC}img")
                href = hrefs[image.get("binaryItemIDRef")]
                pictures[hashlib.sha256(package.read(href)).hexdigest()] += 1
    return {"texts": Counter(texts), "scripts": Counter(scripts), "pictures": pictures}


def outer_containers(root):
    """Read actual top-level objects; a label by itself cannot create a container."""
    result = []
    for paragraph in root.findall(f"{HP}p"):
        for run in paragraph.findall(f"{HP}run"):
            for obj in run:
                if obj.tag == f"{HP}tbl":
                    cells = obj.findall(f"{HP}tr/{HP}tc")
                    if len(cells) != 1 or not (cells[0].get("name") or "").startswith(
                        "question:"
                    ):
                        continue
                    content = cells[0].find(f"{HP}subList")
                elif obj.find(f".//{HP}drawText") is not None:
                    draw_text = obj.find(f".//{HP}drawText")
                    content = draw_text.find(f"{HP}subList")
                    if content is None:
                        continue
                else:
                    continue
                actual_text = "".join(
                    node.text or "" for node in content.iter(f"{HP}t")
                ).strip()
                marker = QUESTION.match(actual_text)
                if marker:
                    result.append((paragraph, obj, content, int(marker.group(1))))
    return result


def rewrite(source, target, mutate):
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(target, "w") as output:
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename == "Contents/section0.xml":
                root = etree.fromstring(data)
                mutate(root)
                data = etree.tostring(root, encoding="utf-8", xml_declaration=True)
            output.writestr(info, data)


def test_group_boundaries():
    def item(text, page=1, column=0):
        return {"stem": text, "source_page": page, "layout": {"source_column": column}}

    items = [
        item("[1~2] Read this shared passage."),
        item("Shared passage continuation."),
        item("1. First question starts here."),
        item("The first question continues in the next column.", column=1),
        item("The same question continues on the next page.", page=2),
        item("2. Second question starts here.", page=2),
        item("* 확인 사항", page=2),
        item("Document closing note.", page=2),
        item("1. A new exam variant starts here.", page=3),
    ]
    expected = [
        SimpleNamespace(page_number=p, number=n) for p, n in [(1, 1), (2, 2), (3, 1)]
    ]
    inventory = annotate_question_groups(items, expected)
    layouts = [item["layout"] for item in items]
    check(
        inventory["inventory_matches"] and inventory["question_count"] == 3,
        "group boundaries match the independent question inventory",
    )
    check(
        len({layouts[index]["question_group"] for index in (2, 3, 4)}) == 1,
        "a whole question retains its group across column and page boundaries",
    )
    check(
        layouts[0]["question_group_kind"]
        == layouts[1]["question_group_kind"]
        == "shared_passage"
        and layouts[6]["question_group_kind"]
        == layouts[7]["question_group_kind"]
        == "document_note",
        "shared passages and closing notes remain outside question containers",
    )
    check(
        layouts[8]["question_group"] == "v2:q01",
        "restarted question numbering receives a distinct exam variant",
    )
    incomplete = annotate_question_groups(
        [item("1. Only one question is present.")], expected
    )
    check(
        not incomplete["inventory_matches"] and incomplete["missing_question_markers"],
        "missing question starts cannot be hidden by a successful group count",
    )


def verify_output(source, output, provenance, expected_numbers, baseline=None):
    from app.pdf_question_inspection import inspect_question_units

    audit = inspect_pdf_editability(source, output, provenance)
    units = inspect_question_units(source, output, required=True, provenance=provenance)
    check(
        audit["ok"] and units["ok"],
        f"actual source and native container audit pass: {output.name}: "
        f"editability={audit['issues']}, units={units['issues']}",
    )
    check(
        not _verify_no_draw_text_equations(output),
        "package validation accepts native equations in structurally valid whole-question boxes",
    )
    with zipfile.ZipFile(output) as package:
        root = etree.fromstring(package.read("Contents/section0.xml"))
        containers = outer_containers(root)
        check(
            [entry[3] for entry in containers] == expected_numbers,
            "there is exactly one actual outer container for each ordered question",
        )
        for _, _, content, number in containers:
            paragraph_starts = []
            for paragraph in content.findall(f"{HP}p"):
                text = "".join(
                    t.text or "" for t in paragraph.findall(f"{HP}run/{HP}t")
                ).strip()
                marker = QUESTION.match(text)
                if marker:
                    paragraph_starts.append(int(marker.group(1)))
            check(
                paragraph_starts == [number],
                f"question {number} contains one real question start",
            )
    if baseline:
        before, after = native_state(baseline), native_state(output)
        # Recovering true native scripts moves symbols out of text runs and
        # replaces the old wrong "1015" with "10^{15}". Compare literal glyphs
        # across both storage types here; the independent source attachment
        # audit above requires the correct mathematical structure and owner.
        from app.pdf_script_attachments import GREEK

        for state in (before, after):
            glyphs = Counter()
            for values in (state["texts"], state["scripts"]):
                for text, count in values.items():
                    text = "".join(GREEK.get(char, char) for char in text)
                    text = re.sub(r"[\s{}^_]", "", text)
                    for char in text:
                        glyphs[char] += count
            state["texts"] = glyphs
            del state["scripts"]
        check(
            before == after,
            "containers preserve prior literal glyphs and picture bytes while source audits verify mathematical structure",
        )
    return containers


def test_synthetic():
    from app.pdf_question_inspection import inspect_question_units

    folder = Path(RUNTIME.name)
    source, output = folder / "science.pdf", folder / "questions.hwpx"
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((45, 60), "Science examination", fontsize=14)
        page.insert_text((45, 140), "1. Read the scientific observation.", fontsize=9)
        page.insert_text(
            (45, 165), "This editable sentence continues after the heading.", fontsize=9
        )
        page.draw_rect(fitz.Rect(45, 190, 270, 245))
        page.insert_text(
            (55, 215),
            "The complete boxed explanation belongs to question one.",
            fontsize=8,
        )
        page.insert_text((45, 275), "A=", fontsize=10)
        page.insert_text((70, 266), "1", fontsize=10)
        page.insert_text((70, 281), "2", fontsize=10)
        page.draw_line(fitz.Point(68, 270), fitz.Point(82, 270))
        page.insert_text((45, 305), "is.", fontsize=10)
        page.insert_text((320, 140), "2. Compare the two measurements.", fontsize=9)
        page.insert_text(
            (320, 165), "The complete second question stays together.", fontsize=9
        )
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 50), False)
        pix.clear_with(110)
        page.insert_image(fitz.Rect(330, 190, 390, 240), pixmap=pix)
        pdf.save(source)
    stats = w.write_pdf_structured_hwpx(source, output)
    verify_output(source, output, stats["image_provenance"], [1, 2])
    check(
        len(native_state(output)["pictures"]) == 1 and native_state(output)["scripts"],
        "native source figure and fraction survive inside the question containers",
    )

    def spill_body(root):
        host, _, content, _ = outer_containers(root)[0]
        paragraph = next(
            p
            for p in content.findall(f"{HP}p")
            if "editable sentence" in "".join(p.itertext())
        )
        content.remove(paragraph)
        root.insert(list(root).index(host) + 1, paragraph)

    def combine_questions(root):
        first, second = outer_containers(root)
        for paragraph in list(second[2]):
            first[2].append(paragraph)
        root.remove(second[0])

    def duplicate_line_container(root):
        first = outer_containers(root)[0]
        duplicate = deepcopy(first[0])
        temporary_root = etree.Element(root.tag)
        temporary_root.append(duplicate)
        copied_content = outer_containers(temporary_root)[0][2]
        paragraphs = copied_content.findall(f"{HP}p")
        for paragraph in paragraphs[1:]:
            copied_content.remove(paragraph)
        temporary_root.remove(duplicate)
        root.insert(list(root).index(first[0]) + 1, duplicate)

    def spill_short_tail(root):
        host, _, content, _ = outer_containers(root)[0]
        text = next(
            t for t in content.iter(f"{HP}t") if (t.text or "").rstrip().endswith("is.")
        )
        text.text = (text.text or "").rstrip()[:-3]
        paragraph = etree.Element(f"{HP}p", id="90001", paraPrIDRef="0", styleIDRef="0")
        run = etree.SubElement(paragraph, f"{HP}run", charPrIDRef="0")
        etree.SubElement(run, f"{HP}t").text = "is."
        root.insert(list(root).index(host) + 1, paragraph)

    def fake_question_name(root):
        _, _, content, _ = outer_containers(root)[0]
        first_text = next(t for t in content.iter(f"{HP}t") if (t.text or "").strip())
        first_text.text = "A named box containing only an arbitrary line."

    def move_picture_to_another_question(root):
        first, second = outer_containers(root)
        picture = next(second[2].iter(f"{HP}pic"))
        picture.getparent().remove(picture)
        paragraph = first[2].findall(f"{HP}p")[-1]
        etree.SubElement(paragraph, f"{HP}run", charPrIDRef="0").append(picture)

    for name, mutate in (
        ("spilled_body", spill_body),
        ("two_questions_in_one", combine_questions),
        ("duplicate_line_container", duplicate_line_container),
        ("short_sentence_tail_outside", spill_short_tail),
        ("name_only_line_box", fake_question_name),
        ("picture_in_another_question", move_picture_to_another_question),
    ):
        malformed = folder / f"{name}.hwpx"
        rewrite(output, malformed, mutate)
        if name == "picture_in_another_question":
            check(
                native_state(output) == native_state(malformed),
                "moving a picture between boxes preserves all global text, equations and image counts",
            )
            check(
                "source_question_picture_outside_its_box"
                in inspect_question_units(
                    source,
                    malformed,
                    required=True,
                    provenance=stats["image_provenance"],
                )["issues"],
                "source geometry assigns each picture to its own question independently of global counts",
            )
        check(
            not inspect_question_units(
                source, malformed, required=True, provenance=stats["image_provenance"]
            )["ok"],
            f"actual structure rejects {name}",
        )
        if name in {"duplicate_line_container", "name_only_line_box"}:
            check(
                bool(_verify_no_draw_text_equations(malformed)),
                f"package-only equation validation also rejects {name}",
            )


def test_rendered_word_fraction():
    import rhwp
    from app.pdf_question_rendering import inspect_question_rendering

    numerator = "분자에 포함된 탄소의 양"
    denominator = "분모에 포함된 산소의 양"
    items = [
        {
            "stem": "1. 한글 분수의 값을 확인하시오.",
            "tables": [
                [
                    [
                        r"ㄱ. 현재 $\frac{"
                        + numerator
                        + "}{"
                        + denominator
                        + r"}$ 은 8이다."
                    ]
                ]
            ],
            "source_page": 1,
            "layout": {"source_content": True, "source_column": 0},
        }
    ]
    annotate_question_groups(items)
    folder = Path(RUNTIME.name)
    broken, fixed = folder / "nested_fraction.hwpx", folder / "flat_fraction.hwpx"
    with patch(
        "app.pdf_question_tables.flatten_question_fraction_tables", return_value=0
    ):
        hwpx_writer_v2.write_hwpx(
            broken,
            "과학탐구 영역",
            deepcopy(items),
            "kice_science",
            native_math=True,
            preserve_source_layout=True,
        )
    hwpx_writer_v2.write_hwpx(
        fixed,
        "과학탐구 영역",
        deepcopy(items),
        "kice_science",
        native_math=True,
        preserve_source_layout=True,
    )
    with zipfile.ZipFile(broken) as package:
        broken_root = etree.fromstring(package.read("Contents/section0.xml"))
        broken_header = etree.fromstring(package.read("Contents/header.xml"))
    check(
        len(_native_text_fraction_scripts(broken_root, broken_header)) == 1,
        "the historical invisible fraction still contains a genuine native fraction in XML",
    )
    old_render = inspect_question_rendering(broken, rhwp)
    check(
        not old_render["ok"]
        and old_render["unsupported_nested_tables"] > 0
        and old_render["missing_rendered_text"],
        "actual rendering rejects the historically invisible nested fraction despite valid XML",
    )
    visible = inspect_question_rendering(fixed, rhwp)
    check(
        visible["ok"]
        and not visible["unsupported_nested_tables"]
        and not visible["missing_rendered_text"],
        "flattened native fraction operands reach actual rendered text without nested tables",
    )
    check(
        native_state(broken) == native_state(fixed),
        "flattening preserves all native text and equations rather than replacing them with pixels",
    )
    with zipfile.ZipFile(fixed) as package:
        root = etree.fromstring(package.read("Contents/section0.xml"))
        header = etree.fromstring(package.read("Contents/header.xml"))
    valid_scripts = _native_text_fraction_scripts(root, header)
    check(
        len(valid_scripts) == 1
        and numerator in valid_scripts[0]
        and denominator in valid_scripts[0],
        "actual flattened adjacent cells retain the correct numerator and denominator",
    )
    for change in ("row_address", "cell_width", "fraction_rule"):
        forged = deepcopy(root)
        num = next(
            cell
            for cell in forged.iter(f"{HP}tc")
            if (cell.get("name") or "").endswith(":numerator")
        )
        den = next(
            cell
            for cell in forged.iter(f"{HP}tc")
            if (cell.get("name") or "").endswith(":denominator")
        )
        if change == "row_address":
            den.find(f"{HP}cellAddr").set(
                "rowAddr", num.find(f"{HP}cellAddr").get("rowAddr")
            )
        elif change == "cell_width":
            size = den.find(f"{HP}cellSz")
            size.set("width", str(int(size.get("width")) + 1))
        else:
            num.set("borderFillIDRef", den.get("borderFillIDRef"))
        check(
            not _native_text_fraction_scripts(forged, header),
            f"fraction labels cannot conceal invalid {change}",
        )
    numerator_cell = next(
        cell
        for cell in root.iter(f"{HP}tc")
        if (cell.get("name") or "").endswith(":numerator")
    )
    for change in ("white_rule", "zero_width_rule"):
        forged_header = deepcopy(header)
        hh = "{http://www.hancom.co.kr/hwpml/2011/head}"
        border = forged_header.find(
            f".//{hh}borderFill[@id='{numerator_cell.get('borderFillIDRef')}']/{hh}bottomBorder"
        )
        border.set(
            "color" if change == "white_rule" else "width",
            "#FFFFFF" if change == "white_rule" else "0.0 mm",
        )
        check(
            not _native_text_fraction_scripts(root, forged_header),
            f"fraction labels cannot conceal an invisible {change}",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-folder", type=Path)
    parser.add_argument("--baseline-folder", type=Path)
    args = parser.parse_args()
    test_group_boundaries()
    test_synthetic()
    test_rendered_word_fraction()
    if args.real_folder:
        for entry in json.loads(
            (args.real_folder / "audit.json").read_text(encoding="utf-8")
        ):
            name = entry["source"]["name"]
            output = args.real_folder / (Path(name).stem + "_native.hwpx")
            baseline = (
                args.baseline_folder / output.name if args.baseline_folder else None
            )
            verify_output(
                ROOT / "data/uploads" / name,
                output,
                entry["stats"]["image_provenance"],
                list(range(1, 21)),
                baseline,
            )
    print("QUESTION_CONTAINERS_OK")


if __name__ == "__main__":
    main()
