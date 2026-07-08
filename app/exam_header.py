"""시험명 파서 — PDF 상단 헤더/파일명에서 마스트헤드 문자열을 도출한다.

제품 B(원본 PDF→편집형 HWPX) 병목 #6: 모든 kice 템플릿의 masthead_title 이
'2025학년도 대학수학능력시험 … 6월 모의평가'로 하드코딩돼 원본이 3월/9월 학평이어도
6월/수능으로 오표기된다. 이 순수 모듈이 연도·월·주관·시험종류를 파싱해 동적
마스트헤드를 만들고, 파싱 실패 시 빈 문자열을 돌려 호출부가 템플릿 폴백하게 한다.

순수 stdlib(외부 의존성 0). recognition/writer 어디에도 의존하지 않아 단위 검증이 쉽다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# "2025학년도" 또는 "2024년" 형태의 연도.
_YEAR_RE = re.compile(r"(20\d{2})\s*(?:학년도|년)")
# "6월", "3 월" — 앞에 숫자가 붙은 연도 일부('2024')를 월로 오인하지 않도록 (?<!\d).
_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})\s*월")
# "고3", "고 2".
_GRADE_RE = re.compile(r"고\s*([1-3])")


@dataclass(frozen=True)
class ExamMeta:
    year: str = ""       # 예: "2025"
    month: str = ""      # 예: "6"
    organizer: str = ""  # 평가원 | 교육청
    exam_type: str = ""  # 수능 | 모의평가 | 학력평가 | 모의고사
    grade: str = ""      # 1 | 2 | 3

    def ok(self) -> bool:
        # 연도와 시험종류가 모두 있어야 신뢰 가능한 마스트헤드를 만든다.
        return bool(self.year and self.exam_type)


def parse_exam_header(text: str) -> ExamMeta:
    """헤더 텍스트/파일명에서 시험 메타를 파싱한다. 실패 항목은 빈 문자열."""
    normalized = re.sub(r"[\s_]+", " ", str(text or "")).strip()
    year_match = _YEAR_RE.search(normalized)
    month_match = _MONTH_RE.search(normalized)
    grade_match = _GRADE_RE.search(normalized)

    organizer = ""
    exam_type = ""
    # 우선순위: 학력평가 > 모의평가 > 수능 (모의평가 문구가 있으면 수능으로 오판 방지).
    if "전국연합학력평가" in normalized or "학력평가" in normalized:
        organizer, exam_type = "교육청", "학력평가"
    elif "모의평가" in normalized:
        organizer, exam_type = "평가원", "모의평가"
    elif "대학수학능력시험" in normalized or "수능" in normalized:
        organizer, exam_type = "평가원", "수능"
    elif "교육청" in normalized or "모의고사" in normalized:
        organizer, exam_type = "교육청", "모의고사"

    return ExamMeta(
        year=year_match.group(1) if year_match else "",
        month=month_match.group(1) if month_match else "",
        organizer=organizer,
        exam_type=exam_type,
        grade=grade_match.group(1) if grade_match else "",
    )


def masthead_from_meta(meta: ExamMeta) -> str:
    """파싱된 메타 → 문제지 마스트헤드 문자열. 불충분하면 "" (호출부 템플릿 폴백)."""
    if not meta.ok():
        return ""
    year = f"{meta.year}학년도"
    if meta.organizer == "평가원":
        if meta.exam_type == "수능":
            return f"{year} 대학수학능력시험 문제지"
        month = f"{meta.month}월 " if meta.month else ""
        return f"{year} 대학수학능력시험 {month}모의평가 문제지"
    # 교육청(학력평가/모의고사)
    grade = f"고{meta.grade} " if meta.grade else ""
    kind = "전국연합학력평가" if meta.exam_type == "학력평가" else meta.exam_type
    month = f"{meta.month}월 " if meta.month else ""
    return f"{year} {month}{grade}{kind} 문제지"


def masthead_from_text(text: str) -> str:
    """헤더/파일명 텍스트 → 마스트헤드 문자열(원샷). 실패 시 ""."""
    return masthead_from_meta(parse_exam_header(text))
