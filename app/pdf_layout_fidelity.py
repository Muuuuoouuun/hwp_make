"""Render-based PDF to HWPX layout fidelity checks."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageStat

try:
    import rhwp
except Exception:  # pragma: no cover - optional runtime dependency
    rhwp = None

STRICT_ALIGNMENT_REVIEW_THRESHOLD = 0.75
FOREGROUND_OVERLAP_REVIEW_THRESHOLD = 0.10
ASPECT_RATIO_TOLERANCE = 0.02
LAYOUT_VIEW_BLUR_RADIUS = 1.0
DETAILED_FOREGROUND_REFERENCE = 0.88
DETAILED_LINE_TOLERANCE_PX = 6


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


def _mask_array(mask: Image.Image) -> np.ndarray:
    return np.asarray(mask, dtype=np.float32) / 255.0


def _without_long_vertical_rules(mask: np.ndarray) -> np.ndarray:
    clean = mask.copy()
    if clean.size == 0:
        return clean
    long_rule_columns = clean.sum(axis=0) >= clean.shape[0] * 0.62
    clean[:, long_rule_columns] = 0.0
    return clean


def _smooth_profile(values: np.ndarray, radius: int = 3) -> np.ndarray:
    if values.size == 0 or radius <= 0:
        return values.astype(np.float32, copy=False)
    kernel = np.ones(radius * 2 + 1, dtype=np.float32)
    kernel /= kernel.sum()
    return np.convolve(values.astype(np.float32), kernel, mode="same")


def _profile_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return 1.0 if left.size == right.size else 0.0
    size = min(left.size, right.size)
    left = _smooth_profile(left[:size])
    right = _smooth_profile(right[:size])
    left_sum = float(left.sum())
    right_sum = float(right.sum())
    if left_sum <= 1e-6 and right_sum <= 1e-6:
        return 1.0
    if left_sum <= 1e-6 or right_sum <= 1e-6:
        return 0.0

    left_dist = left / left_sum
    right_dist = right / right_sum
    distribution = max(0.0, 1.0 - float(np.abs(left_dist - right_dist).sum()) * 0.5)
    left_peak = float(left.max()) or 1.0
    right_peak = float(right.max()) or 1.0
    left_shape = left / left_peak
    right_shape = right / right_peak
    union = float(np.maximum(left_shape, right_shape).sum())
    soft_iou = (
        float(np.minimum(left_shape, right_shape).sum()) / union
        if union > 1e-6
        else 1.0
    )
    return max(0.0, min(1.0, distribution * 0.65 + soft_iou * 0.35))


def _row_profile_score(source: np.ndarray, output: np.ndarray) -> float:
    height, width = source.shape
    regions = (
        (0.07, 0.93, 0.055, 0.22),
        (0.07, 0.49, 0.17, 0.93),
        (0.51, 0.93, 0.17, 0.93),
    )
    scores: list[float] = []
    for left, right, top, bottom in regions:
        x0, x1 = int(width * left), int(width * right)
        y0, y1 = int(height * top), int(height * bottom)
        src = _without_long_vertical_rules(source[y0:y1, x0:x1])
        out = _without_long_vertical_rules(output[y0:y1, x0:x1])
        scores.append(_profile_similarity(src.sum(axis=1), out.sum(axis=1)))
    return sum(scores) / len(scores)


def _column_profile_score(source: np.ndarray, output: np.ndarray) -> float:
    height, width = source.shape
    y0, y1 = int(height * 0.055), int(height * 0.93)
    x0, x1 = int(width * 0.055), int(width * 0.945)
    src = _without_long_vertical_rules(source[y0:y1, x0:x1])
    out = _without_long_vertical_rules(output[y0:y1, x0:x1])
    return _profile_similarity(src.sum(axis=0), out.sum(axis=0))


def _line_band_centers(mask: np.ndarray) -> list[float]:
    if mask.size == 0:
        return []
    clean = _without_long_vertical_rules(mask)
    profile = clean.sum(axis=1)
    active = profile >= max(2.0, clean.shape[1] * 0.006)
    centers: list[float] = []
    start: int | None = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(active) - 1):
            end = index if not value else index + 1
            height = end - start
            if 2 <= height <= 24:
                weights = profile[start:end]
                total = float(weights.sum())
                if total > 0:
                    positions = np.arange(start, end, dtype=np.float32)
                    centers.append(float((positions * weights).sum() / total))
            start = None
    return centers


def _line_band_match_score(source: np.ndarray, output: np.ndarray) -> float:
    height, width = source.shape
    scores: list[float] = []
    for left, right in ((0.07, 0.49), (0.51, 0.93)):
        x0, x1 = int(width * left), int(width * right)
        y0, y1 = int(height * 0.17), int(height * 0.93)
        src_centers = _line_band_centers(source[y0:y1, x0:x1])
        out_centers = _line_band_centers(output[y0:y1, x0:x1])
        if not src_centers and not out_centers:
            scores.append(1.0)
            continue
        matched = 0
        out_index = 0
        for center in src_centers:
            while (
                out_index < len(out_centers)
                and out_centers[out_index] < center - DETAILED_LINE_TOLERANCE_PX
            ):
                out_index += 1
            candidates = []
            for candidate_index in (out_index, out_index + 1):
                if candidate_index < len(out_centers):
                    distance = abs(out_centers[candidate_index] - center)
                    if distance <= DETAILED_LINE_TOLERANCE_PX:
                        candidates.append((distance, candidate_index))
            if candidates:
                _distance, chosen = min(candidates)
                matched += 1
                out_index = chosen + 1
        denominator = len(src_centers) + len(out_centers)
        scores.append((2.0 * matched / denominator) if denominator else 1.0)
    return sum(scores) / len(scores)


def _occupancy_grid_score(source_mask: Image.Image, output_mask: Image.Image) -> float:
    target_size = (80, 113)
    source_soft = source_mask.filter(ImageFilter.MaxFilter(5)).resize(
        target_size, Image.Resampling.BOX
    )
    output_soft = output_mask.filter(ImageFilter.MaxFilter(5)).resize(
        target_size, Image.Resampling.BOX
    )
    source = np.asarray(source_soft, dtype=np.float32) / 255.0
    output = np.asarray(output_soft, dtype=np.float32) / 255.0
    union = float(np.maximum(source, output).sum())
    return float(np.minimum(source, output).sum()) / union if union > 1e-6 else 1.0


def _bbox_similarity(
    source_bbox: tuple[int, int, int, int] | None,
    output_bbox: tuple[int, int, int, int] | None,
    size: tuple[int, int],
) -> float:
    if source_bbox is None and output_bbox is None:
        return 1.0
    if source_bbox is None or output_bbox is None:
        return 0.0
    width, height = size
    scales = (width, height, width, height)
    normalized_delta = sum(
        abs(float(left) - float(right)) / max(1.0, float(scale))
        for left, right, scale in zip(source_bbox, output_bbox, scales)
    ) / 4.0
    return max(0.0, 1.0 - normalized_delta * 5.0)


def _detailed_geometry_metrics(
    source_mask: Image.Image,
    output_mask: Image.Image,
    *,
    foreground_overlap: float,
) -> dict[str, float]:
    source = _mask_array(source_mask)
    output = _mask_array(output_mask)
    row_score = _row_profile_score(source, output)
    column_score = _column_profile_score(source, output)
    line_score = _line_band_match_score(source, output)
    occupancy_score = _occupancy_grid_score(source_mask, output_mask)
    source_count = float(source.sum())
    output_count = float(output.sum())
    density_score = (
        min(source_count, output_count) / max(source_count, output_count)
        if source_count > 0 or output_count > 0
        else 1.0
    )
    bbox_score = _bbox_similarity(source_mask.getbbox(), output_mask.getbbox(), source_mask.size)
    foreground_score = min(1.0, foreground_overlap / DETAILED_FOREGROUND_REFERENCE)
    total = (
        row_score * 0.25
        + line_score * 0.20
        + occupancy_score * 0.20
        + foreground_score * 0.15
        + column_score * 0.10
        + bbox_score * 0.05
        + density_score * 0.05
    )
    return {
        "detailed_layout_score": round(total * 100.0, 2),
        "row_alignment_score": round(row_score * 100.0, 2),
        "line_band_match_score": round(line_score * 100.0, 2),
        "occupancy_grid_score": round(occupancy_score * 100.0, 2),
        "foreground_geometry_score": round(foreground_score * 100.0, 2),
        "column_alignment_score": round(column_score * 100.0, 2),
        "content_bbox_score": round(bbox_score * 100.0, 2),
        "ink_density_score": round(density_score * 100.0, 2),
    }


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
    detailed = _detailed_geometry_metrics(
        source_mask,
        output_mask,
        foreground_overlap=foreground_overlap,
    )
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
        **detailed,
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
        detailed_values = [float(page["detailed_layout_score"]) for page in pages]
        overall_detailed_layout_score = sum(detailed_values) / len(detailed_values)
        minimum_detailed_layout_score = min(detailed_values)
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
        overall_detailed_layout_score = 0.0
        minimum_detailed_layout_score = 0.0

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
        "overall_detailed_layout_score": round(overall_detailed_layout_score, 2),
        "minimum_detailed_layout_score": round(minimum_detailed_layout_score, 2),
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
