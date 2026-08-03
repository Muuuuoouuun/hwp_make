from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import fitz  # PyMuPDF
except Exception:
    print("SKIP: PyMuPDF(fitz) unavailable")
    raise SystemExit(2)

try:
    from PIL import Image, ImageDraw
except Exception:
    print("SKIP: Pillow unavailable")
    raise SystemExit(2)

tmp = tempfile.TemporaryDirectory(prefix="hwp_make_pdf_layout_api_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = tmp.name

from fastapi.testclient import TestClient  # noqa: E402

from app import pdf_layout_fidelity  # noqa: E402
from app.main import app  # noqa: E402
from app.pdf_layout_writer import _pdf_output_text  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify  # noqa: E402

_failures: list[str] = []
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{(' - ' + detail) if detail else ''}")
    if not condition:
        _failures.append(name)


def make_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 38), "Mock English Test", fontsize=12, fontname="helv")
    page.insert_textbox(
        fitz.Rect(48, 86, 270, 250),
        "1. Read the passage and choose the best answer.\n"
        "The river was quiet, and the old bridge held the morning light.\n"
        "1) bright  2) quiet  3) narrow  4) broken  5) distant",
        fontsize=10,
        fontname="times-roman",
    )
    page.insert_textbox(
        fitz.Rect(310, 86, 540, 250),
        "2. Which sentence best completes the paragraph?\n"
        "Students compared the two maps and wrote a short explanation.\n"
        "1) However  2) Therefore  3) Likewise  4) Instead  5) Otherwise",
        fontsize=10,
        fontname="times-roman",
    )
    page.draw_rect(fitz.Rect(48, 290, 270, 380), color=(0, 0, 0), width=0.8)
    page.insert_textbox(
        fitz.Rect(58, 302, 260, 368),
        "A boxed passage should stay inside a real HWPX table cell, not overlap choices.",
        fontsize=9.5,
        fontname="times-roman",
    )
    return doc.tobytes()


def make_two_page_pdf() -> bytes:
    doc = fitz.open(stream=make_pdf(), filetype="pdf")
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 38), "Second limited page", fontsize=12, fontname="helv")
    page.insert_textbox(
        fitz.Rect(48, 86, 270, 250),
        "1. This page should be omitted when max_pages=1.",
        fontsize=10,
        fontname="times-roman",
    )
    return doc.tobytes()


def make_image_only_pdf() -> bytes:
    image = Image.new("RGB", (595, 842), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((45, 40, 550, 790), outline="black", width=3)
    draw.rectangle((80, 120, 420, 160), fill="black")
    draw.rectangle((80, 210, 360, 250), fill="black")
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=image_bytes.getvalue())
    return doc.tobytes()


def make_math_score_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 38), "Mock Math Test", fontsize=12, fontname="helv")
    page.insert_textbox(
        fitz.Rect(48, 86, 540, 190),
        "1. $f(x)=\\sqrt{x^2+1}$ and $\\min_{x\\in A} f(x)$.\n"
        "2. $P(A)=\\frac{1}{2}$, $\\lim_{x\\to0} \\frac{\\sin x}{x}=1$, and $x^2+y^2=1$.",
        fontsize=10,
        fontname="times-roman",
    )
    return doc.tobytes()


