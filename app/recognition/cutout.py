"""문항/그림 이미지 cutout.

pdf_segment 가 만든 문항 박스(렌더 픽셀 좌표)를 받아 페이지 래스터에서 잘라낸다.
- render_page_images: PDF → 페이지별 PIL 이미지(문항 박스와 동일 dpi로 정렬)
- crop_box / tight_trim: 박스 crop + 여백 제거
- problem_cutout_png: 문항 박스 전체 → PNG 바이트 (이미지-only 문항 폴백용)
- figure_cutouts_png: 문항 박스 안의 그림(도형/그래프) 영역만 → PNG 바이트 리스트

whitespace-trim 은 edb_builder.build_tight_crop_image_bytes 의 알고리즘을 PIL getbbox
기반의 빠른 형태로 이식했다. 의존성: PyMuPDF(fitz, 렌더) + PIL. numpy/opencv 불필요.
"""
from __future__ import annotations

import io
from typing import Iterable

from PIL import Image, ImageChops

from app.recognition.schema import Box

try:  # PyMuPDF: PDF 페이지 래스터 렌더용 (앱 런타임엔 이미 설치됨)
    import fitz  # type: ignore
except Exception:  # pragma: no cover - 렌더 없이도 crop 유틸은 동작
    fitz = None


DEFAULT_DPI = 150


def render_page_images(pdf_bytes: bytes, *, dpi: int = DEFAULT_DPI) -> list[Image.Image]:
    """PDF의 각 페이지를 PIL 이미지로 렌더한다.

    dpi 는 pdf_segment.segment_pdf 가 문항 박스를 계산한 dpi 와 반드시 같아야
    픽셀 좌표가 정렬된다(호출부는 PageModel.metadata['dpi'] 를 넘길 것).
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF(fitz)가 없어 PDF를 렌더할 수 없습니다.")
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    images: list[Image.Image] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)
    return images


def _clamp_box_px(box: Box, width: int, height: int, *, pad: int = 0) -> tuple[int, int, int, int]:
    left = max(0, int(round(box.left)) - pad)
    top = max(0, int(round(box.top)) - pad)
    right = min(width, int(round(box.right)) + pad)
    bottom = min(height, int(round(box.bottom)) + pad)
    if right <= left:
        right = min(width, left + 1)
    if bottom <= top:
        bottom = min(height, top + 1)
    return left, top, right, bottom


def crop_box(image: Image.Image, box: Box, *, pad: int = 0) -> Image.Image:
    rect = _clamp_box_px(box, image.width, image.height, pad=pad)
    return image.crop(rect)


def tight_trim(image: Image.Image, *, white_threshold: int = 244, min_trim_ratio: float = 0.02) -> Image.Image:
    """바깥쪽 흰 여백을 잘라낸다(내용이 조금이라도 있을 때만).

    알파가 있으면 알파 기준, 없으면 흰색(=배경) 대비 차이의 bbox 기준.
    edb_builder._content_bbox 와 동일 취지이나 PIL 내장으로 O(1) 스캔.
    """
    if "A" in image.getbands():
        alpha = image.getchannel("A")
        bbox = alpha.point(lambda px: 255 if px > 2 else 0).getbbox()
    else:
        gray = image.convert("L")
        # white_threshold 이상(=배경)인 픽셀을 흰색으로, 나머지를 검게 만든 뒤 bbox.
        mask = gray.point(lambda px: 0 if px >= white_threshold else 255)
        bbox = mask.getbbox()
    if not bbox:
        return image
    left, top, right, bottom = bbox
    orig_w, orig_h = image.size
    trimmed_w, trimmed_h = right - left, bottom - top
    if (orig_w - trimmed_w) > orig_w * min_trim_ratio or (orig_h - trimmed_h) > orig_h * min_trim_ratio:
        return image.crop(bbox)
    return image


def _to_png_bytes(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def problem_cutout_png(image: Image.Image, box: Box, *, pad: int = 6, trim: bool = True) -> bytes:
    """문항 박스 전체를 잘라 PNG 바이트로. 이미지-only 문항 폴백/디버그용."""
    crop = crop_box(image, box, pad=pad)
    if trim:
        crop = tight_trim(crop)
    return _to_png_bytes(crop)


def _intersection_area(a: Box, b: Box) -> float:
    left = max(a.left, b.left)
    top = max(a.top, b.top)
    right = min(a.right, b.right)
    bottom = min(a.bottom, b.bottom)
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def figure_cutouts_png(
    image: Image.Image,
    problem_box: Box,
    figure_boxes: Iterable[Box],
    *,
    pad: int = 4,
    min_area_px: float = 900.0,
    min_overlap_frac: float = 0.6,
    trim: bool = True,
) -> list[bytes]:
    """문항 박스 안에 들어있는 그림(도형/그래프) 영역만 각각 잘라 PNG 리스트로.

    figure_boxes: 페이지의 임베디드 그림/벡터 bbox(픽셀 좌표) — pdf_segment 가
    PageModel.metadata['figure_bboxes_px'] 로 넘겨준다.
    문항 박스와 min_overlap_frac 이상 겹치는 그림만, 너무 작은 건 제외.
    """
    out: list[bytes] = []
    for fig in figure_boxes:
        area = fig.area
        if area < min_area_px:
            continue
        if area <= 0 or _intersection_area(fig, problem_box) < area * min_overlap_frac:
            continue
        crop = crop_box(image, fig, pad=pad)
        if trim:
            crop = tight_trim(crop)
        if crop.width < 8 or crop.height < 8:
            continue
        out.append(_to_png_bytes(crop))
    return out
