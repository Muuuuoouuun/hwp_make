"""Verify English passage markers and physically fragmented answer options.

Synthetic cases always run. The two local real exam PDFs also exercise the
complete editor import when available; storage is isolated in a temporary folder.
"""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_TMP = tempfile.TemporaryDirectory(prefix="hwpmake_english_choices_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = _TMP.name

from app import importers, storage  # noqa: E402
from app.recognition.pipeline import recognize_pdf  # noqa: E402


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def line(text: str, x: float, y: float, width: float = 100, height: float = 20) -> dict:
    return {"text": text, "bbox_px": [x, y, width, height]}


def words(text: str) -> Counter:
    return Counter(re.findall(r"[A-Za-z가-힣0-9]+", text))


def choice_key(choices: list[str]) -> tuple[str, ...]:
    return tuple(re.sub(r"[^A-Za-z가-힣0-9]", "", choice).casefold() for choice in choices)


def split(lines: list[dict]) -> tuple[str, list[str]]:
    text = "\n".join(row["text"] for row in lines)
    stem, choices = importers._split_english_stem_and_choices(text, lines)
    check(words(text) == words(stem + "\n" + "\n".join(choices)), "split lost or duplicated source words")
    return stem, choices


def synthetic() -> None:
    # One printed sentence can arrive as a title block plus many one-word PDF
    # lines. The title bbox spans the question; its glyph bbox proves the row.
    title = line("34. A", 0, 100, 500, 400)
    title["pdf_line_chars"] = [{"c": "34. A", "bbox": [0, 100, 45, 120]}]
    rows = [title, line("powerful", 160, 100), line("particularly", 50, 100),
            line("way in which human", 250, 100), line("beings adapt to their circumstances.", 0, 130, 500)]
    for with_choices in (False, True):
        selected = rows + ([line(f"{label}answer {index}", 0, 180 + index * 30, 300)
                           for index, label in enumerate("①②③④⑤")] if with_choices else [])
        stem, choices = split(selected)
        check("34. A particularly powerful way in which human\nbeings adapt" in stem,
              "same-baseline words stayed in separate paragraphs or the next row was merged")
        check(len(choices) == (5 if with_choices else 0), "row joining changed choice separation")

    # A line break before ⑤ must not move the rest of this sentence out of the
    # passage. The same holds even when every marked phrase starts a new line.
    for prompt in ("29. 다음 글의 밑줄 친 부분 중, 어법상 틀린 것은?",
                   "30. 다음 글의 밑줄 친 부분 중, 문맥상 낱말의 쓰임이 적절하지 않은 것은?"):
        rows = [line(prompt, 0, 0, 500)] + [
            line(f"{label}{body}", 0, 40 + index * 30, 500)
            for index, (label, body) in enumerate(zip("①②③④⑤", (
                "Reading connects people", "focus on a story", "carry its meaning",
                "share the emotion", "reflected in the pages of a book")))
        ]
        stem, choices = split(rows)
        check(not choices and "⑤reflected in the pages" in stem, "in-passage grammar/vocabulary labels became choices")

    stem, choices = split([line("25. 다음 도표의 내용과 일치하지 않는 것은?", 0, 0, 500),
                           line("A survey. ①First. ②Second. ③Third. ④Fourth.", 0, 40, 500),
                           line("⑤The percentage is higher", 0, 70, 500)])
    check(not choices and "⑤The percentage" in stem, "partial standalone label set stole a passage line")

    # Real PDFs emit words before their labels and vary the baseline by font.
    rows = [line("40. 빈칸 (A), (B)에 들어갈 말은?", 0, 0, 500)]
    expected = ["uncertainty …… lose", "imbalance …… split", "challenges …… secure",
                "stability …… reach", "advantages …… support"]
    for index in (1, 0, 3, 2, 4):
        x, y = (index % 2) * 300, 100 + (index // 2) * 35
        first, separator, second = expected[index].split()
        rows += [line(first, x + 30, y - 4, 110), line(second, x + 180, y - 4),
                 line("①②③④⑤"[index], x, y, 20), line(separator, x + 145, y, 30)]
    stem, choices = split(rows)
    check(choices == expected, f"A/B pairs were not reconstructed by row and x: {choices!r}")
    check("uncertainty" not in stem and "lose" not in stem, "choice fragments leaked into the stem")

    rows = [line("36. 순서에 맞게 배열한 것은?", 0, 0, 500)]
    for index, sequence in enumerate(("ACB", "BAC", "BCA", "CAB", "CBA")):
        x, y = (index % 2) * 300, 100 + (index // 2) * 35
        rows += [line(f"({sequence[2]})", x + 170, y - 4, 30),
                 line(f"({sequence[0]})", x + 35, y - 4, 30),
                 line(f"({sequence[1]})", x + 100, y - 4, 30),
                 line("-", x + 75, y, 20), line("-", x + 140, y, 20),
                 line("①②③④⑤"[index], x, y, 20)]
    check(split(rows)[1] == ["(A) - (C) - (B)", "(B) - (A) - (C)", "(B) - (C) - (A)",
                            "(C) - (A) - (B)", "(C) - (B) - (A)"], "permutation choices stayed fragmented")

    # A long option wraps under its label; the next passage remains in the stem.
    rows = [line("41. 글의 제목은?", 0, 0, 500)]
    for index, label in enumerate("①②③④⑤"):
        rows += [line(f"{label}A long title {index}", 0, 80 + index * 70, 300),
                 line("continued on another line", 25, 110 + index * 70, 300)]
    rows += [line("[43~45] 다음 글을 읽고 물음에 답하시오.", 0, 440, 500)]
    stem, choices = split(rows)
    check(all(choice.endswith("continued on another line") for choice in choices), "wrapped option text was not joined")
    check("[43~45]" in stem, "next passage heading was absorbed by the final option")
    for markers in ("❶❷❸❹❺", "➀➁➂➃➄"):
        rows = [line("1. 알맞은 응답은?", 0, 0, 300)] + [
            line(f"{marker}answer {index}", 0, 40 + index * 30, 300)
            for index, marker in enumerate(markers)
        ]
        check(split(rows)[1] == [f"answer {index}" for index in range(5)], "alternative circled font markers lost choices")
    rows.append({"text": "A source line with missing geometry"})
    stem, choices = split(rows)
    check("A source line with missing geometry" in stem and not choices, "incomplete geometry dropped source text")
    print("PASS: synthetic English markers, A/B pairs, permutations, wrapped choices, word preservation")


def english_literal_import() -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 50), "English", fontsize=12)
    literals = ["1. A particularly powerful example.", "Don't split don't into variables.",
                "Schedule: 9 a.m. - 12 p.m.", "Choose (A) and (B). CO2 is mentioned."]
    for index, text in enumerate(literals):
        page.insert_text((40, 120 + index * 30), text, fontsize=10)
    payload = document.tobytes()
    document.close()
    # An official English page header must isolate the prose path even with a
    # neutral upload filename. These math-only operations must not run at all.
    with patch("app.importers._repair_pdf_stem_fractions_from_geometry", side_effect=AssertionError("English used math fraction repair")), \
         patch("app.importers.reading_order_line_geometries", side_effect=AssertionError("English used math reading-order repair")), \
         patch("app.importers.repair_problem_math_layout", side_effect=AssertionError("English used formula fencing")):
        imported = importers.import_pdf("literal.pdf", payload, {})
    problem, = imported["created"]
    for text in literals:
        check(text in problem["stem"], f"English literal text changed: {text!r}")
    check("$" not in problem["stem"], "English prose acquired a math fence")
    check(not problem["layout"]["math_geometry_repairs"], "English recorded math geometry repairs")
    print("PASS: header-detected English import preserves articles, contractions, times, A/B labels and CO2")


def real_pdf(source: Path, expected_pairs: list[tuple[str, str]]) -> bool:
    if not source.exists():
        print(f"SKIP: local real PDF missing: {source.relative_to(ROOT)}")
        return False
    payload = source.read_bytes()
    recognized = recognize_pdf(payload, filename=source.name)
    source_variants: dict[str, set[tuple[str, ...]]] = {}
    for problem in recognized.problems:
        split(problem.line_geometries)
        choices = importers._split_english_stem_and_choices(problem.text, problem.line_geometries)[1]
        source_variants.setdefault(str(problem.number), set()).add(choice_key(choices))
    # Odd/even forms reorder the same A/B pairs. Their source x/y positions
    # independently determine the expected label order for each source page.
    pair_orders: dict[int, list[tuple[str, str]]] = {}
    with fitz.open(stream=payload, filetype="pdf") as document:
        for page_number in {problem.page_number for problem in recognized.problems if problem.number == 40}:
            positioned = []
            page = document[page_number - 1]
            for pair in expected_pairs:
                matches = page.search_for(pair[0])
                check(bool(matches), f"source Q40 word {pair[0]!r} missing from page {page_number}")
                rect = max(matches, key=lambda item: item.y0)
                positioned.append((rect.y0, rect.x0, pair))
            top = min(item[0] for item in positioned)
            pair_orders[page_number] = [item[2] for item in sorted(positioned,
                key=lambda item: (round((item[0] - top) / 10), item[1]))]
    imported = importers.import_pdf(source.name, payload, {"subject": "영어"})
    problems = imported["created"] + imported["existing"]
    source_by_instance = {(problem.page_number, str(problem.number)): problem for problem in recognized.problems}
    for problem in problems:
        original = source_by_instance[(problem["source_page"], str(problem["number"]))]
        source_text = original.shared_passage_text + original.text
        editable_text = problem["stem"] + "".join(problem["choices"])
        check(source_text.count("$") == editable_text.count("$"),
              f"{source.name}: Q{problem['number']} introduced formula fences into English prose")
    for number, expected_variants in source_variants.items():
        actual_variants = {choice_key(problem["choices"]) for problem in problems if str(problem["number"]) == number}
        check(expected_variants <= actual_variants,
              f"{source.name}: Q{number} discarded a source variant with different answer choices")
    for number in (29, 30, 36, 37, 40, 43):
        matches = [problem for problem in problems if str(problem["number"]) == str(number)]
        check(bool(matches), f"{source.name}: missing Q{number}")
        for problem in matches:
            choices = problem["choices"]
            if number in (29, 30):
                check(not choices, f"{source.name}: Q{number} has an independent passage choice")
                check(all(label in problem["stem"] for label in "①②③④⑤"), f"Q{number} passage marker lost")
            else:
                check(len(choices) == 5, f"{source.name}: Q{number} has {len(choices)} choices")
            if number == 40:
                for choice, (first, second) in zip(choices, pair_orders[problem["source_page"]]):
                    check(first in choice and second in choice and choice.index(first) < choice.index(second),
                          f"{source.name}: Q40 paired words separated: {choice!r}")
            if number in (36, 37, 43):
                check(all(len(re.findall(r"\([A-D]\)", choice)) == 3 for choice in choices),
                      f"{source.name}: Q{number} lost permutation items")
    if len(recognized.problems) == 45:
        check(len(problems) == 45, "high1 source did not produce all 45 questions")
        article = next(problem for problem in problems if str(problem["number"]) == "34")
        check("34. A particularly powerful way in which human" in article["stem"],
              "high1 Q34 source baseline was split into single-word paragraphs")
        repeated = importers.import_pdf(source.name, payload, {"subject": "영어"})
        check(not repeated["created"] and len(repeated["existing"]) == 45,
              "reimporting the same high1 PDF did not reuse its 45 existing questions")
    variant_numbers = [number for number, variants in source_variants.items() if len(variants) > 1]
    print(f"PASS: actual editor import {source.relative_to(ROOT)}; {len(problems)} rows, "
          f"all choice variants kept ({','.join(variant_numbers) or 'none'}), Q29/30 and five-option Q36/37/40/43")
    return True


def main() -> None:
    synthetic()
    storage.init_db()
    english_literal_import()
    actual_count = sum((
        real_pdf(ROOT / "data/external_exam_qa/2026_june_high1/english.pdf", [
            ("automatic", "support"), ("purposeful", "challenge"), ("analytical", "confirm"),
            ("detailed", "explain"), ("immediate", "alter")]),
        real_pdf(ROOT / "data/external_exam_qa/2026_csat/문제지/영어/영어.pdf", [
            ("uncertainty", "lose"), ("imbalance", "split"), ("challenges", "secure"),
            ("stability", "reach"), ("advantages", "support")]),
    ))
    print(f"English choice verification PASS (synthetic + {actual_count} real PDFs)")


if __name__ == "__main__":
    try:
        main()
    finally:
        _TMP.cleanup()
