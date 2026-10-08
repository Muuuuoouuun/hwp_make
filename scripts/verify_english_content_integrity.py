"""English PDF -> Premium import -> real HWPX/DOCX content regression.

Run without arguments for a same-page mixed-passage PDF plus the two local
exam PDFs. Missing real sources return 2 (never a misleading PASS). Use
--synthetic-only for the portable regression. Every run uses a fresh database
and account; no existing user data, remote AI, or preview renderer is used.

Passage expectations come from the source PDF, not the recognition output.
Each required question is exported alone, so text on another question cannot
hide a missing passage. Reverse-order exports also check selection ordering.
Only XML text/math script nodes count as document content; image alt text does
not qualify as an editable passage.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import os
from pathlib import Path
import posixpath
import re
import sys
import tempfile
import unicodedata
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwpmake_english_integrity_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import importers, main, storage  # noqa: E402
from app.recognition.pipeline import recognize_pdf  # noqa: E402


def normalized(text: str) -> str:
    # PDF soft hyphens become visible hyphens in the native writers. Ignore
    # typography and whitespace, while preserving word and paragraph order.
    text = unicodedata.normalize("NFKC", str(text))
    return "".join(char.lower() for char in text if char.isalnum())


def package_text(payload: bytes, extension: str) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = ["word/document.xml"] if extension == "docx" else sorted(
            name for name in archive.namelist()
            if re.fullmatch(r"Contents/section\d+\.xml", name)
        )
        assert names, "HWPX contains no section XML"
        return "\n".join(
            "".join(node.text or "" for node in ET.fromstring(archive.read(name)).iter()
                    if node.tag.rsplit("}", 1)[-1] in {"t", "script"})
            for name in names
        )


def package_math_nodes(payload: bytes, extension: str) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = ["word/document.xml"] if extension == "docx" else [
            name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)]
        return [node.tag.rsplit("}", 1)[-1]
                for name in names for node in ET.fromstring(archive.read(name)).iter()
                if node.tag.rsplit("}", 1)[-1] in {"equation", "script", "oMath", "oMathPara"}]


def image_fingerprint(data: bytes) -> tuple[int, int, str]:
    pixmap = fitz.Pixmap(data)
    pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    if pixmap.alpha:
        pixmap = fitz.Pixmap(pixmap, 0)
    return pixmap.width, pixmap.height, hashlib.sha256(pixmap.samples).hexdigest()


def package_picture_references(payload: bytes, extension: str, source_images: list[bytes]) -> tuple[int, list[str]]:
    """Count actual drawing references and resolve every reference to an asset."""
    issues: list[str] = []
    source_fingerprints = {image_fingerprint(data) for data in source_images}
    matched_source = False
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if extension == "docx":
            document = ET.fromstring(archive.read("word/document.xml"))
            refs = [value for node in document.iter() if node.tag.rsplit("}", 1)[-1] == "blip"
                    for key, value in node.attrib.items() if key.rsplit("}", 1)[-1] == "embed"]
            relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
            targets = {node.attrib.get("Id"): posixpath.normpath("word/" + node.attrib["Target"])
                       for node in relationships if node.attrib.get("Type", "").endswith("/image")
                       and node.attrib.get("TargetMode") != "External"}
        else:
            sections = [name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)]
            refs = [node.attrib["binaryItemIDRef"] for name in sections
                    for node in ET.fromstring(archive.read(name)).iter()
                    if node.tag.rsplit("}", 1)[-1] == "img" and node.attrib.get("binaryItemIDRef")]
            manifest = ET.fromstring(archive.read("Contents/content.hpf"))
            targets = {}
            for node in manifest.iter():
                if node.tag.rsplit("}", 1)[-1] != "item" or not node.attrib.get("href"):
                    continue
                target = node.attrib["href"]
                targets[node.attrib.get("id")] = (target if target in archive.namelist()
                                                   else posixpath.normpath("Contents/" + target))
        for ref in refs:
            target = targets.get(ref)
            if target is None or target not in archive.namelist():
                issues.append(f"picture reference {ref!r} has no packaged image asset ({target!r})")
                continue
            try:
                pixmap = fitz.Pixmap(archive.read(target))
                if pixmap.width < 20 or pixmap.height < 20:
                    issues.append(f"picture asset {target!r} is smaller than a usable chart")
                if image_fingerprint(archive.read(target)) in source_fingerprints:
                    matched_source = True
            except Exception as exc:
                issues.append(f"picture asset {target!r} cannot be decoded: {type(exc).__name__}")
        if source_fingerprints and not matched_source:
            issues.append("no actual drawing refers to the imported chart's pixel content")
        return len(refs), issues


def source_excerpt(page: str, start: str, end: str, *, include_end: bool = False) -> str:
    """Extract a complete source region between independent, unique anchors."""
    compact = normalized(page)
    left = compact.index(normalized(start))
    right = compact.index(normalized(end), left + len(normalized(start)))
    if include_end:
        right += len(normalized(end))
    excerpt = compact[left:right]
    assert len(excerpt) >= 35, f"Trivial source oracle: {start!r}"
    return excerpt


def mixed_page_pdf() -> tuple[bytes, dict[int, list[tuple[str, str]]]]:
    """A numbered question and two shared passages coexist on the same page."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rows = [
        "40. A separate question before both shared passages.",
        "1) separate alpha 2) separate beta 3) separate gamma",
        "[41~42] Read the following passage and answer the questions.",
        "A lighthouse keeper records every ship entering the harbor.",
        "The ledger distinguishes the red vessel from the green vessel.",
        "Only a complete record can explain the unexpected arrival.",
        "41. Which title best describes the lighthouse record?",
        "1) First title 2) Second title 3) Third title",
        "42. Which vessel arrived unexpectedly according to the ledger?",
        "1) Red vessel 2) Green vessel 3) Blue vessel",
        "[43~45] Read the following story and answer the questions.",
        "(A) Nora found an old letter inside the village library.",
        "(B) Her brother carried the letter to the retired librarian.",
        "(C) The librarian explained its origin and identified its author.",
        "(D) Together they restored the letter and preserved its history.",
        "43. Choose the correct order of the story paragraphs.",
        "1) B C D 2) C B D 3) D B C",
        "44. Who explained the origin of the letter?",
        "1) Nora 2) Her brother 3) The librarian",
        "45. Which statement about the restored letter is correct?",
        "1) It was preserved 2) It was discarded 3) It disappeared",
    ]
    for index, text in enumerate(rows):
        page.insert_text((48, 65 + index * 32), text, fontsize=10)
    payload = doc.tobytes()
    doc.close()
    first = " ".join(rows[3:6])
    second = " ".join(rows[11:15])
    return payload, {
        **{number: [("shared 41-42", normalized(first))] for number in (41, 42)},
        **{number: [("shared 43-45, all four paragraphs", normalized(second))]
           for number in (43, 44, 45)},
    }


