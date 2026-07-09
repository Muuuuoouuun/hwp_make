"""Render-based PDF to HWPX layout fidelity checks."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageChops, ImageFilter, ImageStat

try:
    import rhwp
except Exception:  # pragma: no cover - optional runtime dependency
    rhwp = None

STRICT_ALIGNMENT_REVIEW_THRESHOLD = 0.75
FOREGROUND_OVERLAP_REVIEW_THRESHOLD = 0.10
ASPECT_RATIO_TOLERANCE = 0.02
LAYOUT_VIEW_BLUR_RADIUS = 1.0


def _render_hwpx_page(document: Any, page_index: int) -> Image.Image:
    png = bytes(document.render_png(page_index))
    if not png:
        raise RuntimeError(f"rhwp returned an empty PNG for page {page_index + 1}")
    return Image.open(io.BytesIO(png)).convert("RGB")


def _render_pdf_page(page: fitz.Page, target_size: tuple[int, int]) -> Image.Image:
    width, height = target_size
    scale_x = width / float(page.rect.width)
    scale_y = height / float(page.rect.height)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale_x, scale_y), alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    if image.size != target_size:
        image = image.resize(target_size, Image.Resampling.BICUBIC)
    return image


def _foreground_mask(image: Image.Image, threshold: int = 245) -> Image.Image:
    gray = image.convert("L")
    return gray.point(lambda pixel: 255 if pixel < threshold else 0, mode="L")


def _foreground_count(mask: Image.Image) -> int:
    histogram = mask.histogram()
    return int(histogram[255]) if len(histogram) > 255 else 0


def _intersection_count(left: Image.Image, right: Image.Image) -> int:
    return _foreground_count(ImageChops.multiply(left, right))


def _expanded_bbox(mask: Image.Image, margin: int = 24) -> tuple[int, int, int, int]:
    bbox = mask.getbbox()
    if bbox is None:
        return (0, 0, mask.width, mask.height)
    left, top, right, bottom = bbox
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(mask.width, right + margin),
        min(mask.height, bottom + margin),
    )


def _safe_aspect_ratio(width: float, height: float) -> float:
    if height <= 0:
        return 0.0
    return float(width) / float(height)


def _page_metrics(source: Image.Image, output: Image.Image) -> dict[str, Any]:
    source_gray = source.convert("L")
    output_gray = output.convert("L")

    whole_diff = ImageChops.difference(source_gray, output_gray)
    whole_mean_abs_diff = float(ImageStat.Stat(whole_diff).mean[0])
    whole_visual_similarity = max(0.0, 1.0 - whole_mean_abs_diff / 255.0)

    layout_source = source_gray.filter(ImageFilter.GaussianBlur(LAYOUT_VIEW_BLUR_RADIUS))
    layout_output = output_gray.filter(ImageFilter.GaussianBlur(LAYOUT_VIEW_BLUR_RADIUS))
    layout_diff = ImageChops.difference(layout_source, layout_output)
    layout_mean_abs_diff = float(ImageStat.Stat(layout_diff).mean[0])
    layout_view_similarity = max(0.0, 1.0 - layout_mean_abs_diff / 255.0)

    source_mask = _foreground_mask(source_gray)
    output_mask = _foreground_mask(output_gray)
    union_mask = ImageChops.lighter(source_mask, output_mask)
    bbox = _expanded_bbox(union_mask)

    source_crop = source_gray.crop(bbox)
    output_crop = output_gray.crop(bbox)
    diff = ImageChops.difference(source_crop, output_crop)
    mean_abs_diff = float(ImageStat.Stat(diff).mean[0])
    visual_similarity = max(0.0, 1.0 - mean_abs_diff / 255.0)

    source_mask_crop = source_mask.crop(bbox)
    output_mask_crop = output_mask.crop(bbox)
    source_fg = _foreground_count(source_mask_crop)
    output_fg = _foreground_count(output_mask_crop)
    if source_fg == 0 and output_fg == 0:
        foreground_overlap = 1.0
    elif source_fg == 0 or output_fg == 0:
        foreground_overlap = 0.0
    else:
        source_dilated = source_mask_crop.filter(ImageFilter.MaxFilter(7))
        output_dilated = output_mask_crop.filter(ImageFilter.MaxFilter(7))
        source_covered = _intersection_count(source_mask_crop, output_dilated) / source_fg
        output_covered = _intersection_count(output_mask_crop, source_dilated) / output_fg
        foreground_overlap = (source_covered + output_covered) / 2.0

    strict_alignment = (visual_similarity * 0.75) + (foreground_overlap * 0.25)
    return {
        "visual_sync_ratio": round(visual_similarity, 4),
        "visual_similarity_ratio": round(visual_similarity, 4),
        "content_visual_sync_ratio": round(visual_similarity, 4),
        "whole_page_visual_sync_ratio": round(whole_visual_similarity, 4),
        "layout_view_sync_ratio": round(layout_view_similarity, 4),
        "foreground_overlap_ratio": round(foreground_overlap, 4),
        "strict_alignment_ratio": round(strict_alignment, 4),
        "mean_abs_luma_diff": round(mean_abs_diff, 3),
        "whole_page_mean_abs_luma_diff": round(whole_mean_abs_diff, 3),
        "layout_view_mean_abs_luma_diff": round(layout_mean_abs_diff, 3),
        "content_bbox_px": list(bbox),
        "source_foreground_pixels": source_fg,
        "output_foreground_pixels": output_fg,
    }


def analyze_pdf_hwpx_fidelity(
    pdf_path: str | Path,
    hwpx_path: str | Path,
    output_dir: str | Path,
    *,
    max_pages: int = 3,
    target_sync_ratio: float = 0.9,
    allow_truncated_by_max_pages: bool = False,
    artifact_mode: str = "all",
) -> dict[str, Any]:
    """Render PDF/HWPX pages and compute visual sync ratios.

    The score is an automated QA signal, not a substitute for Hancom visual
    review. It compares rendered luminance over the document content area and
    adds a tolerant foreground-overlap check so text shifts are visible in the
    report instead of being hidden by white page background.
    """

    if rhwp is None:
        return {
            "available": False,
            "skipped": True,
            "reason": "rhwp unavailable",
            "target_sync_ratio": target_sync_ratio,
            "meets_target": None,
        }

    pdf_path = Path(pdf_path)
    hwpx_path = Path(hwpx_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_all_artifacts = artifact_mode == "all"
    save_failure_artifacts = artifact_mode == "failures"

    pages: list[dict[str, Any]] = []
    try:
        hwpx_doc = rhwp.parse(str(hwpx_path))
        hwp_page_count = int(hwpx_doc.page_count)
        with fitz.open(pdf_path) as pdf_doc:
            pdf_page_count = len(pdf_doc)
            page_count = max(0, min(pdf_page_count, hwp_page_count, max_pages))
            for page_index in range(page_count):
                pdf_page = pdf_doc[page_index]
                output_image = _render_hwpx_page(hwpx_doc, page_index)
                source_image = _render_pdf_page(pdf_page, output_image.size)
                metrics = _page_metrics(source_image, output_image)
                should_save_artifacts = save_all_artifacts or (
                    save_failure_artifacts
                    and float(metrics.get("layout_view_sync_ratio") or 0.0) < target_sync_ratio
                )

                source_name = f"source_page_{page_index + 1:03d}.png"
                output_name = f"output_page_{page_index + 1:03d}.png"
                diff_name = f"diff_page_{page_index + 1:03d}.png"
                if should_save_artifacts:
                    diff_image = ImageChops.difference(
                        source_image.convert("RGB"), output_image.convert("RGB")
                    )
                    source_image.save(output_dir / source_name)
                    output_image.save(output_dir / output_name)
                    diff_image.save(output_dir / diff_name)

                pdf_aspect = _safe_aspect_ratio(pdf_page.rect.width, pdf_page.rect.height)
                output_aspect = _safe_aspect_ratio(output_image.width, output_image.height)
                aspect_delta = abs(pdf_aspect - output_aspect)
                pages.append(
                    {
                        "page": page_index + 1,
                        "source_png": source_name,
                        "output_png": output_name,
                        "diff_png": diff_name,
                        "pdf_page_size_pt": [
                            round(float(pdf_page.rect.width), 3),
                            round(float(pdf_page.rect.height), 3),
                        ],
                        "source_size_px": list(source_image.size),
                        "output_size_px": list(output_image.size),
                        "pdf_page_aspect_ratio": round(pdf_aspect, 4),
                        "output_aspect_ratio": round(output_aspect, 4),
                        "aspect_ratio_delta": round(aspect_delta, 4),
                        "aspect_ratio_mismatch": aspect_delta > ASPECT_RATIO_TOLERANCE,
                        **metrics,
                    }
                )
    except Exception as exc:
        return {
            "available": True,
            "skipped": False,
            "error": f"{type(exc).__name__}: {exc}",
            "target_sync_ratio": target_sync_ratio,
        }

    if pages:
        sync_values = [float(page["visual_sync_ratio"]) for page in pages]
        strict_values = [float(page["strict_alignment_ratio"]) for page in pages]
        visual_values = [float(page["visual_similarity_ratio"]) for page in pages]
        whole_page_values = [
            float(page.get("whole_page_visual_sync_ratio", page["visual_sync_ratio"]))
            for page in pages
        ]
        layout_view_values = [
            float(page.get("layout_view_sync_ratio", page["visual_sync_ratio"]))
            for page in pages
        ]
        overlap_values = [float(page["foreground_overlap_ratio"]) for page in pages]
        overall_sync = min(sync_values)
        mean_sync = sum(sync_values) / len(sync_values)
        overall_whole_page_sync = min(whole_page_values)
        mean_whole_page_sync = sum(whole_page_values) / len(whole_page_values)
        overall_layout_view_sync = min(layout_view_values)
        mean_layout_view_sync = sum(layout_view_values) / len(layout_view_values)
        min_strict = min(strict_values)
        min_visual = min(visual_values)
        min_overlap = min(overlap_values)
        max_aspect_delta = max(float(page["aspect_ratio_delta"]) for page in pages)
    else:
        overall_sync = 0.0
        mean_sync = 0.0
        overall_whole_page_sync = 0.0
        mean_whole_page_sync = 0.0
        overall_layout_view_sync = 0.0
        mean_layout_view_sync = 0.0
        min_strict = 0.0
        min_visual = 0.0
        min_overlap = 0.0
        max_aspect_delta = 0.0

    compared_possible_pages = min(pdf_page_count, hwp_page_count)
    raw_page_count_mismatch = pdf_page_count != hwp_page_count
    limited_by_max_pages = (
        allow_truncated_by_max_pages
        and max_pages > 0
        and pdf_page_count > max_pages
        and hwp_page_count == max_pages
        and len(pages) == max_pages
    )
    page_count_mismatch = raw_page_count_mismatch and not limited_by_max_pages
    truncated_by_max_pages = page_count < compared_possible_pages
    truncated = page_count < max(pdf_page_count, hwp_page_count)
    missing_foreground_pages = [
        int(page["page"])
        for page in pages
        if int(page["source_foreground_pixels"]) > 0 and int(page["output_foreground_pixels"]) == 0
    ]
    unexpected_foreground_pages = [
        int(page["page"])
        for page in pages
        if int(page["source_foreground_pixels"]) == 0 and int(page["output_foreground_pixels"]) > 0
    ]
    aspect_mismatch_pages = [
        int(page["page"]) for page in pages if bool(page.get("aspect_ratio_mismatch"))
    ]
    meets_visual_similarity_target = bool(pages) and overall_sync >= target_sync_ratio
    meets_whole_page_sync_target = bool(pages) and overall_whole_page_sync >= target_sync_ratio
    meets_layout_view_sync_target = bool(pages) and overall_layout_view_sync >= target_sync_ratio
    meets_strict_alignment_review = bool(pages) and min_strict >= STRICT_ALIGNMENT_REVIEW_THRESHOLD
    meets_foreground_overlap_review = (
        bool(pages) and min_overlap >= FOREGROUND_OVERLAP_REVIEW_THRESHOLD
    )
    review_flags: list[str] = []
    if page_count_mismatch:
        review_flags.append("page_count_mismatch")
    if truncated_by_max_pages:
        review_flags.append("truncated_by_max_pages")
    if aspect_mismatch_pages:
        review_flags.append("aspect_ratio_mismatch")
    if missing_foreground_pages:
        review_flags.append("missing_output_foreground")
    if unexpected_foreground_pages:
        review_flags.append("unexpected_output_foreground")
    if pages and not meets_strict_alignment_review:
        review_flags.append("strict_alignment_below_review_threshold")
    if pages and not meets_foreground_overlap_review:
        review_flags.append("foreground_overlap_below_review_threshold")

    return {
        "available": True,
        "skipped": False,
        "target_sync_ratio": target_sync_ratio,
        "artifact_mode": artifact_mode,
        "strict_alignment_review_threshold": STRICT_ALIGNMENT_REVIEW_THRESHOLD,
        "foreground_overlap_review_threshold": FOREGROUND_OVERLAP_REVIEW_THRESHOLD,
        "layout_view_blur_radius": LAYOUT_VIEW_BLUR_RADIUS,
        "aspect_ratio_tolerance": ASPECT_RATIO_TOLERANCE,
        "pdf_page_count": pdf_page_count,
        "hwpx_page_count": hwp_page_count,
        "max_pages": max_pages,
        "truncated": truncated,
        "truncated_by_max_pages": truncated_by_max_pages,
        "limited_by_max_pages": limited_by_max_pages,
        "raw_page_count_mismatch": raw_page_count_mismatch,
        "page_count_mismatch": page_count_mismatch,
        "pages_compared": len(pages),
        "overall_sync_ratio": round(overall_sync, 4),
        "mean_sync_ratio": round(mean_sync, 4),
        "overall_whole_page_sync_ratio": round(overall_whole_page_sync, 4),
        "mean_whole_page_sync_ratio": round(mean_whole_page_sync, 4),
        "overall_layout_view_sync_ratio": round(overall_layout_view_sync, 4),
        "mean_layout_view_sync_ratio": round(mean_layout_view_sync, 4),
        "min_strict_alignment_ratio": round(min_strict, 4),
        "min_visual_similarity_ratio": round(min_visual, 4),
        "min_foreground_overlap_ratio": round(min_overlap, 4),
        "max_aspect_ratio_delta": round(max_aspect_delta, 4),
        "missing_foreground_pages": missing_foreground_pages,
        "unexpected_foreground_pages": unexpected_foreground_pages,
        "aspect_ratio_mismatch_pages": aspect_mismatch_pages,
        "meets_visual_similarity_target": meets_visual_similarity_target,
        "meets_whole_page_sync_target": meets_whole_page_sync_target,
        "meets_layout_view_sync_target": meets_layout_view_sync_target,
        "meets_strict_alignment_review": meets_strict_alignment_review,
        "meets_foreground_overlap_review": meets_foreground_overlap_review,
        "review_flags": review_flags,
        "needs_human_review": bool(review_flags),
        "meets_target": (
            meets_layout_view_sync_target
            and meets_strict_alignment_review
            and meets_foreground_overlap_review
            and not page_count_mismatch
            and not truncated_by_max_pages
            and not aspect_mismatch_pages
            and not missing_foreground_pages
        ),
        "pages": pages,
    }
