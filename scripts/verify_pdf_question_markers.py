"""Source-backed regression for standalone and unspaced exam question markers."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.pdf_question_markers import question_number, shared_question_range  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def main():
    for text, expected in (("36.", 36), ("37.\n", 37), ("2.단순 관점에 대한 비판", 2),
                           ("7.연대 보증인에 대한 이해", 7), ("18.Read this passage.", 18),
                           ("1. Read the observation.", 1)):
        check(question_number(text) == expected, f"reads the printed question marker: {text!r}")
    for text in ("1.5배", "36.7", "1.2.3", "1) bright", "① 첫째", "[36~37] Read", "36...", "100. Too high"):
        check(question_number(text) is None, f"does not invent a question marker: {text!r}")
    check(shared_question_range("[36~37] 주어진 글 다음에 이어질 글의 순서") == (36, 37),
          "common instructions remain a shared passage marker")
    check(shared_question_range("［1～3］ 다음 글을 읽고 물음에 답하시오.") == (1, 3),
          "fullwidth range punctuation remains a shared passage marker")
    check(shared_question_range("[3점]") is None and shared_question_range("[7~3]") is None,
          "scores and inverted ranges are not common passages")

    # This exercises the production grouping after its marker parser is wired.
    from app.pdf_native_content import annotate_question_groups
    items = [
        {"stem": "35. Existing preceding question.", "source_page": 6},
        {"stem": "[36~37] 주어진 글 다음에 이어질 글의 순서를 고르시오.", "source_page": 6},
        {"stem": "36.", "source_page": 6},
        {"stem": "", "tables": [[["A boxed passage with the full question content."]]], "source_page": 6},
        {"stem": "① (A)-(B)-(C)", "source_page": 6},
        {"stem": "37.", "source_page": 7},
        {"stem": "The next question's own passage.", "source_page": 7},
        {"stem": "[1~3] 다음 글을 읽고 물음에 답하시오.", "source_page": 8},
        {"stem": "1. First question in the next variant.", "source_page": 8},
        {"stem": "2.단순 관점에 대한 비판으로 가장 적절한 것은?", "source_page": 8},
    ]
    original = deepcopy(items)
    expected = [SimpleNamespace(page_number=page, number=number) for page, number in ((6,35),(6,36),(7,37),(8,1),(8,2))]
    result = annotate_question_groups(items, expected)
    check(result["inventory_matches"] and result["question_count"] == 5,
          "standalone and unspaced markers match the actual source inventory")
    check(items[1]["layout"]["question_group_kind"] == items[7]["layout"]["question_group_kind"] == "shared_passage",
          "shared instructions are outside the preceding and following question boxes")
    check(items[2]["layout"]["question_group"] == items[3]["layout"]["question_group"] == items[4]["layout"]["question_group"],
          "a standalone marker owns its actual following passage and choices")
    check(items[5]["layout"]["question_number"] == 37 and items[9]["layout"]["question_group"] == "v2:q02",
          "page changes and restarted variants retain distinct source question groups")
    check(all({k:v for k,v in item.items() if k != "layout"} == old for item,old in zip(items,original)),
          "marker recovery does not manufacture or rewrite native source text")
    missing = annotate_question_groups([{"stem": "No printed marker here.", "source_page": 6}], expected)
    check(not missing["inventory_matches"] and missing["missing_question_markers"],
          "a genuinely absent printed marker still fails the inventory gate")
    print("PDF_QUESTION_MARKERS_OK")


if __name__ == "__main__":
    main()
