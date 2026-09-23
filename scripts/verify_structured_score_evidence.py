"""A low-quality render cannot receive a high overall structure-only score."""
# ruff: noqa: E402
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import _pdf_structured_objective_score


def main():
    stats = dict(paragraphs=10, source_problem_count=2, output_problem_count=2,
                 source_layout_coverage_ratio=1, editable_text_coverage_ratio=1,
                 source_text_preservation_ratio=1)
    style = dict(available=True)
    def score(fidelity):
        return _pdf_structured_objective_score(stats=stats, style_profile=style,
                                              open_safety={"ok": True}, fidelity=fidelity)
    poor = score({"available": True, "overall_harsh_layout_score": 12.5})
    assert poor["structure_objective_score"] > 12.5, poor
    assert poor["objective_score"] == 12.5, poor
    assert poor["meets_objective_score_target"] is False
    for fidelity in ({"available": False}, {"available": True},
                     {"available": True, "skipped": True, "overall_harsh_layout_score": 100}):
        result = score(fidelity)
        assert result["objective_score"] is None and not result["objective_score_available"], result
    stats['draw_text_boxes'] = 20
    stats['verified_question_units'] = {
        'ok':True,'question_count':2,'source_inline_label_count':8,'source_graph_annotation_count':10}
    verified = score({'available':True,'overall_harsh_layout_score':100})
    stats['verified_question_units']['source_graph_annotation_count'] = 9
    mismatch = score({'available':True,'overall_harsh_layout_score':100})
    assert verified['score_components']['layout']['score'] == mismatch['score_components']['layout']['score']+25
    stats['verified_question_units'].update(ok=False,source_graph_annotation_count=10)
    failed = score({'available':True,'overall_harsh_layout_score':100})
    assert failed['score_components']['layout']['score'] == mismatch['score_components']['layout']['score']
    print("STRUCTURED_SCORE_EVIDENCE_OK: visual loss caps overall score; missing render remains unverified")


if __name__ == "__main__":
    main()
