"""Endnote exams keep answers and promote pure choice tables to choice fields."""

from __future__ import annotations

import io
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from lxml import etree
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwpx_table_choices_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

from app import importers, storage  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def add_text(parent, value: str) -> None:
    paragraph = etree.SubElement(parent, HP + "p")
    run = etree.SubElement(paragraph, HP + "run")
    etree.SubElement(run, HP + "t").text = value


def source_package() -> bytes:
    section = etree.Element(HP + "section", nsmap={"hp": HP[1:-1]})
    for number in range(1, 5):
        paragraph = etree.SubElement(section, HP + "p")
        run = etree.SubElement(paragraph, HP + "run")
        etree.SubElement(run, HP + "t").text = f"{number}. Choose the answer."
        table = etree.SubElement(run, HP + "tbl")
        if number == 2:
            row = etree.SubElement(table, HP + "tr")
            cell = etree.SubElement(row, HP + "tc")
            add_text(cell, "Options table")
            etree.SubElement(cell, HP + "img", binaryItemIDRef="fig")
        if number == 4:
            for values in (list("①②③④⑤"), ["one", "two", "three", "four", "five"]):
                row = etree.SubElement(table, HP + "tr")
                for value in values:
                    add_text(etree.SubElement(row, HP + "tc"), value)
        else:
            for label, value in zip("①②③④⑤", ("one", "two", "three", "four", "five")):
                row = etree.SubElement(table, HP + "tr")
                if number == 3:
                    add_text(etree.SubElement(row, HP + "tc"), label)
                    add_text(etree.SubElement(row, HP + "tc"), value)
                else:
                    add_text(etree.SubElement(row, HP + "tc"), f"{label} {value}")
        note = etree.SubElement(run, HP + "endNote", number=str(number))
        add_text(note, "[답] ③")
        add_text(note, f"[풀이] Explanation {number}")
    buffer = io.BytesIO()
    image = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, format="PNG")
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/section0.xml", etree.tostring(section))
        archive.writestr("BinData/fig.png", image.getvalue())
    return buffer.getvalue()


def main() -> None:
    storage.init_db()
    result = importers.import_hwpx("choices.hwpx", source_package(), {})
    assert len(result["ordered_ids"]) == 4, result
    first, second, third, fourth = (storage.get_problem(item_id) for item_id in result["ordered_ids"])
    assert [item["number"] for item in (first, second, third, fourth)] == ["1", "2", "3", "4"]
    for problem in (first, third, fourth):
        assert problem["choices"] == ["one", "two", "three", "four", "five"]
        assert problem["tables"] == [], "pure choice table was duplicated in output"
    assert second["choices"] == [], "mixed table was misclassified as choices"
    assert "Options table" in str(second["tables"]), "mixed table was discarded"
    assert len(second["image_paths"]) == 1, "image inside a table was discarded"
    assert (storage.DATA_DIR / second["image_paths"][0]).is_file()
    for number, problem in enumerate((first, second, third, fourth), 1):
        assert problem["answer"] == "③"
        assert problem["explanation"] == f"Explanation {number}"
        assert "Explanation" not in problem["stem"], "endnote leaked into stem"
    print("HWPX_TABLE_CHOICES_OK: three choice layouts extracted, mixed table and image retained, endnotes isolated")


if __name__ == "__main__":
    main()
