"""Premium numbering regression: validation and actual HWPX/DOCX XML outputs."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.exam_numbering import NumberingError, prepare_export_problems
from assess_premium_numbering import document_text


def expect_error(problems, *, code=None, reason=None, **options):
    before = deepcopy(problems)
    try:
        prepare_export_problems(problems, **options)
    except NumberingError as exc:
        assert exc.detail["message"]
        if code:
            assert exc.detail["code"] == code, exc.detail
        if reason:
            assert any(i["reason"] == reason and i["position"] == 1 for i in exc.detail["items"]), exc.detail
        assert problems == before
    else:
        raise AssertionError(f"Expected validation failure: {options}")


def verify_rules():
    normal = [{"id": 5, "number": "27", "stem": "27. 본문", "choices": ["가", "나"]}]
    for start in (0, 1000, -1, True, 1.5, "1", None):
        expect_error(normal, start_number=start, code="invalid_start_number")
    expect_error(normal, numbering_mode="random", code="invalid_numbering_mode")
    assert prepare_export_problems(normal, "sequential", 999)[0]["number"] == "999"
    expect_error(normal * 2, numbering_mode="sequential", start_number=999, code="number_range_exceeded")
    assert len(prepare_export_problems(normal * 999, "sequential")) == 999
    expect_error(normal * 1000, numbering_mode="sequential", code="number_range_exceeded")
    assert prepare_export_problems([], "sequential") == []

    for number in (None, "", "  "):
        blank = [{**normal[0], "number": number}]
        expect_error(blank, reason="missing_original_number")
        assert prepare_export_problems(blank, "sequential")[0]["number"] == "1"
    duplicate = [normal[0], {**normal[0], "id": 6}]
    expect_error(duplicate, reason="duplicate_original_number")
    assert [p["number"] for p in prepare_export_problems(duplicate, confirm_duplicate_numbers=True)] == ["27", "27"]
    assert [p["number"] for p in prepare_export_problems(duplicate, "sequential")] == ["1", "2"]

    unsupported = [
        ({"problem_type": "passage"}, "passage"),
        ({"number": "[21~23]"}, "passage"),
        ({"stem": "[21~23] 다음 글을 읽으시오."}, "passage"),
        ({"group_id": "g1"}, "group"),
        ({"layout": {"shared_passage": {"range": [21, 23]}}}, "group"),
        ({"layout": {"block_type": "problem_with_shared_passage"}}, "group"),
        ({"layout": {"continuation": True}}, "continuation"),
        ({"layout": {"source_text_flow": True}}, "source_text_flow"),
        ({"layout": {"source_page": 1, "column_index": 1}}, "source_layout"),
        ({"preserve_source_layout": True}, "source_layout"),
        ({"stem": "", "choices": [], "image_paths": ["scan.png"]}, "image_only"),
        ({"layout": {"block_type": "image_fallback"}}, "image_only"),
        ({"layout": "unknown"}, "unknown_layout"),
    ]
    for additions, reason in unsupported:
        items = [{**normal[0], **additions}]
        expect_error(items, numbering_mode="sequential", reason=reason)
        expect_error(items, numbering_mode="preserve", reason=reason)

    editable = [{**normal[0], "source_page": 1, "layout": {
        "block_type": "problem", "bbox_px": [1, 2, 100, 300], "column_index": 1,
    }}]
    assert prepare_export_problems(editable, "sequential")[0]["number"] == "1"
    for prefix in ("27. 본문", "문제 27. 본문", "27) 본문"):
        result = prepare_export_problems([{**normal[0], "stem": prefix}], "sequential")
        assert result[0]["stem"] == "본문", result
    for stem in ("27.5 + x", "27.+x", "$27.5+x$", "(27) + x", "다음은 27. 문제", "12. 다른 번호"):
        assert prepare_export_problems([{**normal[0], "stem": stem}], "sequential")[0]["stem"] == stem
    cloned = prepare_export_problems(normal, "sequential")
    cloned[0]["choices"].append("다")
    assert normal[0]["choices"] == ["가", "나"]
    assert normal[0]["stem"] == "27. 본문" and "_numbering_prepared" not in normal[0]
    print("PASS validation, unsupported inputs, prefix safety, boundaries, deep-copy isolation")


def verify_documents(folder):
    os.environ["HWP_MAKE_DATA_DIR"] = folder
    from app import docx_writer, exam_templates, hwpx_writer_v2, storage

    storage.ensure_dirs()
    sources = [
        {"number": "12", "stem": "문제 12. 첫째문항", "answer": "1", "explanation": "첫째해설"},
        {"number": "27", "stem": "27. 둘째문항", "answer": "2", "explanation": "둘째해설"},
        {"number": "5", "stem": "5) 셋째문항", "answer": "3", "explanation": "셋째해설"},
    ]
    before = deepcopy(sources)
    selected = [sources[1], sources[2], sources[0]]
    template = exam_templates.get_template("kice_math")
    for mode, start, labels in [("preserve", 1, ["27", "5", "12"]), ("sequential", 1, ["1", "2", "3"]), ("sequential", 21, ["21", "22", "23"])]:
        prepared = prepare_export_problems(selected, mode, start)
        expected_answers = " ".join(f"{label}. {answer}" for label, answer in zip(labels, ["2", "3", "1"]))
        assert " ".join(exam_templates.quick_answer_lines(prepared, template)[0].split()) == expected_answers
        expected_explanations = [f"{label}. 정답 {answer}" for label, answer in zip(labels, ["2", "3", "1"])]
        assert [e[0] for e in exam_templates.explanation_entries(prepared, template)] == expected_explanations
        for extension, writer in [("hwpx", hwpx_writer_v2.write_hwpx), ("docx", docx_writer.write_docx)]:
            path = Path(folder) / f"{mode}_{start}.{extension}"
            writer(path, "Premium test", prepared, "kice_math", include_answer_sheet=True)
            text = " ".join(document_text(path).split())
            markers = ["둘째문항", "셋째문항", "첫째문항"]
            assert [text.index(m) for m in markers] == sorted(text.index(m) for m in markers)
            for label, marker in zip(labels, markers):
                assert f"{label}. {marker}" in text, text
            assert expected_answers in text, text
            for heading, marker in zip(expected_explanations, ["둘째해설", "셋째해설", "첫째해설"]):
                assert text.index(heading) < text.index(marker), text
            assert sources == before, "Writer or preparation changed source objects"
            print(f"PASS {mode} start={start} {extension}: body, answer table, explanation order")

    for extension, writer in [("hwpx", hwpx_writer_v2.write_hwpx), ("docx", docx_writer.write_docx)]:
        for mode, original in [("sequential", "27"), ("preserve", "1")]:
            raw = [{"number": original, "stem": "1.5 + x의 값을 구하시오.", "answer": "3"}]
            path = Path(folder) / f"decimal_{mode}.{extension}"
            writer(path, "Decimal test", prepare_export_problems(raw, mode), "kice_math")
            assert "1.1.5+x" in "".join(document_text(path).split()), (extension, mode, document_text(path))
        # Missing answers and explanations are not invented and do not stop export.
        path = Path(folder) / f"missing.{extension}"
        writer(path, "Missing test", prepare_export_problems([{"number": "", "stem": "문항"}], "sequential"), "kice_math", include_answer_sheet=True)
        assert "1. 문항" in " ".join(document_text(path).split())
    print("PASS both writers: decimal content survives, missing answers/explanations accepted")


def main():
    verify_rules()
    with tempfile.TemporaryDirectory(prefix="hwp-premium-numbering-") as folder:
        verify_documents(folder)
    print("PREMIUM_NUMBERING_OK")


if __name__ == "__main__":
    main()
