from __future__ import annotations

import base64
import binascii
import csv
import io
import re
import shutil
import sqlite3
import struct
import uuid
import zipfile
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

from lxml import etree
from PIL import Image
from pypdf import PdfReader

from . import storage
from .math_text import normalize_recognized_math_layout_text, normalize_recognized_math_text
from .pdf_math_geometry import (
    glyphs_near_mark,
    line_geometry_glyphs,
    line_geometry_source_text,
    reading_order_line_geometries,
    repair_problem_math_layout,
)

try:  # OCR은 선택 사항: pytesseract + tesseract 실행 파일이 있을 때만 사용
    import pytesseract

    pytesseract.get_tesseract_version()
    HAS_OCR = True
except Exception:
    pytesseract = None
    HAS_OCR = False

try:  # rhwp(러스트 HWP 엔진)는 선택 사항: 있으면 HWP 텍스트 추출에 우선 사용
    import rhwp
except Exception:
    rhwp = None


SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z가-힣._ -]+")
MAX_PDF_PAGES = 500
MAX_IMAGE_PIXELS = 50_000_000
QUESTION_START_RE = re.compile(
    r"(?m)(?=^\s*(?:문제\s*)?\d{1,3}\s*[\.\)]|\n\s*(?:문제\s*)?\d{1,3}\s*[\.\)])"
)
# 시험지 제작 도구마다 서로 다른 원문자 블록을 쓴다. 한컴 기본 원문자(①),
# dingbat 음각(❶), dingbat sans-serif(➀)를 모두 같은 선택지 마커로 취급한다.
CIRCLED_CHOICE_MARKERS = "①②③④⑤⑥⑦⑧⑨❶❷❸❹❺❻❼❽❾➀➁➂➃➄➅➆➇➈"
INLINE_CIRCLED_CHOICE_RE = re.compile(rf"([{CIRCLED_CHOICE_MARKERS}])\s*")
INLINE_NUMERIC_CHOICE_RE = re.compile(r"(?<![\w/])([1-5])(?:[\.\)])?(?:\s+|$)")
CHOICE_LINE_RE = re.compile(
    rf"^\s*(?P<label>[{CIRCLED_CHOICE_MARKERS}]|\(?[1-9]\)|[1-9][\.\)]|[A-Ea-e][\.\)])\s*(?P<body>.+)$"
)
BARE_NUMERIC_CHOICE_LINE_RE = re.compile(r"^\s*(?P<label>[1-5])\s+(?P<body>\S.+)$")
NUMERIC_CHOICE_LABEL_RE = re.compile(r"^\(?([1-9])[\.\)]?$")
PDF_CHOICE_FRACTION_LABELS = "①②③④⑤"
PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS = "\u25a1\u25a2\ue06d"
PDF_CHOICE_FRACTION_RE = re.compile(
    rf"^\s*(?P<label>[{PDF_CHOICE_FRACTION_LABELS}])\s*(?P<sign>-?)"
    rf"\s*[{PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS}](?P<den>[A-Za-z0-9α-ωΑ-Ωπ∞+\-.]+)?\s*$"
)
PDF_CHOICE_EXPONENT_FRACTION_RE = re.compile(
    rf"^\s*(?P<label>[{PDF_CHOICE_FRACTION_LABELS}])\s*"
    rf"(?P<base>[A-Za-z0-9α-ωΑ-Ωπ∞+\-.]+)"
    rf"\s*[{PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS}](?P<den>[A-Za-z0-9α-ωΑ-Ωπ∞+\-.]+)?\s*$"
)
PDF_CHOICE_UNIT_FRACTION_RE = re.compile(
    rf"^\s*(?P<sign>-?)\s*[{PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS}](?P<den>[0-9]{{1,3}})\s*$"
)
PDF_CHOICE_FRACTION_PART_RE = re.compile(
    r"^[A-Za-z0-9α-ωΑ-Ωπ∞√∑∫+\-./*(){}\[\]\\_=^]+$"
)
PDF_CHOICE_GEOMETRY_LABEL_RE = re.compile(
    rf"^\s*(?P<label>[{PDF_CHOICE_FRACTION_LABELS}])\s*(?P<body>.*)$"
)
PDF_STEM_FRACTION_PART_RE = re.compile(
    r"^[A-Za-z0-9α-ωΑ-Ωπ∞√∑∫+\-./*(){}\[\]\\_^]+$"
)
ANSWER_LINE_RE = re.compile(r"^\s*(?:정답|답)(?:\s*[:：]|\s+)(?P<value>.+?)\s*$")
EXPLANATION_LINE_RE = re.compile(r"^\s*(?:해설|풀이)(?:(?:\s*[:：]|\s+)(?P<value>.*))?\s*$")
SCORE_MARKER_RE = re.compile(r"\[\s*\d+\s*점\s*\]")
PDF_FORM_LABEL_RE = re.compile(r"\(?\s*(?:홀수형|짝수형|미적분|확률과\s*통계|기하)\s*\)?")


class _Sink:
    """가져오기 중 문항을 만들며 중복은 건너뛰고 그 수를 센다.

    같은 출처 재가져오기로 건너뛴 문항은 existing에 모아, 호출자가
    "이미 있는 문항으로 다시 내보내기" 같은 멱등 동작을 만들 수 있게 한다."""

    __slots__ = ("created", "existing", "ordered_ids", "skipped", "_seen")

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.existing: list[dict[str, Any]] = []
        # created/existing alone lose source order on a partially repeated import.
        self.ordered_ids: list[int] = []
        self.skipped = 0
        self._seen: set[str] = set()

    def add(self, data: dict[str, Any]) -> dict[str, Any] | None:
        problem = storage.create_problem_unique(data, self._seen)
        if problem is None:
            self.skipped += 1
            duplicate = storage.find_existing_problem(data)
            if duplicate is not None:
                known_ids = {item["id"] for item in self.created}
                known_ids.update(item["id"] for item in self.existing)
                if duplicate["id"] not in known_ids:
                    self.existing.append(duplicate)
                    self.ordered_ids.append(duplicate["id"])
        else:
            self.created.append(problem)
            self.ordered_ids.append(problem["id"])
        return problem


def _dedup_notices(sink: _Sink) -> list[str]:
    return [f"중복 {sink.skipped}개는 이미 있는 문항이라 건너뛰었습니다."] if sink.skipped else []


def safe_filename(filename: str) -> str:
    name = Path(filename or "upload").name.strip() or "upload"
    name = SAFE_NAME_RE.sub("_", name)
    return name[:120]


def decode_base64(data: str) -> bytes:
    """Decode a Base64 payload without accepting truncated or garbage input."""
    if not isinstance(data, str) or not data.strip():
        raise ValueError("Base64 데이터가 비어 있습니다.")
    if "," in data and data.split(",", 1)[0].startswith("data:"):
        data = data.split(",", 1)[1]
    compact = re.sub(r"\s+", "", data)
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("올바른 Base64 데이터가 아닙니다.") from exc
    if not decoded:
        raise ValueError("디코딩된 파일이 비어 있습니다.")
    return decoded


def save_upload(filename: str, payload: bytes) -> str:
    storage.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    directory = storage.upload_directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stamp}_{uuid.uuid4().hex[:8]}_{safe_filename(filename)}"
    path.write_bytes(payload)
    return path.relative_to(storage.DATA_DIR).as_posix()


