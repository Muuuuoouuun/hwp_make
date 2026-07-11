"""인식 파이프라인 오케스트레이터(결정론적).

born-digital PDF → 문항 단위 구조화 결과를 만든다. 순수 인식 레이어이므로
storage/importers 에 의존하지 않는다(순환 방지). 산출물은 RecognizedProblem
리스트 + "어느 페이지가 AI 폴백 후보인가" 라우팅 판정이다.

흐름:
  1. pdf_segment.segment_pdf → 페이지별 PageModel(문항 박스 + 자식 블록, 픽셀 좌표)
  2. cutout.render_page_images → 페이지 래스터(문항 박스와 동일 dpi)
  3. 문항마다 텍스트(제목+본문+선지) 재구성 + 그림 cutout(PNG bytes)
  4. 텍스트 마커가 없는 페이지(스캔/텍스트레이어 없음)는 router 로 AI 폴백 판정

실제 AI/OCR '실행'은 이 모듈이 하지 않는다(키·엔진 유무는 여기서 판정만 하고,
스캔 페이지의 실행 폴백은 상위 importers 가 기존 OCR/텍스트 경로로 처리한다).
그래서 API 키가 없어도 이 모듈은 완전한 결정론적 baseline 을 항상 반환한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.recognition.schema import Box, ContentBlock, PageModel, Subject
from app.recognition import cutout
from app.recognition.pdf_segment import segment_pdf
from app.exam_header import masthead_from_text
from app.math_text import is_recoverable_pua_math_char, normalize_recognized_math_layout_text

# 문항 본문에서 이 비율 이상이 아직 복원되지 않은 PUA이면 텍스트만으로는 부족하다고 본다.
# 이 경우 보존용 crop을 붙이되, 가능한 라인/문자 좌표는 계속 남겨 후속 수식 복원에 쓴다.
_PUA_UNRELIABLE_RATIO = 0.12


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class RecognizedProblem:
    number: int
    page_number: int  # 1-based
    column_index: int
    text: str  # 제목+본문+선지를 읽기순서로 이은 전체 문항 텍스트(PUA 정리됨)
    figure_pngs: list[bytes] = field(default_factory=list)
    box: Box | None = None
    text_reliable: bool = True  # False면 PUA 글리프로 텍스트가 깨짐(수식폰트) → 이미지 우선
    problem_image_png: bytes | None = None  # 텍스트 불안정 시 문항 전체 crop(충실 이미지)
    column_count: int = 0
    page_width_px: int = 0
    page_height_px: int = 0
    line_geometries: list[dict[str, Any]] = field(default_factory=list)
    figure_boxes: list[Box] = field(default_factory=list)


@dataclass(slots=True)
class RecognitionResult:
    problems: list[RecognizedProblem] = field(default_factory=list)
    page_count: int = 0
    exam_title: str = ""
    pages_with_markers: int = 0
    empty_page_numbers: list[int] = field(default_factory=list)
    ai_available: bool = False
    ai_used: bool = False
    routing: list[dict[str, Any]] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.problems)


# ---------------------------------------------------------------------------
# 과목 추론(파일명 힌트)
# ---------------------------------------------------------------------------
_SUBJECT_HINTS: list[tuple[tuple[str, ...], Subject]] = [
    (("수학", "미적분", "확률과통계", "기하", "math"), Subject.MATH),
    (("물리", "화학", "생명", "지구과학", "과학", "science"), Subject.SCIENCE),
    (("국어", "화작", "언매", "문학", "독서", "korean"), Subject.KOREAN),
    (("영어", "english"), Subject.ENGLISH),
    (("사회", "역사", "지리", "윤리", "경제", "정치", "social"), Subject.SOCIAL),
]


def infer_subject(filename: str | None) -> Subject:
    name = str(filename or "")
    for keywords, subject in _SUBJECT_HINTS:
        if any(kw in name for kw in keywords):
            return subject
    return Subject.UNKNOWN


# ---------------------------------------------------------------------------
# 문항 텍스트 재구성
# ---------------------------------------------------------------------------
def _problem_text(page: PageModel, blocks_by_id: dict[str, ContentBlock], unit_meta_ids: list[str]) -> str:
    """문항에 속한 블록들을 읽기순서로 이어 전체 텍스트를 만든다(원문, PUA 미정리)."""
    blocks = [blocks_by_id[bid] for bid in unit_meta_ids if bid in blocks_by_id]
    blocks.sort(key=lambda b: b.reading_order)
    lines = [str(b.text).strip() for b in blocks if b.text and str(b.text).strip()]
    return "\n".join(lines)


def _problem_line_geometries(
    blocks_by_id: dict[str, ContentBlock],
    unit_meta_ids: list[str],
) -> list[dict[str, Any]]:
    """문항에 속한 PDF 라인의 텍스트/bbox/char geometry를 QA와 수식 복원용으로 보존한다."""
    blocks = [blocks_by_id[bid] for bid in unit_meta_ids if bid in blocks_by_id]
    blocks.sort(key=lambda b: b.reading_order)
    lines: list[dict[str, Any]] = []
    for block in blocks:
        chars = block.metadata.get("pdf_line_chars") or []
        spans = block.metadata.get("pdf_line_spans") or []
        if not chars and not spans:
            continue
        payload: dict[str, Any] = {
            "block_id": block.block_id,
            "block_type": str(block.block_type),
            "text": _clean_pua(str(block.text or "")),
            "bbox_px": [block.bbox.left, block.bbox.top, block.bbox.width, block.bbox.height],
        }
        if chars:
            payload["pdf_line_chars"] = chars
        if spans:
            payload["pdf_line_spans"] = spans
        lines.append(payload)
    return lines


def _is_pua(ch: str) -> bool:
    code = ord(ch)
    # PUA U+E000..U+F8FF, or control chars (tab/newline/CR excepted)
    return (0xE000 <= code <= 0xF8FF) or (code < 32 and code not in (9, 10, 13))


def _pua_ratio(text: str) -> float:
    """PUA/control char ratio; high == broken math-font glyphs."""
    meaningful = [ch for ch in text if not ch.isspace()]
    if not meaningful:
        return 0.0
    return sum(1 for ch in meaningful if _is_pua(ch) and not is_recoverable_pua_math_char(ch)) / len(meaningful)


def _clean_pua(text: str) -> str:
    """Recover known math-font glyphs and collapse unknown PUA/control runs."""
    return normalize_recognized_math_layout_text(text)


def _figures_from_metadata(page: PageModel) -> list[Box]:
    out: list[Box] = []
    for item in page.metadata.get("figure_bboxes_px", []) or []:
        try:
            left, top, right, bottom = item
        except (TypeError, ValueError):
            continue
        out.append(Box.from_points(float(left), float(top), float(right), float(bottom)))
    return out


def _text_light_figures(page: PageModel, figures: list[Box]) -> list[Box]:
    """Return image candidates while excluding bordered editable-text blocks."""
    raw_counts = page.metadata.get("figure_text_char_counts") or []
    counts: list[int] = []
    for value in raw_counts:
        try:
            counts.append(int(value))
        except (TypeError, ValueError):
            counts.append(0)
    if len(counts) < len(figures):
        counts.extend([0] * (len(figures) - len(counts)))
    return [
        figure
        for index, figure in enumerate(figures)
        if figure.area >= _MIN_FIGURE_AREA_PX
        and figure.width >= 60.0
        and figure.height >= 60.0
        and counts[index] < 24
    ]


# 그림 언급 키워드(본문에 있으면 도형/그래프/표가 딸린 문항으로 본다).
_VISUAL_CUE = ("그림", "그래프", "도형", "좌표평면", "자료", "표는", "곡선", "직선", "삼각형", "사각형", "지도", "회로", "장치")
# 문항 내부 그림으로 인정할 최소 면적(px²). 150dpi 기준 ~2.5×2.5cm.
_MIN_FIGURE_AREA_PX = 22000.0


def _box_center_in(box: Box, outer: Box) -> bool:
    cx = (box.left + box.right) / 2.0
    cy = (box.top + box.bottom) / 2.0
    return outer.left <= cx <= outer.right and outer.top <= cy <= outer.bottom


def _box_intersection_area(a: Box, b: Box) -> float:
    left = max(a.left, b.left)
    top = max(a.top, b.top)
    right = min(a.right, b.right)
    bottom = min(a.bottom, b.bottom)
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def _problem_has_figure(box: Box | None, figures: list[Box], text: str) -> bool:
    """문항에 도형/그래프/표 등 그림이 딸려 있는지."""
    if box is not None:
        for fig in figures:
            if fig.area >= _MIN_FIGURE_AREA_PX and _box_center_in(fig, box):
                return True
    return any(cue in text for cue in _VISUAL_CUE)


def _page_needs_raster(page: PageModel, *, any_problems: bool) -> bool:
    """Decide whether a segmented page needs the expensive raster pass."""
    if not page.problems:
        return any_problems

    blocks_by_id = {block.block_id: block for block in page.blocks}
    figures = _figures_from_metadata(page)
    text_light_figures = _text_light_figures(page, figures)
    for unit in page.problems:
        title_block = blocks_by_id.get(unit.metadata.get("title_block_id", ""))
        box = title_block.bbox if title_block else None
        if box is None:
            continue
        block_ids = list(unit.stem_block_ids) + list(unit.choice_block_ids)
        raw_text = _problem_text(page, blocks_by_id, block_ids)
        if _pua_ratio(raw_text) >= _PUA_UNRELIABLE_RATIO:
            return True
        if not text_light_figures:
            continue
        text = _clean_pua(raw_text)
        if _problem_has_figure(box, figures, text) and any(
            _box_intersection_area(figure, box) >= figure.area * 0.6
            for figure in text_light_figures
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# AI 폴백 가용성/판정 (실행은 상위에서)
# ---------------------------------------------------------------------------
def _ai_available() -> bool:
    """Gemini/OpenAI 키(env 또는 저장) 또는 로컬 OCR 엔진이 있으면 True."""
    import os

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return True
    try:
        from app.recognition.settings import load_user_settings  # lazy

        stored = load_user_settings()
        if stored.get("gemini_api_key") or stored.get("openai_api_key"):
            return True
    except Exception:
        pass
    try:
        from app.recognition.ocr_backend import build_ocr_backend  # lazy

        backend = build_ocr_backend("auto")
        name = str(getattr(backend, "name", "") or "").lower()
        return name not in {"", "none", "noop", "no_ocr", "base"}
    except Exception:
        return False


def _route_empty_page(page: PageModel, *, ai_enabled: bool) -> dict[str, Any]:
    """마커 없는 페이지의 라우팅 판정 요약(router.decide_page_route)."""
    decision: dict[str, Any] = {
        "page": page.page_id,
        "reason": "no_text_markers",
        "should_use_ai": ai_enabled,
        "route": "local_only",
    }
    try:
        from app.recognition import router  # lazy

        result = router.decide_page_route(
            page, ocr_mode="none", ai_enabled=ai_enabled, ai_mode="auto"
        )
        decision.update(
            {
                "route": getattr(result, "route", "local_only"),
                "should_use_ai": bool(getattr(result, "should_use_ai", ai_enabled)),
                "quality_status": getattr(result, "quality_status", None),
                "next_best_action": getattr(result, "next_best_action", None),
                "trigger_reasons": list(getattr(result, "trigger_reasons", []) or []),
            }
        )
    except Exception as exc:  # 라우터가 없어도 파이프라인은 계속된다
        decision["router_error"] = f"{type(exc).__name__}: {exc}"
    return decision


def _page_fallback_problem(page: PageModel, page_number: int, page_img: Any | None) -> RecognizedProblem | None:
    """마커 없는 혼합문서 페이지를 이미지-only 문항으로 보존한다.

    전체 문서가 스캔이면 상위 레거시/OCR 경로가 처리해야 하므로 호출부는 이미
    any_problems=True 인 혼합문서에서만 이 함수를 호출한다.
    """
    if page_img is None:
        return None
    page_box = Box.from_points(0.0, 0.0, float(page.width_px), float(page.height_px))
    try:
        image_png = cutout.problem_cutout_png(page_img, page_box, pad=0, trim=False)
    except Exception:
        return None
    text_lines = [
        str(block.text or "").strip()
        for block in page.sorted_blocks()
        if block.text and str(block.text or "").strip()
    ]
    return RecognizedProblem(
        number=0,
        page_number=page_number,
        column_index=1,
        text=_clean_pua("\n".join(text_lines)),
        box=page_box,
        text_reliable=False,
        problem_image_png=image_png,
        column_count=1,
        page_width_px=page.width_px,
        page_height_px=page.height_px,
    )


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def recognize_pdf(
    pdf_bytes: bytes,
    *,
    filename: str | None = None,
    dpi: int = 150,
    subject: Subject | None = None,
) -> RecognitionResult:
    """born-digital PDF 를 문항 단위로 인식한다.

    반환된 RecognitionResult.found 가 False 면(문항 0개) 스캔/텍스트레이어 없음 →
    상위 호출자가 기존 OCR/텍스트 경로로 폴백해야 한다.
    """
    if subject is None:
        subject = infer_subject(filename)

    result = RecognitionResult()
    try:
        pages = segment_pdf(pdf_bytes, dpi=dpi, subject=subject)
    except Exception as exc:
        result.notices.append(f"PDF 구조 분석 실패({type(exc).__name__}) — 기존 방식으로 처리합니다.")
        return result

    result.page_count = len(pages)
    header_source = " ".join(
        str(page.metadata.get("header_text") or "").strip()
        for page in pages
        if str(page.metadata.get("header_text") or "").strip()
    )
    result.exam_title = masthead_from_text(f"{header_source} {filename or ''}")
    result.ai_available = _ai_available()
    any_problems = any(page.problems for page in pages)

    page_images: dict[int, Any] = {}
    if any_problems:
        try:
            raster_page_indexes = {
                page_index
                for page_index, page in enumerate(pages)
                if _page_needs_raster(page, any_problems=any_problems)
            }
            page_images = cutout.render_selected_page_images(
                pdf_bytes,
                raster_page_indexes,
                dpi=dpi,
            )
        except Exception as exc:
            result.notices.append(f"페이지 렌더 실패({type(exc).__name__}) — 그림 없이 텍스트만 가져옵니다.")
            page_images = {}

    for page_index, page in enumerate(pages):
        marker_count = int(page.metadata.get("marker_count") or 0)
        if marker_count > 0:
            result.pages_with_markers += 1
        elif page.metadata.get("error") or marker_count == 0:
            # 마커 없음/에러 → AI 폴백 후보
            result.empty_page_numbers.append(page_index + 1)
            result.routing.append(_route_empty_page(page, ai_enabled=result.ai_available))

        if not page.problems:
            if any_problems:
                page_img = page_images.get(page_index)
                fallback = _page_fallback_problem(page, page_index + 1, page_img)
                if fallback is not None:
                    result.problems.append(fallback)
            continue

        blocks_by_id = {b.block_id: b for b in page.blocks}
        figures = _figures_from_metadata(page)
        text_light_figures = _text_light_figures(page, figures)
        page_img = page_images.get(page_index)

        for unit in page.problems:
            block_ids = list(unit.stem_block_ids) + list(unit.choice_block_ids)
            raw_text = _problem_text(page, blocks_by_id, block_ids)
            line_geometries = _problem_line_geometries(blocks_by_id, block_ids)
            number = int(unit.metadata.get("pdf_problem_number") or unit.metadata.get("problem_number") or 0)

            title_block = blocks_by_id.get(unit.metadata.get("title_block_id", ""))
            box = title_block.bbox if title_block else None

            # 텍스트 신뢰도: 아직 복원되지 않은 PUA 비율이 높으면 본문 텍스트만 믿지 않는다.
            text_reliable = _pua_ratio(raw_text) < _PUA_UNRELIABLE_RATIO
            text = _clean_pua(raw_text)
            has_figure = _problem_has_figure(box, figures, text)

            # 문항 전체 crop은 텍스트가 신뢰 불가인 경우의 보존 장치다. 그림/도표는 가능하면
            # 지역 crop으로 분리하고, 텍스트/좌표는 후속 native equation 복원용으로 유지한다.
            figure_pngs: list[bytes] = []
            figure_boxes: list[Box] = []
            problem_image_png: bytes | None = None
            if page_img is not None and box is not None:
                if not text_reliable:
                    try:
                        problem_image_png = cutout.problem_cutout_png(page_img, box)
                    except Exception:
                        problem_image_png = None
                elif has_figure:
                    try:
                        figure_boxes = [
                            figure
                            for figure in text_light_figures
                            if _box_intersection_area(figure, box) >= figure.area * 0.6
                        ]
                        figure_pngs = cutout.figure_cutouts_png(page_img, box, figure_boxes)
                        figure_boxes = figure_boxes[: len(figure_pngs)]
                    except Exception:
                        figure_pngs = []
                        figure_boxes = []

            result.problems.append(
                RecognizedProblem(
                    number=number,
                    page_number=page_index + 1,
                    column_index=int(unit.metadata.get("column_index") or 0),
                    text=text,
                    figure_pngs=figure_pngs,
                    box=box,
                    text_reliable=text_reliable,
                    problem_image_png=problem_image_png,
                    column_count=int(page.metadata.get("column_count") or 0),
                    page_width_px=page.width_px,
                    page_height_px=page.height_px,
                    line_geometries=line_geometries,
                    figure_boxes=figure_boxes,
                )
            )

    # 읽기 순서: 페이지 → 컬럼 → (박스 top)
    result.problems.sort(
        key=lambda p: (p.page_number, p.column_index, p.box.top if p.box else 0.0)
    )

    image_fallback = sum(1 for p in result.problems if not p.text_reliable)
    if image_fallback:
        extra = (
            " OCR/AI 키를 설정하면 이미지에서 실제 텍스트도 추출할 수 있습니다."
            if not result.ai_available
            else " OCR/AI 폴백으로 텍스트 추출을 시도할 수 있습니다."
        )
        result.notices.append(
            f"{image_fallback}개 문항은 아직 복원되지 않은 수식 PUA 비율이 높아 "
            f"보존용 문항 이미지를 함께 가져왔습니다.{extra}"
        )

    if result.empty_page_numbers:
        n = len(result.empty_page_numbers)
        if result.ai_available:
            result.notices.append(
                f"{n}개 페이지에서 텍스트 마커를 찾지 못했습니다(스캔 추정). OCR/AI 폴백 대상으로 표시했습니다."
            )
        else:
            result.notices.append(
                f"{n}개 페이지는 텍스트 마커가 없어(스캔 추정) 기존 방식으로 처리합니다. "
                f"OCR/AI 키를 설정하면 이런 페이지도 자동 인식할 수 있습니다."
            )
    return result
