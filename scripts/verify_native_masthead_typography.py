"""Source masthead positions and whole editable paragraphs survive save/reopen."""

from pathlib import Path
from copy import deepcopy
import sys
import tempfile
import zipfile
from types import SimpleNamespace
import fitz
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pdf_masthead_typography import measure_source_masthead
from app.hwpx_writer_v2 import write_hwpx, HwpxDocument
from app.pdf_native_content import annotate_question_groups
from app.pdf_question_rendering import _multiply, _transform, IDENTITY
from hwpx.oxml import HwpxOxmlParagraph
import rhwp

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def package(path):
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read("Contents/section0.xml")), etree.fromstring(
            z.read("Contents/header.xml")
        )


def text_positions(path, page=0):
    svg = etree.fromstring(rhwp.parse(str(path)).render_svg(page).encode())
    result = []
    for node in svg.iter('{http://www.w3.org/2000/svg}text'):
        matrix = IDENTITY
        for parent in [*reversed(list(node.iterancestors())), node]:
            matrix = _multiply(matrix, _transform(parent.get('transform', '')))
        x, y = float(node.get('x', 0)), float(node.get('y', 0))
        result.append((''.join(node.itertext()), matrix[0]*x + matrix[2]*y + matrix[4],
                       matrix[1]*x + matrix[3]*y + matrix[5]))
    return result


