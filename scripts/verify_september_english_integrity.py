"""Source-driven September 2026 English recognition/import/premium regression.

The three official EBSi PDFs and their frozen source marker manifests are the
oracle. No June/CSAT vocabulary or product splitter supplies expected content.
Every question is exported alone through the authenticated API in both formats;
shared passages cannot be rescued by an adjacent selected question.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unicodedata
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwpmake_september_english_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import main, storage  # noqa: E402
from app.recognition.pipeline import recognize_pdf  # noqa: E402

DATASETS = ("2026_september_high1", "2026_september_high2", "2027_kice_september_high3")
LABELS = "①②③④⑤"
RANGE = re.compile(r"^\s*\[\s*(\d{1,2})\s*[~～∼\-–]\s*(\d{1,2})\s*\]")
HEADER = re.compile(r"^(?:고[123]|영어\s*영역|홀수형|짝수형)$")


def normalized(text: str) -> str:
    text = re.sub(f"[{LABELS}]", "", str(text))
    return "".join(c.casefold() for c in unicodedata.normalize("NFKC", text) if c.isalnum())


def package_text(payload: bytes, extension: str) -> tuple[str, int, int]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = ["word/document.xml"] if extension == "docx" else sorted(
            (name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)),
            key=lambda name: int(re.search(r"section(\d+)", name).group(1)),
        )
        roots = [ET.fromstring(archive.read(name)) for name in names]
        def node_text(node: ET.Element) -> str:
            local = node.tag.rsplit("}", 1)[-1]
            if local in {"t", "script"}:
                return node.text or ""
            value = "".join(node_text(child) for child in node)
            return value + "\n" if local == "p" else value
        text = "\n".join(node_text(root) for root in roots)
        math = sum(node.tag.rsplit("}", 1)[-1] in {"equation", "oMath"} for root in roots for node in root.iter())
        pictures = sum(node.tag.rsplit("}", 1)[-1] in {"pic", "blip"} for root in roots for node in root.iter())
        return text, math, pictures


def glyph_text(glyphs: list[dict]) -> str:
    """Read physical glyph rows; different PDF line fragments share a row."""
    rows: list[list[dict]] = []
    for glyph in sorted(glyphs, key=lambda c: (c["baseline"], c["bbox"][0])):
        if rows and abs(glyph["baseline"] - rows[-1][0]["baseline"]) <= 3.0:
            rows[-1].append(glyph)
        else:
            rows.append([glyph])
    return "\n".join("".join(c["c"] for c in sorted(row, key=lambda c: c["bbox"][0])) for row in rows)


@dataclass
class Question:
    number: int
    page: int
    rows: list[dict] = field(default_factory=list)
    shared: list[tuple[tuple[int, int], list[dict]]] = field(default_factory=list)
    choices: list[str] = field(default_factory=list)
    stem: str = ""
    required: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"number": self.number, "source_page": self.page, "stem": self.stem,
                "choices": self.choices, "required": self.required,
                "shared_ranges": [list(span) for span, _ in self.shared]}


def source_questions(source: Path, entry: dict) -> dict[int, Question]:
    """Independent source geometry: column-major body flow and option cells.

    Question anchors are frozen straight from source glyphs in manifest.json.
    Option contents follow the five actual printed labels in source glyph row
    order. This does not call the recognizer or importer splitter.
    """
    anchors = {(row["page"], row["number"]): row for row in entry["source_question_markers"]}
    all_rows: list[dict] = []
    footer_tops: dict[tuple[int, int], float] = {}
    comparison_tables: list[dict] = []
    with fitz.open(source) as doc:
        for page in doc:
            # The source vector grid, rather than product option geometry,
            # independently fixes rows and columns of program-choice tables.
            for table in page.find_tables().tables:
                cells = table.extract()
                if (len(cells) >= 6 and len(cells[0]) >= 2
                    and [str(row[0] or "").strip() for row in cells[-5:]] == list("ABCDE")):
                    comparison_tables.append({"page": page.number + 1, "bbox": table.bbox,
                                              "body_top": table.rows[-5].bbox[1], "cells": cells[-5:]})
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    glyphs = []
                    for span in line["spans"]:
                        glyphs.extend({"c": c["c"], "bbox": c["bbox"], "baseline": c["origin"][1],
                                       "font_size": span["size"]} for c in span["chars"])
                    text = "".join(c["c"] for c in glyphs).strip()
                    if not text or HEADER.fullmatch(text):
                        continue
                    column = int(line["bbox"][0] >= page.rect.width / 2)
                    # The centered printed page fraction lies around 91% of
                    # the B4 page. Numeric table cells elsewhere are content.
                    page_fraction = (re.fullmatch(r"[0-9]{1,2}", text)
                                     and line["bbox"][1] > page.rect.height * .88
                                     and page.rect.width * .40 < line["bbox"][0] < page.rect.width * .58)
                    if (text.isdigit() and line["bbox"][1] < 130) or page_fraction:
                        continue
                    # Source printer notices and page furniture are not prose.
                    if line["bbox"][1] > page.rect.height * .94:
                        continue
                    if "확인 사항" in text or "확인사항" in text or re.search(r"이제\s*듣기\s*문제가\s*끝났", text):
                        footer_tops[(page.number + 1, column)] = min(footer_tops.get((page.number + 1, column), float("inf")), line["bbox"][1])
                        continue
                    if "이 문제지" in text and "저작권" in text:
                        continue
                    page_number = page.number + 1
                    match = re.match(r"^\s*(\d{1,2})\s*\.", text)
                    marker = None
                    if match and (page_number, int(match.group(1))) in anchors:
                        anchor = anchors[(page_number, int(match.group(1)))]
                        if abs(line["bbox"][0] - anchor["bbox"][0]) < 1 and abs(line["bbox"][1] - anchor["bbox"][1]) < 1:
                            marker = int(match.group(1))
                    all_rows.append({"text": text, "glyphs": glyphs, "bbox": line["bbox"],
                                     "page": page_number, "column": column,
                                     "question": marker, "width": page.rect.width})
    all_rows = [row for row in all_rows if row["bbox"][1] < footer_tops.get((row["page"], row["column"]), float("inf"))]
    all_rows.sort(key=lambda row: (row["page"], row["column"], round(row["bbox"][1] / 3), row["bbox"][0]))
    questions: dict[int, Question] = {}
    shared_blocks: list[tuple[tuple[int, int], list[dict]]] = []
    current: Question | None = None
    shared: tuple[tuple[int, int], list[dict]] | None = None
    for row in all_rows:
        range_match = RANGE.match(row["text"])
        if range_match:
            shared = ((int(range_match.group(1)), int(range_match.group(2))), [row])
            shared_blocks.append(shared)
            current = None
        elif row["question"] is not None:
            number = row["question"]
            if number in questions:
                raise AssertionError(f"Source oracle repeated question {number}")
            current = Question(number, row["page"], [row])
            questions[number] = current
            shared = None
        elif shared is not None:
            shared[1].append(row)
        elif current is not None:
            current.rows.append(row)
    assert sorted(questions) == entry["expected_question_numbers"], "Independent source numbering disagrees with frozen manifest"
    for question in questions.values():
        question.shared = [(span, rows) for span, rows in shared_blocks if span[0] <= question.number <= span[1]]
        for span, rows in question.shared:
            content = "\n".join(glyph_text(row["glyphs"]) for row in rows)
            question.required.append((f"shared {span[0]}-{span[1]}", normalized(content)))
        text = "\n".join(row["text"] for row in question.rows)
        first_rows = " ".join(row["text"] for _, rows in question.shared for row in rows)
        first_rows += " " + " ".join(row["text"] for row in question.rows[:4])
        inline = question.number == 25 or bool(re.search(r"밑줄\s*친\s*(?:부분|낱말)|어법상\s*틀린|주어진\s*문장.{0,65}들어가|흐름.{0,25}관계\s*없는\s*문장", first_rows))
        glyphs = [c for row in question.rows for c in row["glyphs"]]
        labels = [c for c in glyphs if c["c"] in LABELS]
        source_text = glyph_text(glyphs)
        # Listening picture Q4 has labels inside an actual illustration.
        if not inline and question.number != 4:
            assert sorted(c["c"] for c in labels) == list(LABELS), (question.number, "source five-option set is ambiguous", text)
            parts = re.split(f"([{LABELS}])", source_text)
            assert parts[1::2] == list(LABELS), (question.number, "source physical option order is ambiguous", parts)
            question.choices = [part.strip() for part in parts[2::2]]
            assert all(normalized(value) for value in question.choices), (question.number, "empty source option")
            question.stem = parts[0]
            table_matches = [table for table in comparison_tables if table["page"] == question.page
                             and all(table["body_top"] <= (c["bbox"][1] + c["bbox"][3]) / 2 <= table["bbox"][3]
                                     and c["bbox"][0] < table["bbox"][0] for c in labels)]
            assert len(table_matches) <= 1, "Source comparison table is ambiguous"
            if table_matches:
                table = table_matches[0]
                question.choices = [" ".join(str(cell or "").replace("\n", " ") for cell in row)
                                    for row in table["cells"]]
                question.stem = glyph_text([c for c in glyphs
                                           if not table["body_top"] <= (c["bbox"][1] + c["bbox"][3]) / 2 <= table["bbox"][3]])
            if re.search(r"(?m)^\s*\*", question.choices[-1]):
                last, glossary = re.split(r"(?m)^\s*(?=\*)", question.choices[-1], maxsplit=1)
                question.choices[-1] = last.rstrip()
                question.stem += "\n" + glossary
        else:
            question.stem = source_text
        if question.number == 4:
            # The complete textual prompt precedes the source drawing.
            prompt = [row for row in question.rows if any("가" <= c <= "힣" for c in row["text"])]
            question.required.append(("complete picture prompt", normalized("\n".join(row["text"] for row in prompt))))
        elif question.number == 25:
            # Chart lettering is carried by the picture. Its complete analysis
            # is source prose below the actual "The graph" line.
            prose_start = re.search(r"The\s+(?:above\s+)?graph", question.stem)
            assert prose_start, "Source chart analysis has no identifiable opening"
            analysis = re.split(r"(?m)^\s*\*", question.stem[prose_start.start():], maxsplit=1)[0]
            question.required.append(("complete editable chart analysis", normalized(analysis)))
            question.required.append(("chart prompt", normalized(question.rows[0]["text"])))
        else:
            question.required.append(("complete question stem", normalized(question.stem)))
        assert all(content for _, content in question.required), (question.number, "empty source region")
    return questions


class Regression:
    def __init__(self, client: TestClient, output: Path):
        self.client = client
        self.output = output
        self.failures: list[str] = []
        self.checks = 0
        self.exports = 0
        self.cases: list[dict] = []

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.failures.append(message)
            print("[FAIL] " + message, flush=True)

    def required(self, actual: str, question: Question, label: str) -> None:
        compact = normalized(actual)
        for role, content in question.required:
            self.check(content in compact, f"{label}: missing/reordered {role} ({len(content)} chars)")

    def export(self, problems: list[dict], extension: str, name: str, save: bool = False,
               numbering_mode: str = "preserve") -> tuple[str, int, int] | None:
        response = self.client.post("/api/export", json={
            "ids": [p["id"] for p in problems], "workspace": "premium", "numbering_mode": numbering_mode,
            "title": "September 2026 English source integrity", "template_key": "kice_english",
            "format": extension, "native_math": True, "include_answer_sheet": False,
        })
        self.exports += 1
        self.check(response.status_code == 200, f"{name} {extension}: authenticated premium export HTTP {response.status_code} {response.text[:200] if response.status_code != 200 else ''}")
        if response.status_code != 200:
            return None
        if save:
            (self.output / f"{name}.{extension}").write_bytes(response.content)
        try:
            return package_text(response.content, extension)
        except Exception as exc:
            self.check(False, f"{name} {extension}: invalid package {type(exc).__name__}: {exc}")
            return None

    def case(self, dataset: str, source: Path, entry: dict, questions: dict[int, Question]) -> None:
        started = time.perf_counter()
        before = len(self.failures)
        payload = source.read_bytes()
        recognition = recognize_pdf(payload, filename=f"{dataset}_english.pdf")
        by_number = {p.number: p for p in recognition.problems}
        self.check(len(recognition.problems) == 45 and sorted(by_number) == list(range(1, 46)), f"{dataset}: recognition must preserve all 45 source questions exactly once")
        for number, question in questions.items():
            problem = by_number.get(number)
            self.check(problem is not None, f"{dataset} recognition q{number}: missing")
            if problem is not None:
                self.check(problem.page_number == question.page, f"{dataset} recognition q{number}: wrong source page")
                self.check(problem.source_literal_text, f"{dataset} recognition q{number}: actual English source proof is absent")
                self.required(problem.shared_passage_text + "\n" + problem.text, question, f"{dataset} recognition q{number}")
                for choice in question.choices:
                    self.check(normalized(choice) in normalized(problem.text), f"{dataset} recognition q{number}: source option lost/reordered {choice!r}")
                if number in (4, 25):
                    self.check(bool(problem.figure_pngs), f"{dataset} recognition q{number}: source illustration/chart missing")
        response = self.client.post("/api/import", json={
            "kind": "pdf", "filename": f"{dataset}_english.pdf", "data_base64": base64.b64encode(payload).decode("ascii"),
            "metadata": {"math_ai_recognition": False, "allow_remote": False},
        })
        self.check(response.status_code == 200, f"{dataset}: authenticated import HTTP {response.status_code}")
        if response.status_code != 200:
            return
        imported = response.json()
        problems = {item["id"]: storage.get_problem(item["id"]) for item in [*imported.get("created", []), *imported.get("existing", [])]}
        stored = {int(p["number"]): p for p in problems.values() if str(p.get("number", "")).isdigit()}
        self.check(len(problems) == 45 and sorted(stored) == list(range(1, 46)), f"{dataset}: import must retain all 45 source questions exactly once")
        for number, question in questions.items():
            problem = stored.get(number)
            self.check(problem is not None, f"{dataset} import q{number}: missing")
            if problem is None:
                continue
            self.check(problem.get("source_page") == question.page, f"{dataset} import q{number}: wrong source page")
            self.check((problem.get("layout") or {}).get("source_literal_text") is True, f"{dataset} import q{number}: source proof was lost at storage boundary")
            self.required(problem.get("stem", ""), question, f"{dataset} import q{number}")
            actual_choices = problem.get("choices") or []
            self.check([normalized(c) for c in actual_choices] == [normalized(c) for c in question.choices], f"{dataset} import q{number}: choice bodies/order differ: expected {question.choices!r}, actual {actual_choices!r}")
            source_problem = by_number.get(number)
            if source_problem:
                source_dollars = (source_problem.shared_passage_text + source_problem.text).count("$")
                self.check((problem.get("stem", "") + "".join(actual_choices)).count("$") == source_dollars, f"{dataset} import q{number}: literal currency changed or math fences appeared")
            # Every source instance is inspected alone, including 42/44/45.
            for extension in ("hwpx", "docx"):
                label = f"{dataset}-q{number:02d}"
                package = self.export([problem], extension, label, save=number in (6, 25, 29, 30, 34, 40, 41, 42, 43, 44, 45))
                if package is None:
                    continue
                text, math_count, picture_count = package
                self.required(text, question, f"{label} {extension} alone")
                self.check(math_count == 0, f"{label} {extension}: English prose became {math_count} equation objects")
                for index, choice in enumerate(question.choices):
                    self.check(normalized(choice) in normalized(text), f"{label} {extension}: source choice {index + 1} is absent")
                if "$" in question.stem or any("$" in c for c in question.choices):
                    expected_dollars = question.stem.count("$") + sum(c.count("$") for c in question.choices)
                    self.check(text.count("$") == expected_dollars, f"{label} {extension}: literal currency glyph count changed")
                if number in (4, 25):
                    self.check(picture_count > 0, f"{label} {extension}: no actual picture object")
                own_shared = {span for span, _ in question.shared}
                for other in questions.values():
                    for (span, _), (role, content) in zip(other.shared, other.required):
                        if span not in own_shared and len(content) >= 100:
                            self.check(content not in normalized(text), f"{label} {extension}: unrelated {role} leaked into singleton")
        selected = [stored[n] for n in sorted(stored)]
        for ordered, order_name in ((selected, "full"), (list(reversed(selected)), "reverse")):
            for extension in ("hwpx", "docx"):
                package = self.export(ordered, extension, f"{dataset}-{order_name}", save=True)
                if package:
                    text, _, _ = package
                    for question in questions.values():
                        self.required(text, question, f"{dataset} {order_name} {extension}")
                    printed = re.findall(r"(?<!\d)(\d{1,2})\s*\.", text)
                    cursor = 0
                    for problem in ordered:
                        number = str(problem["number"])
                        try:
                            cursor = printed.index(number, cursor) + 1
                        except ValueError:
                            self.check(False, f"{dataset} {order_name} {extension}: requested preserved numbering order is missing q{number}")
                            break
                    else:
                        self.check(True, f"{dataset} {order_name} {extension}: preserved order")
        # The actual UI starts with sequential numbering, so preserve-only
        # tests must not conceal a default whole-selection validation blocker.
        for extension in ("hwpx", "docx"):
            package = self.export(selected, extension, f"{dataset}-ui-sequential", save=True, numbering_mode="sequential")
            if package:
                text, _, _ = package
                for question in questions.values():
                    self.required(text, question, f"{dataset} UI sequential {extension}")
        self.cases.append({"dataset": dataset, "recognized_count": len(recognition.problems), "imported_count": len(problems), "source_questions": len(questions), "failure_count": len(self.failures) - before, "seconds": time.perf_counter() - started})
        print(f"[DONE] {dataset}: source {len(questions)}, recognition {len(recognition.problems)}, import {len(problems)}, {len(self.failures) - before} failures", flush=True)


def verify_literal_guards(regression: Regression) -> None:
    """Actual source headers/fonts prove the bank gate independently of names."""
    prose = ("Compare financial(A), memories(a), and financial(A^2).",
             "The prices are $40 and $50, respectively.",
             "Choose (A), (B), or (C); keep CO2 and x2 as English labels.")

    def pdf(areas: list[str], *, equation_font: Path | None = None) -> bytes:
        with fitz.open() as document:
            for index, area in enumerate(areas, 1):
                page = document.new_page(width=842, height=1191)
                if area:
                    page.insert_text((280, 100), area, fontname="korea", fontsize=28)
                page.insert_text((85, 240), f"{index}. Source guard page {index}.", fontname="tiro", fontsize=13)
                for line, text in enumerate(prose):
                    page.insert_text((85, 270 + line * 24), text, fontname="tiro", fontsize=11)
                if area != "영어 영역":
                    page.insert_text((85, 365), "f(x) and $x^{2}$", fontname="tiro", fontsize=11)
                if equation_font:
                    page.insert_font(fontname="equation_source", fontfile=str(equation_font))
                    page.insert_text((85, 395), "f(x)", fontname="equation_source", fontsize=12)
            return document.tobytes()

    english = pdf(["영어 영역"])
    recognized = recognize_pdf(english, filename="neutral.pdf").problems
    regression.check(len(recognized) == 1 and recognized[0].source_literal_text,
                     "literal guard: actual English source with neutral filename lacks proof")
    response = regression.client.post("/api/import", json={
        "kind": "pdf", "filename": "neutral.pdf", "data_base64": base64.b64encode(english).decode("ascii"),
        "metadata": {"math_ai_recognition": False, "allow_remote": False},
    })
    regression.check(response.status_code == 200, "literal guard: neutral English import failed")
    created = response.json().get("created", []) if response.status_code == 200 else []
    regression.check(len(created) == 1, "literal guard: neutral English import did not create exactly one item")
    if created:
        problem = storage.get_problem(created[0]["id"])
        regression.check(problem["layout"].get("source_literal_text") is True,
                         "literal guard: source proof did not reach bank storage")
        for extension in ("hwpx", "docx"):
            package = regression.export([problem], extension, "synthetic-neutral-english", save=True)
            if package:
                text, equations, _ = package
                regression.check(equations == 0, f"literal guard {extension}: prose became an equation")
                for expected in prose:
                    regression.check(normalized(expected) in normalized(text),
                                     f"literal guard {extension}: literal source phrase changed: {expected}")
                regression.check(text.count("$") == 2, f"literal guard {extension}: $40/$50 glyphs changed")

    math = recognize_pdf(pdf(["수학 영역"]), filename="english.pdf").problems
    regression.check(bool(math) and not any(p.source_literal_text for p in math),
                     "literal guard: actual math area lost to an English filename")
    mixed = recognize_pdf(pdf(["영어 영역", "수학 영역", ""]), filename="english.pdf").problems
    regression.check([(p.page_number, p.source_literal_text) for p in mixed]
                     == [(1, True), (2, False), (3, False)],
                     "literal guard: latest actual math area did not carry to a headerless continuation")
    candidates = (Path("C:/Windows/Fonts/HancomEQN.ttf"), Path("C:/Windows/Fonts/HYHWPEQ.TTF"))
    font = next((p for p in candidates if p.is_file()), None)
    if font:
        equation = recognize_pdf(pdf(["영어 영역"], equation_font=font), filename="neutral.pdf").problems
        regression.check(bool(equation) and not any(p.source_literal_text for p in equation),
                         "literal guard: genuine source equation font was labeled literal")
    else:
        print("SKIP optional bank equation-font source fixture: font file unavailable", flush=True)

    # A genuine nonliteral bank item continues to use the ordinary math path.
    for source in ("f(x)", "$x^{2}$"):
        problem = storage.create_problem({"number": "1", "stem": source, "choices": [],
                                          "layout": {"block_type": "problem", "source_literal_text": False}})
        for extension in ("hwpx", "docx"):
            package = regression.export([problem], extension, "synthetic-math-negative")
            if package:
                regression.check(package[1] > 0, f"literal guard {extension}: genuine {source} lost equation behavior")


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tmp/september-2026-english-integrity")
    parser.add_argument("--oracle-only", action="store_true", help="Freeze source-only expectations without running the product")
    parser.add_argument("--literal-only", action="store_true", help="Run portable source-proof/math negative cases only")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for dataset in DATASETS:
        manifest_path = ROOT / "data/external_exam_qa" / dataset / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry, = [entry for entry in manifest["files"] if entry["subject"] == "영어"]
        source = ROOT / entry["source_path"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["sha256"], f"Source SHA mismatch: {dataset}"
        questions = source_questions(source, entry)
        (output / f"{dataset}-source-oracle.json").write_text(json.dumps({"source_sha256": entry["sha256"], "questions": [questions[n].to_dict() for n in sorted(questions)]}, ensure_ascii=False, indent=2), encoding="utf-8")
        cases.append((dataset, source, entry, questions))
        print(f"[SOURCE] {dataset}: {len(questions)} questions, {sum(bool(q.choices) for q in questions.values())} independent five-option sets", flush=True)
    if args.oracle_only:
        print("SEPTEMBER_ENGLISH_SOURCE_ORACLE_OK")
        return 0
    with TestClient(main.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["Origin"] = "http://127.0.0.1"
        setup = client.post("/api/session/setup", json={"name": "September English integrity", "password": "isolated-september-english-integrity-2026"})
        assert setup.status_code == 200, f"Isolated authenticated account setup failed: {setup.status_code} {setup.text}"
        regression = Regression(client, output)
        verify_literal_guards(regression)
        if not args.literal_only:
            for case in cases:
                regression.case(*case)
    report = {"checks": regression.checks, "real_authenticated_premium_exports": regression.exports,
              "source_question_count": 0 if args.literal_only else 135, "scope": "literal_only" if args.literal_only else "english3",
              "failures": regression.failures, "cases": regression.cases, "status": "pass" if not regression.failures else "fail"}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "failures"}, ensure_ascii=False))
    print("SEPTEMBER_ENGLISH_INTEGRITY_OK" if not regression.failures else "SEPTEMBER_ENGLISH_INTEGRITY_FAIL")
    return bool(regression.failures)


if __name__ == "__main__":
    raise SystemExit(run())
