"""교사에게 보여 줄 변환 실패 문구.

엔진 예외 문구(영문 진단·서버 절대경로·repr)는 로그에만 남기고, API 응답에는
알려진 실패 유형 코드와 한국어 안내만 싣는다. detail 은 {code, message, hint}
로 통일하며, 프런트(friendlyErrorMessage)와 데스크톱 워커는 detail.message 를 쓴다.
"""
from __future__ import annotations

import logging
import re
from typing import Any

LOG = logging.getLogger("hwp_make.errors")

# code -> (message, hint)
MESSAGES: dict[str, tuple[str, str]] = {
    "empty": (
        "빈 파일이라 변환할 수 없습니다.",
        "내용이 들어 있는 파일을 다시 선택해 주세요.",
    ),
    "encrypted": (
        "암호가 걸린 PDF라서 열 수 없습니다.",
        "PDF 보기 프로그램에서 암호를 해제해 다시 저장한 뒤 올려 주세요.",
    ),
    "damaged": (
        "파일이 손상되어 열 수 없습니다.",
        "원본 파일을 다시 내려받거나 다시 저장한 뒤 올려 주세요.",
    ),
    "not_pdf": (
        "PDF 파일만 원본 레이아웃 HWPX로 만들 수 있습니다.",
        "파일 확장자와 실제 내용이 PDF인지 확인해 주세요.",
    ),
    "scan_only": (
        "글자를 선택할 수 없는 스캔(사진) PDF라서 편집할 수 있는 문서로 바꾸지 못했습니다.",
        "글자가 선택되는 원본 PDF나 한글·워드 원본 파일을 올려 주세요.",
    ),
    "no_questions": (
        "문항 번호를 찾지 못해 문항별로 나누지 못했습니다.",
        "'1.' '2.'처럼 번호가 붙은 시험지인지 확인해 주세요.",
    ),
    "unsupported_structure": (
        "원본의 문항 배치를 분석하지 못했습니다. 정답표·해설처럼 번호 없는 쪽이 섞여 있을 수 있습니다.",
        "정답·해설 쪽을 뺀 문제지 PDF로 다시 시도해 보세요.",
    ),
    "invalid_request": (
        "요청 내용이 올바르지 않습니다.",
        "화면을 새로 고친 뒤 파일을 다시 선택해 주세요.",
    ),
    "import_failed": (
        "파일 내용을 읽지 못했습니다.",
        "파일이 열리는지 확인한 뒤 다시 올려 주세요.",
    ),
    "export_failed": (
        "문서를 만드는 중 문제가 생겼습니다.",
        "잠시 후 다시 시도해 주세요. 계속되면 문항 내용을 확인해 주세요.",
    ),
    "preview_failed": (
        "미리보기를 만들지 못했습니다.",
        "내려받기는 그대로 할 수 있습니다. 결과 파일을 한글에서 확인해 주세요.",
    ),
    "conversion_failed": (
        "변환 중 예기치 않은 문제가 생겼습니다.",
        "잠시 후 다시 시도해 주세요. 계속되면 한글·워드 원본 파일로 올려 주세요.",
    ),
    "format_mismatch": (
        "선택한 파일 형식과 실제 파일 내용이 다릅니다.",
        "확장자가 맞는 원본 파일인지 확인해 주세요.",
    ),
    "too_large": (
        "파일이 너무 커서 처리할 수 없습니다.",
        "쪽을 나누거나 용량을 줄인 파일로 다시 올려 주세요.",
    ),
    "busy": (
        "다른 변환이 진행 중입니다.",
        "잠시 후 다시 시도해 주세요.",
    ),
    "collect_failed": (
        "웹 페이지에서 문항을 가져오지 못했습니다.",
        "주소가 맞는지, 로그인 없이 열리는 공개 페이지인지 확인해 주세요.",
    ),
    "output_damaged": (
        "생성한 HWPX 파일이 손상되어 제공할 수 없습니다.",
        "다시 변환해 주세요. 계속되면 한글·워드 원본 파일로 올려 주세요.",
    ),
    "no_editable_content": (
        "편집할 수 있는 문항이나 문장을 찾지 못해 편집형 문서를 제공할 수 없습니다.",
        "글자를 선택할 수 있는 PDF인지 확인해 주세요.",
    ),
    "not_found": (
        "찾는 문항이나 파일이 없습니다. 이미 삭제되었을 수 있습니다.",
        "목록을 새로 고친 뒤 다시 시도해 주세요.",
    ),
    "save_failed": (
        "저장할 위치에 파일을 쓰지 못했습니다.",
        "같은 이름의 파일이 한글 등에서 열려 있으면 닫고, 다른 폴더나 이름으로 저장해 보세요.",
    ),
    "strict_check_failed": (
        "엄격 검사에서 문항 결함이 발견되어 결과물을 제공하지 않았습니다.",
        "엄격 검사 없이 변환하면 확인할 문항 안내와 함께 파일을 받을 수 있습니다.",
    ),
}