def _clean_text(value: str) -> str:
    value = normalize_recognized_math_text(value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _recognized_pdf_loose_duplicate_key(number: str, stem: str) -> str:
    """Fingerprint repeated odd/even-form PDF problems despite choice/image drift."""
    value = normalize_recognized_math_text(str(stem or ""))
    score = SCORE_MARKER_RE.search(value)
    if score:
        value = value[: score.end()]
    else:
        value = "\n".join(value.splitlines()[:6])
    value = re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", value)
    value = PDF_FORM_LABEL_RE.sub("", value)
    value = re.sub(r"[^0-9A-Za-z가-힣α-ωΑ-Ω]+", "", value)
    if len(value) < 24:
        return ""
    return f"{str(number or '').strip()}:{value[:180]}"


def _looks_like_math_pdf(*values: str) -> bool:
    return any("수학" in str(value or "") or "math" in str(value or "").lower() for value in values)


def _decode_text(payload: bytes) -> str:
    """텍스트/CSV류 입력은 UTF-8을 우선하고, 오래된 윈도우 한글(cp949)도 받는다."""
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _split_questions(page_text: str) -> list[str]:
    text = _clean_text(page_text)
    if not text:
        return []
    chunks = [chunk.strip() for chunk in QUESTION_START_RE.split(text) if chunk.strip()]
    if len(chunks) <= 1:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if _looks_like_single_passage(text, paragraphs):
            return [text]
        return paragraphs if len(paragraphs) > 1 else [text]
    return chunks


def _looks_like_single_passage(text: str, paragraphs: list[str]) -> bool:
    """번호 없는 국어 지문처럼 긴 글은 빈 줄 기준으로 여러 문항처럼 쪼개지 않는다."""
    if len(paragraphs) <= 1:
        return False
    if re.search(r"\[(?:지문|보기|자료)\]|\<(?:보기|지문)\>", text):
        return True
    long_paragraphs = [para for para in paragraphs if len(para) >= 80]
    return len(text) >= 600 and len(long_paragraphs) >= 2


def _plain_text_chunks(text: str, report: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """줄글/붙여넣기 텍스트를 문항 chunk로 바꾼다."""
    clean = _clean_text(text)
    if not clean:
        return []
    line_blocks = [(line, [], []) for line in clean.splitlines()]
    report = {} if report is None else report
    chunks = _paragraphs_to_chunks(line_blocks, report)
    # 정답표를 잘라 냈으면 빈 줄 기준 재분할로 정답표가 되살아나지 않게 그대로 쓴다.
    if len(chunks) > 1 or any(chunk.get("number_hint") for chunk in chunks) or report.get("answer_key_found"):
        return chunks

    split = [{"text": chunk, "images": [], "tables": []} for chunk in _split_questions(clean)]
    if len(split) > 1 and not QUESTION_LINE_RE.match(split[0]["text"]):
        first_numbered = next(
            (index for index, chunk in enumerate(split[1:], start=1) if QUESTION_LINE_RE.match(chunk["text"])),
            None,
        )
        if first_numbered is not None:
            split[first_numbered]["text"] = f"{split[0]['text']}\n{split[first_numbered]['text']}"
            split.pop(0)
    return split


def _extract_number(text: str, fallback: int) -> str:
    match = re.match(r"\s*(?:문제\s*)?(\d{1,3})\s*[\.\)]", text)
    return match.group(1) if match else str(fallback)


def import_pdf(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    """PDF 가져오기.

    1순위: 인식 파이프라인(app.recognition) — born-digital 시험지를 문항 단위로 분리하고
           텍스트, 수식 PUA, 라인/문자 좌표, 그림 후보를 보존한다. 텍스트 신뢰도가 낮은
           일부 영역만 보존용 이미지 fallback을 붙인다.
    2순위: 스캔/텍스트레이어 없음 등 결정론적 인식이 불가능한 경우 pypdf+OCR 경로.
    """
    if not payload.startswith(b"%PDF"):
        raise ValueError("올바른 PDF 파일이 아닙니다.")
    try:
        page_count = len(PdfReader(io.BytesIO(payload)).pages)
    except Exception as exc:
        raise ValueError(f"PDF를 열 수 없습니다: {exc}") from exc
    if page_count > MAX_PDF_PAGES:
        raise ValueError(f"PDF는 {MAX_PDF_PAGES}쪽 이하만 처리할 수 있습니다.")
    recognized = _import_pdf_recognized(filename, payload, metadata)
    if recognized is not None:
        return recognized
    return _legacy_import_pdf(filename, payload, metadata)


def _import_pdf_recognized(
    filename: str, payload: bytes, metadata: dict[str, Any]
) -> dict[str, Any] | None:
    """인식 파이프라인으로 PDF 문항을 가져온다. born-digital 이 아니면 None(→ 레거시)."""
    try:
        from .recognition.pipeline import recognize_pdf
    except Exception:
        return None  # 인식 스택(fitz 등) 불가 → 레거시로
    try:
        result = recognize_pdf(payload, filename=filename)
    except Exception:
        return None
    if not result.found:
        return None  # 스캔/텍스트레이어 없음 → 레거시가 처리

    save_upload(filename, payload)  # 원본 PDF 보관
    stem_name = Path(filename).stem
    sink = _Sink()
    # 문제 쪽 뒤에 붙은 정답·해설 쪽은 문항이 아니다. 그 쪽의 인식 결과는 건너뛰고 정답만 옮긴다.
    answer_page, answer_key = _pdf_answer_key_pages(payload, result.problems)
    # 정답 쪽 앞 문항의 마지막 번호. 정답 쪽 뒤에 그보다 큰 번호가 이어지면(단원별 정답) 진짜 문항이다.
    last_before_answers = max((int(prob.number) for prob in result.problems
                               if answer_page and str(prob.number or "").isdigit()
                               and int(prob.page_number or 0) < answer_page), default=0)

    def _after_answer_numbers(prob: Any) -> bool:
        return str(prob.number or "").isdigit() and last_before_answers > 0 and int(prob.number) > last_before_answers
    answer_key_skipped = 0
    answer_key_mapped = 0
    answer_key_numbers: set[str] = set()
    loose_seen: set[str] = set()
    loose_dedup_enabled = _looks_like_math_pdf(filename, getattr(result, "exam_title", ""))

    def layout_payload(prob: Any) -> dict[str, Any]:
        box = getattr(prob, "box", None)
        bbox_px = None
        if box is not None:
            bbox_px = [box.left, box.top, box.width, box.height]
        pdf_lines = list(getattr(prob, "line_geometries", []) or [])
        shared_passage_lines = list(getattr(prob, "shared_passage_line_geometries", []) or [])
        passage_range = getattr(prob, "shared_passage_range", None)
        payload = {
            "column_count": int(getattr(prob, "column_count", 0) or 0),
            "column_index": int(getattr(prob, "column_index", 0) or 0),
            "page": {
                "number": int(getattr(prob, "page_number", 0) or 0),
                "width_px": int(getattr(prob, "page_width_px", 0) or 0),
                "height_px": int(getattr(prob, "page_height_px", 0) or 0),
            },
            "bbox_px": bbox_px,
            "block_type": (
                "image_fallback"
                if getattr(prob, "problem_image_png", None)
                else "problem_with_shared_passage"
                if getattr(prob, "shared_passage_text", "")
                else "problem"
            ),
            "pdf_lines": [*shared_passage_lines, *pdf_lines],
            "pdf_line_count": len(shared_passage_lines) + len(pdf_lines),
        }
        if passage_range:
            payload["shared_passage"] = {
                "range": [int(passage_range[0]), int(passage_range[1])],
                "source_page": int(getattr(prob, "shared_passage_page_number", 0) or 0),
                "line_count": len(shared_passage_lines),
            }
        return payload

    for prob in result.problems:
        if answer_page and int(prob.page_number or 0) >= answer_page and not _after_answer_numbers(prob):
            answer_key_skipped += 1
            continue
        image_paths: list[str] = []
        math_geometry_repairs: dict[str, int] = {}
        image_only_fallback = bool(prob.problem_image_png) and (
            not prob.text_reliable or not str(prob.text or "").strip()
        )
        if image_only_fallback and prob.problem_image_png:
            rp = _save_image_bytes(f"{stem_name}_q{prob.number}.png", prob.problem_image_png)
            if rp:
                image_paths.append(rp)
        for fig_index, fig_png in enumerate(prob.figure_pngs, start=1):
            rp = _save_image_bytes(f"{stem_name}_q{prob.number}_fig{fig_index}.png", fig_png)
            if rp:
                image_paths.append(rp)

        # 텍스트가 신뢰 불가인 문항만 image-only fallback으로 보존한다. 신뢰 가능한 PDF 라인은
        # stem/choices와 좌표 메타데이터를 유지해 이후 native equation 복원에 사용한다.
        if image_only_fallback:
            stem_text, choices = "", []
        else:
            source_choice_labels = re.findall(r"[①②③④⑤]", str(prob.text or ""))
            source_choice_order_noncanonical = source_choice_labels[:5] != sorted(source_choice_labels[:5])
            pdf_line_geometries = list(getattr(prob, "line_geometries", []) or [])
            geometry_source = "\n".join(
                str(line.get("text") or "")
                for line in pdf_line_geometries
                if isinstance(line, dict) and str(line.get("text") or "").strip()
            )
            repaired_geometry_source = _repair_pdf_stem_fractions_from_geometry(
                geometry_source,
                pdf_line_geometries,
            )
            source_text = str(prob.text or "")
            if (
                repaired_geometry_source
                and _placeholder_count_in_fields(repaired_geometry_source, [])
                < _placeholder_count_in_fields(source_text, [])
            ):
                source_text = repaired_geometry_source
            # The PDF content stream can emit the fragments of one equation row
            # out of reading order.  Re-linearizing them by x only wins when it
            # actually resolves structures the stream order hid, and the
            # re-ordered geometry then has to travel with the re-ordered text so
            # every later geometry lookup still matches line for line.
            reading_order_geometries = reading_order_line_geometries(pdf_line_geometries)
            if reading_order_geometries is not None:
                reading_order_source = line_geometry_source_text(reading_order_geometries)
                if _placeholder_count_in_fields(
                    reading_order_source, []
                ) < _placeholder_count_in_fields(source_text, []):
                    source_text = reading_order_source
                    pdf_line_geometries = reading_order_geometries
            stem_text, choices = _split_stem_and_choices(source_text)
            geometry_split = _split_stem_and_choices_from_pdf_geometry(
                source_text,
                pdf_line_geometries,
            )
            if geometry_split is not None:
                geometry_stem, geometry_choices = geometry_split
                geometry_placeholder_count = _placeholder_count_in_fields(geometry_stem, geometry_choices)
                text_placeholder_count = _placeholder_count_in_fields(stem_text, choices)
                geometry_nonempty = sum(1 for choice in geometry_choices if str(choice or "").strip())
                text_nonempty = sum(1 for choice in choices if str(choice or "").strip())
                if (
                    (
                        len(geometry_choices) >= len(choices)
                        and geometry_placeholder_count < text_placeholder_count
                    )
                    or (
                        len(geometry_choices) > len(choices)
                        and geometry_placeholder_count <= text_placeholder_count
                        and geometry_nonempty >= max(text_nonempty, min(4, len(geometry_choices)))
                    )
                    or (
                        len(geometry_choices) == len(choices)
                        and len(geometry_choices) >= 4
                        and geometry_placeholder_count <= text_placeholder_count
                        and geometry_nonempty >= 4
                        and geometry_choices != choices
                        and source_choice_order_noncanonical
                    )
                ):
                    stem_text, choices = geometry_stem, geometry_choices
            stem_text = normalize_recognized_math_layout_text(stem_text)
            choices = [normalize_recognized_math_layout_text(choice) for choice in choices]
            geometry_stem = _repair_pdf_stem_fractions_from_geometry(stem_text, pdf_line_geometries)
            if _placeholder_count_in_fields(geometry_stem, choices) < _placeholder_count_in_fields(stem_text, choices):
                stem_text = geometry_stem
            stem_text, choices, math_geometry_repairs = repair_problem_math_layout(
                stem_text,
                choices,
                pdf_line_geometries,
            )
            shared_passage_text = str(getattr(prob, "shared_passage_text", "") or "").strip()
            if shared_passage_text:
                stem_text = f"{shared_passage_text}\n{stem_text}".strip()

        number = str(prob.number) if prob.number else ""
        loose_key = _recognized_pdf_loose_duplicate_key(number, stem_text) if loose_dedup_enabled else ""
        if loose_key and loose_key in loose_seen:
            sink.skipped += 1
            continue
        if loose_key:
            loose_seen.add(loose_key)

        title = f"{stem_name} #{number}" if number else stem_name
        key_answer = answer_key.get(str(int(number))) if number.isdigit() else None
        if key_answer:
            answer_key_numbers.add(str(int(number)))
            answer_key_mapped += 1
        sink.add(
            {
                **metadata,
                "source_type": "pdf",
                "source_name": filename,
                "source_page": prob.page_number,
                "number": number,
                "title": title,
                "stem": stem_text,
                "choices": choices,
                "answer": key_answer or "",
                "image_paths": image_paths,
                "tables": [],
                "layout": {
                    **layout_payload(prob),
                    "math_geometry_repairs": math_geometry_repairs,
                },
            }
        )

    notices = [f"{len(sink.created)}개 문항을 PDF에서 자동 인식했습니다(문항 분리 + 그림/이미지 추출)."]
    if getattr(result, "exam_title", ""):
        notices.append(f"시험지 제목 감지: {result.exam_title}")
    notices.extend(result.notices)
    if answer_page:
        notices.extend(_answer_key_notices({
            "answer_key_found": True, "answer_key_mapped": answer_key_mapped,
            "answer_key_unmatched": len(set(answer_key) - answer_key_numbers),
        }))
    notices.extend(_dedup_notices(sink))
    return {"created": sink.created, "existing": sink.existing, "ordered_ids": sink.ordered_ids, "notices": notices, "exam_title": getattr(result, "exam_title", "")}


def _pdf_answer_key_pages(payload: bytes, problems: list[Any]) -> tuple[int | None, dict[str, str]]:
    """문제 쪽 뒤에서 '정답 및 해설'·'빠른 정답'으로 시작하는 첫 쪽(1부터)과 그 뒤 쪽들의 정답."""
    question_pages = [int(prob.page_number or 0) for prob in problems if prob.number]
    if not question_pages:
        return None, {}
    try:
        import fitz

        with fitz.open(stream=payload, filetype="pdf") as document:
            texts = [page.get_text("text") for page in document]
    except Exception:
        return None, {}
    first_question_page = min(question_pages)
    for page_number in range(first_question_page + 1, len(texts) + 1):
        if _pdf_page_answer_key_start(texts[page_number - 1]):
            # 앞 쪽들의 어떤 번호보다 큰 새 문항이 인식된 쪽은 정답 쪽이 아니라 문항 쪽이다.
            earlier = [int(prob.number) for prob in problems if str(prob.number or "").isdigit()
                       and int(prob.page_number or 0) < page_number]
            here = [int(prob.number) for prob in problems if str(prob.number or "").isdigit()
                    and int(prob.page_number or 0) == page_number]
            if earlier and here and min(here) > max(earlier):
                continue
            return page_number, _parse_answer_key(texts[page_number - 1:])
    return None, {}


def _legacy_import_pdf(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    sink = _Sink()
    notices: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(payload))
        # Accessing ``pages`` forces pypdf to validate the page tree before the
        # source is persisted or any DB row is created.
        len(reader.pages)
    except Exception as exc:  # pragma: no cover - library-specific errors
        raise ValueError(f"PDF를 열 수 없습니다: {exc}") from exc
    save_upload(filename, payload)

    sequence = 1
    total_pdf_images = 0
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_images: list[str] = []
        try:
            for image_file in page.images:
                rel_path = _save_image_bytes(image_file.name or f"p{page_index}.png", image_file.data)
                if rel_path:
                    page_images.append(rel_path)
        except Exception:
            pass
        chunks = _split_questions(page_text)
        if not chunks:
            if page_images:
                sink.add(
                    {
                        **metadata,
                        "source_type": "pdf",
                        "source_name": filename,
                        "source_page": page_index,
                        "title": f"{Path(filename).stem} {page_index}쪽 이미지",
                        "stem": "",
                        "image_paths": page_images,
                    }
                )
                total_pdf_images += len(page_images)
            else:
                notices.append(f"{page_index}쪽에서 텍스트를 찾지 못했습니다.")
            continue
        for chunk_index, chunk in enumerate(chunks):
            number = _extract_number(chunk, sequence)
            sink.add(
                {
                    **metadata,
                    "source_type": "pdf",
                    "source_name": filename,
                    "source_page": page_index,
                    "number": number,
                    "title": f"{Path(filename).stem} #{number}",
                    "stem": chunk,
                    # 페이지 내 위치를 알 수 없어 페이지 첫 문항에 모아 붙인다.
                    "image_paths": page_images if chunk_index == 0 else [],
                }
            )
            sequence += 1
        total_pdf_images += len(page_images)
    if total_pdf_images:
        notices.append(f"PDF 이미지 {total_pdf_images}개를 페이지별 첫 문항에 첨부했습니다. 필요하면 편집에서 옮기세요.")
    notices.extend(_dedup_notices(sink))
    # 새로 만든 것도, 건너뛴 중복도 없을 때만 스캔 PDF 안내용 빈 문항을 만든다.
    if not sink.created and not sink.skipped:
        sink.add(
            {
                **metadata,
                "source_type": "pdf",
                "source_name": filename,
                "title": Path(filename).stem,
                "stem": "스캔 PDF이거나 텍스트를 추출하지 못했습니다. 이미지로 등록하거나 본문을 직접 입력하세요.",
            }
        )
    return {"created": sink.created, "existing": sink.existing, "ordered_ids": sink.ordered_ids, "notices": notices}


def import_image(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    notices: list[str] = []
    width = height = 0
    try:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError(f"이미지는 {MAX_IMAGE_PIXELS:,}픽셀 이하만 처리할 수 있습니다.")
            image.verify()
    except Exception as exc:
        raise ValueError(f"올바른 이미지 파일이 아닙니다: {exc}") from exc

    rel_path = save_upload(filename, payload)
    full_path = storage.DATA_DIR / rel_path

    stem = metadata.get("stem") or ""
    has_real_text = bool(stem)
    if not stem and HAS_OCR:
        try:
            with Image.open(full_path) as image:
                ocr_text = pytesseract.image_to_string(image, lang="kor+eng")
            stem = _clean_text(ocr_text)
            if stem:
                has_real_text = True
                notices.append("OCR로 본문을 추출했습니다. 내용을 확인하세요.")
        except Exception as exc:
            notices.append(f"OCR 실패: {exc}")
    if not stem:
        # 식별 텍스트가 없으면 같은 안내 문구가 서로 중복으로 잡히지 않도록 중복 검사에서 뺀다.
        stem = "이미지 문항입니다. 본문이 필요하면 오른쪽 편집 영역에서 입력하세요."
    data = {
        **metadata,
        "source_type": "image",
        "source_name": filename,
        "title": metadata.get("title") or Path(filename).stem,
        "stem": stem,
        "image_paths": [rel_path],
    }
    problem = storage.create_problem_unique(data) if has_real_text else storage.create_problem(data)
    if problem is None:
        duplicate = storage.find_existing_problem(data)
        return {
            "created": [],
            "existing": [duplicate] if duplicate else [],
            "ordered_ids": [duplicate["id"]] if duplicate else [],
            "notices": ["이미 같은 본문의 문항이 있어 건너뛰었습니다.", *notices],
        }
    if width and height:
        notices.append(f"이미지 크기: {width}x{height}")
    return {"created": [problem], "ordered_ids": [problem["id"]], "notices": notices}


def import_text(
    filename: str,
    payload: bytes,
    metadata: dict[str, Any],
    source_type: str = "text",
) -> dict[str, Any]:
    save_upload(filename, payload)
    text = _decode_text(payload)
    report: dict[str, Any] = {}
    chunks = _plain_text_chunks(text, report)
    if not chunks:
        return {"created": [], "notices": ["텍스트에서 문항을 찾지 못했습니다."]}
    sink = _create_from_chunks(chunks, source_type, filename, metadata)
    notices = [f"{len(sink.created)}개 문항을 텍스트에서 가져왔습니다.", *_answer_key_notices(report)]
    notices.extend(_dedup_notices(sink))
    return {"created": sink.created, "existing": sink.existing, "ordered_ids": sink.ordered_ids, "notices": notices}


FIELD_ALIASES = {
    "number": ["number", "num", "no", "문항", "문항번호", "번호"],
    "subject": ["subject", "과목"],
    "unit": ["unit", "chapter", "단원", "소단원"],
    "tags": ["tags", "tag", "태그"],
    "title": ["title", "제목"],
    "stem": ["stem", "question", "body", "content", "본문", "문제", "문항본문"],
    "answer": ["answer", "정답"],
    "explanation": ["explanation", "solution", "해설", "풀이"],
}


def _first(row: dict[str, Any], key: str) -> str:
    aliases = FIELD_ALIASES.get(key, [key])
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in aliases:
        value = lowered.get(alias.lower())
        if value is not None:
            return str(value).strip()
    return ""


def _choices_from_row(row: dict[str, Any]) -> list[str]:
    choices: list[str] = []
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for index in range(1, 10):
        for key in (f"choice{index}", f"option{index}", f"선지{index}", f"보기{index}"):
            if key.lower() in lowered and str(lowered[key.lower()]).strip():
                choices.append(str(lowered[key.lower()]).strip())
                break
    combined = lowered.get("choices") or lowered.get("options") or lowered.get("선지") or lowered.get("보기")
    if combined and not choices:
        choices = [
            part.strip()
            for part in re.split(r"\s*(?:\||;|\n)\s*", str(combined))
            if part.strip()
        ]
    return choices


def _split_inline_circled_choices(line: str) -> tuple[str, list[str]]:
    matches = list(INLINE_CIRCLED_CHOICE_RE.finditer(line))
    if len(matches) < 2:
        return line, []
    prefix = line[: matches[0].start()].strip()
    choices: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        value = line[start:end].strip()
        choices.append(value or match.group(1))
    if len(choices) < 2:
        return line, []
    return prefix, choices


def _split_inline_numeric_choices(line: str) -> tuple[str, list[str]]:
    matches = list(INLINE_NUMERIC_CHOICE_RE.finditer(line))
    if len(matches) < 3:
        return line, []
    labels = [int(match.group(1)) for match in matches]
    if labels[:3] != [1, 2, 3] or labels != sorted(labels) or len(set(labels)) != len(labels):
        return line, []
    prefix = line[: matches[0].start()].strip()
    choices: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        value = line[start:end].strip()
        choices.append(value or match.group(1))
    if len(choices) < 3:
        return line, []
    return prefix, choices


def _bare_numeric_choice_body(lines: list[str], index: int, choices_started: bool) -> str | None:
    match = BARE_NUMERIC_CHOICE_LINE_RE.match(lines[index].strip())
    if not match:
        return None
    label = int(match.group("label"))
    if label == 1 and not choices_started:
        lookahead: list[int] = []
        for raw in lines[index : index + 5]:
            next_match = BARE_NUMERIC_CHOICE_LINE_RE.match(raw.strip())
            if not next_match:
                break
            lookahead.append(int(next_match.group("label")))
        if lookahead[:3] != [1, 2, 3]:
            return None
    elif choices_started and label <= 5:
        pass
    else:
        return None
    return match.group("body").strip()


def _numeric_choice_label(label: str) -> int | None:
    match = NUMERIC_CHOICE_LABEL_RE.match(label.strip())
    return int(match.group(1)) if match else None


def _numeric_choice_sequence_starts(lines: list[str], index: int) -> bool:
    labels: list[int] = []
    for raw in lines[index : index + 5]:
        match = CHOICE_LINE_RE.match(raw.strip())
        if not match:
            break
        label = _numeric_choice_label(match.group("label"))
        if label is None:
            break
        labels.append(label)
    return labels[:3] == [1, 2, 3]


def _choice_line_body(
    lines: list[str],
    index: int,
    choices_started: bool,
    choice_count: int,
) -> str | None:
    line = lines[index].strip()
    match = CHOICE_LINE_RE.match(line)
    if not match:
        return None
    # 첫 줄의 "1. 문제..."는 문항 번호이므로 선지로 보지 않는다.
    if index == 0 and QUESTION_LINE_RE.match(line):
        return None
    label = match.group("label")
    number = _numeric_choice_label(label)
    if number is None:
        return match.group("body").strip()
    if not choices_started:
        if number != 1 or not _numeric_choice_sequence_starts(lines, index):
            return None
    elif number != choice_count + 1:
        return None
    return match.group("body").strip()


def _pdf_choice_fraction_part(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped or len(stripped) > 80:
        return False
    if any(marker in stripped for marker in PDF_CHOICE_FRACTION_LABELS + PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS):
        return False
    if re.search(r"[\uac00-\ud7a3]", stripped):
        return False
    return bool(PDF_CHOICE_FRACTION_PART_RE.match(stripped))


def _pdf_choice_label_order(label: str) -> int:
    try:
        return PDF_CHOICE_FRACTION_LABELS.index(label)
    except ValueError:
        return 99


def _pdf_choice_exponent_base(value: str) -> bool:
    stripped = str(value or "").strip()
    return bool(stripped) and bool(re.search(r"[A-Za-z0-9α-ωΑ-Ωπ∞)\]}]", stripped))


def _pdf_choice_run(
    lines: list[str],
    index: int,
    pattern: re.Pattern[str],
) -> tuple[list[re.Match[str]], int] | None:
    matches: list[re.Match[str]] = []
    cursor = index
    while cursor < len(lines) and len(matches) < 5:
        match = pattern.match(lines[cursor].strip())
        if not match:
            break
        matches.append(match)
        cursor += 1
    labels = [match.group("label") for match in matches]
    if len(matches) < 2 or len(set(labels)) != len(labels):
        return None
    return matches, cursor


def _pdf_choice_denominators(
    lines: list[str],
    cursor: int,
    missing_count: int,
) -> tuple[list[str], int] | None:
    denominators: list[str] = []
    while (
        len(denominators) < missing_count
        and cursor < len(lines)
        and _pdf_choice_fraction_part(lines[cursor])
    ):
        denominators.append(lines[cursor].strip())
        cursor += 1
    if len(denominators) != missing_count:
        return None
    return denominators, cursor


def _render_pdf_choice_fraction_rows(
    matches: list[re.Match[str]],
    numerator_by_label: dict[str, str],
    denominator_by_label: dict[str, str],
    *,
    exponent: bool,
) -> list[str]:
    rows: list[str] = []
    for match in sorted(matches, key=lambda item: _pdf_choice_label_order(item.group("label"))):
        label = match.group("label")
        numerator = numerator_by_label[label]
        denominator = denominator_by_label[label]
        if exponent:
            rows.append(f"{label}{match.group('base')}^{{\\frac{{{numerator}}}{{{denominator}}}}}")
        else:
            sign = "-" if match.groupdict().get("sign") else ""
            rows.append(f"{label}{sign}\\frac{{{numerator}}}{{{denominator}}}")
    return rows


def _repair_pdf_choice_layout_after_numerators(
    lines: list[str],
    index: int,
    repaired: list[str],
    pattern: re.Pattern[str],
    *,
    exponent: bool,
) -> tuple[list[str], int, int] | None:
    run = _pdf_choice_run(lines, index, pattern)
    if run is None:
        return None
    matches, cursor = run
    count = len(matches)
    if exponent and not all(_pdf_choice_exponent_base(match.group("base")) for match in matches):
        return None
    if len(repaired) < count:
        return None
    numerator_rows = [line.strip() for line in repaired[-count:]]
    if not all(_pdf_choice_fraction_part(row) for row in numerator_rows):
        return None

    missing_count = sum(1 for match in matches if not (match.groupdict().get("den") or ""))
    denominator_rows, denominator_cursor = _pdf_choice_denominators(lines, cursor, missing_count) or (None, None)
    if denominator_rows is None or denominator_cursor is None:
        return None

    labels = sorted((match.group("label") for match in matches), key=_pdf_choice_label_order)
    numerator_by_label = {label: numerator_rows[offset] for offset, label in enumerate(labels)}
    denominator_iter = iter(denominator_rows)
    denominator_by_label: dict[str, str] = {}
    for match in matches:
        label = match.group("label")
        denominator_by_label[label] = (match.groupdict().get("den") or next(denominator_iter)).strip()

    return (
        _render_pdf_choice_fraction_rows(
            matches,
            numerator_by_label,
            denominator_by_label,
            exponent=exponent,
        ),
        denominator_cursor,
        count,
    )


def _repair_pdf_choice_layout_before_parts(
    lines: list[str],
    index: int,
    pattern: re.Pattern[str],
    *,
    exponent: bool,
) -> tuple[list[str], int, int] | None:
    run = _pdf_choice_run(lines, index, pattern)
    if run is None:
        return None
    matches, cursor = run
    count = len(matches)
    if exponent and not all(_pdf_choice_exponent_base(match.group("base")) for match in matches):
        return None
    if any(match.groupdict().get("den") for match in matches):
        return None
    numerator_rows = [line.strip() for line in lines[cursor : cursor + count]]
    if len(numerator_rows) != count or not all(_pdf_choice_fraction_part(row) for row in numerator_rows):
        return None
    denominator_cursor = cursor + count
    denominator_rows = [line.strip() for line in lines[denominator_cursor : denominator_cursor + count]]
    if len(denominator_rows) != count or not all(_pdf_choice_fraction_part(row) for row in denominator_rows):
        return None

    numerator_by_label = {
        match.group("label"): numerator_rows[offset] for offset, match in enumerate(matches)
    }
    denominator_by_label = {
        match.group("label"): denominator_rows[offset] for offset, match in enumerate(matches)
    }
    return (
        _render_pdf_choice_fraction_rows(
            matches,
            numerator_by_label,
            denominator_by_label,
            exponent=exponent,
        ),
        denominator_cursor + count,
        0,
    )


def _repair_pdf_choice_fraction_layout(text: str) -> str:
    """Rejoin PDF choice fractions split into numerator/placeholder/denominator rows."""
    lines = str(text or "").splitlines()
    if len(lines) < 6:
        return str(text or "")

    repaired: list[str] = []
    index = 0
    while index < len(lines):
        converted: tuple[list[str], int, int] | None = None
        for pattern, exponent in (
            (PDF_CHOICE_EXPONENT_FRACTION_RE, True),
            (PDF_CHOICE_FRACTION_RE, False),
        ):
            converted = _repair_pdf_choice_layout_after_numerators(
                lines,
                index,
                repaired,
                pattern,
                exponent=exponent,
            )
            if converted is not None:
                break
            converted = _repair_pdf_choice_layout_before_parts(
                lines,
                index,
                pattern,
                exponent=exponent,
            )
            if converted is not None:
                break

        if converted is not None:
            rows, next_index, pop_count = converted
            for _ in range(pop_count):
                if repaired:
                    repaired.pop()
            repaired.extend(rows)
            index = next_index
            continue

        repaired.append(lines[index])
        index += 1

    return "\n".join(repaired)


def _bbox_center(bbox: Any) -> tuple[float, float] | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        left, top, width, height = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    return left + width / 2.0, top + height / 2.0


def _bbox_top(bbox: Any) -> float | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        return float(bbox[1])
    except (TypeError, ValueError):
        return None


def _rect_center(rect: Any) -> tuple[float, float] | None:
    if not isinstance(rect, list) or len(rect) != 4:
        return None
    try:
        left, top, right, bottom = [float(value) for value in rect]
    except (TypeError, ValueError):
        return None
    return (left + right) / 2.0, (top + bottom) / 2.0


def _pdf_line_placeholder_centers(line: dict[str, Any]) -> list[tuple[float, float]]:
    centers: list[tuple[float, float]] = []
    for char in line.get("pdf_line_chars") or []:
        if not isinstance(char, dict):
            continue
        value = str(char.get("c") or "")
        normalized = normalize_recognized_math_text(value)
        if value not in PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS and not any(
            marker in normalized for marker in PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS
        ):
            continue
        center = _rect_center(char.get("bbox"))
        if center is not None:
            centers.append(center)
    return centers


def _pdf_stem_fraction_part(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or len(stripped) > 80:
        return False
    if any(marker in stripped for marker in PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS):
        return False
    if PDF_CHOICE_GEOMETRY_LABEL_RE.match(stripped):
        return False
    if re.search(r"[\uac00-\ud7a3]", stripped):
        return False
    if any(char in stripped for char in "<>=,"):
        return False
    if not re.search(r"[A-Za-z0-9α-ωΑ-Ωπ∞√∑∫]", stripped):
        return False
    if stripped in {"+", "-", "*", "/", "^", "_"}:
        return False
    return bool(PDF_STEM_FRACTION_PART_RE.match(stripped))


def _pdf_stem_fraction_head_allows(text: str, placeholder_offset: int) -> bool:
    head = str(text or "")[:placeholder_offset].rstrip()
    if not head:
        return True
    return head[-1] in "=+-*/([{,"


def _pdf_stem_fraction_suffix_allows(text: str, placeholder_offset: int) -> bool:
    suffix = str(text or "")[placeholder_offset + 1 :].strip()
    return suffix in {"", ")", "]", "}", ","}


def _matched_pdf_stem_entries(
    stem: str,
    line_geometries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_lines = [line for line in str(stem or "").splitlines()]
    entries: list[dict[str, Any]] = []
    geometry_cursor = 0
    for stem_index, raw in enumerate(source_lines):
        text = raw.strip()
        if not text:
            continue
        while geometry_cursor < len(line_geometries):
            line = line_geometries[geometry_cursor]
            geometry_cursor += 1
            if not isinstance(line, dict):
                continue
            if str(line.get("text") or "").strip() != text:
                continue
            entries.append({"stem_index": stem_index, "geometry_index": geometry_cursor - 1, "line": line})
            break
    return entries


def _nearest_pdf_stem_fraction_part(
    entries: list[dict[str, Any]],
    *,
    stem_index: int,
    placeholder_center_x: float,
    placeholder_center_y: float,
    above: bool,
    used_stem_indices: set[int],
) -> dict[str, Any] | None:
    candidates: list[tuple[float, float, int, dict[str, Any]]] = []
    for entry in entries:
        candidate_stem_index = int(entry["stem_index"])
        if candidate_stem_index == stem_index or candidate_stem_index in used_stem_indices:
            continue
        line = entry["line"]
        text = str(line.get("text") or "").strip()
        if not _pdf_stem_fraction_part(text):
            continue
        center = _bbox_center(line.get("bbox_px"))
        if center is None:
            continue
        center_x, center_y = center
        x_distance = abs(center_x - placeholder_center_x)
        if x_distance > 70:
            continue
        vertical = placeholder_center_y - center_y if above else center_y - placeholder_center_y
        if vertical <= 0 or vertical > 100:
            continue
        candidates.append((vertical, x_distance, candidate_stem_index, entry))
    if not candidates:
        return None
    _, _, _, entry = sorted(candidates)[0]
    return entry


def _repair_pdf_stem_fractions_from_geometry_legacy(
    stem: str,
    line_geometries: list[dict[str, Any]],
) -> str:
    """Recover simple stacked fractions in stems from exact placeholder char geometry."""
    if not stem or not line_geometries:
        return str(stem or "")
    entries = _matched_pdf_stem_entries(stem, line_geometries)
    if not entries:
        return str(stem or "")

    output_lines = [line for line in str(stem or "").splitlines()]
    used_stem_indices: set[int] = set()
    changed = False
    for entry in entries:
        stem_index = int(entry["stem_index"])
        if stem_index in used_stem_indices:
            continue
        line = entry["line"]
        text = str(line.get("text") or "").strip()
        placeholder_matches = list(re.finditer(r"[\u25a1\u25a2]", text))
        if not placeholder_matches:
            continue
        placeholder_centers = _pdf_line_placeholder_centers(line)
        if len(placeholder_centers) < len(placeholder_matches):
            continue

        replacements: list[tuple[int, int, str]] = []
        local_used: set[int] = set()
        for match, center in zip(placeholder_matches, placeholder_centers):
            if not _pdf_stem_fraction_head_allows(text, match.start()):
                continue
            if not _pdf_stem_fraction_suffix_allows(text, match.start()):
                continue
            numerator_entry = _nearest_pdf_stem_fraction_part(
                entries,
                stem_index=stem_index,
                placeholder_center_x=center[0],
                placeholder_center_y=center[1],
                above=True,
                used_stem_indices=used_stem_indices | local_used,
            )
            denominator_entry = _nearest_pdf_stem_fraction_part(
                entries,
                stem_index=stem_index,
                placeholder_center_x=center[0],
                placeholder_center_y=center[1],
                above=False,
                used_stem_indices=used_stem_indices | local_used,
            )
            if numerator_entry is None or denominator_entry is None:
                continue
            numerator = str(numerator_entry["line"].get("text") or "").strip()
            denominator = str(denominator_entry["line"].get("text") or "").strip()
            replacements.append((match.start(), match.end(), rf"\frac{{{numerator}}}{{{denominator}}}"))
            local_used.add(int(numerator_entry["stem_index"]))
            local_used.add(int(denominator_entry["stem_index"]))

        if not replacements:
            continue
        rebuilt = text
        for start, end, replacement in sorted(replacements, reverse=True):
            rebuilt = f"{rebuilt[:start]}{replacement}{rebuilt[end:]}"
        output_lines[stem_index] = rebuilt
        used_stem_indices.update(local_used)
        changed = True

    if not changed:
        return str(stem or "")
    return _clean_text("\n".join(line for index, line in enumerate(output_lines) if index not in used_stem_indices))


PDF_GEOMETRY_TOKEN_MARKS = frozenset("+-*/()[]{}.,π∞√×÷=<>|")


def _pdf_geometry_char_rect(char: dict[str, Any]) -> tuple[float, float, float, float] | None:
    bbox = char.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        left, top, right, bottom = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _pdf_geometry_token_char(value: Any) -> str:
    normalized = normalize_recognized_math_text(str(value or "")).strip()
    if not normalized or any(marker in normalized for marker in PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS):
        return ""
    if re.search(r"[\uac00-\ud7a3\u4e00-\u9fff]", normalized):
        return ""
    if all(char.isalnum() or char in PDF_GEOMETRY_TOKEN_MARKS for char in normalized):
        return normalized
    return ""


def _pdf_geometry_has_rich_chars(line_geometries: list[dict[str, Any]]) -> bool:
    for line in line_geometries:
        if not isinstance(line, dict):
            continue
        for char in line.get("pdf_line_chars") or []:
            if not isinstance(char, dict) or _pdf_geometry_char_rect(char) is None:
                continue
            if _pdf_geometry_token_char(char.get("c")):
                return True
    return False


def _pdf_geometry_math_token(
    line_geometries: list[dict[str, Any]],
    *,
    bar_rect: tuple[float, float, float, float],
    above: bool,
) -> dict[str, Any] | None:
    left, top, right, bottom = bar_rect
    bar_x = (left + right) / 2.0
    bar_y = (top + bottom) / 2.0
    bar_width = right - left
    horizontal_margin = max(6.0, min(14.0, bar_width * 0.18))
    grouped: dict[int, list[tuple[float, float, float, str]]] = {}

    for line_index, line in enumerate(line_geometries):
        if not isinstance(line, dict):
            continue
        for char in line.get("pdf_line_chars") or []:
            if not isinstance(char, dict):
                continue
            value = _pdf_geometry_token_char(char.get("c"))
            rect = _pdf_geometry_char_rect(char)
            if not value or rect is None:
                continue
            char_left, char_top, char_right, char_bottom = rect
            if char_right < left - horizontal_margin or char_left > right + horizontal_margin:
                continue
            center_x = (char_left + char_right) / 2.0
            center_y = (char_top + char_bottom) / 2.0
            vertical = bar_y - center_y if above else center_y - bar_y
            if vertical <= 3.0 or vertical > 46.0:
                continue
            grouped.setdefault(line_index, []).append((center_x, center_y, vertical, value))

    candidates: list[tuple[float, float, int, dict[str, Any]]] = []
    for line_index, chars in grouped.items():
        chars.sort(key=lambda item: item[0])
        runs: list[list[tuple[float, float, float, str]]] = []
        for char in chars:
            if not runs or char[0] - runs[-1][-1][0] > max(15.0, bar_width * 0.42):
                runs.append([char])
            else:
                runs[-1].append(char)
        for run in runs:
            token = "".join(item[3] for item in run)
            if not token or not any(char.isalnum() for char in token):
                continue
            center_x = sum(item[0] for item in run) / len(run)
            vertical = sum(item[2] for item in run) / len(run)
            x_distance = abs(center_x - bar_x)
            if x_distance > max(18.0, bar_width * 0.55):
                continue
            candidate = {
                "line_index": line_index,
                "text": token,
                "center_x": center_x,
                "vertical": vertical,
            }
            candidates.append((vertical, x_distance, -len(token), candidate))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[:3])[0][3]


def _pdf_geometry_near_mark(
    line_geometries: list[dict[str, Any]],
    *,
    bar_rect: tuple[float, float, float, float],
    marks: str,
) -> bool:
    """Radical-vinculum vs vector-accent discrimination for a single bar.

    The geometric predicate lives in ``pdf_math_geometry`` so the nested-bar
    analysis there applies exactly the same evidence rule.
    """
    return glyphs_near_mark(
        line_geometry_glyphs(line_geometries),
        bar_rect=bar_rect,
        marks=marks,
    )


def _pdf_geometry_bar_repair(
    line_geometries: list[dict[str, Any]],
    bar_rect: tuple[float, float, float, float],
) -> tuple[str, list[tuple[int, str]], str | None] | None:
    numerator = _pdf_geometry_math_token(line_geometries, bar_rect=bar_rect, above=True)
    denominator = _pdf_geometry_math_token(line_geometries, bar_rect=bar_rect, above=False)
    if numerator is not None and denominator is not None:
        numerator_text = str(numerator["text"])
        denominator_text = str(denominator["text"])
        if abs(float(numerator["center_x"]) - float(denominator["center_x"])) > max(
            16.0,
            (bar_rect[2] - bar_rect[0]) * 0.48,
        ):
            return None
        replacement = rf"\frac{{{numerator_text}}}{{{denominator_text}}}"
        consumed = [
            (int(numerator["line_index"]), numerator_text),
            (int(denominator["line_index"]), denominator_text),
        ]
        return replacement, consumed, denominator_text

    if denominator is None or numerator is not None:
        return None
    base = str(denominator["text"])
    if not re.fullmatch(r"[A-Za-z]{1,4}", base):
        return None
    if _pdf_geometry_near_mark(line_geometries, bar_rect=bar_rect, marks="√"):
        return None
    command = "vec" if _pdf_geometry_near_mark(line_geometries, bar_rect=bar_rect, marks="⃗→←") else "overline"
    return rf"\{command}{{{base}}}", [(int(denominator["line_index"]), base)], None


def _replace_nth_placeholder(text: str, occurrence: int, replacement: str) -> str:
    matches = list(re.finditer(r"[\u25a1\u25a2]", text))
    if occurrence < 0 or occurrence >= len(matches):
        return text
    match = matches[occurrence]
    return f"{text[:match.start()]}{replacement}{text[match.end():]}"


def _repair_pdf_stem_fractions_from_geometry(stem: str, line_geometries: list[dict[str, Any]]) -> str:
    """Recover stacked fractions and line accents using PDF character geometry.

    Real exam PDFs encode a fraction bar, overline, vector accent, and an empty
    worksheet box with the same private-use glyph.  Whole-line proximity can
    therefore attach unrelated text to a bar.  This pass only converts a bar
    when its individual character rectangle has aligned math glyphs above and
    below (fraction), or a short Latin point name immediately below (accent).
    """
    source = str(stem or "")
    if not source or not line_geometries:
        return source
    if not _pdf_geometry_has_rich_chars(line_geometries):
        return _repair_pdf_stem_fractions_from_geometry_legacy(source, line_geometries)

    source_lines = source.splitlines()
    geometry_texts = [str(line.get("text") or "") if isinstance(line, dict) else "" for line in line_geometries]
    if len(source_lines) != len(geometry_texts) or any(
        source_line.strip() != geometry_text.strip()
        for source_line, geometry_text in zip(source_lines, geometry_texts)
    ):
        return source

    placeholder_repairs: dict[int, list[str]] = {}
    fraction_overrides: dict[int, list[tuple[str, str]]] = {}
    consumed: list[tuple[int, str]] = []
    for line_index, line in enumerate(line_geometries):
        if not isinstance(line, dict):
            continue
        bars: list[tuple[float, tuple[str, list[tuple[int, str]], str | None]]] = []
        for char in line.get("pdf_line_chars") or []:
            if not isinstance(char, dict):
                continue
            raw = str(char.get("c") or "")
            if raw not in PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS:
                continue
            rect = _pdf_geometry_char_rect(char)
            if rect is None:
                continue
            repair = _pdf_geometry_bar_repair(line_geometries, rect)
            if repair is not None:
                bars.append(((rect[0] + rect[2]) / 2.0, repair))
        if not bars:
            continue
        bars.sort(key=lambda item: item[0])
        square_count = len(re.findall(r"[\u25a1\u25a2]", source_lines[line_index]))
        square_repairs = [repair for _, repair in bars if repair[2] is None or square_count > 0]
        if square_count and len(square_repairs) <= square_count:
            for replacement, used_parts, _ in square_repairs:
                placeholder_repairs.setdefault(line_index, []).append(replacement)
                consumed.extend(used_parts)
            square_count -= len(square_repairs)

        for _, (replacement, used_parts, denominator) in bars:
            if denominator is None:
                continue
            synthetic = rf"\frac{{1}}{{{denominator}}}"
            if synthetic not in source_lines[line_index]:
                continue
            fraction_overrides.setdefault(line_index, []).append((synthetic, replacement))
            # ``synthetic`` already carries the denominator text, and the whole token is
            # swapped for ``replacement`` later.  Consuming that denominator separately
            # would strip the digit out of ``\frac{1}{den}`` before the swap runs, so the
            # override could no longer match and the numerator would be lost.
            consumed.extend(part for part in used_parts if part != (line_index, denominator))

    if not placeholder_repairs and not fraction_overrides:
        return source

    output_lines = list(source_lines)
    for line_index, token in consumed:
        if not (0 <= line_index < len(output_lines)) or not token:
            continue
        output_lines[line_index] = output_lines[line_index].replace(token, "", 1)
    for line_index, replacements in placeholder_repairs.items():
        for occurrence, replacement in enumerate(replacements):
            output_lines[line_index] = _replace_nth_placeholder(output_lines[line_index], occurrence, replacement)
    for line_index, overrides in fraction_overrides.items():
        for old, replacement in overrides:
            output_lines[line_index] = output_lines[line_index].replace(old, replacement, 1)

    repaired = _clean_text("\n".join(output_lines))
    if _placeholder_count_in_fields(repaired, []) >= _placeholder_count_in_fields(source, []):
        return source
    return repaired


def _pdf_choice_geometry_part(text: str) -> bool:
    return _pdf_choice_fraction_part(text) and not PDF_CHOICE_GEOMETRY_LABEL_RE.match(str(text or "").strip())


def _pdf_choice_geometry_label_body(label_line: str) -> tuple[str, str] | None:
    match = PDF_CHOICE_GEOMETRY_LABEL_RE.match(str(label_line or "").strip())
    if not match:
        return None
    return match.group("label"), match.group("body").strip()


def _nearest_pdf_choice_part(
    indexed_lines: list[tuple[int, dict[str, Any]]],
    *,
    label_index: int,
    label_center_x: float,
    label_top: float,
    above: bool,
    used: set[int],
) -> tuple[int, str] | None:
    candidates: list[tuple[float, float, int, str]] = []
    for index, line in indexed_lines:
        if index == label_index or index in used:
            continue
        text = str(line.get("text") or "").strip()
        if not _pdf_choice_geometry_part(text):
            continue
        bbox = line.get("bbox_px")
        center = _bbox_center(bbox)
        top = _bbox_top(bbox)
        if center is None or top is None:
            continue
        center_x, _ = center
        x_distance = abs(center_x - label_center_x)
        if x_distance > 90:
            continue
        vertical = label_top - top if above else top - label_top
        if vertical <= 0 or vertical > 60:
            continue
        candidates.append((vertical, x_distance, index, text))
    if not candidates:
        return None
    _, _, index, text = sorted(candidates)[0]
    return index, text


def _pdf_choice_from_geometry_body(
    body: str,
    numerator: str | None,
    denominator: str | None,
) -> str:
    text = str(body or "").strip()
    sample_label = PDF_CHOICE_FRACTION_LABELS[0]

    def fraction(num: str, den: str, sign: str = "") -> str:
        return f"{sign}\\frac{{{num.strip()}}}{{{den.strip()}}}"

    if not any(char in text for char in PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS):
        body_denominator = text
        sign = ""
        if body_denominator.startswith(("-", "\u2212")):
            sign = "-"
            body_denominator = body_denominator[1:].strip()
        if numerator and body_denominator and _pdf_choice_fraction_part(body_denominator):
            return fraction(numerator, body_denominator, sign)
        if numerator and denominator and (not text or text in {"-", "\u2212", "+"}):
            return fraction(numerator, denominator, "-" if text in {"-", "\u2212"} else "")
        if numerator and denominator and not text:
            return fraction(numerator, denominator)
        return _normalize_pdf_choice_body(text)

    exponent_match = PDF_CHOICE_EXPONENT_FRACTION_RE.match(f"{sample_label}{text}")
    fraction_match = PDF_CHOICE_FRACTION_RE.match(f"{sample_label}{text}")
    if exponent_match and numerator and denominator and _pdf_choice_exponent_base(exponent_match.group("base")):
        return f"{exponent_match.group('base')}^{{\\frac{{{numerator}}}{{{denominator}}}}}"
    if fraction_match:
        sign = "-" if fraction_match.groupdict().get("sign") else ""
        inline_denominator = (fraction_match.groupdict().get("den") or "").strip()
        denominator = denominator or inline_denominator or None
        if numerator and denominator:
            return f"{sign}\\frac{{{numerator}}}{{{denominator}}}"
        if denominator:
            return f"{sign}\\frac{{1}}{{{denominator}}}"
    return text


def _split_stem_and_choices_from_pdf_geometry(
    text: str,
    line_geometries: list[dict[str, Any]],
) -> tuple[str, list[str]] | None:
    """Use PDF line bbox geometry to rejoin fraction choices split across rows."""
    if not line_geometries:
        return None
    indexed_lines = [
        (index, line)
        for index, line in enumerate(line_geometries)
        if isinstance(line, dict) and str(line.get("text") or "").strip()
    ]
    label_entries: list[dict[str, Any]] = []
    for index, line in indexed_lines:
        parsed = _pdf_choice_geometry_label_body(str(line.get("text") or ""))
        if parsed is None:
            continue
        label, body = parsed
        bbox = line.get("bbox_px")
        center = _bbox_center(bbox)
        top = _bbox_top(bbox)
        if center is None or top is None:
            continue
        label_entries.append(
            {
                "index": index,
                "label": label,
                "body": body,
                "center_x": center[0],
                "top": top,
            }
        )
    if len(label_entries) < 2:
        return None

    used: set[int] = {int(entry["index"]) for entry in label_entries}
    choices_by_label: dict[str, str] = {}
    for entry in sorted(label_entries, key=lambda item: _pdf_choice_label_order(str(item["label"]))):
        label = str(entry["label"])
        body = str(entry["body"])
        numerator: str | None = None
        denominator: str | None = None
        body_text = body.strip()
        has_placeholder = any(char in body_text for char in PDF_CHOICE_FRACTION_PLACEHOLDER_CHARS)
        body_is_sign = body_text in {"-", "\u2212", "+"}
        body_can_be_denominator = bool(
            body_text
            and not body_is_sign
            and _pdf_choice_fraction_part(body_text.lstrip("-\u2212+"))
        )
        needs_above_part = has_placeholder or not body_text or body_is_sign or body_can_be_denominator
        needs_below_part = has_placeholder or not body_text or body_is_sign
        if needs_above_part:
            numerator_item = _nearest_pdf_choice_part(
                indexed_lines,
                label_index=int(entry["index"]),
                label_center_x=float(entry["center_x"]),
                label_top=float(entry["top"]),
                above=True,
                used=used,
            )
            if numerator_item is not None:
                used.add(numerator_item[0])
                numerator = numerator_item[1]
        if needs_below_part:
            denominator_item = _nearest_pdf_choice_part(
                indexed_lines,
                label_index=int(entry["index"]),
                label_center_x=float(entry["center_x"]),
                label_top=float(entry["top"]),
                above=False,
                used=used,
            )
            if denominator_item is not None:
                used.add(denominator_item[0])
                denominator = denominator_item[1]
        choices_by_label[label] = _pdf_choice_from_geometry_body(body, numerator, denominator)

    labels = sorted(choices_by_label, key=_pdf_choice_label_order)
    if len(labels) < 2:
        return None
    choices = [choices_by_label[label] for label in labels]
    if not choices:
        return None

    stem_lines: list[str] = []
    for index, line in indexed_lines:
        if index in used:
            continue
        stem_lines.append(str(line.get("text") or "").strip())
    stem = re.sub(r"\n{3,}", "\n\n", "\n".join(stem_lines)).strip()
    return stem, [_normalize_pdf_choice_body(choice) for choice in choices]


def _placeholder_count_in_fields(stem: str, choices: list[str]) -> int:
    values = [stem, *choices]
    return sum(str(value or "").count("\u25a1") + str(value or "").count("\u25a2") for value in values)


def _normalize_pdf_choice_body(value: str) -> str:
    text = str(value or "").strip()
    match = PDF_CHOICE_UNIT_FRACTION_RE.match(text)
    if match:
        sign = "-" if match.group("sign") else ""
        return f"{sign}\\frac{{1}}{{{match.group('den')}}}"
    return text


def _split_stem_and_choices(text: str) -> tuple[str, list[str]]:
    """본문 안에 붙어 들어온 객관식 선지를 stem과 choices로 나눈다."""
    if not text:
        return "", []
    stem_lines: list[str] = []
    choices: list[str] = []
    lines = _repair_pdf_choice_fraction_layout(text).splitlines()
    for line_index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            stem_lines.append("")
            continue
        prefix, inline_choices = _split_inline_circled_choices(line)
        if inline_choices:
            if prefix:
                stem_lines.append(prefix)
            choices.extend(inline_choices)
            continue
        prefix, inline_choices = _split_inline_numeric_choices(line)
        if inline_choices:
            if prefix:
                stem_lines.append(prefix)
            choices.extend(inline_choices)
            continue
        choice_body = _choice_line_body(lines, line_index, bool(choices), len(choices))
        if choice_body is not None:
            choices.append(choice_body)
            continue
        bare_body = _bare_numeric_choice_body(lines, line_index, bool(choices))
        if bare_body is not None:
            choices.append(bare_body)
            continue
        stem_lines.append(raw_line.rstrip())
    return _clean_text("\n".join(stem_lines)), [_normalize_pdf_choice_body(choice) for choice in choices]


def _strip_leading_leaked_choice_block(stem: str, existing_choices: list[str]) -> str:
    """Drop a stale leading ①-⑤ block when HWP IR already has this problem's choices."""
    if not stem or len(existing_choices) < 2:
        return stem
    stripped = stem.lstrip()
    if not stripped or stripped[0] not in CIRCLED_CHOICE_MARKERS:
        return stem
    cleaned_stem, leaked_choices = _split_stem_and_choices(stem)
    if len(leaked_choices) < 5 or not cleaned_stem.strip():
        return stem
    return cleaned_stem


def _is_answer_heading(value: str) -> bool:
    normalized = re.sub(r"\s+", "", value)
    return normalized in {"및해설", "및풀이", "해설", "풀이"}


def _split_answer_explanation(text: str) -> tuple[str, str, str]:
    """본문 끝에 섞인 정답/해설 줄을 별도 필드로 분리한다."""
    body_lines: list[str] = []
    explanation_lines: list[str] = []
    answer = ""
    mode = "body"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        answer_match = ANSWER_LINE_RE.match(line)
        if answer_match and not _is_answer_heading(answer_match.group("value")):
            answer = answer_match.group("value").strip()
            mode = "body"
            continue
        explanation_match = EXPLANATION_LINE_RE.match(line)
        if explanation_match:
            mode = "explanation"
            first = (explanation_match.group("value") or "").strip()
            if first:
                explanation_lines.append(first)
            continue
        if mode == "explanation":
            explanation_lines.append(raw_line.rstrip())
        else:
            body_lines.append(raw_line.rstrip())
    return (
        _clean_text("\n".join(body_lines)),
        answer,
        _clean_text("\n".join(explanation_lines)),
    )


def _problem_from_row(row: dict[str, Any], source_type: str, source_name: str) -> dict[str, Any] | None:
    stem = _first(row, "stem")
    title = _first(row, "title")
    if not stem and not title:
        return None
    choices = _choices_from_row(row)
    if stem and not choices:
        stem, extracted_answer, extracted_explanation = _split_answer_explanation(stem)
        stem, choices = _split_stem_and_choices(stem)
    else:
        extracted_answer = ""
        extracted_explanation = ""
    return {
        "source_type": source_type,
        "source_name": source_name,
        "number": _first(row, "number"),
        "subject": _first(row, "subject"),
        "unit": _first(row, "unit"),
        "tags": _first(row, "tags"),
        "title": title or (stem[:40] + ("..." if len(stem) > 40 else "")),
        "stem": stem,
        "choices": choices,
        "answer": _first(row, "answer") or extracted_answer,
        "explanation": _first(row, "explanation") or extracted_explanation,
    }


def import_csv(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    save_upload(filename, payload)
    text = _decode_text(payload)
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample) if "," in sample or "\t" in sample else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    sink = _Sink()
    for row in reader:
        problem_data = _problem_from_row(row, "csv", filename)
        if problem_data:
            sink.add({**metadata, **problem_data})
    return {
        "created": sink.created,
        "existing": sink.existing,
        "ordered_ids": sink.ordered_ids,
        "notices": [f"{len(sink.created)}개 문항을 가져왔습니다.", *_dedup_notices(sink)],
    }


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [row[0] for row in rows]


def _sqlite_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def import_sqlite(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    rel_path = save_upload(filename, payload)
    src = storage.DATA_DIR / rel_path
    temp = storage.DATA_DIR / f"tmp_{uuid.uuid4().hex}.sqlite3"
    shutil.copyfile(src, temp)
    sink = _Sink()
    notices: list[str] = []
    try:
        conn = sqlite3.connect(temp)
        conn.row_factory = sqlite3.Row
        for table in _sqlite_tables(conn):
            table_identifier = _sqlite_identifier(table)
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table_identifier})")]
            lower_columns = {column.lower() for column in columns}
            has_text = any(alias.lower() in lower_columns for alias in FIELD_ALIASES["stem"])
            has_title = any(alias.lower() in lower_columns for alias in FIELD_ALIASES["title"])
            if not has_text and not has_title:
                continue
            rows = conn.execute(f"SELECT * FROM {table_identifier} LIMIT 1000").fetchall()
            for row in rows:
                problem_data = _problem_from_row(dict(row), "sqlite", f"{filename}:{table}")
                if problem_data:
                    sink.add({**metadata, **problem_data})
            notices.append(f"{table}: {len(rows)}행 확인")
    finally:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass
        temp.unlink(missing_ok=True)
    if not sink.created:
        notices.append("가져올 수 있는 question/stem/body/title 컬럼을 찾지 못했습니다.")
    notices.extend(_dedup_notices(sink))
    return {"created": sink.created, "existing": sink.existing, "ordered_ids": sink.ordered_ids, "notices": notices}


QUESTION_LINE_RE = re.compile(r"^\s*(?:문제\s*)?(\d{1,3})\s*[\.\)]")
PASSAGE_LEAD_RE = re.compile(r"^\s*\[\s*\d{1,2}\s*[~∼\-–]\s*\d{1,2}\s*\]")
QUESTION_TRAILER_RE = re.compile(
    r"^\s*\[(?P<score>\d+점)\]\[(?P<context>[^\]]*?(?P<number>\d{1,3})\s*(?:번)?)\]\s*$"
)


def _save_image_bytes(name: str, payload: bytes) -> str | None:
    """이미지 바이트를 업로드 폴더에 저장하고 상대 경로를 돌려준다. 유효하지 않으면 None."""
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                return None
            image.verify()
    except Exception:
        return None
    return save_upload(name, payload)


def _first_child_math_text(element: Any, name: str) -> str:
    for child in element:
        if _local_name(child) == name:
            return _omml_text(child)
    return ""


def _first_descendant_math_text(element: Any, name: str) -> str:
    for child in element.iter():
        if child is element:
            continue
        if _local_name(child) == name:
            return _omml_text(child)
    return ""


def _child_math_texts(element: Any, name: str) -> list[str]:
    return [_omml_text(child) for child in element if _local_name(child) == name]


def _math_attr(element: Any, *names: str) -> str:
    wanted = set(names)
    for key, value in getattr(element, "attrib", {}).items():
        if str(key).rsplit("}", 1)[-1] in wanted and value:
            return str(value)
    return ""


def _first_descendant_math_attr(element: Any, child_name: str, *attr_names: str) -> str:
    for child in element.iter():
        if child is element:
            continue
        if _local_name(child) == child_name:
            value = _math_attr(child, *attr_names)
            if value:
                return value
    return ""


def _latex_group(value: str) -> str:
    text = value.strip()
    return text if text.startswith("{") and text.endswith("}") else "{" + text + "}"


def _latex_delimiter(value: str, default: str = ".") -> str:
    text = (value or default).strip() or default
    return {"{": r"\{", "}": r"\}", " ": "."}.get(text, text)


def _matrix_text(element: Any) -> str:
    rows: list[str] = []
    for row_node in element:
        if _local_name(row_node) != "mr":
            continue
        cells = [cell for cell in _child_math_texts(row_node, "e")]
        rows.append(" & ".join(cells))
    if not rows:
        return ""
    return r"\begin{matrix}" + r" \\ ".join(rows) + r"\end{matrix}"


def _omml_text(element: Any) -> str:
    """Word OMML 수식을 편집 가능한 LaTeX 스타일 텍스트 표현으로 바꾼다."""
    name = _local_name(element)
    if name == "t":
        return element.text or ""
    if name == "chr":
        return _math_attr(element, "val") or element.text or ""
    if name == "f":
        num = _first_child_math_text(element, "num")
        den = _first_child_math_text(element, "den")
        return f"\\frac{_latex_group(num)}{_latex_group(den)}" if num or den else ""
    if name == "rad":
        deg = _first_child_math_text(element, "deg")
        base = _first_child_math_text(element, "e")
        return f"\\sqrt[{deg}]{_latex_group(base)}" if deg else f"\\sqrt{_latex_group(base)}"
    if name == "d":
        body = _first_child_math_text(element, "e")
        beg = _latex_delimiter(_first_descendant_math_attr(element, "begChr", "val"), ".")
        end = _latex_delimiter(_first_descendant_math_attr(element, "endChr", "val"), ".")
        return f"\\left{beg}{body}\\right{end}" if body else ""
    if name == "bar":
        body = _first_child_math_text(element, "e")
        pos = _first_descendant_math_attr(element, "pos", "val")
        command = "underline" if pos == "bot" else "overline"
        return f"\\{command}{_latex_group(body)}" if body else ""
    if name == "sSup":
        base = _first_child_math_text(element, "e")
        sup = _first_child_math_text(element, "sup")
        return f"{base}^{_latex_group(sup)}" if sup else base
    if name == "sSub":
        base = _first_child_math_text(element, "e")
        sub = _first_child_math_text(element, "sub")
        return f"{base}_{_latex_group(sub)}" if sub else base
    if name == "sSubSup":
        base = _first_child_math_text(element, "e")
        sub = _first_child_math_text(element, "sub")
        sup = _first_child_math_text(element, "sup")
        if sub and sup:
            return f"{base}_{_latex_group(sub)}^{_latex_group(sup)}"
        return f"{base}_{_latex_group(sub)}" if sub else f"{base}^{_latex_group(sup)}"
    if name == "nary":
        symbol = _first_child_math_text(element, "chr") or _first_descendant_math_text(element, "chr") or "∑"
        sub = _first_child_math_text(element, "sub")
        sup = _first_child_math_text(element, "sup")
        body = _first_child_math_text(element, "e")
        symbol = {"∑": r"\sum", "Σ": r"\sum", "∫": r"\int", "∏": r"\prod"}.get(symbol, symbol)
        limit = ""
        if sub and sup:
            limit = f"_{_latex_group(sub)}^{_latex_group(sup)}"
        elif sub:
            limit = f"_{_latex_group(sub)}"
        elif sup:
            limit = f"^{_latex_group(sup)}"
        return f"{symbol}{limit} {body}".strip()
    if name == "acc":
        accent = _first_child_math_text(element, "chr") or _first_descendant_math_text(element, "chr")
        body = _first_child_math_text(element, "e")
        command = {
            "\u0305": "overline",
            "\u00af": "overline",
            "\u20d7": "vec",
            "\u2192": "vec",
            "\u0332": "underline",
        }.get(accent, "overline")
        return f"\\{command}{_latex_group(body)}" if body else ""
    if name == "limLow":
        base = _first_child_math_text(element, "e")
        limit = _first_child_math_text(element, "lim")
        command = r"\lim" if base.strip() == "lim" else base
        return f"{command}_{_latex_group(limit)}" if limit else command
    if name == "limUpp":
        base = _first_child_math_text(element, "e")
        limit = _first_child_math_text(element, "lim")
        command = r"\lim" if base.strip() == "lim" else base
        return f"{command}^{_latex_group(limit)}" if limit else command
    if name == "m":
        return _matrix_text(element)
    if name == "func":
        fname = _first_child_math_text(element, "fName")
        body = _first_child_math_text(element, "e")
        return f"{fname}({body})" if fname else body
    return "".join(_omml_text(child) for child in element)


def _docx_paragraph_text(para: Any) -> str:
    parts: list[str] = []
    for child in para._p.iterchildren():
        name = _local_name(child)
        if name in {"oMath", "oMathPara"}:
            math = _omml_text(child).strip()
            if math:
                parts.append(f"${math}$")
            continue
        if name == "r":
            run_text = "".join(
                node.text or ""
                for node in child.iter()
                if _local_name(node) == "t" and node.text
            )
            if run_text:
                parts.append(run_text)
    return "".join(parts).strip()


def _docx_cell_text(cell: Any) -> str:
    lines = [
        _docx_paragraph_text(paragraph).strip()
        for paragraph in getattr(cell, "paragraphs", []) or []
    ]
    return "\n".join(line for line in lines if line)


ANSWER_KEY_PAIR_RE = re.compile(
    rf"(?<![\d.])(\d{{1,3}})\s*(?:번\s*)?(?:[.):]\s*)?(?:정답\s*[:：]?\s*)?([{CIRCLED_CHOICE_MARKERS[:9]}])"
)
# 숫자 선지 목록('① 1 ② 2 …'): 원문자로 시작하는 '원문자-숫자' 묶음. 앞에 번호가 없으면 정답 짝이 아니다
# ('1 ③ 2 ① 3 ④' 빠른 정답은 '③ 2 ① 3' 앞에 번호 '1' 이 있어 그대로 읽는다).
_NUMERIC_CHOICE_RUN_RE = re.compile(
    rf"[{CIRCLED_CHOICE_MARKERS}]\s*\d{{1,3}}(?:\s+[{CIRCLED_CHOICE_MARKERS}]\s*\d{{1,3}})+"
)


def _answer_key_pairs(text: str) -> list[tuple[str, str]]:
    """ANSWER_KEY_PAIR_RE 짝 중 숫자 선지 목록 안에서 시작하는 짝을 뺀다."""
    text = text or ""
    blocked: list[tuple[int, int]] = []
    for run in _NUMERIC_CHOICE_RUN_RE.finditer(text):
        index = run.start() - 1
        while index >= 0 and text[index].isspace():
            index -= 1
        if index < 0 or not text[index].isdigit():
            blocked.append(run.span())
    return [
        (match.group(1), match.group(2))
        for match in ANSWER_KEY_PAIR_RE.finditer(text)
        if not any(start <= match.start() < end for start, end in blocked)
    ]


# '[정답표] 1. ③ …' 처럼 대괄호 정답표 머리로 시작하는 묶음.
ANSWER_KEY_LEAD_RE = re.compile(r"^\s*\[\s*정답\s*표\s*\]")
# '2025학년도 … 화학I 정답 및 해설' 처럼 앞에 시험 제목이 붙은 머리 줄의 끝부분.
ANSWER_KEY_TITLE_RE = re.compile(r"(?:정답\s*(?:및|과)\s*해설|빠른\s*정답|정답\s*표)\s*$")


def _answer_key_start(text: str, following: list[str] | tuple[str, ...] = ()) -> bool:
    """문서 끝 정답표·해설 묶음의 시작인가. 문항마다 붙은 '[정답] ③' 줄은 제외한다.

    머리글('빠른 정답', '정답 및 해설', '정답표', '[정답표]')로 시작할 때만 인정한다.
    문항마다 '[정답] ③' 이 붙은 묶음은 '[정답]' 개수와 상관없이 문항이다.
    following 은 이 문단 뒤의 문단들이다. 제목이 앞에 붙은 머리('… 정답 및 해설')는
    오인을 막기 위해 문항 번호로 시작하지 않는 짧은 한 줄이고, 바로 뒤가 선지 줄이 아니며,
    뒤따르는 내용에 '번호-원문자 정답' 짝이 2개 이상일 때만 인정한다.
    """
    t = (text or "").strip()
    if not t:
        return False
    lines = [line.strip() for line in t.splitlines() if line.strip()]
    first = lines[0]
    # 문항 번호로 시작하는 묶음은 인라인 '[정답]' 이 여러 개여도 정답 섹션이 아니다(개수 규칙 제거).
    if QUESTION_LINE_RE.match(first) or QUESTION_TRAILER_RE.match(first):
        return False
    if _ANSWER_SECTION_HEADER_RE.match(first) or ANSWER_KEY_LEAD_RE.match(first):
        return True
    if (len(first) <= 60 and "?" not in first and ANSWER_KEY_TITLE_RE.search(first)):
        rest = [*lines[1:], *(str(block or "").strip() for block in following)]
        rest = [line for line in rest if line]
        if rest and _CHOICE_LINE_START_RE.match(rest[0]):
            return False  # '철수가 만든 정답표' 다음 선지 줄: 발문의 일부다.
        # 평가원 정답표처럼 번호와 원문자가 다른 줄에 있어도 짝을 읽도록 줄을 이어 넘긴다.
        return len(_parse_answer_key([chr(10).join(rest)])) >= 2
    return False


def _pdf_page_answer_key_start(page_text: str) -> bool:
    """PDF 한 쪽이 정답·해설 쪽으로 시작하는가(머리글 줄을 고려해 앞 세 줄 각각을 머리 후보로 본다)."""
    lines = [line.strip() for line in (page_text or "").splitlines() if line.strip()]
    for index in range(min(3, len(lines))):
        line = lines[index]
        if QUESTION_LINE_RE.match(line) or QUESTION_TRAILER_RE.match(line):
            return False  # 문항이 먼저 나오는 쪽은 문항 쪽이다.
        # 쪽 전체가 아니라 그 줄과 뒤 내용으로 판단한다('[정답] ③' 개수 규칙은 쓰지 않는다).
        if _answer_key_start(line, lines[index + 1:]):
            return True
    return False


def _parse_answer_key(texts: list[str], tables: list[list[list[str]]] = ()) -> dict[str, str]:
    """'1. ③ 2. ⑤', '1번 정답 ②', 번호행/정답행 표에서 {번호: 원문자 정답}을 모은다."""
    answers: dict[str, str] = {}
    for table in tables:
        for header, values in zip(table, table[1:]):
            if header and all(str(cell).strip().isdigit() for cell in header):
                for number, value in zip(header, values):
                    value = str(value).strip()
                    if len(value) == 1 and value in CIRCLED_CHOICE_MARKERS[:9]:
                        answers.setdefault(str(int(str(number).strip())), value)
        texts = [*texts, *(" ".join(str(cell) for cell in row) for row in table)]
    for text in texts:
        for number, value in _answer_key_pairs(text):
            answers.setdefault(str(int(number)), value)
    return answers


def _chunk_number(chunk: dict[str, Any]) -> str:
    hint = str(chunk.get("number_hint") or "")
    if hint:
        return hint
    match = QUESTION_LINE_RE.match(str(chunk.get("text") or ""))
    return str(int(match.group(1))) if match else ""


def _apply_answer_key(chunks: list[dict[str, Any]], answers: dict[str, str]) -> tuple[int, int]:
    """정답표 정답을 번호가 같은 문항의 answer 로 옮긴다. (넣은 수, 짝 없는 수)."""
    mapped = 0
    matched: set[str] = set()
    for chunk in chunks:
        number = _chunk_number(chunk)
        if number not in answers:
            continue
        matched.add(number)
        if chunk.get("answer") or _split_answer_explanation(str(chunk.get("text") or ""))[1]:
            continue  # 문항에 이미 적힌 정답을 덮지 않는다.
        chunk["answer"] = answers[number]
        mapped += 1
    return mapped, len(set(answers) - matched)


def _resumes_questions(text: str, last_number: int) -> bool:
    """정답 묶음 뒤 문단이 직전 문항의 다음 번호 문항으로 다시 시작하는가('11. ③' 같은 정답 짝은 제외)."""
    match = QUESTION_LINE_RE.match(text or "")
    return bool(match) and last_number > 0 and int(match.group(1)) == last_number + 1         and not ANSWER_KEY_PAIR_RE.match((text or "").strip())


def _answer_key_notices(report: dict[str, Any]) -> list[str]:
    if not report.get("answer_key_found"):
        return []
    message = "문서 끝의 정답·해설 부분은 문항으로 만들지 않았습니다."
    if report.get("answer_key_mapped"):
        message += f" 정답 {report['answer_key_mapped']}개는 번호가 같은 문항의 정답 칸에 넣었습니다."
    if report.get("answer_key_unmatched"):
        message += f" 번호가 맞는 문항이 없는 정답 {report['answer_key_unmatched']}개는 넣지 못했습니다."
    if not report.get("answer_key_mapped"):
        message += " 정답은 직접 확인해 넣어 주세요."
    return [message]


def _paragraphs_to_chunks(
    blocks: list[tuple[str, list[str], list[list[list[str]]]]],
    report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """(문단 텍스트, 이미지 경로들, 표들) 목록을 문항 번호 기준으로 묶는다.

    문항 뒤에 오는 정답표·해설 묶음('빠른 정답 1. ① 2. ②')은 가짜 문항이 되지 않게
    잘라 내고, 정답은 번호가 같은 문항의 answer 로 옮긴다(결과는 report 에 기록).
    """
    chunks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending_lead: dict[str, Any] | None = None
    answer_blocks: list[tuple[str, list[str], list[list[list[str]]]]] = []
    kept_blocks: list[tuple[str, list[str], list[list[list[str]]]]] = []
    seen_question = False
    last_number = 0
    index = 0
    while index < len(blocks):
        text = blocks[index][0] or ""
        # 문항이 하나라도 나온 뒤의 정답 섹션 머리만 인정한다(해설지 전체 문서는 그대로 둔다).
        if seen_question and _answer_key_start(text, [block[0] for block in blocks[index + 1:index + 6]]):
            end = index + 1
            # 단원별 정답표처럼 정답 묶음 뒤에 다음 번호 문항이 이어지면 그 문항부터 다시 살린다.
            while end < len(blocks) and not _resumes_questions(blocks[end][0], last_number):
                end += 1
            answer_blocks.extend(blocks[index:end])
            index = end
            continue
        question = QUESTION_LINE_RE.match(text)
        trailer = QUESTION_TRAILER_RE.match(text)
        if question or trailer:
            seen_question = True
            last_number = max(last_number, int(question.group(1) if question else trailer.group("number")))
        kept_blocks.append(blocks[index])
        index += 1
    blocks = kept_blocks

    def append_block(target: dict[str, Any], text: str, images: list[str], tables: list[list[list[str]]]) -> None:
        if text:
            target["text"].append(text)
        target["images"].extend(images)
        target["tables"].extend(tables)

    for text, images, tables in blocks:
        trailer_match = QUESTION_TRAILER_RE.match(text)
        if trailer_match and (current is not None or pending_lead is not None):
            if current is None:
                current = pending_lead or {"text": [], "images": [], "tables": []}
                pending_lead = None
                chunks.append(current)
            append_block(current, text, images, tables)
            current["number_hint"] = str(int(trailer_match.group("number")))
            current = None
            continue
        if QUESTION_LINE_RE.match(text):
            current = {
                "text": [],
                "images": [],
                "tables": [],
            }
            if pending_lead is not None:
                current["text"].extend(pending_lead["text"])
                current["images"].extend(pending_lead["images"])
                current["tables"].extend(pending_lead["tables"])
                pending_lead = None
            append_block(current, text, images, tables)
            chunks.append(current)
            continue
        if current is not None and PASSAGE_LEAD_RE.match(text):
            pending_lead = {"text": [], "images": [], "tables": []}
            append_block(pending_lead, text, images, tables)
            current = None
            continue
        if current is None:
            if pending_lead is None:
                pending_lead = {"text": [], "images": [], "tables": []}
            append_block(pending_lead, text, images, tables)
            continue
        append_block(current, text, images, tables)
    if pending_lead is not None and not chunks:
        chunks.append(pending_lead)
    result = []
    for chunk in chunks:
        body = _clean_text("\n".join(chunk["text"]))
        if body or chunk["images"] or chunk["tables"]:
            result.append(
                {
                    "text": body,
                    "images": chunk["images"],
                    "tables": chunk["tables"],
                    "number_hint": chunk.get("number_hint", ""),
                }
            )
    if answer_blocks:
        answers = _parse_answer_key(
            [text for text, _, _ in answer_blocks],
            [table for _, _, tables in answer_blocks for table in tables],
        )
        mapped, unmatched = _apply_answer_key(result, answers)
        if report is not None:
            report.update(answer_key_found=True, answer_key_mapped=mapped, answer_key_unmatched=unmatched)
    return result


def _create_from_chunks(
    chunks: list[dict[str, Any]],
    source_type: str,
    filename: str,
    metadata: dict[str, Any],
) -> _Sink:
    sink = _Sink()
    for sequence, chunk in enumerate(chunks, start=1):
        text, answer, explanation = _split_answer_explanation(chunk["text"])
        answer = str(chunk.get("answer") or answer)
        explanation = str(chunk.get("explanation") or explanation)
        text, choices = _split_stem_and_choices(text)
        number = (
            str(chunk.get("number_hint") or "")
            or (_extract_number(text, sequence) if QUESTION_LINE_RE.match(text) else "")
        )
        title = f"{Path(filename).stem} #{number}" if number else Path(filename).stem
        sink.add(
            {
                **metadata,
                "source_type": source_type,
                "source_name": filename,
                "number": number,
                "title": title,
                "stem": text,
                "choices": choices,
                "answer": answer,
                "explanation": explanation,
                "image_paths": chunk["images"],
                "tables": chunk.get("tables") or [],
            }
        )
    return sink


VISUAL_CUE_RE = re.compile(r"(그림|그래프|도형|좌표평면|자료|표|곡선|직선|삼각형|사각형|원)")


def _attach_unpositioned_images(chunks: list[dict[str, Any]], images: list[str]) -> str:
    """위치 정보가 없는 HWP BinData 이미지를 문항들에 최대한 분산 배치한다."""
    if not chunks or not images:
        return ""
    if len(chunks) == 1:
        chunks[0]["images"] = [*images, *chunks[0]["images"]]
        return f"이미지 {len(images)}개는 위치를 알 수 없어 첫 문항에 첨부했습니다."

    cue_indexes = [
        index
        for index, chunk in enumerate(chunks)
        if VISUAL_CUE_RE.search(str(chunk.get("text") or ""))
    ]
    order: list[int] = []
    seen: set[int] = set()
    for index in cue_indexes:
        if index not in seen:
            order.append(index)
            seen.add(index)
    for index in range(len(chunks)):
        if index not in seen:
            order.append(index)
            seen.add(index)

    for image_index, image in enumerate(images):
        target = order[min(image_index, len(order) - 1)]
        chunks[target]["images"].append(image)
    return f"이미지 {len(images)}개는 HWP 내부 위치를 직접 읽지 못해 문항 순서 기준으로 분산 첨부했습니다."


def import_docx(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    from docx import Document as DocxDocument

    save_upload(filename, payload)
    notices: list[str] = []
    try:
        document = DocxDocument(io.BytesIO(payload))
    except Exception as exc:
        return {"created": [], "notices": [f"DOCX를 열 수 없습니다: {exc}"]}

    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    blip_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    embed_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    blocks: list[tuple[str, list[str], list[list[list[str]]]]] = []
    image_count = 0
    # 문단과 표를 문서 순서대로 훑어 표를 해당 문항에 정확히 붙인다.
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            images: list[str] = []
            for blip in para._p.iter(blip_ns):
                rel_id = blip.get(embed_attr)
                try:
                    part = (
                        document.part.rels[rel_id].target_part
                        if rel_id in document.part.rels
                        else None
                    )
                    if part is None:
                        continue
                    rel_path = _save_image_bytes(Path(part.partname).name, part.blob)
                except Exception:
                    continue
                if rel_path:
                    images.append(rel_path)
                    image_count += 1
            blocks.append((_docx_paragraph_text(para), images, []))
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows = [[_docx_cell_text(cell) for cell in row.cells] for row in table.rows]
            if any(any(cell for cell in row) for row in rows):
                blocks.append(("", [], [rows]))

    report: dict[str, Any] = {}
    chunks = _paragraphs_to_chunks(blocks, report)
    notices.extend(_answer_key_notices(report))
    if not chunks:
        return {"created": [], "notices": ["DOCX에서 내용을 찾지 못했습니다."]}
    sink = _create_from_chunks(chunks, "docx", filename, metadata)
    if image_count:
        notices.append(f"이미지 {image_count}개를 함께 가져왔습니다.")
    notices.extend(_dedup_notices(sink))
    return {"created": sink.created, "existing": sink.existing, "ordered_ids": sink.ordered_ids, "notices": notices}


def _local_name(element: Any) -> str:
    tag = element.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _hwpx_cell_text(tc: Any) -> str:
    parts: list[str] = []
    for kind, value in _hwpx_inline_items(tc):
        if kind == "text":
            parts.append(value)
        elif kind == "equation":
            parts.append(_hwpx_equation_text(value))
    return "".join(parts).strip()


def _hwpx_int_attr(node: Any, name: str) -> int | None:
    try:
        return int(node.get(name))
    except (TypeError, ValueError):
        return None


def _hwpx_table_rows(tbl: Any) -> list[list[str]]:
    """hp:tbl 엘리먼트에서 행×열 셀 텍스트를 뽑아 2차원 배열로 돌려준다.

    셀 주소(cellAddr)와 병합(cellSpan)이 있으면 격자에 배치해 병합으로 가려진
    칸은 빈 문자열로 둔다. 주소가 없거나 모순되면 행마다 순서대로 잇는다.
    """
    placed: list[tuple[int, int, int, int, str]] = []
    sequential: list[list[str]] = []
    addressed = True
    for tr in tbl:
        if _local_name(tr) != "tr":
            continue
        cells: list[str] = []
        for tc in tr:
            if _local_name(tc) != "tc":
                continue
            text = _hwpx_cell_text(tc)
            cells.append(text)
            addr = next((child for child in tc if _local_name(child) == "cellAddr"), None)
            span = next((child for child in tc if _local_name(child) == "cellSpan"), None)
            row = _hwpx_int_attr(addr, "rowAddr") if addr is not None else None
            col = _hwpx_int_attr(addr, "colAddr") if addr is not None else None
            if row is None or col is None or row < 0 or col < 0:
                addressed = False
                continue
            row_span = max(1, _hwpx_int_attr(span, "rowSpan") or 1) if span is not None else 1
            col_span = max(1, _hwpx_int_attr(span, "colSpan") or 1) if span is not None else 1
            placed.append((row, col, row_span, col_span, text))
        if cells:
            sequential.append(cells)
    if not addressed or not placed:
        return sequential
    row_count = max(row + row_span for row, _, row_span, _, _ in placed)
    col_count = max(col + col_span for _, col, _, col_span, _ in placed)
    # 비정상적으로 큰 주소(손상 파일)는 격자 대신 순서 배열로 둔다.
    if row_count * col_count > 20000:
        return sequential
    grid: list[list[str | None]] = [[None] * col_count for _ in range(row_count)]
    for row, col, row_span, col_span, text in placed:
        for r in range(row, min(row + row_span, row_count)):
            for c in range(col, min(col + col_span, col_count)):
                if grid[r][c] is not None:
                    return sequential
                grid[r][c] = text if (r, c) == (row, col) else ""
    return [[cell or "" for cell in row] for row in grid if any(cell is not None for cell in row)]


_HWPX_SPACE_ELEMENTS = {"nbSpace", "fwSpace", "hwSpace"}


def _hwpx_click_here_guide(field: Any) -> str | None:
    """Unfilled click-here field guide text (shown dimmed, never printed)."""
    if str(field.get("type") or "").upper() != "CLICK_HERE" or field.get("dirty") == "1":
        return None
    from_command = None
    for param in field.iter():
        if _local_name(param) != "stringParam":
            continue
        name = param.get("name")
        value = param.text or ""
        if name == "Direction" and value:
            return value
        if name == "Command":
            match = re.search(r"Direction:wstring:(\d+):", value)
            if match:
                from_command = value[match.end() : match.end() + int(match.group(1))] or None
    return from_command


def _hwpx_inline_items(
    node: Any,
    *,
    skip: frozenset[str] = frozenset(),
    images_only: frozenset[str] = frozenset(),
) -> list[tuple[str, Any]]:
    """Document-order text/equation/image items of an HWPX subtree.

    - ``hp:t`` mixed content keeps the text after tab/lineBreak/space children.
    - ``hp:switch`` renders one branch (the first ``hp:case``, else
      ``hp:default``) the way Hancom does, so alternates are not duplicated.
    - Hidden comments and untouched click-here guide text are not body text.
    - Subtrees named in ``skip`` are ignored; in ``images_only`` subtrees only
      pictures are kept.
    """
    items: list[tuple[str, Any]] = []

    def walk(element: Any, pictures_only: bool) -> None:
        name = _local_name(element)
        if name in skip or name == "hiddenComment":
            return
        if name in images_only:
            pictures_only = True
        if name == "img":
            items.append(("img", element))
            return
        if pictures_only:
            for child in element:
                walk(child, True)
            return
        if name == "equation":
            items.append(("equation", element))
            return
        if name == "t":
            if element.text:
                items.append(("text", element.text))
            for child in element:
                child_name = _local_name(child)
                if child_name == "tab":
                    items.append(("text", "\t"))
                elif child_name == "lineBreak":
                    items.append(("text", "\n"))
                elif child_name in _HWPX_SPACE_ELEMENTS:
                    items.append(("text", " "))
                if child.tail:
                    items.append(("text", child.tail))
            return
        if name == "fieldBegin":
            guide = _hwpx_click_here_guide(element)
            items.append(("field_begin", (element.get("id") or "", guide)))
            return
        if name == "fieldEnd":
            items.append(("field_end", element.get("beginIDRef") or ""))
            return
        if name == "switch":
            children = list(element)
            branch = next((child for child in children if _local_name(child) == "case"), None)
            if branch is None:
                branch = next((child for child in children if _local_name(child) == "default"), None)
            if branch is not None:
                walk(branch, pictures_only)
            return
        for child in element:
            walk(child, pictures_only)

    walk(node, False)
    return _drop_click_here_guides(items)


def _drop_click_here_guides(items: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    result: list[tuple[str, Any]] = []
    open_fields: list[tuple[str, str | None, int]] = []
    for kind, value in items:
        if kind == "field_begin":
            field_id, guide = value
            open_fields.append((field_id, guide, len(result)))
            continue
        if kind == "field_end":
            for index in range(len(open_fields) - 1, -1, -1):
                field_id, guide, start = open_fields[index]
                if field_id != value and value:
                    continue
                del open_fields[index:]
                inside = result[start:]
                inside_text = "".join(v for k, v in inside if k == "text").strip()
                if guide and inside_text == guide.strip() and all(k == "text" for k, _ in inside):
                    del result[start:]
                break
            continue
        result.append((kind, value))
    return result


def _inside_hwpx_container(node: Any, names: set[str]) -> bool:
    iter_ancestors = getattr(node, "iterancestors", None)
    if iter_ancestors is None:
        return False
    return any(_local_name(parent) in names for parent in iter_ancestors())


def _hwpx_equation_text(node: Any) -> str:
    for attr in ("script", "text", "formula", "eqn"):
        value = node.get(attr)
        if value:
            text = value.strip()
            return text if text.startswith("$") and text.endswith("$") else f"${text}$"
    for child in node.iter():
        if child is node or _local_name(child) != "script" or not child.text:
            continue
        text = str(child.text).strip()
        if text:
            return text if text.startswith("$") and text.endswith("$") else f"${text}$"
    texts = [
        str(child.text).strip()
        for child in node.iter()
        if child is not node and child.text and str(child.text).strip()
    ]
    text = " ".join(texts).strip()
    return f"${text}$" if text else "[수식 개체]"


def _hwpx_manifest_map(archive: zipfile.ZipFile) -> dict[str, str]:
    """content.hpf의 item id → zip 내 실제 경로 매핑."""
    mapping: dict[str, str] = {}
    names = set(archive.namelist())
    try:
        root = etree.fromstring(archive.read("Contents/content.hpf"))
    except Exception:
        return mapping
    for item in root.iter():
        if _local_name(item) != "item":
            continue
        item_id, href = item.get("id"), item.get("href")
        if not item_id or not href:
            continue
        candidates = [href, f"Contents/{href}", href.removeprefix("../"), f"BinData/{Path(href).name}"]
        for candidate in candidates:
            if candidate in names:
                mapping[item_id] = candidate
                break
    return mapping


_ENDNOTE_LEADING_ANSWER_RE = re.compile(
    r"^\s*((?:[①②③④⑤⑥⑦⑧⑨⑩](?:\s*[,，·]\s*[①②③④⑤⑥⑦⑧⑨⑩])*)|\d{1,3})(?=\s|$)"
)


def _hwpx_top_paragraphs(root: Any) -> list[Any]:
    """Paragraphs of ``root`` that are not nested inside another paragraph."""
    found: list[Any] = []

    def walk(element: Any) -> None:
        for child in element:
            if _local_name(child) == "p":
                found.append(child)
            else:
                walk(child)

    walk(root)
    return found


def _hwpx_endnote_fields(note: Any) -> tuple[str, str]:
    """Read answer-leading exam endnotes without leaking them into the stem.

    Two layouts are recognized: explicit ``[답]``/``[풀이]`` labels, and the
    education-office form whose note number is drawn by ``hp:autoNum`` (for
    example ``문3）``) and whose first text is the answer (`` ④``).
    """
    lines: list[str] = []
    for para in _hwpx_top_paragraphs(note):
        parts: list[str] = []
        for kind, value in _hwpx_inline_items(para):
            if kind == "text":
                parts.append(value)
            elif kind == "equation":
                parts.append(_hwpx_equation_text(value))
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    answer = ""
    explanation: list[str] = []
    labelled = any(line.startswith("[답]") for line in lines)
    for index, line in enumerate(lines):
        if line.startswith("[답]"):
            answer = line.removeprefix("[답]").strip()
        elif line.startswith("[풀이]"):
            rest = line.removeprefix("[풀이]").strip()
            if rest:
                explanation.append(rest)
        elif index == 0 and not labelled and (match := _ENDNOTE_LEADING_ANSWER_RE.match(line)):
            answer = match.group(1).strip()
            rest = line[match.end() :].strip()
            if rest:
                explanation.append(rest)
        else:
            explanation.append(line)
    return answer, _clean_text("\n".join(explanation))


def _hwpx_answer_endnote_chunks(
    paragraphs: list[tuple[str, list[str], list[list[list[str]]]]],
    markers: list[tuple[int, str, str, str]],
) -> list[dict[str, Any]] | None:
    """Use numbered answer endnotes as boundaries only for a complete exam sequence."""
    if len(markers) < 2:
        return None
    numbers = [number for _, number, _, _ in markers]
    if numbers != [str(index) for index in range(1, len(markers) + 1)]:
        return None
    if sum(bool(answer) for _, _, answer, _ in markers) < len(markers) * 0.8:
        return None
    chunks: list[dict[str, Any]] = []
    for index, (start, number, answer, explanation) in enumerate(markers):
        end = markers[index + 1][0] if index + 1 < len(markers) else len(paragraphs)
        blocks = paragraphs[start:end]
        if index == 0:
            blocks = [*paragraphs[:start], *blocks]
        body = _clean_text("\n".join(text for text, _, _ in blocks if text))
        images = [image for _, paths, _ in blocks for image in paths]
        tables = [table for _, _, grids in blocks for table in grids]
        if not body and not images and not tables:
            return None
        chunks.append({
            "text": body, "images": images, "tables": tables,
            "number_hint": number, "answer": answer, "explanation": explanation,
        })
    return chunks


def _attach_endnotes_by_position(
    chunks: list[dict[str, Any]],
    paragraphs: list[tuple[str, list[str], list[list[list[str]]]]],
    markers: list[tuple[int, str, str, str]],
) -> list[str]:
    """미주가 달린 문단 텍스트를 순서대로 찾아 그 문항의 answer/explanation 에 넣는다."""
    cursor = 0
    attached = 0
    for position, _number, answer, explanation in markers:
        if not answer and not explanation:
            continue
        anchor = paragraphs[position][0].strip() if position < len(paragraphs) else ""
        if not anchor:
            continue
        index = next((i for i in range(cursor, len(chunks)) if anchor in str(chunks[i].get("text") or "")), None)
        if index is None:
            continue
        cursor = index
        chunk = chunks[index]
        if answer and not chunk.get("answer"):
            chunk["answer"] = answer
        if explanation:
            chunk["explanation"] = "\n".join(part for part in (chunk.get("explanation"), explanation) if part)
        attached += 1
    total = sum(bool(answer or explanation) for _, _, answer, explanation in markers)
    if not total:
        return []
    message = f"미주에 있던 정답·해설 {total}개 중 {attached}개를 해당 문항의 정답·해설 칸에 넣었습니다."
    if attached < total:
        message += f" {total - attached}개는 연결할 문항을 찾지 못했으니 원본을 확인해 주세요."
    return [message]


_HANGUL_INITIALS = (0, 2, 3, 5, 6, 7, 9, 11, 12, 14, 15, 16, 17, 18)
_HANGUL_MEDIALS = (0, 4, 8, 13, 18, 20)  # ㅏ ㅓ ㅗ ㅜ ㅡ ㅣ: 가…하, 거…허, 고…


def _roman_numeral(value: int, upper: bool) -> str:
    if value <= 0 or value > 3999:
        return str(value)
    pairs = (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    )
    out = []
    for number, symbol in pairs:
        while value >= number:
            out.append(symbol)
            value -= number
    text = "".join(out)
    return text if upper else text.lower()


def _format_head_number(value: int, num_format: str) -> str:
    """Hancom paraHead counter → text (rules from kordoc para-heading.ts)."""
    if value == 0 and num_format == "DIGIT":
        return "0"
    value = max(1, value)
    index = value - 1
    if num_format == "CIRCLED_DIGIT":
        if index < 20:
            return chr(0x2460 + index)
        if index < 35:
            return chr(0x3251 + index - 20)
        if index < 50:
            return chr(0x32B1 + index - 35)
        return f"({value})"
    if num_format in {"HANGUL_SYLLABLE", "CIRCLED_HANGUL_SYLLABLE"}:
        if num_format == "CIRCLED_HANGUL_SYLLABLE" and index < 14:
            return chr(0x326E + index)
        vowel = _HANGUL_MEDIALS[min(index // 14, len(_HANGUL_MEDIALS) - 1)]
        return chr(0xAC00 + _HANGUL_INITIALS[index % 14] * 588 + vowel * 28)
    if num_format in {"HANGUL_JAMO", "CIRCLED_HANGUL_JAMO"}:
        if num_format == "CIRCLED_HANGUL_JAMO" and index < 14:
            return chr(0x3260 + index)
        return "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"[index % 14]
    if num_format == "LATIN_CAPITAL":
        return chr(0x41 + index % 26)
    if num_format == "LATIN_SMALL":
        return chr(0x61 + index % 26)
    if num_format == "CIRCLED_LATIN_CAPITAL" and index < 26:
        return chr(0x24B6 + index)
    if num_format == "CIRCLED_LATIN_SMALL" and index < 26:
        return chr(0x24D0 + index)
    if num_format == "ROMAN_CAPITAL":
        return _roman_numeral(value, True)
    if num_format == "ROMAN_SMALL":
        return _roman_numeral(value, False)
    return str(value)


class _HwpxParagraphNumbering:
    """Hancom automatic paragraph numbers (paraPr heading type NUMBER).

    The number is drawn by Hancom, not stored in ``hp:t``; exams numbered
    this way lost their question numbers on import. Counters follow Hancom:
    one counter per level of each numbering, deeper levels reset when a level
    advances, and empty numbered paragraphs still consume a number.
    """

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self.headings: dict[str, tuple[str, int]] = {}
        self.numberings: dict[str, dict[int, tuple[str, str, int]]] = {}
        self.counters: dict[str, list[int]] = {}
        try:
            root = etree.fromstring(
                archive.read("Contents/header.xml"), etree.XMLParser(resolve_entities=False, no_network=True)
            )
        except Exception:
            return
        for node in root.iter():
            name = _local_name(node)
            if name == "paraPr" and node.get("id") is not None:
                heading = next((child for child in node.iter() if _local_name(child) == "heading"), None)
                if heading is not None and heading.get("type") == "NUMBER" and heading.get("idRef"):
                    try:
                        level = int(heading.get("level") or 0)
                    except ValueError:
                        level = 0
                    self.headings[node.get("id")] = (heading.get("idRef"), min(max(level, 0) + 1, 10))
            elif name == "numbering" and node.get("id"):
                heads: dict[int, tuple[str, str, int]] = {}
                for head in node:
                    if _local_name(head) != "paraHead":
                        continue
                    try:
                        level = int(head.get("level") or "")
                        start = int(head.get("start") or 1)
                    except ValueError:
                        continue
                    if 1 <= level <= 10:
                        heads[level] = (head.get("numFormat") or "DIGIT", "".join(head.itertext()), start)
                if heads:
                    self.numberings[node.get("id")] = heads

    def prefix(self, paragraph: Any) -> str:
        heading = self.headings.get(paragraph.get("paraPrIDRef") or "")
        if heading is None:
            return ""
        numbering_id, level = heading
        heads = self.numberings.get(numbering_id)
        if not heads:
            return ""
        counters = self.counters.setdefault(numbering_id, [-1] * 11)
        head = heads.get(level)
        counters[level] = (head[2] if head else 1) if counters[level] < 0 else counters[level] + 1
        for deeper in range(level + 1, 11):
            counters[deeper] = -1
        template = head[1].strip() if head else f"^{level}."

        def expand(match: re.Match[str]) -> str:
            ref_level = int(match.group(1))
            ref_head = heads.get(ref_level)
            value = counters[ref_level] if counters[ref_level] >= 0 else (ref_head[2] if ref_head else 1)
            return _format_head_number(value, ref_head[0] if ref_head else "DIGIT")

        text = re.sub(r"\^(10|[1-9])", expand, template)
        return re.sub(r"\^(?![^\W_])", "", text).strip()


def _hwpx_section_order(archive: zipfile.ZipFile, names: list[str]) -> list[str]:
    """Section parts in reading order: content.hpf spine, else numeric order.

    A plain string sort would put section10 before section2.
    """
    sections = [name for name in names if re.fullmatch(r"Contents/section\d+\.xml", name)]
    numeric = sorted(sections, key=lambda name: int(re.search(r"(\d+)\.xml$", name).group(1)))
    try:
        root = etree.fromstring(
            archive.read("Contents/content.hpf"), etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except Exception:
        return numeric
    hrefs: dict[str, str] = {}
    for item in root.iter():
        if _local_name(item) == "item" and item.get("id") and item.get("href"):
            hrefs[item.get("id")] = item.get("href")
    ordered: list[str] = []
    for ref in root.iter():
        if _local_name(ref) != "itemref":
            continue
        href = hrefs.get(ref.get("idref") or "", "")
        for candidate in (href, f"Contents/{href}", href.removeprefix("../")):
            if candidate in sections and candidate not in ordered:
                ordered.append(candidate)
                break
    if not ordered:
        return numeric
    return ordered + [name for name in numeric if name not in ordered]


def import_hwpx(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    save_upload(filename, payload)
    notices: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except Exception as exc:
        return {"created": [], "notices": [f"HWPX를 열 수 없습니다(zip 아님): {exc}"]}

    with archive:
        names = archive.namelist()
        sections = _hwpx_section_order(archive, names)
        if not sections:
            return {"created": [], "notices": ["HWPX 안에서 section XML을 찾지 못했습니다."]}
        bin_map = _hwpx_manifest_map(archive)
        numbering = _HwpxParagraphNumbering(archive)
        saved_bins: dict[str, str | None] = {}
        paragraphs: list[tuple[str, list[str], list[list[list[str]]]]] = []
        answer_endnotes: list[tuple[int, str, str, str]] = []
        image_count = 0
        for section_name in sections:
            try:
                root = etree.fromstring(archive.read(section_name))
            except Exception as exc:
                notices.append(f"{section_name} 분석 실패: {exc}")
                continue
            # 본문 문단(hp:p)만 직접 순회한다(셀 안의 중첩 문단은 표로 따로 처리).
            for para in root:
                if _local_name(para) != "p":
                    continue
                for note in para.iter():
                    if _local_name(note) != "endNote":
                        continue
                    answer, explanation = _hwpx_endnote_fields(note)
                    answer_endnotes.append((len(paragraphs), note.get("number") or "", answer, explanation))
                # 바깥 표만 표로 만든다. 중첩 표의 글은 바깥 표 셀 글에 이미 들어간다.
                tables = [
                    _hwpx_table_rows(node) for node in para.iter()
                    if _local_name(node) == "tbl" and not _inside_hwpx_container(node, {"endNote", "tbl"})
                ]
                tables = [rows for rows in tables if rows]
                texts: list[str] = []
                images: list[str] = []
                # 미주 안 그림은 해당 문항에 붙이고, 미주 글은 정답·풀이로만 쓴다.
                for kind, node in _hwpx_inline_items(
                    para, skip=frozenset({"tbl"}), images_only=frozenset({"endNote"})
                ):
                    if kind == "text":
                        texts.append(node)
                    elif kind == "equation":
                        texts.append(_hwpx_equation_text(node))
                    elif kind == "img":
                        ref = node.get("binaryItemIDRef") or node.get("binaryItemIDRef".lower()) or ""
                        if ref not in saved_bins:
                            zip_path = bin_map.get(ref)
                            if zip_path is None:
                                # 매니페스트에 없으면 BinData에서 같은 이름을 추정
                                guess = [n for n in names if n.startswith("BinData/") and Path(n).stem == ref]
                                zip_path = guess[0] if guess else None
                            saved_bins[ref] = (
                                _save_image_bytes(Path(zip_path).name, archive.read(zip_path)) if zip_path else None
                            )
                        if saved_bins[ref]:
                            images.append(saved_bins[ref])
                            image_count += 1
                number_prefix = numbering.prefix(para)
                text = "".join(texts).strip()
                if number_prefix and text:
                    text = f"{number_prefix} {text}"
                paragraphs.append((text, images, tables))

    answer_note_chunks = _hwpx_answer_endnote_chunks(paragraphs, answer_endnotes)
    report: dict[str, Any] = {}
    chunks = answer_note_chunks or _paragraphs_to_chunks(paragraphs, report)
    notices.extend(_answer_key_notices(report))
    if answer_endnotes and not answer_note_chunks and chunks:
        # 미주 경계 조건(1..N 연속·정답 80%)을 못 채워도 미주 정답·해설을 버리지 않고
        # 미주가 달린 문단을 담은 문항에 옮긴다. 못 옮긴 수는 안내로 남긴다.
        notices.extend(_attach_endnotes_by_position(chunks, paragraphs, answer_endnotes))
    if not chunks:
        return {"created": [], "notices": ["HWPX에서 내용을 찾지 못했습니다."]}
    sink = _create_from_chunks(chunks, "hwpx", filename, metadata)
    if image_count:
        notices.append(f"이미지 {image_count}개를 함께 가져왔습니다.")
    if answer_note_chunks:
        table_questions = sum(bool(chunk["tables"]) for chunk in answer_note_chunks)
        if table_questions:
            notices.append(
                f"표가 있는 문항 {table_questions}개는 표 내부의 선택지·수식이 개별 선택지 칸으로 분리되지 않았을 수 있습니다."
            )
    notices.extend(_dedup_notices(sink))
    return {"created": sink.created, "existing": sink.existing, "ordered_ids": sink.ordered_ids, "notices": notices}


# --- HWP(5.0 바이너리) 텍스트 추출 -------------------------------------------
# 문단 텍스트(HWPTAG_PARA_TEXT) 레코드의 UTF-16LE 문자열에서 컨트롤 문자를 걸러낸다.
# 코드 1~9, 11~12, 14~23은 8 WCHAR(16바이트)짜리 인라인/확장 컨트롤이다.
_HWP_EXTENDED = {1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
HWPTAG_PARA_TEXT = 67


def _hwp_decode_text(data: bytes) -> str:
    out: list[str] = []
    i = 0
    length = len(data) - 1
    while i < length:
        code = data[i] | (data[i + 1] << 8)
        if code == 9:
            out.append("\t")
            i += 16
        elif code in _HWP_EXTENDED:
            i += 16
        elif code in (10, 13):
            out.append("\n")
            i += 2
        elif code < 32:
            i += 2
        else:
            out.append(chr(code))
            i += 2
    return "".join(out)


def _hwp_iter_records(stream: bytes):
    pos = 0
    size_total = len(stream)
    while pos + 4 <= size_total:
        (header,) = struct.unpack_from("<I", stream, pos)
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        pos += 4
        if size == 0xFFF:
            if pos + 4 > size_total:
                break
            (size,) = struct.unpack_from("<I", stream, pos)
            pos += 4
        if pos + size > size_total:
            break
        yield tag, stream[pos : pos + size]
        pos += size


_ANSWER_SECTION_RE = re.compile(r"^\s*(?:\[정답\]|빠른\s*정답|정답\s*(?:및|과)\s*해설|정답\s*표)")
# 정답 섹션 '시작' 판단용 머리글('[정답]' 인라인 줄은 문항에 붙은 것이므로 뺀다).
_ANSWER_SECTION_HEADER_RE = re.compile(r"^\s*(?:빠른\s*정답|정답\s*(?:및|과)\s*해설|정답\s*표)")
_CHOICE_LINE_START_RE = re.compile(rf"^\s*[{CIRCLED_CHOICE_MARKERS}]")


def _looks_like_answer_section(text: str) -> bool:
    """문항 뒤에 오는 정답표/해설 섹션인가(문항이 아니므로 제외 대상)."""
    t = (text or "").strip()
    if not t:
        return False
    return bool(_ANSWER_SECTION_RE.match(t)) or t.count("[정답]") >= 3


def _import_hwp_via_ir(
    filename: str, payload: bytes, metadata: dict[str, Any]
) -> dict[str, Any] | None:
    """rhwp to_ir() 로 원본 HWP → 편집 가능한 문항(텍스트+수식EQN+이미지). 실패 시 None."""
    try:
        from .importers_hwp_ir import hwp_to_problems
    except Exception:
        return None
    try:
        problems = hwp_to_problems(
            payload,
            filename,
            _save_image_bytes,
            _split_inline_circled_choices,
            chunk_paragraphs=_paragraphs_to_chunks,
            split_stem_choices=_split_stem_and_choices,
        )
    except Exception:
        return None
    if not problems:
        return None
    stem_name = Path(filename).stem
    sink = _Sink()
    answer_section = False
    trailing_source_count = 0
    intent_count = 0
    for prob in problems:
        num = str(prob.get("number") or "")
        stem_text = prob.get("stem", "") or ""
        # 정답표·해설 섹션은 문항 뒤에 오므로, 한 번 만나면 이후 항목도 전부 제외한다.
        combined = stem_text + " " + " ".join(
            str(cell) for tbl in (prob.get("tables") or []) for row in tbl for cell in row
        )
        if answer_section or _looks_like_answer_section(combined):
            answer_section = True
            continue
        # 공유 지문은 원본 문제지처럼 테두리 박스로 낸다. writer 가 tables 를 테두리 표로
        # 렌더하므로, 안내문("[1~3] 다음 글을...")은 stem(박스 위), 지문 본문은 1열 표(박스
        # 안)에 넣으면 편집 가능한 텍스트가 박스 안에 배치된다.
        # 본문은 문단마다 한 행으로 나눈다(1×1 표 한 칸에 3천 자를 넣으면 셀이 쪽 높이를
        # 넘어 한컴/rhwp 가 쪽을 수백 장 만든다). writer 는 layout.passage_box 를 보고 행
        # 사이 선을 지우고 쪽 높이 기준으로 표를 나눠 하나의 상자처럼 보이게 한다.
        if prob.get("is_passage"):
            head, _, body = stem_text.partition("\n")
            body_rows = [[line.strip()] for line in body.split("\n") if line.strip()]
            sink.add(
                {
                    **metadata,
                    "source_type": "hwp",
                    "source_name": filename,
                    "number": num,
                    "title": f"{stem_name} 지문{num}",
                    "unit": prob.get("unit") or metadata.get("unit", ""),
                    "stem": head.strip(),
                    "choices": [],
                    "image_paths": prob.get("image_paths", []),
                    "tables": [body_rows] if body_rows else [],
                    "layout": {"passage_box": True} if body_rows else None,
                    # 공유 지문 1차 분리: 목록/집계에서 문항과 구분되는 행 타입.
                    "problem_type": "passage",
                }
            )
            continue
        # 번호가 비어 있으면 stem 선두("1." 등)에서 추출한다. 안 그러면 writer 가 순번
        # 인덱스를 붙여 "2. 1. …"처럼 중복 표기된다(지문이 순번 슬롯을 차지하므로).
        if not num and QUESTION_LINE_RE.match(stem_text):
            num = _extract_number(stem_text, "")
        choices = prob.get("choices", []) or []
        # 선지가 아직 stem 에 섞여 있으면(국어/영어 문단-청킹 경로) 분리해 번호·문제·보기를
        # 각각 편집 가능한 필드로 나눈다. 수학 마커 경로는 이미 선지가 분리돼 있어 건너뛴다.
        if not choices:
            stem_text, choices = _split_stem_and_choices(stem_text)
        else:
            stem_text = _strip_leading_leaked_choice_block(stem_text, choices)
        source_metadata: dict[str, Any] = {}
        for key in ("score", "source_marker", "intent", "marker_style"):
            value = prob.get(key)
            if value not in (None, ""):
                source_metadata[key] = value
        if prob.get("marker_style") == "trailing_source":
            trailing_source_count += 1
        if prob.get("intent"):
            intent_count += 1
        problem_layout = dict(prob.get("layout") or {})
        if source_metadata:
            problem_layout["source_metadata"] = source_metadata
        # 병합 셀: 표 모델(2차원 문자열)은 그대로 두고 TableGrid.spans 만 layout 에 옮긴다.
        # 표 순서와 맞춘 리스트([[row, col, row_span, col_span], ...] / 없으면 []).
        table_spans = [list(getattr(tbl, "spans", None) or []) for tbl in (prob.get("tables") or [])]
        if any(table_spans):
            problem_layout["table_spans"] = table_spans
        sink.add(
            {
                **metadata,
                "source_type": "hwp",
                "source_name": filename,
                "number": num,
                "title": f"{stem_name} #{num}" if num else stem_name,
                "unit": prob.get("unit") or metadata.get("unit", ""),
                "stem": stem_text,
                "choices": choices,
                "image_paths": prob.get("image_paths", []),
                "tables": prob.get("tables", []),
                "layout": problem_layout or None,
            }
        )
    notices = [f"{len(sink.created)}개 문항을 HWP에서 편집 가능하게 가져왔습니다(수식·이미지 포함)."]
    if trailing_source_count:
        notices.append(
            f"후행 출처 마커 {trailing_source_count}개와 출제의도 {intent_count}개를 문항 메타데이터로 보존했습니다."
        )
    notices.extend(_dedup_notices(sink))
    return {"created": sink.created, "existing": sink.existing, "ordered_ids": sink.ordered_ids, "notices": notices}


def import_hwp(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    import olefile

    save_upload(filename, payload)
    # 1순위: rhwp to_ir() — 편집 가능한 [텍스트+수식(EQN)+이미지] 직접 추출. 수식은 $EQN$ 로
    #   stem 에 인라인 삽입돼 writer 의 native_math 가 hp:equation 으로 방출한다.
    #   실패/미설치면 아래 기존 경로(rhwp.paragraphs → OLE 레코드 → PrvText)로 폴백.
    ir_result = _import_hwp_via_ir(filename, payload, metadata)
    if ir_result is not None:
        return ir_result
    notices: list[str] = []
    try:
        ole = olefile.OleFileIO(io.BytesIO(payload))
    except Exception as exc:
        return {"created": [], "notices": [f"HWP 파일이 아닙니다: {exc}"]}

    with ole:
        if not ole.exists("FileHeader"):
            return {"created": [], "notices": ["HWP FileHeader가 없습니다. 한글 5.0 형식이 아닙니다."]}
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0] if len(header) >= 40 else 0
        compressed = bool(flags & 0x1)
        if flags & 0x2:
            return {"created": [], "notices": ["암호가 걸린 HWP는 가져올 수 없습니다."]}
        # 배포용 문서(flag 0x4)는 본문이 ViewText 에 암호화돼 BodyText 가 없다.
        distribution = bool(flags & 0x4)

        # 본문 텍스트 1순위: rhwp 엔진 (설치된 경우)
        paragraphs: list[tuple[str, list[str], list[list[list[str]]]]] = []
        if rhwp is not None:
            try:
                doc = rhwp.Document.from_bytes(payload)
                for para_text in doc.paragraphs():
                    for line in para_text.splitlines() or [""]:
                        paragraphs.append((line.strip(), [], []))
            except Exception:
                paragraphs = []

        # 2순위: BodyText/Section* 레코드 직접 파싱
        if not any(text for text, _, _ in paragraphs):
            paragraphs = []
            section_names = sorted(
                (entry for entry in ole.listdir() if len(entry) == 2 and entry[0] == "BodyText"),
                key=lambda entry: int(re.sub(r"\D", "", entry[1]) or 0),
            )
            for entry in section_names:
                raw = ole.openstream(entry).read()
                if compressed:
                    try:
                        raw = zlib.decompress(raw, -15)
                    except Exception as exc:
                        notices.append(f"{'/'.join(entry)} 압축 해제 실패: {exc}")
                        continue
                for tag, record in _hwp_iter_records(raw):
                    if tag != HWPTAG_PARA_TEXT:
                        continue
                    text = _hwp_decode_text(record)
                    for line in text.split("\n"):
                        paragraphs.append((line.strip(), [], []))

        # PrvText 보조: 본문 파싱이 실패했을 때 미리보기 텍스트라도 사용
        if not any(text for text, _, _ in paragraphs) and ole.exists("PrvText"):
            preview = ole.openstream("PrvText").read().decode("utf-16-le", errors="ignore")
            paragraphs = [(line.strip(), [], []) for line in preview.splitlines()]
            if distribution:
                notices.append(
                    "배포용(읽기 전용) HWP라 본문이 암호화되어 있어 미리보기 텍스트(문서 앞부분)만 가져왔습니다. "
                    "전체를 가져오려면 배포용 설정을 해제한 원본이나 HWPX/PDF로 다시 올려 주세요."
                )
            else:
                notices.append("본문 레코드 대신 미리보기 텍스트를 사용했습니다.")
        elif distribution and not any(text for text, _, _ in paragraphs):
            return {
                "created": [],
                "notices": ["배포용(읽기 전용) HWP라 본문이 암호화되어 있어 가져올 수 없습니다. 원본이나 HWPX/PDF로 올려 주세요."],
            }

        # 첨부 이미지: BinData 스토리지 전체 추출
        images: list[str] = []
        for entry in ole.listdir():
            if len(entry) != 2 or entry[0] != "BinData":
                continue
            blob = ole.openstream(entry).read()
            if compressed:
                try:
                    blob = zlib.decompress(blob, -15)
                except Exception:
                    pass
            rel_path = _save_image_bytes(entry[1], blob)
            if rel_path:
                images.append(rel_path)

    report: dict[str, Any] = {}
    chunks = _paragraphs_to_chunks(paragraphs, report)
    notices.extend(_answer_key_notices(report))
    if not chunks:
        return {"created": [], "notices": ["HWP에서 텍스트를 추출하지 못했습니다.", *notices]}
    if images:
        notice = _attach_unpositioned_images(chunks, images)
        if notice:
            notices.append(notice)
    sink = _create_from_chunks(chunks, "hwp", filename, metadata)
    notices.extend(_dedup_notices(sink))
    return {"created": sink.created, "existing": sink.existing, "ordered_ids": sink.ordered_ids, "notices": notices}
