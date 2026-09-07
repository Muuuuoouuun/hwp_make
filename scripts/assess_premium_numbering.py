"""Feasibility probe only: copy-based numbering is not a public API feature."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def document_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = (
            ["word/document.xml"] if path.suffix == ".docx" else
            sorted(n for n in archive.namelist() if n.startswith("Contents/section") and n.endswith(".xml"))
        )
        return "".join(
            node.text or ""
            for name in names
            for node in ET.fromstring(archive.read(name)).iter()
            if node.tag.rsplit("}", 1)[-1] == "t"
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hwp-premium-assessment-") as folder:
        # Isolate storage before importing application modules.
        os.environ["HWP_MAKE_DATA_DIR"] = folder
        from app import docx_writer, exam_templates, hwpx_writer_v2, storage

        storage.ensure_dirs()
        originals = [
            {"number": "12", "stem": "첫째문항 확인", "answer": "1", "explanation": "첫째해설"},
            {"number": "27", "stem": "둘째문항 확인", "answer": "2", "explanation": "둘째해설"},
        ]
        baseline = copy.deepcopy(originals)
        template = exam_templates.get_template("kice_math")
        for mode, labels in [("preserve", ["27", "12"]), ("sequential", ["1", "2"]), ("start_41", ["41", "42"])]:
            items = copy.deepcopy(list(reversed(originals)))
            if mode != "preserve":
                for item, label in zip(items, labels):
                    item["number"] = label
            answers = exam_templates.quick_answer_lines(items, template)
            explanations = exam_templates.explanation_entries(items, template)
            assert answers == [f"{labels[0]}. 2    {labels[1]}. 1"], answers
            assert [entry[0] for entry in explanations] == [f"{labels[0]}. 정답 2", f"{labels[1]}. 정답 1"]
            for extension, writer in [("hwpx", hwpx_writer_v2.write_hwpx), ("docx", docx_writer.write_docx)]:
                path = Path(folder) / f"{mode}.{extension}"
                writer(path, "Premium assessment", items, "kice_math", include_answer_sheet=True)
                text = " ".join(document_text(path).split())
                assert text.index("둘째문항") < text.index("첫째문항"), text
                for label, marker in zip(labels, ["둘째문항", "첫째문항"]):
                    assert f"{label}. {marker}" in text, text
                for heading, _ in explanations:
                    assert heading in text, text
                assert " ".join(answers[0].split()) in text, text
                print(f"PASS {mode} {extension}: body, answers, explanations = {','.join(labels)}")
            assert originals == baseline, "Source content changed"
        print("PREMIUM_NUMBERING_FEASIBILITY_OK (text fixtures; no API or payment implementation)")


if __name__ == "__main__":
    main()