def real_expectations(pages: list[str], exam: str) -> dict[tuple[int, int], list[tuple[str, str]]]:
    expectations: dict[tuple[int, int], list[tuple[str, str]]] = {}
    if exam == "high1":
        regions = [
            (4, (25,), "complete editable chart analysis", "The graph above shows", "26. George Bird Grinnell"),
            (5, (29,), "complete inline-label grammar passage", "Literature, in its essence", "30. 다음 글의 밑줄 친 부분"),
            (5, (30,), "complete inline-label vocabulary passage", "A viewfinder is a piece of card", "[31~34]"),
            (6, (34,), "complete passage with literal article A", "A particularly powerful way", "① changing behaviors"),
            (6, (36,), "opening passage", "During the Ice Age, not only", "(A) In this type"),
            (7, (37,), "opening passage", "The big difference between working", "(A) But remember"),
            (7, (38,), "sentence to insert", "Adults who were told to gesture", "If you gesture while describing"),
            (7, (39,), "sentence to insert", "Unfortunately, deforestation is preventing", "Approximately 15-20%"),
            (7, (40,), "complete main passage", "We go out in the world every day", "We perform a(n)"),
            (7, (40,), "complete summary sentence", "We perform a(n)", "them."),
            (8, (41, 42), "complete shared 41-42", "Commercial businesses aim for predictability", "41. 윗글의 제목"),
            (8, (43, 44, 45), "complete shared 43-45, all four paragraphs", "Emma was a talented vocalist", "43. 주어진 글"),
        ]
    else:
        regions = [
            (4, (25,), "complete editable chart analysis", "The graph above shows", "26. Max Kleiber"),
            (5, (29,), "complete inline-label grammar passage", "We are exceptionally smart", "30. 다음 글의 밑줄 친 부분"),
            (5, (30,), "complete inline-label vocabulary passage", "Situational ethics is an ethical theory", "[31~34]"),
            (6, (34,), "complete literal English passage", "Kant was a strong defender", "① regarded as reasonably"),
            (6, (36,), "opening passage", "We usually think of a clock", "(A) Indeed"),
            (7, (37,), "opening passage", "Philosophy allows us to ask", "(A) This means"),
            (7, (38,), "sentence to insert", "Sometimes these internal narratives", "While stories clearly dominate"),
            (7, (39,), "sentence to insert", "The difference is that the action", "A video game has its own"),
            (7, (40,), "complete main passage", "In modern societies, the performing arts", "In a situation of financial"),
            (7, (40,), "complete summary sentence", "In a situation of financial", "audiences who value those experiences."),
            (8, (41, 42), "complete shared 41-42", "There is an obvious problem", "41. 윗글의 제목"),
            (8, (43, 44, 45), "complete shared 43-45, all four paragraphs", "Mia, let’s go walk our dog", "43. 주어진 글"),
        ]
    for offset in range(0, len(pages), 8):
        for page, numbers, role, start, end in regions:
            source_page = page + offset
            text = source_excerpt(pages[source_page - 1], start, end,
                                  include_end=role == "complete summary sentence")
            for number in numbers:
                expectations.setdefault((source_page, number), []).append((role, text))
        # Clock punctuation and currency signs are ordinary text in this
        # announcement. Dollar counts are checked separately from normalization.
        literal_anchors = (["9 a.m. - 12 p.m.", "1 p.m. - 4 p.m.", "$100 per person"]
                           if exam == "high1" else ["Deadline: December 12, 2025", "MP3 format only"])
        for anchor in literal_anchors:
            expected = normalized(anchor)
            assert expected in normalized(pages[offset + 3]), f"Source literal missing: {anchor!r}"
            expectations.setdefault((offset + 4, 27), []).append((f"literal announcement {anchor!r}", expected))
        if exam == "high1":
            anchor = "better than if you don’t gesture"
            assert normalized(anchor) in normalized(pages[offset + 6])
            expectations[(offset + 7, 38)].append(("literal contraction don't", normalized(anchor)))
    return expectations