def main():
    with tempfile.TemporaryDirectory(prefix="native_masthead_") as temp:
        doc = fitz.open()
        page = doc.new_page(width=842, height=1191)
        assert not measure_source_masthead(
            page, 220
        ), "unmeasured headers must keep template defaults"
        page.insert_text(
            (150, 100), "2026학년도 시험 문제지", fontname="korea", fontsize=19
        )
        page.insert_text(
            (240, 145), "과학탐구영역(지구과학I)", fontname="korea", fontsize=30
        )
        page.insert_text((90, 138), '제2 교시', fontname='korea', fontsize=19)
        page.insert_text((735, 100), '1', fontname='helv', fontsize=25)
        page.draw_line((85, 190), (750, 190), width=1)
        meta = measure_source_masthead(page, 220)
        assert (
            meta
            and meta["area"]["spans"][0]["font_size_pt"]
            > meta["title"]["spans"][0]["font_size_pt"]
        )
        extraction = page.get_text("dict")
        title_line = next(line for block in extraction["blocks"] for line in block.get("lines", [])
                          if "문제지" in "".join(s.get("text", "") for s in line["spans"]))
        title_line["spans"].append({**title_line["spans"][-1], "text": "            1", "size": 40})
        joined_number = SimpleNamespace(get_text=lambda _: extraction, rect=page.rect)
        measured = measure_source_masthead(joined_number, 220)
        assert measured["title"]["text"] == meta["title"]["text"]
        assert max(s["font_size_pt"] for s in measured["title"]["spans"]) == 19
        for subject in ("국어 영역", "수학 영역", "영어 영역"):
            plain = doc.new_page(width=842, height=1191)
            plain.insert_text((150, 100), "2026학년도 시험 문제지", fontname="korea", fontsize=19)
            plain.insert_text((150, 145), subject, fontname="korea", fontsize=30)
            measured = measure_source_masthead(plain, 220)
            assert measured and measured["area"]["text"] == subject
        items = [
            {
                "stem": "1. Read the native paragraph and compare the observed values.",
                "source_page": 1,
                "layout": {
                    "source_content": True,
                    "source_page_width_pt": 842,
                    "source_column": 1,
                    "source_bbox_pt": [100, 230, 420, 245],
                    "source_masthead_area": meta["area"]["text"],
                    "source_typography": {
                        "font_size_pt": 11,
                        "font_name": "Helvetica",
                        "line_spacing_pt": 16,
                        "source_column_width_pt": 320,
                    },
                },
            }
        ]
        for number, top in ((2, 160), (3, 700)):
            item = deepcopy(items[0])
            item['stem'] = f'{number}. Read the complete paragraph before choosing the answer.'
            item['source_page'] = 2
            item['layout']['source_bbox_pt'] = [100, top, 420, top+15]
            items.append(item)
        annotate_question_groups(items)
        paths = []
        for enabled in (False, True):
            copied = deepcopy(items)
            if enabled:
                copied[0]["layout"]["source_masthead_typography"] = meta
            path = Path(temp) / f"{enabled}.hwpx"
            write_hwpx(
                path,
                meta["title"]["text"],
                copied,
                "kice_science",
                native_math=True,
                preserve_source_layout=True,
            )
            paths.append(path)
        before, _ = package(paths[0])
        after, header = package(paths[1])
        assert rhwp.parse(str(paths[1])).page_count == 2
        assert text_positions(paths[0], 1) == text_positions(paths[1], 1), 'first-page masthead changed following-page body flow'
        running = after.find('.//' + HP + 'header')
        assert running is not None, "measured full-width masthead must be a section header"
        assert len(after.findall(HP + 'p')) == 1, "template blank header lines remain in body flow"
        native_margin = after.find('.//' + HP + 'pagePr/' + HP + 'margin')
        scale = 59528 / 842
        assert abs(int(native_margin.get('top')) + int(native_margin.get('header')) - 230*scale) <= 1
        positions = text_positions(paths[1])
        for name in ('title', 'area', 'period_geometry', 'page_number'):
            left, baseline = meta[name]['bbox_pt'][0]*scale/75, meta[name]['baseline_pt']*scale/75
            assert any(abs(x-left) < .1 and abs(y-baseline) < .1 for _, x, y in positions), (name, left, baseline)
        for row_index, row in enumerate(running.findall('.//' + HP + 'tbl/' + HP + 'tr')):
            cells = row.findall(HP + 'tc')
            assert all(int(c.find(HP + 'cellAddr').get('rowAddr')) == row_index for c in cells)
            assert sum(int(c.find(HP + 'cellSpan').get('colSpan')) for c in cells) == int(row.getparent().get('colCnt'))
        for tag in ('charPr', 'paraPr', 'borderFill'):
            ids = [p.get('id') for p in header.iter(HH + tag)]
            assert len(ids) == len(set(ids)), 'duplicate native style ID: ' + tag
        runs = [
            r
            for p in running.iter(HP + "p")
            for r in p.findall(HP + "run")
        ]
        heights = {}
        for name in ("title", "area"):
            needle = meta[name]["spans"][0]["text"]
            run = next(r for r in runs if r.findtext(HP + "t") == needle)
            style = header.find(
                ".//" + HH + 'charPr[@id="' + run.get("charPrIDRef") + '"]'
            )
            heights[name] = int(style.get("height"))
            expected = round(meta[name]["spans"][0]["font_size_pt"] * 59528 / 842)
            assert abs(heights[name] - expected) <= 1, (heights[name], expected)
        assert heights["area"] > heights["title"]
        assert (
            len(list(before.iter(HP + "drawText")))
            == len(list(after.iter(HP + "drawText")))
            == 1
        )
        # Source whitespace is now part of native text-box padding. Changing
        # the masthead can change that whitespace, but must never change the
        # question's actual text area, paragraph text, or cached body geometry.
        def body_signature(section):
            draw = next(section.iter(HP + 'drawText'))
            size = draw.getparent().find(HP + 'sz')
            margin = draw.find(HP + 'textMargin')
            sub = draw.find(HP + 'subList')
            available = int(size.get('height')) - sum(int(margin.get(edge, '0')) for edge in ('top', 'bottom'))
            return (size.get('width'), available, int(sub.get('textHeight')),
                    ''.join(sub.itertext()),
                    [dict(line.attrib) for line in sub.iter(HP + 'lineseg')])

        assert body_signature(before) == body_signature(after), 'masthead modified the editable question body'
        # Edit the same complete title paragraph through the public native API.
        document = HwpxDocument.open(paths[1])
        section = document.sections[0]
        title_node = next(p for p in section.element.find('.//' + HP + 'header').iter(HP + 'p')
                          if any('2026' in (t.text or '') for t in p.findall(HP + 'run/' + HP + 't')))
        paragraph = HwpxOxmlParagraph(title_node, section)
        paragraph.text = paragraph.text.replace('2026', '2027')
        edited = Path(temp) / 'edited.hwpx'
        document.save_to_path(edited)
        revised, _ = package(edited)
        assert '2027학년도' in ''.join(revised.find('.//' + HP + 'header').itertext())
        assert len(list(after.iter(HP + 'p'))) == len(list(revised.iter(HP + 'p')))
        assert ''.join(after.find('.//' + HP + 'drawText').itertext()) == ''.join(revised.find('.//' + HP + 'drawText').itertext())
        assert ''.join(t for t, _, _ in text_positions(edited)).count('2027') == 1
        twice = Path(temp) / 'edited_twice.hwpx'
        HwpxDocument.open(edited).save_to_path(twice)
        assert etree.tostring(package(twice)[0]) == etree.tostring(revised), 're-saving changed native paragraphs'
        print(
            "NATIVE_MASTHEAD_TYPOGRAPHY_OK: source title/area positions within 0.1px, native header/body origin, unique styles, complete paragraph edit/re-save"
        )


if __name__ == "__main__":
    main()