_PATH_RE = re.compile(r"(?:\b[A-Za-z]:[\\/]|\\|/(?:home|Users|tmp|var)/)")
_HANGUL_RE = re.compile(r"[가-힣]")


def detail(code: str, message: str | None = None, **extra: Any) -> dict[str, Any]:
    if code not in MESSAGES:
        code = "conversion_failed"
    default_message, hint = MESSAGES[code]
    return {"code": code, "message": message or default_message, "hint": hint, **extra}


def teacher_head(exc: BaseException) -> str | None:
    """'한국어 안내: 내부 진단' 형태 예외에서 한국어 안내만 꺼낸다(없으면 None)."""
    head = str(exc).split(": ", 1)[0].strip()
    if not head or not _HANGUL_RE.search(head) or _PATH_RE.search(head):
        return None
    return head


_ENGLISH_PHRASE_RE = re.compile(r"[A-Za-z]{2,}(?: [A-Za-z]{2,}){2,}")


def teacher_message(exc: BaseException) -> str | None:
    """한국어로만 된 안내는 통째로('지원 형식: PDF, HWP …'), 내부 진단이 섞였으면 앞의 한국어 안내만."""
    text = str(exc).strip()
    if _HANGUL_RE.search(text) and not _PATH_RE.search(text) and not _ENGLISH_PHRASE_RE.search(text):
        return text
    return teacher_head(exc)


def _pdf_state(data: bytes) -> str | None:
    """PDF 바이트 자체에서 알 수 있는 실패 유형(없으면 None)."""
    if not data:
        return "empty"
    try:
        import fitz

        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                return "encrypted"
            if not document.page_count:
                return "empty"
            # 텍스트 레이어가 거의 없으면 스캔본이다(쪽당 20자 미만).
            chars = sum(len(page.get_text("text").strip()) for page in document)
            if chars < 20 * document.page_count:
                return "scan_only"
    except Exception:  # noqa: BLE001 - 열리지 않는 PDF는 손상으로 분류한다.
        return "damaged"
    return None


def classify_pdf_failure(exc: BaseException, data: bytes) -> str:
    state = _pdf_state(data)
    if state:
        return state
    text = str(exc)
    if "empty PDF" in text:
        return "empty"
    if "no editable problems" in text or "no output problems" in text or "no output content" in text:
        return "no_questions"
    if "no native PDF body content" in text:
        return "no_editable_content"
    # 'native question grouping does not match source inventory' 등 배치 분석 실패.
    return "unsupported_structure"


def classify_import_failure(exc: BaseException, kind: str, data: bytes | None) -> str:
    if data is None:
        # 업로드 데이터 자체를 풀지 못했다(전송 중 손상 등).
        return "invalid_request"
    if not data:
        return "empty"
    if kind == "pdf":
        state = _pdf_state(data)
        if state in {"empty", "encrypted", "damaged"}:
            return state
    return "import_failed"


def log_failure(context: str, exc: BaseException) -> None:
    # 원문 예외(경로·영문 진단·트레이스백)는 서버 로그에만 남긴다.
    LOG.warning("%s: %s", context, exc, exc_info=exc)
