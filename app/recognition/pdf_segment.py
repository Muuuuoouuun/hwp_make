"""PyMuPDF 기반 born-digital PDF 문항(문항) 세그멘테이션.

edb_make/segment.py 의 `_segment_pdf_problem_markers` 계열 알고리즘을 이식하되,
opencv/numpy 픽셀-프로젝션 대신 PyMuPDF 가 제공하는 텍스트-라인 / 이미지 / 드로잉
bbox 지오메트리만으로 같은 결정을 재현한다(경량 의존성).

파이프라인(페이지 단위):
  1. `page.get_text("dict")` 로 라인 텍스트 + bbox 수집
  2. 라인 선두에서 문항번호 마커(`^([1-9][0-9]?)[.)]\\s`) 매칭 — 날짜/헤더 라인 배제
  3. 마커 center-x 를 클러스터링 → 1단/2단 컬럼 판정(edb `_cluster_pdf_marker_columns`)
  4. 컬럼 내부에서 마커 top → 다음 마커 top 으로 문항 박스 생성
  5. 마지막 ①~⑤ 선지 라인까지(연속 라인 포함) 하단을 다듬고, 선지 아래·다음 마커
     위에 놓인 그림(image/drawing) bbox 가 있으면 재부착
  6. 문항마다 TITLE ContentBlock + ProblemUnit 방출(+ 선택적 STEM/CHOICE 자식 블록)

좌표는 모두 렌더 픽셀 공간(포인트 * dpi/72)으로 저장해 다운스트림 컷아웃이 래스터를
바로 crop 할 수 있게 한다.

범위 밖: 스캔/래스터 PDF(텍스트 레이어 없음). 이 모듈은 born-digital 텍스트-마커
경로만 다룬다. 마커가 0개인 페이지는 빈 PageModel 을 돌려주어 호출자가 "결정론적
세그멘테이션 실패 → AI 폴백" 을 감지할 수 있게 한다.
"""
from __future__ import annotations

import re
from typing import Any

try:  # PyMuPDF: 없으면 이 세그멘터는 비활성(호출부가 pypdf 텍스트 경로로 폴백)
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - 선택 의존성
    fitz = None  # type: ignore[assignment]

from app.recognition.schema import (
    Box,
    BlockType,
    ContentBlock,
    PageModel,
    ProblemUnit,
    Subject,
    classify_text_block,
    is_choice_marker,
)

__all__ = ["segment_pdf"]


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
# 문항번호 마커: 라인 선두의 "12." / "3)" 형태. edb 는 `\.` 만 썼지만 스펙에 맞춰
# 닫는 괄호도 허용한다. 구두점 뒤는 공백 '또는 라인 끝'을 허용 — 평가원 수학처럼
# 번호가 별도 라인("23.")으로 놓이는 경우를 잡되, "1.5" 같은 소수는 아래 suffix
# 검사(선두가 숫자면 배제)로 걸러 오탐을 막는다.
_MARKER_RE = re.compile(r"^([1-9][0-9]?)([.)])(?:\s|$)")
_NUMERIC_CHOICE_MARKER_RE = re.compile(r"^\s*([1-5])([.)])(?:\s|$)")

# 인쇄일/헤더 날짜 라인 판정(edb `_looks_like_pdf_print_date_header`).
_DATE_HEADER_RE = re.compile(r"^[0-9]{2,4}\s*[.\-/]?\s*[0-9]{1,2}\s*[.\-/]?\s*[0-9]{1,2}\.")
_AMPM_MARKERS = ("오전", "오후", "AM", "PM")
# 상단 헤더 밴드에서만 배제 근거로 쓰는 토큰(연/월/교시/배점 표기).
_HEADER_TOKENS = ("年", "월", "교시", "점]", "학년도", "모의평가")

# 객관식 선지 마커. 한컴/출판 도구별 원문자 변형을 함께 받는다.
_CHOICE_MARKERS = (
    "①",
    "②",
    "③",
    "④",
    "⑤",
    "❶",
    "❷",
    "❸",
    "❹",
    "❺",
    "➀",
    "➁",
    "➂",
    "➃",
    "➄",
)


# ---------------------------------------------------------------------------
# 텍스트/헤더 판정 helper
# ---------------------------------------------------------------------------
def _looks_like_date_header(text: str) -> bool:
    """인쇄일/타임스탬프 헤더 라인인가(edb 포팅)."""
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if _DATE_HEADER_RE.match(normalized):
        return True
    if any(marker in normalized for marker in _AMPM_MARKERS):
        return normalized[:1].isdigit() and len(re.findall(r"[0-9]+", normalized)) >= 3
    return False


def _looks_like_header_band_line(text: str) -> bool:
    """상단 밴드에서 마커로 오인하기 쉬운 시험지 머리글(교시/학년도 등)."""
    normalized = str(text or "")
    return any(token in normalized for token in _HEADER_TOKENS)


