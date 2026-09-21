"""Create three original questions with note-based and literal numbering.

This fixture isolates question boundaries and note ownership without real exam
content. Its package construction does not itself certify Hancom GUI behavior.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from lxml import etree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.hwpx_writer_v2 import HwpxDocument, write_hwpx

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
QUESTIONS = (
    ("Calculate 2 + 3.", "ANSWER_ALPHA: The sum of two and three is five."),
    ("Calculate 8 - 2.", "ANSWER_BETA: Subtracting two from eight gives six."),
    ("Calculate 3 * 3.", "ANSWER_GAMMA: Multiplying three by three gives nine."),
)


def create(path, literal_numbers, include_notes=True):
    write_hwpx(path, "Synthetic endnote import probe", [
        {"number": str(i), "stem": q, "choices": [], "answer": "", "explanation": ""}
        for i, (q, _) in enumerate(QUESTIONS, 1)
    ], template_key="basic")
    doc = HwpxDocument.open(path)
    for number, (question, explanation) in enumerate(QUESTIONS, 1):
        matches = [p for s in doc.sections for p in s.paragraphs if question in p.text]
        if len(matches) != 1:
            raise ValueError(f"Expected one synthetic paragraph for question {number}")
        paragraph = matches[0]
        paragraph.text = (f"{number}. " if literal_numbers else "") + question
        if not include_notes:
            continue
        note = paragraph.add_endnote(explanation)
        note.element.set("number", str(number))
        note.element.set("suffixChar", "41")
        # A native endnote is held by hp:ctrl, before the anchor text.
        host = next(r for r in paragraph.element.iter(HP + "run") if note.element in list(r))
        host.remove(note.element)
        ctrl = ET.SubElement(host, HP + "ctrl")
        ctrl.append(note.element)
        paragraph.element.remove(host)
        paragraph.element.insert(0, host)
        run = next(note.element.iter(HP + "run"))
        number_ctrl = ET.Element(HP + "ctrl")
        auto = ET.SubElement(number_ctrl, HP + "autoNum", num=str(number), numType="ENDNOTE")
        ET.SubElement(auto, HP + "autoNumFormat", type="DIGIT", userChar="", prefixChar="", suffixChar=")", supscript="0")
        run.insert(0, number_ctrl)
    # The ordinary writer creates separate numbered headings. Remove those so
    # this experiment has only the numbering mechanism named by the fixture.
    for section in doc.sections:
        for paragraph in list(section.element):
            if paragraph.tag != HP + "p" or paragraph.find(".//" + HP + "secPr") is not None:
                continue
            text = "".join(t.text or "" for t in paragraph.iter(HP + "t"))
            if not any(question in text for question, _ in QUESTIONS):
                section.element.remove(paragraph)
        section.mark_dirty()
    doc.save_to_path(path)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for literal, notes, name in (
        (False, True, "synthetic_notes_only.hwpx"),
        (True, True, "synthetic_literal_plus_notes.hwpx"),
        (True, False, "synthetic_literal_control.hwpx"),
    ):
        path = args.output_dir / name
        create(path, literal, notes)
        print(path)


if __name__ == "__main__":
    main()
