from __future__ import annotations

import json
import sys
import time
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pdf_layout_fidelity import analyze_pdf_hwpx_fidelity  # noqa: E402
from app.pdf_layout_writer import write_pdf_structured_hwpx  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify as verify_hwpx  # noqa: E402

from hwpx.tools.package_validator import validate_editor_open_safety  # noqa: E402


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
NS = {"hp": HP, "hh": HH}

CASES = (
    ("2027_kice_june_high3", "korean"),
    ("2027_kice_june_high3", "math"),
    ("2027_kice_june_high3", "english"),
    ("2026_june_high1", "korean"),
    ("2026_june_high1", "math"),
    ("2026_june_high1", "english"),
)


def _paragraph_audit(path: Path) -> dict[str, int]:
    with zipfile.ZipFile(path) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        formats: dict[str, tuple[str, int]] = {}
        for para_pr in header.xpath(".//hh:paraPr", namespaces=NS):
            align = para_pr.find("hh:align", NS)
            margin = para_pr.find("hh:margin", NS)
            intent = margin.find("hh:intent", NS) if margin is not None else None
            formats[str(para_pr.get("id") or "0")] = (
                str(align.get("horizontal") or "") if align is not None else "",
                int(intent.get("value") or 0) if intent is not None else 0,
            )
        paragraphs = 0
        justified = 0
        indented = 0
        tables = 0
        pictures = 0
        equations = 0
        for name in archive.namelist():
            if not name.startswith("Contents/section") or not name.endswith(".xml"):
                continue
            section = etree.fromstring(archive.read(name))
            tables += len(section.findall(f".//{{{HP}}}tbl"))
            pictures += len(section.findall(f".//{{{HP}}}pic"))
            equations += len(section.findall(f".//{{{HP}}}equation"))
            for paragraph in section.findall(f".//{{{HP}}}p"):
                paragraphs += 1
                alignment, intent = formats.get(str(paragraph.get("paraPrIDRef") or "0"), ("", 0))
                justified += int(alignment == "JUSTIFY")
                indented += int(intent != 0)
        return {
            "paragraphs": paragraphs,
            "justified_paragraphs": justified,
            "first_line_indented_paragraphs": indented,
            "tables": tables,
            "pictures": pictures,
            "equations": equations,
        }