def _looks_like_footer_band_line(line: dict[str, Any], height_px: float) -> bool:
    """Drop page footer/copyright lines before assigning text to problems."""
    text = str(line.get("text") or "").strip()
    if not text:
        return False
    box = line.get("box")
    top = float(getattr(box, "top", 0.0) or 0.0)
    if "저작권" in text or "한국교육과정평가원" in text:
        return True
    if top >= height_px * 0.90 and re.fullmatch(r"\d{1,3}", text):
        return True
    return False


def _span_text(span: dict[str, Any]) -> str:
    if "text" in span:
        return str(span.get("text") or "")
    chars = span.get("chars") or []
    return "".join(
        str(char.get("c") or "")
        for char in chars
        if isinstance(char, dict)
    )


def _line_text(line: dict[str, Any]) -> str:
    spans = line.get("spans") or []
    return "".join(
        _span_text(span)
        for span in spans
        if isinstance(span, dict)
    ).strip()


def _starts_with_choice_marker(text: str) -> bool:
    stripped = str(text or "").lstrip()
    return stripped[:1] in _CHOICE_MARKERS or bool(_NUMERIC_CHOICE_MARKER_RE.match(stripped))


def _is_numeric_choice_candidate(marker: dict[str, Any]) -> bool:
    text = str(marker.get("text") or "")
    return bool(_NUMERIC_CHOICE_MARKER_RE.match(text))