class Regression:
    def __init__(self, client: TestClient):
        self.client = client
        self.failures: list[str] = []
        self.check_count = 0
        self.export_count = 0

    @staticmethod
    def chart_labels(exam: str) -> tuple[str, ...]:
        # These are chart-only title/axis/footnote anchors. Ordinary words such
        # as "text messaging" also appear legitimately in the editable analysis.
        if exam == "high1":
            return ("The Extent of People’s Trust in Self-Driving Cars, 2023",
                    "0 20 40 60 80", "U.K. U.S. India",
                    "Note: Over 1,000 respondents surveyed per selected country")
        return ("Percentages of U.S. Teenagers Who Spent Time with Friends by Communication Type (2014-2015)",
                "by Communication Type (2014-2015)", "0 10 20 30 40 50 60 70 (%)",
                "The number of participants is the same for each communication type")

    def chart_labels_absent(self, text: str, exam: str, label: str) -> None:
        for anchor in self.chart_labels(exam):
            self.check(normalized(anchor) not in normalized(text),
                       f"{label}: chart-only label duplicated into editable text: {anchor!r}")

    @staticmethod
    def summary_pairs(exam: str, source_page: int) -> list[tuple[str, str]]:
        if exam == "high1":
            return [('automatic', 'support'), ('purposeful', 'challenge'), ('analytical', 'confirm'),
                    ('detailed', 'explain'), ('immediate', 'alter')]
        if source_page > 8:  # The even form intentionally reorders the choices.
            return [('challenges', 'secure'), ('stability', 'reach'), ('uncertainty', 'lose'),
                    ('imbalance', 'split'), ('advantages', 'support')]
        return [('uncertainty', 'lose'), ('imbalance', 'split'), ('challenges', 'secure'),
                ('stability', 'reach'), ('advantages', 'support')]

    def check(self, condition: bool, message: str) -> None:
        self.check_count += 1
        if not condition:
            self.failures.append(message)
            print(f"  [FAIL] {message}", flush=True)

    def contains(self, actual: str, expected: str, label: str) -> None:
        self.check(expected in normalized(actual), f"{label}: source content missing or reordered ({len(expected)} characters)")

    def excludes(self, actual: str, expected: str, label: str) -> None:
        self.check(expected not in normalized(actual), f"{label}: unrelated shared passage attached to this question")

    def export(self, problems: list[dict], extension: str, label: str) -> str | None:
        response = self.client.post("/api/export", json={
            "ids": [problem["id"] for problem in problems], "workspace": "premium",
            "numbering_mode": "preserve", "title": "English integrity regression",
            "template_key": "kice_english", "format": extension,
            "native_math": True, "include_answer_sheet": False,
        })
        self.export_count += 1
        self.check(response.status_code == 200,
                   f"{label} {extension}: export HTTP {response.status_code} {response.text[:160] if response.status_code != 200 else ''}")
        if response.status_code == 200 and len(problems) == 1 and str(problems[0]["number"]) in {"27", "34", "38"}:
            nodes = package_math_nodes(response.content, extension)
            self.check(not nodes, f"{label} {extension}: literal English article/contraction/time became a native math node {nodes!r}")
            if str(problems[0]["number"]) == "27" and "$100" in problems[0].get("stem", ""):
                self.check("$100" in package_text(response.content, extension),
                           f"{label} {extension}: literal currency $100 lost from document text")
        if response.status_code == 200 and len(problems) == 1 and str(problems[0]["number"]) == "25":
            source_images = []
            for image in problems[0].get("image_paths") or []:
                path = storage.resolve_data_image_path(image, must_exist=True)
                if path is not None and path.is_file():
                    source_images.append(path.read_bytes())
            references, issues = package_picture_references(response.content, extension, source_images)
            self.check(references > 0, f"{label} {extension}: chart has no actual drawing reference")
            for issue in issues:
                self.check(False, f"{label} {extension}: {issue}")
            self.check(not issues, f"{label} {extension}: chart drawing resolves to a valid packaged image")
        return package_text(response.content, extension) if response.status_code == 200 else None

    def case(self, name: str, payload: bytes, expected_count: int,
             expectations: dict[tuple[int, int], list[tuple[str, str]]], exam: str = "synthetic") -> None:
        recognition = recognize_pdf(payload, filename=f"{name}_english.pdf")
        self.check(len(recognition.problems) == expected_count,
                   f"{name}: recognized {len(recognition.problems)} question instances, expected {expected_count}")
        by_instance = {(problem.page_number, problem.number): problem for problem in recognition.problems}

        def foreign_shared(number: int) -> list[tuple[str, str]]:
            opposite = 43 if number in (41, 42) else 41 if number in (43, 44, 45) else None
            return next((contents for (_, other_number), contents in expectations.items()
                         if other_number == opposite), [])

        for key, contents in expectations.items():
            problem = by_instance.get(key)
            self.check(problem is not None, f"{name}: recognition missing page {key[0]} question {key[1]}")
            if problem:
                for role, expected in contents:
                    self.contains(f"{problem.shared_passage_text}\n{problem.text}", expected,
                                  f"{name} recognition p{key[0]} q{key[1]} {role}")
                for role, expected in foreign_shared(key[1]):
                    self.excludes(f"{problem.shared_passage_text}\n{problem.text}", expected,
                                  f"{name} recognition p{key[0]} q{key[1]} foreign {role}")
                if key[1] == 25:
                    self.check(bool(problem.figure_pngs), f"{name} recognition p{key[0]} q25: chart figure missing")
                    self.check(all(image.startswith(b"\x89PNG\r\n\x1a\n") for image in problem.figure_pngs),
                               f"{name} recognition p{key[0]} q25: chart figure is not a PNG")
                    self.check(problem.text_reliable and not problem.problem_image_png,
                               f"{name} recognition p{key[0]} q25: editable chart analysis replaced by whole-question image")
                    self.chart_labels_absent(problem.text, exam, f"{name} recognition p{key[0]} q25")

        response = self.client.post("/api/import", json={
            "kind": "pdf", "filename": f"{name}_english.pdf",
            "data_base64": base64.b64encode(payload).decode("ascii"),
            "metadata": {"math_ai_recognition": False, "allow_remote": False},
        })
        self.check(response.status_code == 200, f"{name}: import HTTP {response.status_code}")
        if response.status_code != 200:
            return
        imported = response.json()
        problems = {item["id"]: storage.get_problem(item["id"])
                    for item in [*imported.get("created", []), *imported.get("existing", [])]}
        self.check(bool(problems), f"{name}: no stored questions")
        by_number: dict[int, list[dict]] = {}
        for problem in problems.values():
            if str(problem.get("number", "")).isdigit():
                by_number.setdefault(int(problem["number"]), []).append(problem)
                source_problem = by_instance.get((problem.get("source_page"), int(problem["number"])))
                if source_problem is not None:
                    source_text = source_problem.shared_passage_text + source_problem.text
                    imported_text = problem.get("stem", "") + "".join(problem.get("choices") or [])
                    self.check(source_text.count("$") == imported_text.count("$"),
                               f"{name} p{problem['source_page']} q{problem['number']}: English prose acquired math fences (literal source currency is allowed)")
        export_requirements: dict[int, tuple[dict, list[tuple[str, str]]]] = {}
        for (page, number), contents in expectations.items():
            candidates = by_number.get(number, [])
            # The problem bank intentionally deduplicates identical variants.
            # Prefer the exact source instance, then require every source region
            # to be present on the reused same-number question.
            exact = [problem for problem in candidates if problem.get("source_page") == page]
            problem = next(iter(exact), None) or next((problem for problem in candidates
                if all(expected in normalized(problem.get("stem", "")) for _, expected in contents)), None)
            if problem is None and candidates:
                problem = candidates[0]
            self.check(problem is not None, f"{name}: import missing page {page} question {number}")
            if problem is None:
                continue
            for role, expected in contents:
                self.contains(problem.get("stem", ""), expected, f"{name} import p{page} q{number} {role}")
            for role, expected in foreign_shared(number):
                self.excludes(problem.get("stem", ""), expected, f"{name} import p{page} q{number} foreign {role}")
            if number == 25:
                self.check(bool(problem.get("image_paths")), f"{name} import p{page} q25: chart image missing")
                for image in problem.get("image_paths") or []:
                    path = storage.resolve_data_image_path(image, must_exist=True)
                    self.check(path is not None and path.is_file(), f"{name} import p{page} q25: chart image file absent")
                self.chart_labels_absent(problem.get("stem", ""), exam, f"{name} import p{page} q25")
            if problem["id"] not in export_requirements:
                export_requirements[problem["id"]] = (problem, [])
            export_requirements[problem["id"]][1].extend(contents)

        if exam != "synthetic":
            for number in (29, 30):
                candidates = by_number.get(number, [])
                self.check(bool(candidates), f"{name}: import missing inline-label question {number}")
                for problem in candidates:
                    self.check(not problem.get("choices"), f"{name} q{number}: inline labels became standalone choices {problem.get('choices')!r}")
                    self.check(all(marker in problem.get("stem", "") for marker in "①②③④⑤"),
                               f"{name} q{number}: inline circled labels lost from stem")
            for problem in by_number.get(40, []):
                pairs = self.summary_pairs(exam, int(problem["source_page"]))
                choices = problem.get("choices") or []
                self.check(len(choices) == 5, f"{name} q40: expected five paired choices, got {choices!r}")
                for index, pair in enumerate(pairs):
                    self.check(index < len(choices) and normalized(choices[index]) == normalized(" ".join(pair)),
                               f"{name} q40 choice {index + 1}: A/B pair {pair!r} missing or mismatched")

            # Choice splitting has its own source/geometry regression in
            # verify_english_choices.py. Here it supplies source variant keys
            # to test the distinct storage/import boundary: a same-number
            # question with a different ordered choice list must survive dedup.
            source_variants: dict[int, dict[tuple[str, ...], tuple[object, list[str]]]] = {}
            for source_problem in recognition.problems:
                _, source_choices = importers._split_english_stem_and_choices(
                    source_problem.text, source_problem.line_geometries)
                if source_choices:
                    signature = tuple(normalized(choice) for choice in source_choices)
                    source_variants.setdefault(source_problem.number, {}).setdefault(
                        signature, (source_problem, source_choices))
            variant_numbers = [number for number, variants in source_variants.items() if len(variants) > 1]
            for number in variant_numbers:
                for signature, (source_problem, source_choices) in source_variants[number].items():
                    stored = next((problem for problem in by_number.get(number, [])
                                   if tuple(normalized(choice) for choice in problem.get("choices", [])) == signature), None)
                    self.check(stored is not None,
                               f"{name} p{source_problem.page_number} q{number}: distinct ordered-choice variant lost during import dedup")
                    if stored is not None:
                        export_requirements.setdefault(stored["id"], (stored, []))
                        export_requirements[stored["id"]][1].extend(
                            (f"source choice {index + 1} from p{source_problem.page_number}", normalized(choice))
                            for index, choice in enumerate(source_choices))
            if variant_numbers:
                print(f"  [VARIANTS] {name}: distinct ordered choices preserved for questions {sorted(variant_numbers)}", flush=True)

        # Export every required question alone, including q42, q44 and q45.
        # A nearby complete passage can never mask an incorrect question stem.
        for problem, contents in export_requirements.values():
            for extension in ("hwpx", "docx"):
                text = self.export([problem], extension, f"{name} q{problem['number']} alone")
                if text is not None:
                    for role, expected in contents:
                        self.contains(text, expected, f"{name} {extension} q{problem['number']} alone {role}")
                    for role, expected in foreign_shared(int(problem['number'])):
                        self.excludes(text, expected, f"{name} {extension} q{problem['number']} alone foreign {role}")
                    if str(problem["number"]) == "25":
                        self.chart_labels_absent(text, exam, f"{name} {extension} q25 alone")
                    if str(problem["number"]) == "40" and exam != "synthetic":
                        for pair in self.summary_pairs(exam, int(problem["source_page"])):
                            self.contains(text, normalized(" ".join(pair)), f"{name} {extension} q40 pair {pair!r}")

        # A combined exam can retain distinct variants of one number. Preserve
        # numbering correctly rejects those duplicates in one export; inspect
        # each variant above, and reorder one representative of each number.
        reversed_by_number = {}
        for problem, _ in reversed(list(export_requirements.values())):
            reversed_by_number.setdefault(str(problem["number"]), problem)
        reversed_problems = list(reversed_by_number.values())
        for extension in ("hwpx", "docx"):
            text = self.export(reversed_problems, extension, f"{name} reversed selection")
            if text is not None:
                for problem, contents in export_requirements.values():
                    for role, expected in contents:
                        self.contains(text, expected, f"{name} reversed {extension} q{problem['number']} {role}")
                # Distinct preserved question numbers must follow the requested
                # order in both actual package formats.
                numbers = re.findall(r"(?<!\d)(\d{1,2})\s*\.", text)
                wanted = [str(problem["number"]) for problem in reversed_problems]
                cursor = 0
                for number in wanted:
                    try:
                        cursor = numbers.index(number, cursor) + 1
                    except ValueError:
                        self.check(False, f"{name} reversed {extension}: question order mismatch, expected {wanted}, got {numbers}")
                        break
                else:
                    self.check(True, f"{name} reversed {extension}: preserved order")
        print(f"  [DONE] {name}: {len(recognition.problems)} recognized instances, {len(problems)} problem-bank rows", flush=True)


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-only", action="store_true", help="Run the portable same-page regression only")
    parser.add_argument("--high1", type=Path, default=ROOT / "data/external_exam_qa/2026_june_high1/english.pdf")
    parser.add_argument("--csat", type=Path, default=ROOT / "data/external_exam_qa/2026_csat/문제지/영어/영어.pdf")
    args = parser.parse_args()
    missing: list[Path] = []
    with TestClient(main.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["Origin"] = "http://127.0.0.1"
        setup = client.post("/api/session/setup", json={"name": "English integrity test", "password": "isolated-english-integrity-2026"})
        assert setup.status_code == 200, f"Isolated account setup failed: {setup.status_code} {setup.text}"
        regression = Regression(client)
        payload, fixture_expectations = mixed_page_pdf()
        regression.case("synthetic_mixed_page", payload, 6, {(1, number): entries for number, entries in fixture_expectations.items()})
        if not args.synthetic_only:
            for name, source, count, pages_expected in (("high1", args.high1, 45, 8), ("csat", args.csat, 90, 16)):
                if not source.is_file():
                    missing.append(source)
                    print(f"  [MISSING] {source}", flush=True)
                    continue
                payload = source.read_bytes()
                with fitz.open(stream=payload, filetype="pdf") as document:
                    pages = [page.get_text("text") for page in document]
                assert len(pages) == pages_expected, f"{name}: expected {pages_expected} source pages, got {len(pages)}"
                regression.case(name, payload, count, real_expectations(pages, name), exam=name)
    print(f"English integrity: {regression.check_count} checks, {regression.export_count} real exports, {len(regression.failures)} failures")
    if regression.failures:
        print("ENGLISH_CONTENT_INTEGRITY_FAIL")
    if missing:
        print("ENGLISH_CONTENT_INTEGRITY_MISSING_SOURCES (see synthetic results above; real-source coverage unavailable)")
        return 2
    if regression.failures:
        return 1
    print("ENGLISH_CONTENT_INTEGRITY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
