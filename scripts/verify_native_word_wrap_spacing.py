"""Joining Korean source wraps must preserve words AND explicit source spaces."""
# ruff: noqa: E402
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_word_wrap_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
from app.hwpx_writer_v2 import write_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_paragraph_flow import inspect_paragraph_flow
from app.pdf_word_wrap import join_source_paragraph

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def change_text(source, target, before, after):
    changed = 0
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.startswith("Contents/section") and info.filename.endswith(".xml"):
                root = etree.fromstring(data)
                for text in root.iter(HP + "t"):
                    if before in (text.text or ""):
                        text.text = text.text.replace(before, after)
                        changed += 1
                data = etree.tostring(root, xml_declaration=True, encoding="utf-8")
            dst.writestr(info, data)
    assert changed


def run(boxed):
    folder = Path(runtime.name) / ("box" if boxed else "body")
    folder.mkdir()
    source, target = folder / "source.pdf", folder / "native.hwpx"
    lines = ["원본 문장의 글자와 단어는 중간에서 끊어질 수 있습니",
             "다 그러나 출력 문단에서는 자연스럽게 이어져야 합니다 ",
             "실제 공백은 없애지 않고 원문과 같은 위치에 둡니다 ",
             "다음 문장도 함께 편집되는 하나의 문단으로 저장합니다."]
    expected = lines[0] + lines[1] + lines[2] + lines[3]
    with fitz.open() as doc:
        page = doc.new_page(width=842, height=1191)
        page.insert_text((80, 40), "Source word boundary test")
        page.insert_text((80, 180), "1. Read the original paragraph.", fontsize=10)
        for index, text in enumerate(lines):
            page.insert_text((80, 215 + 14 * index), text, fontname="korea", fontsize=10)
        if boxed:
            page.draw_rect(fitz.Rect(74, 198, 386, 264))
        page.insert_text((450, 180), "2. The next question stays separate.", fontsize=10)
        doc.save(source)
    items, _ = extract_native_content(source)
    write_hwpx(target, "Word boundaries", items, "kice_science", native_math=True,
               preserve_source_layout=True)
    with zipfile.ZipFile(target) as package:
        root = etree.fromstring(package.read("Contents/section0.xml"))
    paragraphs = ["".join(t.text or "" for t in p.findall(HP + "run/" + HP + "t"))
                  for p in root.iter(HP + "p")]
    assert sum(expected in p for p in paragraphs) == 1, paragraphs
    audit = inspect_paragraph_flow(source, target)
    assert audit["ok"] and audit["source_word_boundaries_checked"] >= 2, audit
    for name, before, after in (("added", "있습니다", "있습니 다"),
                                ("removed", "합니다 실제", "합니다실제")):
        mutant = folder / f"{name}.hwpx"
        change_text(target, mutant, before, after)
        audit = inspect_paragraph_flow(source, mutant)
        assert "source_paragraph_word_spacing_changed" in audit["issues"], audit
    print(f"NATIVE_WORD_WRAP_SPACING_OK ({'box' if boxed else 'body'}): source words/spaces and one paragraph; inserted/deleted boundary spaces rejected")


if __name__ == "__main__":
    # With no source end-space evidence, retain the ordinary separator.
    unknown = [{"spans": [{"text": t, "font": "unknown"}]} for t in ("단어", "연결")]
    assert join_source_paragraph(unknown) == "단어 연결"
    latin = [{"spans": [{"text": t, "font": "known"}]} for t in ("Two", "words")]
    assert join_source_paragraph(latin, {"known"}) == "Two words"
    run(False)
    run(True)