def main() -> int:
    report: dict[str, object] = {"cases": [], "failures": []}
    failures: list[str] = report["failures"]  # type: ignore[assignment]
    for group, subject in CASES:
        source = ROOT / "data" / "external_exam_qa" / group / f"{subject}.pdf"
        output_dir = source.parent / "outputs_developed"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{subject}.hwpx"
        render_dir = ROOT / "tmp" / "pdfs" / "exam_detail_developed" / group / subject
        started = time.perf_counter()
        stats = write_pdf_structured_hwpx(source, output, native_math=True)
        conversion_seconds = time.perf_counter() - started
        fidelity = analyze_pdf_hwpx_fidelity(
            source,
            output,
            render_dir,
            max_pages=int(stats.get("pages") or 0),
            target_sync_ratio=0.90,
            artifact_mode="all",
        )
        structure_issues = verify_hwpx(output, render=False)
        open_safety = validate_editor_open_safety(output)
        paragraph_audit = _paragraph_audit(output)
        case = {
            "group": group,
            "subject": subject,
            "source": str(source.relative_to(ROOT)),
            "output": str(output.relative_to(ROOT)),
            "render_dir": str(render_dir.relative_to(ROOT)),
            "conversion_seconds": round(conversion_seconds, 3),
            "output_bytes": output.stat().st_size,
            "stats": stats,
            "paragraph_audit": paragraph_audit,
            "fidelity": {
                key: fidelity.get(key)
                for key in (
                    "pdf_page_count",
                    "hwpx_page_count",
                    "pages_compared",
                    "page_count_mismatch",
                    "overall_sync_ratio",
                    "min_strict_alignment_ratio",
                    "min_foreground_overlap_ratio",
                    "overall_detailed_layout_score",
                    "minimum_detailed_layout_score",
                    "overall_harsh_layout_score",
                    "minimum_harsh_layout_score",
                    "review_flags",
                )
            },
            "structure_issues": structure_issues,
            "editor_open_safe": bool(open_safety.ok),
        }
        report["cases"].append(case)  # type: ignore[union-attr]

        prefix = f"{group}/{subject}"
        if fidelity.get("page_count_mismatch"):
            failures.append(f"{prefix}: page count mismatch")
        if int(fidelity.get("pages_compared") or 0) != int(stats.get("pages") or 0):
            failures.append(f"{prefix}: not all pages compared")
        if structure_issues:
            failures.append(f"{prefix}: HWPX structure issues: {structure_issues[:3]}")
        if not open_safety.ok:
            failures.append(f"{prefix}: editor-open safety failed: {open_safety.summary}")
        if float(stats.get("editable_text_coverage_ratio") or 0.0) < 0.99:
            failures.append(f"{prefix}: editable text coverage below 99%")
        if int(stats.get("full_page_images") or 0) > 0:
            failures.append(f"{prefix}: full-page raster image used")
        if output.stat().st_size / max(1, int(stats.get("pages") or 0)) > 1_000_000:
            failures.append(f"{prefix}: output exceeds 1 MB per page")
        if float(fidelity.get("min_strict_alignment_ratio") or 0.0) < 0.96:
            failures.append(f"{prefix}: raw strict alignment below 96%")
        if float(fidelity.get("min_foreground_overlap_ratio") or 0.0) < 0.97:
            failures.append(f"{prefix}: raw foreground overlap below 97%")
        if subject in {"korean", "english"} and paragraph_audit["justified_paragraphs"] <= 0:
            failures.append(f"{prefix}: no justified body paragraphs")
        if subject == "math":
            if int(stats.get("math_visual_overlays") or 0) <= 0:
                failures.append(f"{prefix}: no math visual overlays")
            if float(fidelity.get("min_strict_alignment_ratio") or 0.0) < 0.94:
                failures.append(f"{prefix}: strict math alignment below 94%")
            if float(fidelity.get("min_foreground_overlap_ratio") or 0.0) < 0.80:
                failures.append(f"{prefix}: math foreground overlap below 80%")
            if not stats.get("positioned_native_math_enabled"):
                failures.append(f"{prefix}: positioned native math disabled")
            if int(stats.get("positioned_native_equations") or 0) <= 0:
                failures.append(f"{prefix}: no positioned native equations")
            if float(stats.get("native_math_coverage_ratio") or 0.0) < 0.90:
                failures.append(f"{prefix}: native math coverage below 90%")

    report["total_conversion_seconds"] = round(
        sum(float(case["conversion_seconds"]) for case in report["cases"]),  # type: ignore[index]
        3,
    )
    total_pages = sum(
        int(case["fidelity"]["pages_compared"] or 0)  # type: ignore[index]
        for case in report["cases"]  # type: ignore[union-attr]
    )
    weighted_detail = sum(
        float(case["fidelity"]["overall_harsh_layout_score"] or 0.0)  # type: ignore[index]
        * int(case["fidelity"]["pages_compared"] or 0)  # type: ignore[index]
        for case in report["cases"]  # type: ignore[union-attr]
    )
    minimum_detail = min(
        (
            float(case["fidelity"]["minimum_harsh_layout_score"] or 0.0)  # type: ignore[index]
            for case in report["cases"]  # type: ignore[union-attr]
        ),
        default=0.0,
    )
    report["first_pass_targets"] = {
        "average_target": 97.0,
        "minimum_target": 95.0,
        "weighted_average_harsh_layout_score": round(
            weighted_detail / max(1, total_pages), 2
        ),
        "minimum_harsh_layout_score": round(minimum_detail, 2),
        "pages": total_pages,
    }
    if weighted_detail / max(1, total_pages) < 97.0:
        failures.append("first-pass weighted average harsh score below 97")
    if minimum_detail < 95.0:
        failures.append("first-pass minimum harsh score below 95")
    report_path = ROOT / "data" / "external_exam_qa" / "developed_detail_quality_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
