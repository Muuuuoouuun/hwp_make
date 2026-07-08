"""HyhwpEQ(한컴 수식 임베디드 서브셋 폰트) PUA(E0xx) → 유니코드 매핑표.

병목 #2: 평가원 수학/과탐 born-digital PDF는 수식을 ToUnicode 없는 임베디드 서브셋
폰트 HyhwpEQ 로 인코딩해, PyMuPDF get_text 가 U+E000–E1xx PUA 를 돌려준다. math_text 의
기존 SYMBOL_PUA_MAP 은 F0xx(Adobe Symbol)만 커버해 이 글자들이 '복구불가'로 세어져
문항 전체가 편집불가 이미지로 폴백됐다.

이 표는 실물 평가원 PDF 18부(25수능 6과목 + 26-9월 모의평가)에서 각 E0xx 글리프를
렌더·육안 확인해 만든 것이다. 인코딩이 완전히 순차적임을 확인:
  - 대문자 A–Z = U+E000 + (ord-'A')   (21/26 관측, 예외 0)
  - 소문자 a–z(이탤릭) = U+E0E5 + (ord-'a')   (23/26 관측, 예외 0)
  - 숫자 1–9 = U+E034–E03C, 0 = U+E03D
따라서 미관측 글자(D/J/K/N/U 등)도 패턴으로 결정론 채움.

math_text 는 `is_recoverable_pua_math_char`/정규화에서 이 표를 SYMBOL_PUA_MAP 과 병합해
쓰면 된다(폰트 스코프 HANCOM_EQ_FONTS 로 한컴 수식폰트 span 에만 적용 권장).

주의(범위): 이 표는 글리프 '기호'를 복원한다. 위첨자·분수·근호의 2D '구조'는 글리프
위치로 표현되므로 이 선형 치환만으로는 x²가 'x2'가 된다(구조 복원은 별건). 그래도
text_reliable 을 켜 편집 가능 텍스트를 살리는 것이 이미지 폴백보다 낫다.
"""
from __future__ import annotations

# 이 폰트들의 span 에서만 E0xx 를 재해석(다른 폰트의 우연한 PUA 오탐 차단).
HANCOM_EQ_FONTS: tuple[str, ...] = ("HyhwpEQ", "HancomEQN")

# 연산자·구분자·기호(육안 확정)
_OPERATORS: dict[int, str] = {
    0xE044: "(", 0xE045: ")", 0xE046: "-", 0xE047: "=", 0xE048: "+",
    0xE049: "[", 0xE04A: "]", 0xE04B: "{", 0xE04C: "}", 0xE04D: "|",
    0xE04F: ":", 0xE052: ",", 0xE053: ".", 0xE054: "/", 0xE055: "<",
    0xE056: ">", 0xE05B: "∫", 0xE05C: "√", 0xE067: "∑",
    0xE06E: "⃗",
    0xE078: "(", 0xE079: "{", 0xE07A: "", 0xE07B: "|", 0xE101: "|",
}

# 그리스(육안 확정)
_GREEK: dict[int, str] = {
    0xE088: "Δ", 0xE099: "Φ", 0xE09D: "α", 0xE09E: "β",
    0xE0A4: "θ", 0xE0A7: "λ", 0xE0AC: "π", 0xE0AD: "ρ", 0xE0AE: "σ",
}


def _build_map() -> dict[str, str]:
    table: dict[str, str] = {}
    # 대문자 A–Z = U+E000 + offset
    for i in range(26):
        table[chr(0xE000 + i)] = chr(ord("A") + i)
    # 소문자 a–z(이탤릭) = U+E0E5 + offset
    for i in range(26):
        table[chr(0xE0E5 + i)] = chr(ord("a") + i)
    # 숫자 1–9 = U+E034–E03C, 0 = U+E03D
    for d in range(1, 10):
        table[chr(0xE033 + d)] = str(d)
    table[chr(0xE03D)] = "0"
    for code, sym in {**_OPERATORS, **_GREEK}.items():
        table[chr(code)] = sym
    return table


# {PUA 문자: 유니코드 기호}
HANCOM_PUA_MAP: dict[str, str] = _build_map()


def is_hancom_eq_font(font_name: str | None) -> bool:
    name = str(font_name or "").lower()
    return any(f.lower() in name for f in HANCOM_EQ_FONTS)


def recover_pua_char(char: str) -> str | None:
    """E0xx PUA 문자 → 복원 기호. 표에 없으면 None."""
    return HANCOM_PUA_MAP.get(char)
