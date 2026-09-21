"""Read printed question markers without requiring text after the number.

Some exam questions print only ``36.`` above a boxed passage. Korean extraction
also legitimately returns ``2.단순 관점…`` without a space. Neither case calls
for manufacturing question text or guessing a missing number. The caller must
still reconcile these visible markers with the independent source inventory.
"""
from __future__ import annotations

import re

# A period followed by a digit is a decimal/section number, not this exam's
# question marker. Parenthesized answer labels such as "1)" are not markers.
QUESTION_START = re.compile(r"^\s*([1-9]\d?)\.(?![\d.])")
SHARED_PASSAGE_START = re.compile(
    r"^\s*[\[［]\s*([1-9]\d?)\s*[~～∼\-–]\s*([1-9]\d?)\s*[\]］]"
)


def question_number(text: str) -> int | None:
    match = QUESTION_START.match(str(text or ""))
    return int(match[1]) if match else None


def shared_question_range(text: str) -> tuple[int, int] | None:
    match = SHARED_PASSAGE_START.match(str(text or ""))
    if match and int(match[1]) <= int(match[2]):
        return int(match[1]), int(match[2])
    return None


def document_note_heading(text: str) -> bool:
    """Printed headings may space every syllable (확 인 사 항)."""
    compact = re.sub(r"\s+", "", str(text or ""))
    return re.fullmatch(r"[*＊※]?(?:확인사항|유의사항)[:：]?", compact) is not None
