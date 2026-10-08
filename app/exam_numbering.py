"""Pure premium export preparation; the legacy/basic conversion bypasses this module.

Callers translate ``NumberingError.detail`` into a 422 response. Item positions
are one-based. Duplicate original numbers require explicit review in preserve
mode. Returned dictionaries are export snapshots, never storage updates.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re
from typing import Any


class NumberingError(ValueError):
    def __init__(self, code: str, message: str, items: list[dict[str, Any]] | None = None):
        self.detail = {"code": code, "message": message, "items": items or []}
        super().__init__(message)


_PASSAGE_RANGE = re.compile(r"^\s*\[?\s*\d+\s*[~∼\-–]\s*\d+\s*\]?")
_SHARED_HEADING = re.compile(r"^(\s*)\[\s*(\d{1,3})\s*[~∼～\-–]\s*(\d{1,3})\s*\]")


def _shared_number_marker(problem):
    number = str(problem.get("number") or "").strip()
    return list(re.finditer(r"(?m)^[ \t]*(?:문제[ \t]*)?(?P<number>" + re.escape(number)
                           + r")[ \t]*[.)](?:[ \t]+|(?=\r?$))", str(problem.get("stem") or "")))


def _can_renumber_shared(problem):
    """Only rewrite a source-matched heading and one independent question label."""
    layout = problem.get("layout") or {}
    if not isinstance(layout, dict) or not _self_contained_shared_question(problem, layout):
        return False
    heading = _SHARED_HEADING.match(str(problem.get("stem") or ""))
    return bool(heading and [int(heading[2]), int(heading[3])] == list(layout["shared_passage"]["range"])
                and len(_shared_number_marker(problem)) == 1)


def _renumber_shared_snapshot(problem, output_number):
    original = str(problem.get("number") or "").strip()
    if output_number == original:
        return
    marker = _shared_number_marker(problem)[0]
    stem = problem["stem"]
    stem = stem[:marker.start("number")] + output_number + stem[marker.end("number"):]
    # Each selected question already includes its own full passage. A single
    # output label avoids claiming that unselected/interleaved questions belong
    # to this copy. The original range remains intact in provenance metadata.
    problem["stem"] = _SHARED_HEADING.sub(lambda match: match[1] + "[" + output_number + "]", stem, count=1)


def _issue(problem: dict[str, Any], position: int, reason: str, message: str) -> dict[str, Any]:
    return {
        "position": position,
        "problem_id": problem.get("id"),
        "original_number": str(problem.get("number") or "").strip(),
        "reason": reason,
        "message": message,
    }


def _self_contained_shared_question(problem: dict[str, Any], layout: dict[str, Any]) -> bool:
    """An imported question can carry a complete copy of its shared passage.

    Its range and PDF coordinates are provenance, while a separate numbered
    body makes it safe to select and export alone with its original number.
    Range-only passage rows and references to external groups remain unsupported.
    """
    shared = layout.get("shared_passage")
    if layout.get("block_type") != "problem_with_shared_passage" or not isinstance(shared, dict):
        return False
    number = str(problem.get("number") or "").strip()
    passage_range = shared.get("range")
    if not re.fullmatch(r"\d{1,3}", number) or not isinstance(passage_range, (list, tuple)) or len(passage_range) != 2:
        return False
    try:
        if not int(passage_range[0]) <= int(number) <= int(passage_range[1]):
            return False
    except (TypeError, ValueError):
        return False
    stem = str(problem.get("stem") or "")
    marker = re.search(r"(?m)^[ \t]*(?:문제[ \t]*)?" + re.escape(number)
                       + r"[ \t]*[.)](?:[ \t]+|(?=\r?$))", stem)
    return bool(marker and stem[marker.end():].strip())


def _unsupported_reason(problem: dict[str, Any], *, allow_self_contained_shared: bool = False) -> tuple[str, str] | None:
    layout = problem.get("layout") or {}
    if not isinstance(layout, dict):
        return "unknown_layout", "문항 배치 정보를 확인한 후 다시 추가해 주세요."
    self_contained_shared = allow_self_contained_shared and _self_contained_shared_question(problem, layout)
    number = str(problem.get("number") or "")
    if (problem.get("problem_type") == "passage" or problem.get("is_passage")
            or _PASSAGE_RANGE.match(number)
            or (not self_contained_shared and re.match(r"^\s*\[\s*\d+\s*[~∼\-–]\s*\d+\s*\]", str(problem.get("stem") or "")))):
        return "passage", "공유 지문은 아직 자동 번호를 지원하지 않습니다. 해당 묶음을 제외해 주세요."
    if layout.get("block_type") == "problem_with_shared_passage" and not self_contained_shared:
        return "group", "공유 지문에 연결된 문항은 묶음 편집 지원 후 사용할 수 있습니다."
    for key in ("group_id", "passage_id", "passage_item_id", "member_item_ids", "group", "shared_passage"):
        if key == "shared_passage" and self_contained_shared and not problem.get(key):
            continue
        if problem.get(key) or layout.get(key):
            return "group", "공유 지문에 연결된 문항은 묶음 편집 지원 후 사용할 수 있습니다."
    for key, message in (
        ("continuation", "이어지는 문항 조각을 하나의 편집 가능한 문항으로 합쳐 주세요."),
        ("source_text_flow", "원본 흐름 문서를 편집 가능한 일반 문항으로 가져와 주세요."),
    ):
        if problem.get(key) or layout.get(key):
            return key, message
    if (problem.get("image_only") or layout.get("image_only")
            or layout.get("block_type") == "image_fallback"
            or (not str(problem.get("stem") or "").strip()
                and not problem.get("choices") and problem.get("image_paths"))):
        return "image_only", "이미지 속 번호는 바뀌지 않습니다. 텍스트 문항으로 변환·검수해 주세요."
    # Editable PDF imports also carry coordinates as provenance. Their explicit
    # problem block type distinguishes them from fixed source-layout exports.
    fixed_coordinates = layout.get("block_type") != "problem" and not self_contained_shared and (
        (layout.get("column_index") and (layout.get("source_page") or problem.get("source_page")))
        or layout.get("bbox_px") or layout.get("source_lines")
    )
    if (problem.get("source_layout") or problem.get("preserve_source_layout")
            or layout.get("source_layout") or layout.get("preserve_source_layout")
            or fixed_coordinates):
        return "source_layout", "원본 좌표 보존 문서는 기본 변환을 이용하거나 일반 문항으로 가져와 주세요."
    return None


def _strip_original_prefix(stem: str, original_number: str) -> str:
    # A decimal such as 27.5 and expressions such as 27.+x are content.
    # Only a known original label followed by a delimited question marker is removed.
    if not re.fullmatch(r"\d{1,3}", original_number):
        return stem
    prefix = re.compile(
        r"^[ \t]*(?:문제[ \t]*)?" + re.escape(original_number)
        + r"[ \t]*[.)](?:[ \t]+|(?=\r?\n|$))"
    )
    return prefix.sub("", stem, count=1)


def prepare_export_problems(
    problems: list[dict[str, Any]],
    numbering_mode: str = "preserve",
    start_number: int = 1,
    *,
    confirm_duplicate_numbers: bool = False,
) -> list[dict[str, Any]]:
    """Validate and deep-copy an ordered premium selection for both writers/preview.

    ``preserve`` rejects blank numbers and requires confirmation of duplicates.
    Both modes reject unsupported content. ``sequential`` accepts blank/duplicate
    originals and assigns consecutive strings. Start and final numbers must be <= 999.
    ``_numbering_prepared`` tells writers that prefix cleanup already happened;
    it prevents a second pass from mistaking a decimal for the new output number.
    """
    if numbering_mode not in {"preserve", "sequential"}:
        raise NumberingError("invalid_numbering_mode", "번호 방식을 원번호 유지 또는 연속 번호로 선택해 주세요.")
    if isinstance(start_number, bool) or not isinstance(start_number, int) or not 1 <= start_number <= 999:
        raise NumberingError("invalid_start_number", "시작 번호는 1부터 999까지의 정수여야 합니다.")
    if numbering_mode == "sequential" and start_number + len(problems) - 1 > 999:
        raise NumberingError("number_range_exceeded", "마지막 번호가 999를 넘습니다. 시작 번호나 문항 수를 줄여 주세요.")

    issues = []
    counts = Counter(str(p.get("number") or "").strip() for p in problems)
    for position, problem in enumerate(problems, 1):
        original = str(problem.get("number") or "").strip()
        unsupported = _unsupported_reason(problem, allow_self_contained_shared=True)
        if unsupported:
            issues.append(_issue(problem, position, *unsupported))
        elif (numbering_mode == "sequential" and _self_contained_shared_question(problem, problem.get("layout") or {})
              and not _can_renumber_shared(problem)):
            issues.append(_issue(problem, position, "ambiguous_shared_number",
                                 "공유 지문의 원번호·범위가 불명확합니다. 문항 번호와 묶음 안내를 확인해 주세요."))
        elif numbering_mode == "preserve" and not original:
            issues.append(_issue(problem, position, "missing_original_number", "원번호가 비어 있습니다. 원번호를 수정하거나 연속 번호를 선택해 주세요."))
        elif numbering_mode == "preserve" and counts[original] > 1 and not confirm_duplicate_numbers:
            issues.append(_issue(problem, position, "duplicate_original_number", "같은 원번호가 있습니다. 출처를 확인하고 중복 원번호 사용을 확인해 주세요."))
    if issues:
        raise NumberingError("numbering_review_required", "번호 검수 항목을 확인해 주세요.", issues)

    result = deepcopy(problems)
    for offset, problem in enumerate(result):
        original = str(problem.get("number") or "").strip()
        # The writers need to place the label after the copied passage even
        # with the UI's basic/simple templates. Compute this before rewriting
        # the source range, from the same evidence used by the preflight.
        problem.pop("_shared_numbering_prepared", None)
        if _can_renumber_shared(problem):
            problem["_shared_numbering_prepared"] = True
        if (numbering_mode == "sequential"
                and _self_contained_shared_question(problem, problem.get("layout") or {})):
            _renumber_shared_snapshot(problem, str(start_number + offset))
        if isinstance(problem.get("stem"), str):
            problem["stem"] = _strip_original_prefix(problem["stem"], original)
        if numbering_mode == "sequential":
            problem["number"] = str(start_number + offset)
        problem["_numbering_prepared"] = True
    return result