def _nearest_marker_lane(
    lanes: list[dict[str, Any]],
    x: float,
    *,
    tolerance: float,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_distance = tolerance
    for lane in lanes:
        distance = abs(float(lane.get("x") or 0.0) - x)
        if distance <= best_distance:
            best = lane
            best_distance = distance
    return best


def _filter_choice_like_markers(
    markers: list[dict[str, Any]],
    *,
    width_px: float,
    height_px: float,
) -> tuple[list[dict[str, Any]], int]:
    """Keep real problem markers while suppressing numeric 1)-5) choice runs.

    Born-digital PDFs often expose numeric choices as ordinary text lines. The
    same regex that finds "1." and "23." problem starts can therefore split a
    single problem into six pseudo-problems. We track marker lanes by x-position
    and reject low-number markers when they form a local 1..5 run under the most
    recent accepted problem in that lane.
    """
    if len(markers) <= 1:
        return markers, 0

    ordered = sorted(markers, key=lambda item: (item["box"].top, item["box"].left))
    lane_tolerance = max(42.0, width_px * 0.035)
    choice_gap = max(80.0, height_px * 0.075)
    choice_run_gap = max(70.0, height_px * 0.045)
    lanes: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    suppressed = 0

    def choice_run_ahead(start_index: int, x: float) -> bool:
        expected = int(ordered[start_index].get("number") or 0) + 1
        previous_box: Box = ordered[start_index]["box"]
        found = 1
        for future in ordered[start_index + 1 :]:
            future_box: Box = future["box"]
            if future_box.top - previous_box.bottom > choice_run_gap:
                if abs(future_box.left - x) <= lane_tolerance:
                    break
                continue
            if abs(future_box.left - x) > lane_tolerance:
                continue
            if not _is_numeric_choice_candidate(future):
                break
            number = int(future.get("number") or 0)
            if number != expected:
                break
            found += 1
            expected += 1
            previous_box = future_box
            if found >= 3:
                return True
        return False

    for marker_index, marker in enumerate(ordered):
        box: Box = marker["box"]
        x = box.left
        lane = _nearest_marker_lane(lanes, x, tolerance=lane_tolerance)
        if lane is None:
            lane = {
                "x": x,
                "last_problem_number": None,
                "last_problem_bottom": None,
                "choice_next": None,
                "choice_bottom": None,
            }
            lanes.append(lane)
        else:
            lane["x"] = (float(lane.get("x") or x) * 0.8) + (x * 0.2)

        number = int(marker.get("number") or 0)
        last_problem = lane.get("last_problem_number")
        last_problem_bottom = lane.get("last_problem_bottom")
        choice_next = lane.get("choice_next")
        choice_bottom = lane.get("choice_bottom")
        previous_bottom = (
            float(choice_bottom)
            if isinstance(choice_bottom, (int, float))
            else float(last_problem_bottom)
            if isinstance(last_problem_bottom, (int, float))
            else None
        )
        near_previous = previous_bottom is not None and box.top - previous_bottom <= choice_gap
        numeric_choice = _is_numeric_choice_candidate(marker)

        reject_as_choice = False
        if numeric_choice and isinstance(last_problem, int):
            if isinstance(choice_next, int) and near_previous and number == choice_next:
                reject_as_choice = True
            elif near_previous and number <= last_problem:
                reject_as_choice = True
            elif number == 1 and number <= last_problem and choice_run_ahead(marker_index, x):
                reject_as_choice = True

        if reject_as_choice:
            suppressed += 1
            lane["choice_next"] = number + 1 if number < 5 else None
            lane["choice_bottom"] = box.bottom
            continue

        kept.append(marker)
        lane["last_problem_number"] = number
        lane["last_problem_bottom"] = box.bottom
        lane["choice_next"] = None
        lane["choice_bottom"] = None

    kept.sort(key=lambda item: (item["box"].top, item["box"].left))
    return kept, suppressed


# ---------------------------------------------------------------------------
# PyMuPDF 추출 (픽셀 좌표)
# ---------------------------------------------------------------------------
def _scaled_box(bbox: Any, scale: float) -> Box | None:
    if not bbox or len(bbox) != 4:
        return None
    try:
        left, top, right, bottom = (float(v) * scale for v in bbox)
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return Box.from_points(left, top, right, bottom)


def _scaled_drawing_box(bbox: Any, scale: float) -> Box | None:
    if not bbox or len(bbox) != 4:
        return None
    try:
        left, top, right, bottom = (float(v) * scale for v in bbox)
    except (TypeError, ValueError):
        return None
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    min_stroke = max(1.0, scale)
    if right <= left:
        right = left + min_stroke
    if bottom <= top:
        bottom = top + min_stroke
    return Box.from_points(left, top, right, bottom)


def _box_payload(box: Box) -> list[float]:
    return [box.left, box.top, box.right, box.bottom]


def _line_char_payload(line: dict[str, Any], scale: float) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for span_index, span in enumerate(line.get("spans") or []):
        if not isinstance(span, dict):
            continue
        font = str(span.get("font") or "")
        size = span.get("size")
        flags = span.get("flags")
        for char_index, char in enumerate(span.get("chars") or []):
            if not isinstance(char, dict):
                continue
            value = str(char.get("c") or "")
            if not value:
                continue
            box = _scaled_box(char.get("bbox"), scale)
            if box is None:
                continue
            item: dict[str, Any] = {
                "c": value,
                "bbox": _box_payload(box),
                "span": span_index,
                "index": char_index,
            }
            if font:
                item["font"] = font
            if isinstance(size, (int, float)):
                item["size"] = float(size)
            if isinstance(flags, int):
                item["flags"] = flags
            payload.append(item)
    return payload


def _line_span_payload(line: dict[str, Any], scale: float) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for span_index, span in enumerate(line.get("spans") or []):
        if not isinstance(span, dict):
            continue
        text = _span_text(span)
        if not text:
            continue
        box = _scaled_box(span.get("bbox"), scale)
        item: dict[str, Any] = {
            "text": text,
            "index": span_index,
        }
        if box is not None:
            item["bbox"] = _box_payload(box)
        font = str(span.get("font") or "")
        if font:
            item["font"] = font
        size = span.get("size")
        if isinstance(size, (int, float)):
            item["size"] = float(size)
        flags = span.get("flags")
        if isinstance(flags, int):
            item["flags"] = flags
        payload.append(item)
    return payload


def _line_geometry_payload(line: dict[str, Any], scale: float) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    chars = _line_char_payload(line, scale)
    if chars:
        payload["pdf_line_chars"] = chars
    spans = _line_span_payload(line, scale)
    if spans:
        payload["pdf_line_spans"] = spans
    return payload


def _extract_text_lines(page: Any, scale: float) -> list[dict[str, Any]]:
    """페이지의 모든 (비어있지 않은) 텍스트 라인 → {box, text} (픽셀 좌표)."""
    lines: list[dict[str, Any]] = []
    try:
        data = page.get_text("rawdict")
    except Exception:
        try:
            data = page.get_text("dict")
        except Exception:
            return lines
    for block in data.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        for line in block.get("lines") or []:
            if not isinstance(line, dict):
                continue
            text = _line_text(line)
            if not text:
                continue
            box = _scaled_box(line.get("bbox"), scale)
            if box is None:
                continue
            item = {"box": box, "text": text}
            item.update(_line_geometry_payload(line, scale))
            lines.append(item)
    lines.sort(key=lambda item: (item["box"].top, item["box"].left))
    return lines


def _extract_markers(
    text_lines: list[dict[str, Any]],
    *,
    height_px: float,
) -> list[dict[str, Any]]:
    """텍스트 라인에서 문항번호 마커를 뽑는다(edb `_extract_pdf_problem_markers` 포팅)."""
    markers: list[dict[str, Any]] = []
    top_band = height_px * 0.05
    for line in text_lines:
        text = str(line["text"])
        box: Box = line["box"]
        if _looks_like_date_header(text):
            continue
        match = _MARKER_RE.match(text)
        if not match:
            continue
        number = int(match.group(1))
        if not 1 <= number <= 99:
            continue
        # 상단 ~5% 밴드의 교시/날짜성 머리글 배제
        if box.top < top_band and _looks_like_header_band_line(text):
            continue
        if box.height <= 0.5:  # 0 높이 마커 skip
            continue
        markers.append(
            {
                "number": number,
                "punct": match.group(2),
                "text": text[:120],
                "box": box,
                "line": line,
            }
        )
    return markers


def _filter_figure_embedded_markers(
    markers: list[dict[str, Any]],
    figures: list[Box],
    *,
    width_px: float,
    height_px: float,
) -> tuple[list[dict[str, Any]], int]:
    """자료/그림 안의 번호 목록을 실제 문항 시작과 구분한다.

    단순히 figure 안의 모든 번호를 지우면 문항 전체를 테두리로 감싼 출판물에서 실제
    번호까지 잃을 수 있다. 따라서 (1) 비교적 작은 지역 figure 안에 완전히 포함되고,
    (2) figure 밖에서 확인된 문항 마커보다 글자 높이가 확실히 작은 후보만 억제한다.
    """
    if not markers or not figures:
        return markers, 0

    page_area = max(1.0, float(width_px) * float(height_px))
    max_region_area = page_area * 0.20
    margin = 2.0

    def containing_region(marker: dict[str, Any]) -> Box | None:
        box: Box = marker["box"]
        candidates = [
            figure
            for figure in figures
            if figure.area <= max_region_area
            and box.left >= figure.left - margin
            and box.right <= figure.right + margin
            and box.top >= figure.top - margin
            and box.bottom <= figure.bottom + margin
        ]
        return min(candidates, key=lambda figure: figure.area) if candidates else None

    outside_heights = sorted(
        float(marker["box"].height)
        for marker in markers
        if containing_region(marker) is None and float(marker["box"].height) > 0
    )
    if not outside_heights:
        return markers, 0
    middle = len(outside_heights) // 2
    if len(outside_heights) % 2:
        reference_height = outside_heights[middle]
    else:
        reference_height = (outside_heights[middle - 1] + outside_heights[middle]) / 2.0

    kept: list[dict[str, Any]] = []
    suppressed = 0
    for marker in markers:
        region = containing_region(marker)
        marker_height = float(marker["box"].height)
        if region is not None and marker_height <= reference_height * 0.92:
            suppressed += 1
            continue
        kept.append(marker)
    return kept, suppressed


def _union_box(a: Box, b: Box) -> Box:
    return Box.from_points(
        min(a.left, b.left), min(a.top, b.top), max(a.right, b.right), max(a.bottom, b.bottom)
    )


def _intersection_area(a: Box, b: Box) -> float:
    left = max(a.left, b.left)
    top = max(a.top, b.top)
    right = min(a.right, b.right)
    bottom = min(a.bottom, b.bottom)
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def _boxes_near(a: Box, b: Box, gap: float) -> bool:
    """a 를 gap 만큼 확장했을 때 b 와 겹치면 True (인접/중첩 판정)."""
    return not (
        b.left > a.right + gap
        or b.right < a.left - gap
        or b.top > a.bottom + gap
        or b.bottom < a.top - gap
    )


def _merge_boxes(
    boxes: list[Box],
    *,
    gap: float = 8.0,
    max_iter: int = 60,
    max_width: float | None = None,
    max_height: float | None = None,
) -> list[Box]:
    """겹치거나 인접한 박스들을 합성 영역으로 union 한다.

    벡터 그래프는 축·격자·곡선이 각각 별도 드로잉 rect 로 오는데(fitz get_drawings),
    병합하지 않으면 그림 cutout 이 가로 줄무늬처럼 조각난다. 그래프 내부 스트로크는
    서로 겹치므로 union 하면 하나의 그림 영역이 된다.

    max_width/max_height 를 주면 그 크기를 넘는 union 은 하지 않는다 — 과탐처럼 벡터가
    밀집한 페이지에서 서로 다른 문항의 획들이 연쇄 병합돼 '페이지 전체 블롭'이 되는
    과병합을 막는다(단일 문항 그림은 페이지 절반을 넘지 않는다는 가정).
    """
    items = [b for b in boxes if b is not None]
    changed = True
    iterations = 0
    while changed and iterations < max_iter:
        changed = False
        iterations += 1
        merged: list[Box] = []
        used = [False] * len(items)
        for i in range(len(items)):
            if used[i]:
                continue
            current = items[i]
            used[i] = True
            for j in range(i + 1, len(items)):
                if used[j]:
                    continue
                if not _boxes_near(current, items[j], gap):
                    continue
                candidate = _union_box(current, items[j])
                if max_width is not None and candidate.width > max_width:
                    continue
                if max_height is not None and candidate.height > max_height:
                    continue
                current = candidate
                used[j] = True
                changed = True
            merged.append(current)
        items = merged
    return items


def _extract_figures(page: Any, scale: float) -> list[Box]:
    """페이지의 embedded 이미지 + 유의미한 드로잉 bbox(픽셀 좌표).

    개별 벡터 스트로크는 마지막에 `_merge_boxes` 로 합성 그림 영역으로 병합한다.
    """
    figures: list[Box] = []
    try:
        page_w = float(page.rect.width) * scale
        page_h = float(page.rect.height) * scale
    except Exception:
        page_w = page_h = 0.0
    # 임베디드 래스터 이미지
    try:
        for info in page.get_image_info() or []:
            if not isinstance(info, dict):
                continue
            box = _scaled_box(info.get("bbox"), scale)
            if box is not None:
                figures.append(box)
    except Exception:
        pass
    # 벡터 드로잉(도형/그래프). 개별 스트로크가 많으므로 유의미한 크기만 수집.
    try:
        min_area = max(400.0, (page_w * page_h) * 0.0008)
        min_line_length = max(50.0, page_w * 0.04)
        for drawing in page.get_drawings() or []:
            if not isinstance(drawing, dict):
                continue
            rect = drawing.get("rect")
            if rect is None:
                continue
            box = _scaled_drawing_box(
                (rect.x0, rect.y0, rect.x1, rect.y1) if hasattr(rect, "x0") else rect,
                scale,
            )
            if box is None:
                continue
            thin_long_line = (
                min(box.width, box.height) <= max(3.0, scale * 2.0)
                and max(box.width, box.height) >= min_line_length
            )
            if box.area < min_area and not thin_long_line:
                continue
            figures.append(box)
    except Exception:
        pass
    # 개별 스트로크/rect 를 합성 그림 영역으로 병합(가로 줄무늬 조각남 방지).
    # 단일 문항 그림은 페이지 절반 높이/폭 이내라고 보고, 그 이상 커지는 연쇄
    # 과병합(과탐 등 벡터 밀집 페이지의 '페이지 전체 블롭')은 막는다.
    max_w = page_w * 0.8 if page_w else None
    max_h = page_h * 0.5 if page_h else None
    return _merge_boxes(figures, max_width=max_w, max_height=max_h)


# ---------------------------------------------------------------------------
# 컬럼 클러스터링 (edb `_cluster_pdf_marker_columns` / `_column_bounds...` 포팅)
# ---------------------------------------------------------------------------
def _cluster_columns(
    markers: list[dict[str, Any]],
    width_px: float,
) -> tuple[list[list[dict[str, Any]]], list[tuple[float, float]]]:
    """마커 center-x 를 최대 gap 기준으로 1~2 컬럼으로 나눈다.

    Returns (columns, bounds) — bounds[i] = (left, right) 픽셀.
    """
    if not markers:
        return [], []
    pairs = sorted(
        (((m["box"].left + m["box"].right) / 2.0, m) for m in markers),
        key=lambda item: item[0],
    )
    if len(pairs) == 1:
        return [[pairs[0][1]]], [(0.0, width_px)]

    gaps = [
        (pairs[i + 1][0] - pairs[i][0], i)
        for i in range(len(pairs) - 1)
    ]
    largest_gap, split_index = max(gaps, key=lambda item: item[0])
    if largest_gap < max(80.0, width_px * 0.18):
        # 단일 컬럼
        return [[m for _, m in pairs]], [(0.0, width_px)]

    # 2 컬럼: 물리적 컬럼은 대체로 균형이 맞으므로 페이지 중앙을 crop 경계로 쓴다.
    split_x = width_px / 2.0
    left_col = [m for _, m in pairs[: split_index + 1]]
    right_col = [m for _, m in pairs[split_index + 1:]]
    return [left_col, right_col], [(0.0, split_x), (split_x, width_px)]


# ---------------------------------------------------------------------------
# 문항 박스 하단 다듬기 (edb `_trim_pdf_problem_bottom_to_last_choice` 포팅)
# ---------------------------------------------------------------------------
def _lines_in_region(
    text_lines: list[dict[str, Any]],
    *,
    left: float,
    right: float,
    top: float,
    bottom: float,
) -> list[dict[str, Any]]:
    region: list[dict[str, Any]] = []
    for line in text_lines:
        box: Box = line["box"]
        center_x = (box.left + box.right) / 2.0
        if center_x < left - 6.0 or center_x > right + 6.0:
            continue
        if box.bottom < top - 2.0 or box.top > bottom + 2.0:
            continue
        region.append(line)
    region.sort(key=lambda item: (item["box"].top, item["box"].left))
    return region


def _line_inside_figure(line: dict[str, Any], figures: list[Box], problem_box: Box) -> bool:
    box: Box = line["box"]
    center_x = (box.left + box.right) / 2.0
    center_y = (box.top + box.bottom) / 2.0
    for fig in figures:
        if fig.area < 900.0:
            continue
        if _intersection_area(fig, problem_box) < fig.area * 0.6:
            continue
        if fig.left - 2.0 <= center_x <= fig.right + 2.0 and fig.top - 2.0 <= center_y <= fig.bottom + 2.0:
            return True
    return False


def _refine_problem_bottom(
    *,
    region_lines: list[dict[str, Any]],
    figures: list[Box],
    left: float,
    right: float,
    top: float,
    initial_bottom: float,
    height_px: float,
) -> float:
    """다음-마커-top 으로 잡은 initial_bottom 을 실제 콘텐츠 하단으로 다듬는다.

    마지막 ①~⑤ 선지(+연속 라인)까지 내리고, 선지 아래·다음마커 위에 그림이 있으면
    재부착한다. 선지가 없으면 마지막 텍스트 라인까지 다듬어 후행 여백을 제거한다.
    """
    pad = max(8.0, height_px * 0.008)
    min_height = 40.0
    if not region_lines:
        return initial_bottom

    heights = [ln["box"].height for ln in region_lines if ln["box"].height > 0]
    median_h = sorted(heights)[len(heights) // 2] if heights else 18.0
    continuation_gap = max(18.0, min(72.0, max(median_h * 2.2, height_px * 0.018)))

    choice_indexes = [
        i for i, ln in enumerate(region_lines)
        if _starts_with_choice_marker(ln["text"])
    ]
    if choice_indexes:
        content_bottom = region_lines[choice_indexes[-1]]["box"].bottom
        # 마지막 선지 뒤 연속(줄바꿈된) 라인 흡수
        for ln in region_lines[choice_indexes[-1] + 1:]:
            gap = ln["box"].top - content_bottom
            if gap > continuation_gap:
                break
            content_bottom = max(content_bottom, ln["box"].bottom)
    else:
        # 선지 없음 → 마지막 텍스트 라인까지만
        content_bottom = max(ln["box"].bottom for ln in region_lines)

    # 그림(도형/이미지) 재부착: 선지 아래 ~ 다음 마커 위, 컬럼 폭 내부
    max_tail_gap = max(120.0, min(260.0, height_px * 0.12))
    column_width = max(1.0, right - left)
    for fig in figures:
        fig_center_x = (fig.left + fig.right) / 2.0
        if fig_center_x < left - 6.0 or fig_center_x > right + 6.0:
            continue
        if fig.right - fig.left > column_width * 1.4:
            continue  # 전면 배경/테두리성 드로잉 배제
        if fig.top < content_bottom - 4.0 or fig.top > initial_bottom + 2.0:
            continue
        if fig.top - content_bottom > max_tail_gap:
            continue
        content_bottom = max(content_bottom, min(initial_bottom, fig.bottom))

    refined = min(initial_bottom, content_bottom + pad)
    if refined - top < min_height:
        return initial_bottom
    return refined


# ---------------------------------------------------------------------------
# 페이지 세그멘테이션
# ---------------------------------------------------------------------------
def _segment_page(
    page: Any,
    *,
    page_index: int,
    scale: float,
    dpi: int,
    subject: Subject,
) -> PageModel:
    width_pt = float(page.rect.width)
    height_pt = float(page.rect.height)
    width_px = round(width_pt * scale)
    height_px = round(height_pt * scale)
    page_id = f"page-{page_index + 1:03d}"

    base_metadata: dict[str, Any] = {
        "source": "pdf-text-markers",
        "segmenter": "pdf-text-markers",
        "render_scale": scale,
        "dpi": dpi,
        "page_width_pt": width_pt,
        "page_height_pt": height_pt,
    }

    text_lines = _extract_text_lines(page, scale)
    header_cutoff = float(height_px) * 0.13
    base_metadata["header_text"] = " ".join(
        str(line.get("text") or "").strip()
        for line in text_lines
        if str(line.get("text") or "").strip()
        and getattr(line.get("box"), "top", float(height_px)) <= header_cutoff
    )
    footer_removed = sum(
        1 for line in text_lines if _looks_like_footer_band_line(line, float(height_px))
    )
    text_lines = [
        line
        for line in text_lines
        if not _looks_like_footer_band_line(line, float(height_px))
    ]
    base_metadata["footer_line_removed_count"] = footer_removed
    figures = _extract_figures(page, scale)
    base_metadata["figure_bboxes_px"] = [
        [fig.left, fig.top, fig.right, fig.bottom] for fig in figures
    ]

    raw_markers = _extract_markers(text_lines, height_px=float(height_px))
    figure_filtered_markers, suppressed_figure_markers = _filter_figure_embedded_markers(
        raw_markers,
        figures,
        width_px=float(width_px),
        height_px=float(height_px),
    )
    markers, suppressed_choice_markers = _filter_choice_like_markers(
        figure_filtered_markers,
        width_px=float(width_px),
        height_px=float(height_px),
    )
    base_metadata["raw_marker_count"] = len(raw_markers)
    base_metadata["figure_marker_suppressed_count"] = suppressed_figure_markers
    base_metadata["choice_marker_suppressed_count"] = suppressed_choice_markers
    base_metadata["marker_count"] = len(markers)

    page_model = PageModel(
        page_id=page_id,
        width_px=width_px,
        height_px=height_px,
        subject=subject,
        source_path=None,
        blocks=[],
        problems=[],
        metadata=base_metadata,
    )

    if not markers:
        base_metadata["column_count"] = 0
        # 마커 없는 born-digital 페이지도 텍스트를 버리지 않는다. 공유 지문 페이지는 다음
        # 페이지의 실제 문항과 연결할 수 있고, 일반 혼합 페이지 fallback도 검색 가능한
        # 텍스트를 유지할 수 있다. 2단 시험지의 기본 읽기 순서(왼쪽→오른쪽)를 적용한다.
        ordered_lines = sorted(
            text_lines,
            key=lambda line: (
                0 if line["box"].left < float(width_px) * 0.5 else 1,
                line["box"].top,
                line["box"].left,
            ),
        )
        for order, line in enumerate(ordered_lines):
            block_metadata = {
                "segmenter": "pdf-unsegmented-text",
                "unsegmented_page": True,
            }
            block_metadata.update(
                {
                    key: value
                    for key, value in line.items()
                    if key in {"pdf_line_chars", "pdf_line_spans"} and value
                }
            )
            page_model.blocks.append(
                ContentBlock(
                    block_id=f"{page_id}-unsegmented-{order + 1:03d}",
                    block_type=classify_text_block(str(line.get("text") or "")),
                    bbox=line["box"],
                    reading_order=order,
                    text=str(line.get("text") or ""),
                    confidence=1.0,
                    metadata=block_metadata,
                )
            )
        base_metadata["unsegmented_text_block_count"] = len(page_model.blocks)
        return page_model

    columns, bounds = _cluster_columns(markers, float(width_px))
    base_metadata["column_count"] = len(columns)

    # 컬럼별로 문항 서술자(descriptor) 생성
    descriptors: list[dict[str, Any]] = []
    for col_index, (col_markers, (left_bound, right_bound)) in enumerate(
        zip(columns, bounds), start=1
    ):
        ordered = sorted(col_markers, key=lambda m: m["box"].top)
        for i, marker in enumerate(ordered):
            marker_box: Box = marker["box"]
            marker_pad_y = max(10.0, height_px * 0.006)
            top = max(0.0, marker_box.top - marker_pad_y)
            if i + 1 < len(ordered):
                next_top = ordered[i + 1]["box"].top
                initial_bottom = max(top + 40.0, next_top - max(8.0, height_px * 0.004))
            else:
                initial_bottom = float(height_px)
            initial_bottom = min(float(height_px), initial_bottom)

            region_lines = _lines_in_region(
                text_lines,
                left=left_bound,
                right=right_bound,
                top=top,
                bottom=initial_bottom,
            )
            bottom = _refine_problem_bottom(
                region_lines=region_lines,
                figures=figures,
                left=left_bound,
                right=right_bound,
                top=top,
                initial_bottom=initial_bottom,
                height_px=float(height_px),
            )
            region_lines = [
                line
                for line in region_lines
                if line["box"].bottom >= top - 2.0 and line["box"].top <= bottom + 2.0
            ]
            box = Box.from_points(
                left_bound, top, right_bound, min(float(height_px), bottom)
            )
            descriptors.append(
                {
                    "column_index": col_index,
                    "question_band_index": i + 1,
                    "number": marker["number"],
                    "marker_text": marker["text"],
                    "marker_line": marker["line"],
                    "box": box,
                    "region_lines": region_lines,
                }
            )

    # 읽기 순서: (컬럼, top)
    descriptors.sort(key=lambda d: (d["column_index"], d["box"].top))

    block_seq = 0
    unit_seq = 0
    for desc in descriptors:
        block_seq += 1
        title_id = f"{page_id}-block-{block_seq:03d}"
        number = desc["number"]
        marker_text = desc["marker_text"]
        marker_line = desc["marker_line"]

        problem_meta = {
            "segmenter": "pdf-text-markers",
            "pdf_problem_number": number,
            "problem_number": number,
            "problem_number_source": "pdf_text_marker",
            "column_index": desc["column_index"],
            "question_band_index": desc["question_band_index"],
            "force_problem_start": True,
            "marker_kind": "number",
            "marker_text": marker_text,
            "display_title": f"{number}.",
        }
        problem_meta.update(
            {
                key: value
                for key, value in marker_line.items()
                if key in {"pdf_line_chars", "pdf_line_spans"} and value
            }
        )

        # 자식 STEM/CHOICE 블록(선택). 마커 라인 자신은 제외.
        child_ids: list[str] = []
        stem_ids: list[str] = [title_id]
        choice_ids: list[str] = []
        child_blocks: list[ContentBlock] = []
        for line in desc["region_lines"]:
            if line is marker_line:
                continue
            child_text = str(line["text"])
            if not child_text:
                continue
            if _line_inside_figure(line, figures, desc["box"]):
                continue
            block_type = classify_text_block(child_text)
            block_seq += 1
            child_id = f"{page_id}-block-{block_seq:03d}"
            child_metadata = {
                "segmenter": "pdf-text-markers",
                "parent_block_id": title_id,
                "problem_number": number,
                "column_index": desc["column_index"],
            }
            child_metadata.update(
                {
                    key: value
                    for key, value in line.items()
                    if key in {"pdf_line_chars", "pdf_line_spans"} and value
                }
            )
            child_blocks.append(
                ContentBlock(
                    block_id=child_id,
                    block_type=block_type,
                    bbox=line["box"],
                    reading_order=0,  # 임시, 아래에서 리스트 순서대로 재부여
                    text=child_text,
                    confidence=1.0,
                    metadata=child_metadata,
                )
            )
            child_ids.append(child_id)
            if block_type == BlockType.CHOICE or is_choice_marker(child_text):
                choice_ids.append(child_id)
            else:
                stem_ids.append(child_id)

        title_block = ContentBlock(
            block_id=title_id,
            block_type=BlockType.TITLE,
            bbox=desc["box"],
            reading_order=0,  # 임시, 아래에서 재부여
            text=marker_text if marker_text else f"{number}.",
            confidence=1.0,
            children=child_ids,
            metadata=problem_meta,
        )
        page_model.blocks.append(title_block)
        page_model.blocks.extend(child_blocks)

        unit_seq += 1
        page_model.problems.append(
            ProblemUnit(
                unit_id=f"{page_id}-unit-{unit_seq:03d}",
                subject=subject,
                title=str(number),
                stem_block_ids=stem_ids,
                choice_block_ids=choice_ids,
                metadata={
                    "segmenter": "pdf-text-markers",
                    "pdf_problem_number": number,
                    "problem_number": number,
                    "column_index": desc["column_index"],
                    "title_block_id": title_id,
                    "force_problem_start": True,
                },
            )
        )

    # reading_order 를 문서 순서(컬럼→문항→내부라인)대로 재부여: 안정 정렬로
    # 현재 blocks 리스트 순서(문항 title 다음 그 자식들)를 그대로 반영한다.
    for order, block in enumerate(page_model.blocks):
        block.reading_order = order

    base_metadata["problem_count"] = len(page_model.problems)
    base_metadata["document_split_applied"] = True
    return page_model


def segment_pdf(
    pdf_bytes: bytes,
    *,
    dpi: int = 150,
    subject: Subject = Subject.UNKNOWN,
) -> list[PageModel]:
    """born-digital 시험 PDF 를 문항 단위로 분할해 PageModel 리스트를 돌려준다.

    Parameters
    ----------
    pdf_bytes : bytes
        PDF 파일 바이트.
    dpi : int
        다운스트림 래스터 렌더 해상도. 모든 블록 bbox 는 pt * (dpi/72) 픽셀 좌표로 저장.
    subject : Subject
        과목 힌트(ProblemUnit.subject 로 전파).

    Returns
    -------
    list[PageModel]
        페이지당 하나. 마커가 없거나 malformed 인 페이지도 (빈 problems 로) 포함된다.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF(fitz)가 설치되어 있지 않아 PDF 세그멘테이션을 할 수 없습니다.")
    scale = float(dpi) / 72.0
    pages: list[PageModel] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_index in range(doc.page_count):
            try:
                page = doc.load_page(page_index)
                pages.append(
                    _segment_page(
                        page,
                        page_index=page_index,
                        scale=scale,
                        dpi=dpi,
                        subject=subject,
                    )
                )
            except Exception as exc:  # 페이지 단위로 격리 — 절대 전체 실패시키지 않는다
                pages.append(
                    PageModel(
                        page_id=f"page-{page_index + 1:03d}",
                        width_px=0,
                        height_px=0,
                        subject=subject,
                        source_path=None,
                        blocks=[],
                        problems=[],
                        metadata={
                            "source": "pdf-text-markers",
                            "segmenter": "pdf-text-markers",
                            "dpi": dpi,
                            "render_scale": scale,
                            "marker_count": 0,
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                )
    finally:
        doc.close()
    return pages
