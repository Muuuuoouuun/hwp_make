"""Merged native cells must fit content, remain editable and save stably."""
# ruff: noqa: E402
from copy import deepcopy
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import write_hwpx
from app.pdf_native_content import annotate_question_groups
from app.pdf_native_typography import _flow_height
from app.hwpx_writer import _equation_reserved_width, _hancom_eqn_script
from hwpx.tools.table_reflow import fit_table_rows
from scripts.verify_native_question_edit_reflow import verify, state, H


def main():
    # A named EQN operator paints one glyph, not the letters in its command.
    # Keep the width near the 10pt symbol rather than stretching times/triangle
    # into a long cross or a pair of flat chevrons in Korean prose.
    for symbol in ("×", "÷", "△", "∠", "∥", "⊥"):
        assert 300 <= _equation_reserved_width(_hancom_eqn_script(symbol)) <= 1000
    assert _equation_reserved_width(_hancom_eqn_script("△△")) <= 1600
    assert _equation_reserved_width("times") == _equation_reserved_width("TIMES")
    with tempfile.TemporaryDirectory(prefix="merged_table_edit_") as temp:
        folder = Path(temp)
        layout = {
            "source_content": True, "source_page_width_pt": 842, "source_column": 1,
            "source_typography": {"font_size_pt": 11.21, "font_name": "HY신명조",
                                  "line_spacing_pt": 16.7, "source_column_width_pt": 320},
        }
        prose = "자료의 조건을 확인하고 서로 다른 결과가 나타나는 이유를 설명하십시오. " * 3
        table_item = {
            "tables": [[["설명", "결과"], [prose, "A"], ["", "B"]]],
            "source_page": 1,
            "layout": {**deepcopy(layout), "native_tables": [{"index": 0,
                "bbox_pt": [40, 120, 360, 230],
                "cell_bounds": [[[40, 120, 290, 145], [290, 120, 360, 145]],
                                [[40, 145, 290, 230], [290, 145, 360, 180]],
                                [None, [290, 180, 360, 230]]]}]},
        }
        items = [{"stem": "1. 표의 내용을 읽고 물음에 답하시오.", "source_page": 1,
                  "layout": deepcopy(layout)}, table_item]
        annotate_question_groups(items)
        path = folder / "merged.hwpx"
        write_hwpx(path, "Merged cell edit test", items, "kice_science",
                   native_math=True, preserve_source_layout=True)
        root, _ = state(path)
        table = root.find(".//" + H + "tbl")
        merged = next(c for c in table.iter(H + "tc") if c.find(H + "cellSpan").get("rowSpan") == "2")
        height = int(table.find(H + "sz").get("height"))
        assert 0 < height < 15000, height
        assert int(merged.find(H + "cellSz").get("height")) < height
        before = etree.tostring(table)
        fit_table_rows(table, _flow_height, grow_only=True)
        assert etree.tostring(table) == before, "fitting unchanged merged cells grew the table"
        assert rhwp.parse(str(path)).page_count == 1

        edit_folder = folder / "edit"
        edit_folder.mkdir()
        verify(path, edit_folder, table_cells=True)
        after, _ = state(edit_folder / "edited.hwpx")
        edited = after.find(".//" + H + "tbl")
        def cells(t):
            return [(dict(c.find(H + "cellAddr").attrib), dict(c.find(H + "cellSpan").attrib),
                     c.find(H + "cellSz").get("width")) for c in t.iter(H + "tc")]
        assert cells(edited) == cells(table), "editing changed cell ownership or merging"
        assert int(edited.find(H + "sz").get("height")) > height
        fit_table_rows(edited, _flow_height, grow_only=True)
        again = etree.tostring(edited)
        fit_table_rows(edited, _flow_height, grow_only=True)
        assert etree.tostring(edited) == again
    print("NATIVE_MERGED_TABLE_REFLOW_OK: content height, +155 character edit, preserved spans and stable save")


if __name__ == "__main__":
    main()
