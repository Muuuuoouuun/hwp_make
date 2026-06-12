from __future__ import annotations

from dataclasses import dataclass, asdict


DEFAULT_EXPORT_TITLE = "문항 모음"


@dataclass(frozen=True)
class ExamTemplate:
    key: str
    label: str
    description: str
    default_title: str = DEFAULT_EXPORT_TITLE
    masthead_title: str = ""
    area: str = ""
    period: str = ""
    variant: str = ""
    selection: str = ""
    directions: tuple[str, ...] = ()
    show_student_fields: bool = False
    include_answers: bool = True
    include_explanations: bool = True
    merge_question_number: bool = False
    circled_choices: bool = False
    inline_short_choices: bool = False
    compact: bool = False
    columns: int = 1

    def export_option(self) -> dict[str, str | bool | int]:
        data = asdict(self)
        data["directions"] = list(self.directions)
        return data


TEMPLATES: tuple[ExamTemplate, ...] = (
    ExamTemplate(
        key="basic",
        label="기본 문항 모음",
        description="정답과 해설을 함께 담는 기본 내보내기 양식",
    ),
    ExamTemplate(
        key="school_exam",
        label="학교 기출 시험지",
        description="학교 내신 시험지형 머리말과 원형 선지 양식",
        default_title="학교 기출 시험지",
        masthead_title="학교 기출 시험지",
        area="중학교 1학년 2학기 중간고사 [20__]",
        variant="영어",
        directions=("개요 번호와 세부 번호를 유지해 편집하기 좋은 시험지 양식입니다.",),
        include_answers=False,
        include_explanations=False,
        merge_question_number=True,
        circled_choices=True,
        compact=True,
    ),
    ExamTemplate(
        key="kice_korean",
        label="평가원 국어",
        description="수능 국어 영역 문제지 느낌의 머리말과 홀수형 표기",
        default_title="2025학년도 대학수학능력시험 문제지",
        masthead_title="2025학년도 대학수학능력시험 문제지",
        area="국어 영역",
        period="제1교시",
        variant="홀수형",
        include_answers=False,
        include_explanations=False,
        merge_question_number=True,
        circled_choices=True,
        inline_short_choices=True,
        compact=True,
        columns=2,
    ),
    ExamTemplate(
        key="kice_korean_speech_writing",
        label="평가원 국어 화작",
        description="6월 모의평가 국어 영역 화법과 작문 선택과목 양식",
        default_title="2025학년도 대학수학능력시험 6월 모의평가 문제지",
        masthead_title="2025학년도 대학수학능력시험 6월 모의평가 문제지",
        area="국어 영역(화법과 작문)",
        period="제1교시",
        directions=(
            "* 확인 사항",
            "답안지의 해당란에 필요한 내용을 정확히 기입(표기)했는지 확인하시오.",
            "이어서, 선택과목(화법과 작문) 문제가 제시되오니, 자신이 선택한 과목인지 확인하시오.",
        ),
        include_answers=False,
        include_explanations=False,
        merge_question_number=True,
        circled_choices=True,
        inline_short_choices=True,
        compact=True,
        columns=2,
    ),
    ExamTemplate(
        key="kice_korean_language_media",
        label="평가원 국어 언매",
        description="6월 모의평가 국어 영역 언어와 매체 선택과목 양식",
        default_title="2025학년도 대학수학능력시험 6월 모의평가 문제지",
        masthead_title="2025학년도 대학수학능력시험 6월 모의평가 문제지",
        area="국어 영역(언어와 매체)",
        period="제1교시",
        directions=(
            "* 확인 사항",
            "답안지의 해당란에 필요한 내용을 정확히 기입(표기)했는지 확인하시오.",
            "이어서, 선택과목(언어와 매체) 문제가 제시되오니, 자신이 선택한 과목인지 확인하시오.",
        ),
        include_answers=False,
        include_explanations=False,
        merge_question_number=True,
        circled_choices=True,
        inline_short_choices=True,
        compact=True,
        columns=2,
    ),
    ExamTemplate(
        key="kice_math",
        label="평가원 수학",
        description="수능 수학 영역 5지선다형 문제지 양식",
        default_title="2025학년도 대학수학능력시험 문제지",
        masthead_title="2025학년도 대학수학능력시험 문제지",
        area="수학 영역",
        period="제2교시",
        variant="5지선다형",
        include_answers=False,
        include_explanations=False,
        merge_question_number=True,
        circled_choices=True,
        inline_short_choices=True,
        compact=True,
        columns=2,
    ),
    ExamTemplate(
        key="kice_english",
        label="평가원 영어",
        description="수능 영어 영역 홀수형과 듣기 안내문 양식",
        default_title="2025학년도 대학수학능력시험 문제지",
        masthead_title="2025학년도 대학수학능력시험 문제지",
        area="영어 영역",
        period="제3교시",
        variant="홀수형",
        directions=(
            "1번부터 17번까지는 듣고 답하는 문제입니다.",
            "1번부터 15번까지는 한 번만 들려주고, 16번부터 17번까지는 두 번 들려줍니다.",
        ),
        include_answers=False,
        include_explanations=False,
        merge_question_number=True,
        circled_choices=True,
        inline_short_choices=False,
        compact=True,
        columns=2,
    ),
    ExamTemplate(
        key="kice_social",
        label="평가원 사탐",
        description="사회탐구 영역 선택 과목 표기와 수험 정보란 양식",
        default_title="2025학년도 대학수학능력시험 문제지",
        masthead_title="2025학년도 대학수학능력시험 문제지",
        area="사회탐구 영역",
        period="제4교시",
        selection="제 [  ] 선택",
        show_student_fields=True,
        include_answers=False,
        include_explanations=False,
        merge_question_number=True,
        circled_choices=True,
        inline_short_choices=False,
        compact=True,
        columns=2,
    ),
    ExamTemplate(
        key="kice_science",
        label="평가원 과탐",
        description="과학탐구 영역 선택 과목 표기와 수험 정보란 양식",
        default_title="2025학년도 대학수학능력시험 문제지",
        masthead_title="2025학년도 대학수학능력시험 문제지",
        area="과학탐구 영역",
        period="제4교시",
        selection="제 [  ] 선택",
        show_student_fields=True,
        include_answers=False,
        include_explanations=False,
        merge_question_number=True,
        circled_choices=True,
        inline_short_choices=False,
        compact=True,
        columns=2,
    ),
)


TEMPLATE_MAP = {template.key: template for template in TEMPLATES}


def get_template(key: str | None) -> ExamTemplate:
    return TEMPLATE_MAP.get(key or "basic", TEMPLATE_MAP["basic"])


def resolve_export_title(title: str, template: ExamTemplate) -> str:
    clean = (title or "").strip()
    if template.key != "basic" and (not clean or clean == DEFAULT_EXPORT_TITLE):
        return template.default_title
    return clean or template.default_title
