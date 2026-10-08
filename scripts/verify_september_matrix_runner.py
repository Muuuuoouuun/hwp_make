"""Missing source/evidence and unmet quality targets cannot pass the matrix."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_september_exam_matrix import evaluate_evidence, freeze_source, summarize


def main() -> int:
    inventory = {"sha256": "fixed-source", "physical_pages": 2,
                 "question_ids": ["v1:q01", "v1:q02"]}
    audit = {"ok": True, "native_source_text_coverage": 1.0, "rasterized_prose": [],
             "question_units": {"question_ids": inventory["question_ids"]}}
    evidence = {"http_status": 200, "output_exists": True, "source_sha256_after": "fixed-source",
        "renderer_before": {"available": True}, "renderer_changed_during_case": False,
        "quality": {"objective_score_target": 98.0, "objective_score": 99.0,
                    "meets_objective_score_target": True, "review": {"ok": True}, "editability": {"ok": True}},
        "fidelity": {"available": True, "pdf_page_count": 2, "hwpx_page_count": 2,
                     "pages_compared": 2, "page_count_mismatch": False, "truncated": False,
                     "overall_layout_view_sync_ratio": 0.99, "overall_harsh_layout_score": 99.0,
                     "minimum_harsh_layout_score": 98.0, "min_strict_alignment_ratio": 0.99,
                     "min_foreground_overlap_ratio": 0.98},
        "independent_editability": audit, "independent_rendering": {"ok": True},
        "independent_open_safety": {"ok": True}, "rendered_page_count": 2,
        "stats": {"full_page_images": 0, "full_page_raster_fallback": False,
                  "text_visual_overlays": 0, "math_visual_overlays": 0}}
    assert evaluate_evidence(inventory, evidence)["failures"] == []
    for key, value in (('renderer_before', {}), ('renderer_changed_during_case', True),
                       ('renderer_changed_during_case', None)):
        changed = deepcopy(evidence); changed[key] = value
        assert any(name.startswith('renderer_runtime') for name in evaluate_evidence(inventory, changed)['failures'])
    for key in ("text_visual_overlays", "math_visual_overlays"):
        invalid = deepcopy(evidence)
        del invalid["stats"][key]
        assert "no_text_or_math_visual_overlays" in evaluate_evidence(inventory, invalid)["failures"]
    low_score = deepcopy(evidence)
    low_score["quality"].update(objective_score=93.0, meets_objective_score_target=False)
    result = evaluate_evidence(inventory, low_score)
    assert result["development_93_met"] and "api_objective_at_least_98" in result["failures"]
    for key, replacement in (("quality", {}), ("independent_editability", {}),
                             ("independent_rendering", {}), ("independent_open_safety", {})):
        invalid = deepcopy(evidence)
        invalid[key] = replacement
        assert evaluate_evidence(inventory, invalid)["failures"], key
    for key, value in (("pages_compared", 1), ("hwpx_page_count", 1),
                       ("truncated", True), ("min_foreground_overlap_ratio", 0.96)):
        invalid = deepcopy(evidence)
        invalid["fidelity"][key] = value
        assert evaluate_evidence(inventory, invalid)["failures"], key
    invalid = deepcopy(evidence)
    invalid["independent_editability"]["native_source_text_coverage"] = 0.979
    assert "independent_native_text_at_least_98pct" in evaluate_evidence(inventory, invalid)["failures"]
    invalid = deepcopy(evidence)
    invalid["independent_editability"]["question_units"]["question_ids"] = ["v1:q01", "v2:q02"]
    assert "source_printed_question_ids_exact" in evaluate_evidence(inventory, invalid)["failures"]
    assert evaluate_evidence(inventory, {"http_status": 422})["failures"]
    assert evaluate_evidence(inventory, {})["failures"]

    records = [{"selected": True, "status": "PASS"} for _ in range(3)]
    records += [{"selected": False, "status": "NOT_RUN"} for _ in range(48)]
    partial = summarize(records, full_scope=False, errors=[], incomplete=[])
    assert partial["status"] == "PASS_SUBSET" and not partial["full_matrix_passed"]
    incomplete_all = summarize(records, full_scope=True, errors=[], incomplete=[])
    assert not incomplete_all["full_matrix_passed"] and incomplete_all["exit_code"] == 2
    records[0]["status"] = "INCOMPLETE"
    assert summarize(records, full_scope=False, errors=[], incomplete=[])["exit_code"] == 2
    records[0]["status"] = "FAIL"
    assert summarize(records, full_scope=False, errors=[], incomplete=[])["exit_code"] == 1
    assert summarize([], full_scope=True, errors=[], incomplete=["missing manifest"])["exit_code"] == 2

    import fitz
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "source.pdf"
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((60, 60), "1. First actual question", fontsize=14)
        page.insert_text((60, 80), "1. a small numbered passage list", fontsize=10)
        page.insert_text((75, 140), "2. An intentionally indented question", fontsize=14)
        pdf.save(source)
        pdf.close()
        row = {"id": "synthetic", "grade": 1, "subject": "영어", "source": str(source),
               "manifest_sha256": "registered", "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "bytes": source.stat().st_size, "pages": 1, "status": "downloaded",
               "expected_question_count": 2, "expected_number_runs": [[1, 2]]}
        frozen = freeze_source(row)
        assert not frozen["errors"] and not frozen["incomplete"], frozen
        assert frozen["question_ids"] == ["v1:q01", "v1:q02"]
        missing = freeze_source({**row, "source": str(source.with_name("missing.pdf"))})
        assert missing["incomplete"] and not missing["errors"]
        altered = freeze_source({**row, "sha256": "forged"})
        assert altered["errors"] and altered["sha256"] == row["sha256"]
        assert freeze_source({**row, "pages": 2})["errors"]
    print("SEPTEMBER_MATRIX_RUNNER_OK: source byte/page proof, real numbering vs list, missing evidence, 93/98 separation, full-scope completeness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