def check_metric_guards() -> None:
    source = Image.new("RGB", (360, 240), "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((60, 70, 220, 84), fill="black")
    draw.rectangle((60, 100, 160, 114), fill="black")

    blank = Image.new("RGB", source.size, "white")
    blank_metrics = pdf_layout_fidelity._page_metrics(source, blank)
    check(
        "blank output foreground detection",
        blank_metrics["source_foreground_pixels"] > 0
        and blank_metrics["output_foreground_pixels"] == 0
        and blank_metrics["foreground_overlap_ratio"] == 0.0,
        repr(blank_metrics),
    )
    check(
        "blank output strict alignment fails",
        blank_metrics["strict_alignment_ratio"]
        < pdf_layout_fidelity.STRICT_ALIGNMENT_REVIEW_THRESHOLD,
        repr(blank_metrics),
    )

    text_like = Image.new("RGB", source.size, "white")
    text_draw = ImageDraw.Draw(text_like)
    shifted = Image.new("RGB", source.size, "white")
    shifted_draw = ImageDraw.Draw(shifted)
    for x in (60, 130, 215):
        text_draw.rectangle((x, 70, x + 5, 90), fill="black")
        text_draw.rectangle((x, 106, x + 5, 126), fill="black")
        shifted_draw.rectangle((x + 40, 70, x + 45, 90), fill="black")
        shifted_draw.rectangle((x + 40, 106, x + 45, 126), fill="black")
    shifted_metrics = pdf_layout_fidelity._page_metrics(text_like, shifted)
    check(
        "shifted output foreground overlap guard",
        shifted_metrics["foreground_overlap_ratio"]
        < pdf_layout_fidelity.FOREGROUND_OVERLAP_REVIEW_THRESHOLD,
        repr(shifted_metrics),
    )


def _inspect_flow_style(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        header = ET.fromstring(archive.read("Contents/header.xml"))
        section = ET.fromstring(archive.read("Contents/section0.xml"))
    faces = {font.get("face") for font in header.findall(f".//{HH}font") if font.get("face")}
    char_metric_ok = False
    metric_heights = set()
    for char_pr in header.findall(f".//{HH}charPr"):
        ratio = char_pr.find(f"{HH}ratio")
        spacing = char_pr.find(f"{HH}spacing")
        if ratio is None or spacing is None:
            continue
        if (
            ratio.get("hangul") == "95"
            and ratio.get("latin") == "95"
            and spacing.get("hangul") == "-5"
            and spacing.get("latin") == "-5"
        ):
            char_metric_ok = True
            if char_pr.get("height"):
                metric_heights.add(char_pr.get("height"))

    para_165_ids = set()
    for para_pr in header.findall(f".//{HH}paraPr"):
        line_spacing = para_pr.find(f".//{HH}lineSpacing")
        if line_spacing is not None and line_spacing.get("type") == "PERCENT" and line_spacing.get("value") == "165":
            para_id = para_pr.get("id")
            if para_id:
                para_165_ids.add(para_id)
    uses_165 = any((para.get("paraPrIDRef") or "") in para_165_ids for para in section.findall(f".//{HP}p"))

    border_by_id = {border.get("id") or "": border for border in header.findall(f".//{HH}borderFill")}
    divider_refs = {cell.get("borderFillIDRef") or "" for cell in section.findall(f".//{HP}tc")}
    divider_ok = False
    header_bottom_ok = False
    for ref in divider_refs:
        border = border_by_id.get(ref)
        if border is None:
            continue
        right = border.find(f"{HH}rightBorder")
        left = border.find(f"{HH}leftBorder")
        top = border.find(f"{HH}topBorder")
        bottom = border.find(f"{HH}bottomBorder")
        if (
            right is not None
            and right.get("type") == "SOLID"
            and right.get("width") == "0.12 mm"
            and all(
                item is not None and (item.get("type") or "").upper() == "NONE"
                for item in (left, top, bottom)
            )
        ):
            divider_ok = True
        if (
            bottom is not None
            and bottom.get("type") == "SOLID"
            and bottom.get("width") == "0.2 mm"
            and all(
                item is not None and (item.get("type") or "").upper() == "NONE"
                for item in (left, right, top)
            )
        ):
            header_bottom_ok = True
    margin_ok = False
    for cell in section.findall(f".//{HP}tc"):
        margin = cell.find(f"{HP}cellMargin")
        if cell.get("hasMargin") == "1" and margin is not None:
            try:
                if int(margin.get("left") or "0") > 0 or int(margin.get("right") or "0") > 0:
                    margin_ok = True
                    break
            except ValueError:
                pass
    page_margin = section.find(f".//{HP}pagePr/{HP}margin")
    header_footer_zero = (
        page_margin is not None
        and page_margin.get("header") == "0"
        and page_margin.get("footer") == "0"
    )
    table_columns = {table.get("colCnt") for table in section.findall(f".//{HP}tbl")}
    return {
        "faces": faces,
        "char_metric_ok": char_metric_ok,
        "metric_heights": metric_heights,
        "uses_165": uses_165,
        "divider_ok": divider_ok,
        "header_bottom_ok": header_bottom_ok,
        "header_footer_zero": header_footer_zero,
        "separate_header_body_tables": {"2", "3"}.issubset(table_columns),
        "margin_ok": margin_ok,
    }


def main() -> int:
    try:
        check_metric_guards()
        # 병합(2026-08-03) 후 계약: PUA 복원은 _pdf_output_text 가 담당하고,
        # 위첨자 구조는 유니코드 문자가 아니라 char-layout 단계에서 처리된다.
        # 따라서 잔여 PUA 0 + 플랫 텍스트 "x3" 를 핀으로 삼는다.
        recovered = _pdf_output_text("")
        check(
            "HyhwpEQ PUA flow recovery",
            recovered == "x3" and not any(0xE000 <= ord(ch) <= 0xF8FF for ch in recovered),
            f"got {recovered!r}",
        )
        client = TestClient(app)
        rejected = client.post(
            "/api/pdf-layout-export",
            json={
                "filename": "not_pdf.txt",
                "data_base64": base64.b64encode(b"not a pdf").decode("ascii"),
                "boxed_passages": True,
            },
        )
        check("reject non-PDF", rejected.status_code == 400, rejected.text[:240])

        response = client.post(
            "/api/pdf-layout-export",
            json={
                "filename": "mock_english.pdf",
                "data_base64": base64.b64encode(make_pdf()).decode("ascii"),
                "boxed_passages": True,
                "layout_mode": "coordinate",
                "native_math": False,
            },
        )
        check("API status", response.status_code == 200, response.text[:240] if response.status_code != 200 else "")
        if response.status_code != 200:
            return 1
        payload = response.json()
        mode = payload.get("mode")
        check("mode", mode == "pdf_coordinate_hwpx", repr(mode))
        export = payload.get("export") or {}
        output_path = Path(tmp.name) / "exports" / str(export.get("name") or "")
        check("export exists", output_path.is_file(), str(output_path))
        stats = payload.get("stats") or {}
        check("stats pages", stats.get("pages") == 1, repr(stats))
        check("editable flow lines", int(stats.get("flow_lines") or 0) > 0, repr(stats))
        if mode == "pdf_flow_hwpx":
            check("header row detected", int(stats.get("header_rows") or 0) == 1, repr(stats))
            page_margins = stats.get("page_margins_mm") or {}
            check(
                "source-derived side margins",
                float(page_margins.get("left") or 0) > 7 and float(page_margins.get("right") or 0) > 7,
                repr(page_margins),
            )
        check(
            "source text line count",
            int(stats.get("source_text_lines") or 0) >= int(stats.get("flow_lines") or 0),
            repr(stats),
        )
        check("no full-page raster fallback", stats.get("full_page_raster_fallback") is False, repr(stats))
        check("no full-page images", int(stats.get("full_page_images") or 0) == 0, repr(stats))
        check(
            "editable text coverage target",
            float(stats.get("editable_text_coverage_ratio") or 0.0) >= 0.9,
            repr(stats),
        )
        quality = payload.get("quality") or {}
        check("quality target", quality.get("target_sync_ratio") == 0.94, repr(quality))
        check("quality coverage pass", quality.get("meets_editable_text_target") is True, repr(quality))
        check("visual sync target pass", bool(quality.get("meets_visual_sync_target")), repr(quality))
        check("layout-view visual sync target pass", bool(quality.get("meets_layout_view_sync_target")), repr(quality))
        check("objective score target", float(quality.get("objective_score_target") or 0.0) == 96.0, repr(quality))
        check("objective score available", bool(quality.get("objective_score_available")), repr(quality))
        check("objective score recorded", quality.get("objective_score") is not None, repr(quality))
        components = quality.get("score_components") or {}
        check(
            "objective components present",
            {"layout", "font", "math", "balance", "paging", "editable_text", "open_safety"}.issubset(
                set(components)
            ),
            repr(components),
        )
        check(
            "objective component weights",
            abs(sum(float((component or {}).get("weight") or 0.0) for component in components.values()) - 1.0)
            < 0.001,
            repr(components),
        )
        check("font template target pass", quality.get("meets_font_template_target") is True, repr(quality))
        check("native math target n/a", quality.get("meets_native_math_target") is None, repr(quality))
        check("math visual sync target", quality.get("meets_math_visual_sync_target") is True, repr(quality))
        check("paging target pass", quality.get("meets_paging_target") is True, repr(quality))
        check("page standard target pass", quality.get("meets_page_standard_target") is True, repr(quality))
        check("open safety target", quality.get("meets_open_safety_target") is True, repr(quality))
        check("quality no max-page limit", quality.get("limited_by_max_pages") is False, repr(quality))
        check("quality no full-page raster fallback", quality.get("full_page_raster_fallback") is False, repr(quality))
        check(
            "layout-view sync ratio >= 94%",
            float(quality.get("layout_view_sync_ratio") or 0.0) >= 0.94,
            repr(quality),
        )
        check(
            "whole-page visual sync ratio recorded",
            float(quality.get("whole_page_visual_sync_ratio") or 0.0) > 0.0,
            repr(quality),
        )
        check("visual review flags clean", quality.get("visual_review_flags") == [], repr(quality))
        style_profile = payload.get("style_profile") or {}
        check("style profile available", style_profile.get("available") is True, repr(style_profile))
        check("style profile font target", style_profile.get("has_required_font_faces") is True, repr(style_profile))
        check("style profile font type", style_profile.get("font_face_type_ok") is True, repr(style_profile))
        check("style profile char metrics", style_profile.get("char_metric_ok") is True, repr(style_profile))
        check("style profile font bucket", style_profile.get("font_size_bucket_ok") is True, repr(style_profile))
        check("style profile line spacing", style_profile.get("uses_165_line_spacing") is True, repr(style_profile))
        check("style profile page ratio", style_profile.get("page_ratio_ok") is True, repr(style_profile))
        check("style profile page standard", style_profile.get("page_standard_ok") is True, repr(style_profile))
        check("style profile physical page", style_profile.get("page_physical_size_ok") is True, repr(style_profile))
        check("style profile Hancom orientation", style_profile.get("page_orientation_ok") is True, repr(style_profile))
        check("style profile page standard names", style_profile.get("page_standard_names") == ["A4"], repr(style_profile))
        open_safety = payload.get("open_safety") or {}
        check("open safety ok", open_safety.get("ok") is True, repr(open_safety))
        fidelity = payload.get("fidelity") or {}
        check("fidelity has no error", not fidelity.get("error"), repr(fidelity))
        check("fidelity available", bool(fidelity.get("available")) and not fidelity.get("skipped"), repr(fidelity))
        check("fidelity pages", int(fidelity.get("pages_compared") or 0) == 1, repr(fidelity))
        check("fidelity meets target", bool(fidelity.get("meets_target")), repr(fidelity))
        check("fidelity page counts", fidelity.get("pdf_page_count") == 1 and fidelity.get("hwpx_page_count") == 1, repr(fidelity))
        check("fidelity max pages", fidelity.get("max_pages") == 1, repr(fidelity))
        check("fidelity not truncated", fidelity.get("truncated") is False, repr(fidelity))
        check("fidelity page count matched", fidelity.get("page_count_mismatch") is False, repr(fidelity))
        check("fidelity review flags clean", fidelity.get("review_flags") == [], repr(fidelity))
        check("fidelity artifact dir", str(fidelity.get("artifact_dir") or "").endswith("/fidelity_renders"), repr(fidelity))
        run = payload.get("run") or {}
        report = run.get("report") or {}
        report_path = Path(tmp.name) / "exports" / str(report.get("name") or "")
        check("run report exists", report_path.is_file(), str(report_path))
        if report_path.is_file():
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            check("run report stats", report_payload.get("stats") == stats, repr(report_payload.get("stats")))
            check("run report quality", report_payload.get("quality") == quality, repr(report_payload.get("quality")))
            check("run report fidelity", report_payload.get("fidelity") == fidelity, repr(report_payload.get("fidelity")))
            check(
                "run report style profile",
                report_payload.get("style_profile") == style_profile,
                repr(report_payload.get("style_profile")),
            )
            check(
                "run report open safety",
                report_payload.get("open_safety") == open_safety,
                repr(report_payload.get("open_safety")),
            )
        run_folder = str(run.get("folder") or "")
        expected_render_url_prefix = f"/files/exports/{quote(run_folder, safe='/')}/fidelity_renders/"
        artifact_mode = str(fidelity.get("artifact_mode") or "all")
        target_ratio = float(fidelity.get("target_sync_ratio") or 0.0)
        for page in fidelity.get("pages") or []:
            render_sizes: dict[str, tuple[int, int]] = {}
            check("fidelity page aspect ok", page.get("aspect_ratio_mismatch") is False, repr(page))
            check("fidelity page aspect delta", float(page.get("aspect_ratio_delta") or 1.0) < 0.02, repr(page))
            check("fidelity page foreground source", int(page.get("source_foreground_pixels") or 0) > 0, repr(page))
            check("fidelity page foreground output", int(page.get("output_foreground_pixels") or 0) > 0, repr(page))
            source_fg = int(page.get("source_foreground_pixels") or 0)
            output_fg = int(page.get("output_foreground_pixels") or 0)
            foreground_ratio = (output_fg / source_fg) if source_fg else 1.0
            check("fidelity page foreground ratio", 0.1 <= foreground_ratio <= 10.0, repr(page))
            page_below_target = float(page.get("layout_view_sync_ratio") or 0.0) < target_ratio
            expect_render_artifacts = artifact_mode == "all" or (
                artifact_mode == "failures" and page_below_target
            )
            for key in ("source_png", "output_png", "diff_png"):
                render_path = report_path.parent / "fidelity_renders" / str(page.get(key) or "")
                url_key = f"{key}_url"
                url = str(page.get(url_key) or "")
                if expect_render_artifacts:
                    check(f"fidelity render {key}", render_path.is_file(), str(render_path))
                    check(f"fidelity render {key} non-empty", render_path.exists() and render_path.stat().st_size > 0, str(render_path))
                    check(
                        f"fidelity render {url_key}",
                        url.startswith(expected_render_url_prefix) and ":" not in url,
                        url,
                    )
                else:
                    check(f"fidelity render {key} skipped for passing page", not render_path.exists(), str(render_path))
                    check(f"fidelity render {url_key} skipped for passing page", url == "", url)
                if render_path.is_file():
                    with Image.open(render_path) as image:
                        render_sizes[key] = image.size
                        check(f"fidelity render {key} plausible size", image.width >= 300 and image.height >= 300, repr(image.size))
            if render_sizes:
                check("fidelity render dimensions match", len(set(render_sizes.values())) == 1, repr(render_sizes))
        source_copy = ((payload.get("source") or {}).get("copy") or {})
        source_copy_path = Path(tmp.name) / "exports" / str(source_copy.get("name") or "")
        check("source copy exists", source_copy_path.is_file(), str(source_copy_path))
        if output_path.is_file():
            issues = verify(output_path, render=False)
            check("HWPX structure", not issues, "; ".join(issues[:5]))
            style = _inspect_flow_style(output_path)
            faces = style["faces"]
            check("flow font faces", {"신명 중명조", "Times New Roman", "돋움"}.issubset(faces), repr(sorted(faces)))
            check("flow char ratio/spacing", bool(style["char_metric_ok"]))
            metric_heights = set(style["metric_heights"])
            old_dense_heights = {"840", "940", "1080"}
            check(
                "flow font size buckets",
                "1000" in metric_heights and not (metric_heights & old_dense_heights),
                repr(sorted(metric_heights)),
            )
            if mode == "pdf_flow_hwpx":
                check("flow line spacing 165", bool(style["uses_165"]))
                check("flow middle divider", bool(style["divider_ok"]))
                check("flow header bottom border", bool(style["header_bottom_ok"]))
                check("zero implicit header/footer margins", bool(style["header_footer_zero"]))
                check("separate header/body tables", bool(style["separate_header_body_tables"]))
                check("flow cell margins", bool(style["margin_ok"]))
            check(
                "coordinate text lines",
                int(stats.get("text_lines") or 0) >= int(stats.get("source_text_lines") or 0),
                repr(stats),
            )
            check("coordinate line rects", int(stats.get("line_rects") or 0) >= 1, repr(stats))

        math_response = client.post(
            "/api/pdf-layout-export",
            json={
                "filename": "mock_math_score.pdf",
                "data_base64": base64.b64encode(make_math_score_pdf()).decode("ascii"),
                "boxed_passages": True,
                "layout_mode": "coordinate",
                "native_math": False,
            },
        )
        check("math score status", math_response.status_code == 200, math_response.text[:240])
        if math_response.status_code == 200:
            math_payload = math_response.json()
            math_stats = math_payload.get("stats") or {}
            math_quality = math_payload.get("quality") or {}
            math_style = math_payload.get("style_profile") or {}
            math_open_safety = math_payload.get("open_safety") or {}
            math_export = math_payload.get("export") or {}
            math_output_path = Path(tmp.name) / "exports" / str(math_export.get("name") or "")
            check("math source segments", int(math_stats.get("source_math_segments") or 0) >= 5, repr(math_stats))
            check("math visual-first mode", math_stats.get("native_math_enabled") is False, repr(math_stats))
            math_ai_accepted = int(math_stats.get("math_ai_accepted") or 0)
            math_native_equations = int(math_stats.get("native_equations") or 0)
            check(
                "math native equations match ai use",
                (math_native_equations == 0 and math_ai_accepted == 0)
                or (math_native_equations >= math_ai_accepted > 0),
                repr(math_stats),
            )
            check("math visual overlays disabled", int(math_stats.get("math_visual_overlays") or 0) == 0, repr(math_stats))
            check(
                "math visual overlay area zero",
                float(math_stats.get("math_visual_overlay_area_ratio") or 0.0) == 0.0,
                repr(math_stats),
            )
            check("math no full-page raster fallback", math_stats.get("full_page_raster_fallback") is False, repr(math_stats))
            check("math objective recorded", math_quality.get("objective_score") is not None, repr(math_quality))
            check("math native target n/a", math_quality.get("meets_native_math_target") is None, repr(math_quality))
            check("math visual target", math_quality.get("meets_math_visual_sync_target") is True, repr(math_quality))
            math_components = math_quality.get("score_components") or {}
            math_component = math_components.get("math") or {}
            check("math component visual-first", math_component.get("visual_first") is True, repr(math_component))
            check("math visual score >= 95", float(math_component.get("math_visual_score") or 0.0) >= 95.0, repr(math_component))
            check(
                "math style native equations match ai use",
                int(math_style.get("native_equations") or 0) >= math_ai_accepted,
                repr(math_style),
            )
            check("math font target", math_quality.get("meets_font_template_target") is True, repr(math_quality))
            check("math paging target", math_quality.get("meets_paging_target") is True, repr(math_quality))
            check("math open safety", math_open_safety.get("ok") is True, repr(math_open_safety))
            if math_output_path.is_file():
                math_issues = verify(
                    math_output_path,
                    render=False,
                    allow_draw_text_equations=math_ai_accepted > 0,
                )
                check("math HWPX structure", not math_issues, "; ".join(math_issues[:5]))
        limited_response = client.post(
            "/api/pdf-layout-export",
            json={
                "filename": "mock_two_page_limit.pdf",
                "data_base64": base64.b64encode(make_two_page_pdf()).decode("ascii"),
                "max_pages": 1,
                "boxed_passages": True,
                "layout_mode": "coordinate",
                "native_math": False,
            },
        )
        check("max_pages status", limited_response.status_code == 200, limited_response.text[:240])
        if limited_response.status_code == 200:
            limited_payload = limited_response.json()
            limited_stats = limited_payload.get("stats") or {}
            limited_quality = limited_payload.get("quality") or {}
            limited_fidelity = limited_payload.get("fidelity") or {}
            check("max_pages stats pages", limited_stats.get("pages") == 1, repr(limited_stats))
            check("max_pages quality limited", limited_quality.get("limited_by_max_pages") is True, repr(limited_quality))
            check("max_pages visual target", limited_quality.get("meets_visual_sync_target") is True, repr(limited_quality))
            check("max_pages layout-view target", limited_quality.get("meets_layout_view_sync_target") is True, repr(limited_quality))
            check("max_pages raw mismatch retained", limited_fidelity.get("raw_page_count_mismatch") is True, repr(limited_fidelity))
            check("max_pages mismatch allowed", limited_fidelity.get("page_count_mismatch") is False, repr(limited_fidelity))
            check("max_pages fidelity target", limited_fidelity.get("meets_target") is True, repr(limited_fidelity))

        image_response = client.post(
            "/api/pdf-layout-export",
            json={
                "filename": "mock_image_only.pdf",
                "data_base64": base64.b64encode(make_image_only_pdf()).decode("ascii"),
                "boxed_passages": True,
                "layout_mode": "coordinate",
                "native_math": False,
            },
        )
        check("image-only status", image_response.status_code == 200, image_response.text[:240])
        if image_response.status_code == 200:
            image_payload = image_response.json()
            image_stats = image_payload.get("stats") or {}
            image_quality = image_payload.get("quality") or {}
            image_export = image_payload.get("export") or {}
            image_output_path = Path(tmp.name) / "exports" / str(image_export.get("name") or "")
            check("image-only full-page image count", int(image_stats.get("full_page_images") or 0) >= 1, repr(image_stats))
            check(
                "image-only coverage fails",
                float(image_stats.get("editable_text_coverage_ratio", 1.0)) == 0.0,
                repr(image_stats),
            )
            check("image-only quality coverage fails", image_quality.get("meets_editable_text_target") is False, repr(image_quality))
            check("image-only fallback flagged", image_quality.get("full_page_raster_fallback") is True, repr(image_quality))
            check("image-only fallback count", int(image_quality.get("full_page_images") or 0) >= 1, repr(image_quality))
            check("image-only objective fails", image_quality.get("meets_objective_score_target") is False, repr(image_quality))
            if image_output_path.is_file():
                image_issues = verify(image_output_path, render=False)
                check(
                    "image-only structure catches full-page raster",
                    any("full-page raster fallback" in issue for issue in image_issues),
                    repr(image_issues),
                )
        original_rhwp = pdf_layout_fidelity.rhwp
        try:
            pdf_layout_fidelity.rhwp = None
            skipped_response = client.post(
                "/api/pdf-layout-export",
                json={
                    "filename": "mock_no_rhwp.pdf",
                    "data_base64": base64.b64encode(make_pdf()).decode("ascii"),
                    "boxed_passages": True,
                    "layout_mode": "coordinate",
                    "native_math": False,
                },
            )
        finally:
            pdf_layout_fidelity.rhwp = original_rhwp
        check("optional rhwp status", skipped_response.status_code == 200, skipped_response.text[:240])
        if skipped_response.status_code == 200:
            skipped_payload = skipped_response.json()
            skipped_fidelity = skipped_payload.get("fidelity") or {}
            skipped_quality = skipped_payload.get("quality") or {}
            check("optional rhwp fidelity skipped", skipped_fidelity.get("available") is False and skipped_fidelity.get("skipped") is True, repr(skipped_fidelity))
            check("optional rhwp visual target unknown", skipped_quality.get("meets_visual_sync_target") is None, repr(skipped_quality))
            check("optional rhwp layout-view target unknown", skipped_quality.get("meets_layout_view_sync_target") is None, repr(skipped_quality))
            skipped_report = ((skipped_payload.get("run") or {}).get("report") or {})
            skipped_report_path = Path(tmp.name) / "exports" / str(skipped_report.get("name") or "")
            check("optional rhwp report exists", skipped_report_path.is_file(), str(skipped_report_path))
            if skipped_report_path.is_file():
                skipped_report_payload = json.loads(skipped_report_path.read_text(encoding="utf-8"))
                check(
                    "optional rhwp report fidelity",
                    skipped_report_payload.get("fidelity") == skipped_fidelity,
                    repr(skipped_report_payload.get("fidelity")),
                )
        history = client.get("/api/exports")
        check("export history status", history.status_code == 200, history.text[:240])
        if history.status_code == 200:
            history_items = history.json().get("items") or []
            check(
                "export history includes nested HWPX",
                any(item.get("name") == export.get("name") for item in history_items),
                repr(history_items[:3]),
            )
        delete_response = client.delete(f"/api/exports/{quote(str(export.get('name') or ''), safe='')}")
        check("delete nested export", delete_response.status_code == 200, delete_response.text[:240])
        check("deleted nested HWPX missing", not output_path.exists(), str(output_path))
        return 1 if _failures else 0
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    code = main()
    if code == 0:
        print("PDF_LAYOUT_EXPORT_API_OK")
    else:
        print(f"PDF_LAYOUT_EXPORT_API_FAIL ({len(_failures)}): {', '.join(_failures)}")
    raise SystemExit(code)
