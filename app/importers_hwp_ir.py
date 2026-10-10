"""원본 HWP → 편집형 IR 임포트 (rhwp `to_ir()` 기반).

기존 import_hwp 는 rhwp 의 `.paragraphs()`(평문)만 써서 수식·이미지·위치를 전부
버렸다. 이 모듈은 `rhwp.parse(path).to_ir()` 가 주는 구조화 IR(문단 + 수식 EQN
스크립트 + 이미지 바이트 + 위치)을 활용해 **편집 가능한** 문항을 복원한다.

핵심 통찰:
- to_ir 의 FormulaBlock.script 는 한컴 EQN 스크립트 원문(예: `{1} over {2}`)이며,
  이는 이 앱의 writer 가 hp:equation 으로 내보낼 때 쓰는 문법과 동일하다. 그래서
  수식을 `$...$` 로 감싸 stem/choices 텍스트에 인라인 삽입하면, writer 의 native_math
  경로(split_math_text → _hancom_eqn_script)가 **이중변환 없이**(EQN 은 변환기의
  fixed point) hp:equation 으로 방출한다.
- 문단 순서·문단 내 char offset 이 IR 에 있어 원본 읽기순서 그대로 재구성된다.
- `[N점][... NN]` 트레일러 마커는 기존 importers._paragraphs_to_chunks 가 이미
  처리하므로, 이 모듈은 (text, images, tables) 문단 리스트만 만들어 넘긴다.

rhwp/to_ir 이 없거나 실패하면 None 을 반환해 호출자가 기존 경로로 폴백한다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

try:
    import rhwp
except Exception:  # pragma: no cover - 선택 의존성
    rhwp = None

# HWP 편집본 결합 마커: 문항 stem 뒤·선지 앞에 오는 "[N점][시험명 NN]".
# 일부 개인 편집본은 번호 뒤에 "번"을 붙인다.
_MARKER_RE = re.compile(
    r"^\s*\[(\d{1,2})\s*점\]\s*\[[^\]]*?(\d{1,3})\s*(?:번)?\]\s*$"
)
_MARKER_DETAIL_RE = re.compile(
    r"^\s*\[(?P<score>\d{1,2})\s*점\]\s*\[(?P<section>.*?)(?P<number>\d{1,3})"
    r"(?P<number_suffix>\s*번)?\]\s*$"
)
_TRAILING_SOURCE_RE = re.compile(
    r"^\s*\[(?P<section>.*?)(?P<number>\d{1,3})\s*번\]\s*$"
)
_TRAILING_SOURCE_HINT_RE = re.compile(
    r"(?:\d{2,4}|[년월]|고[123]|중[123]|전국|모의|수능|평가|교육청|평가원)"
)
_INTENT_RE = re.compile(r"^\s*\[출제의도\]\s*(?P<intent>.*)$")
_INLINE_SCORE_RE = re.compile(r"\[\s*(?P<score>\d{1,2})\s*점\s*\]")
_CIRCLED = "①②③④⑤⑥⑦⑧⑨❶❷❸❹❺❻❼❽❾➀➁➂➃➄➅➆➇➈"
_ANSWER_SECTION_TEXT_RE = re.compile(
    r"^\s*(?:\[\uc815\ub2f5\]|\ube60\ub978\s*\uc815\ub2f5|\uc815\ub2f5\s*(?:\ubc0f|\uacfc)\s*\ud574\uc124|\uc815\ub2f5\s*\ud45c)"
)
# 국어/영어 공유 지문 헤더: "[1~3] 다음 글을 읽고 물음에 답하시오." 형태.
_PASSAGE_RANGE_RE = re.compile(r"^\s*\[\s*(\d{1,2})\s*[~∼\-–]\s*(\d{1,2})\s*\]")
_QUESTION_LINE_RE = re.compile(r"^\s*(\d{1,2})[.．]\s")


def _extract_leading_passage(stem: str) -> tuple[str | None, str, str]:
    """stem 이 공유 지문으로 시작하면 (지문, 남은문항, 범위라벨)로 분리한다.

    "[1~3] 다음 글을 읽고..." 로 시작하는 국어/영어 문항은 지문이 문두에 붙어 있는데,
    원본 문제지는 지문을 독립 블록으로 배치한다. 첫 실제 문항("1." 등) 앞까지를 지문으로
    떼어 낸다. 지문이 아니면 (None, stem, "") 반환.
    """
    lines = (stem or "").split("\n")
    if not lines:
        return None, stem, ""
    m = _PASSAGE_RANGE_RE.match(lines[0])
    is_passage_header = bool(m) or ("다음 글을 읽" in lines[0]) or ("다음을 읽" in lines[0])
    if not is_passage_header:
        return None, stem, ""
    label = f"[{m.group(1)}~{m.group(2)}]" if m else ""
    # 첫 줄(안내문) 이후에서 "N." 문항 시작을 찾는다.
    for i in range(1, len(lines)):
        if _QUESTION_LINE_RE.match(lines[i]):
            passage = "\n".join(lines[:i]).strip()
            question = "\n".join(lines[i:]).strip()
            if passage and question:
                return passage, question, label
            break
    return None, stem, ""


def _extract_trailing_passage(stem: str) -> tuple[str, str | None, str]:
    """stem 뒤쪽에 다음 공유 지문이 붙었으면 (문항, 지문, 범위라벨)로 분리한다."""
    text = stem or ""
    match = re.search(r"\n\s*(\[\s*(\d{1,2})\s*[~∼\-–]\s*(\d{1,2})\s*\])", text)
    if not match or match.start() <= 0:
        return stem, None, ""
    question = text[: match.start()].strip()
    passage = text[match.start() :].strip()
    if not question or not passage:
        return stem, None, ""
    return question, passage, f"[{match.group(2)}~{match.group(3)}]"


# (text, image_rel_paths, tables) — 기존 importers._paragraphs_to_chunks 입력과 동일
ParaBlock = tuple[str, list[str], list[list[list[str]]]]

# 이미지 저장 콜백: (name, bytes) -> 상대경로 | None
SaveImage = Callable[[str, bytes], "str | None"]


def available() -> bool:
    return rhwp is not None and hasattr(rhwp, "parse")


def _trailing_source_match(value: str) -> re.Match[str] | None:
    match = _TRAILING_SOURCE_RE.match(str(value or "").strip())
    if not match or not _TRAILING_SOURCE_HINT_RE.search(match.group("section")):
        return None
    return match


def _prov(block: Any) -> tuple[int, int, int | None]:
    pr = getattr(block, "prov", None) or getattr(block, "provenance", None)
    return (
        int(getattr(pr, "section_idx", 0) or 0),
        int(getattr(pr, "para_idx", 0) or 0),
        getattr(pr, "char_start", None),
    )


_BOXED_HANGUL_RE = re.compile(
    r"(?i)(?:\{\s*)?box\s*(?:\{\s*)?~*\s*"
    r"(?P<label>\(\s*[가-힣]+\s*\)|[가-힣]+)"
    r"\s*~*\s*\}?(?:\s*\})?"
)
_PLAIN_HANGUL_TOKEN_RE = re.compile(r"(\(\s*[가-힣]+\s*\)|[가-힣]+)")
_HANGUL_SENTINEL_RE = re.compile(r"@@HWP_TEXT_(\d+)@@")


def _wrap_mixed_hangul_eqn(script: str) -> str:
    """EQN 속 한글 라벨은 평문, 나머지는 native equation으로 분리한다."""
    labels: list[str] = []

    def boxed_repl(match: re.Match[str]) -> str:
        labels.append(re.sub(r"\s+", "", match.group("label")))
        return f"@@HWP_TEXT_{len(labels) - 1}@@"

    replaced = _BOXED_HANGUL_RE.sub(boxed_repl, script)
    pieces = re.split(r"(@@HWP_TEXT_\d+@@|\(\s*[가-힣]+\s*\)|[가-힣]+)", replaced)
    out: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        sentinel = _HANGUL_SENTINEL_RE.fullmatch(piece)
        if sentinel:
            out.append(labels[int(sentinel.group(1))])
            continue
        if _PLAIN_HANGUL_TOKEN_RE.fullmatch(piece):
            out.append(re.sub(r"\s+", "", piece))
            continue
        math_part = piece.replace("$", " ").strip()
        if math_part:
            out.append(f"${math_part}$")
    return " ".join(out).strip()


def _wrap_eqn(script: str) -> str:
    """EQN 스크립트를 writer 가 hp:equation 으로 인식하도록 $...$ 로 감싼다.

    스크립트 자체에 $ 가 들어가면 델리미터가 깨지므로 방어적으로 치환한다.
    빈 스크립트/단순 정수는 그대로 텍스트로 둔다(불필요한 수식 개체 방지).
    """
    s = (script or "").strip()
    if not s:
        return ""
    if re.search(r"[\uac00-\ud7a3]", s):
        converted = _wrap_hangul_cases_eqn(s)
        if converted:
            return converted
        converted = _wrap_mixed_hangul_eqn(s)
        if converted:
            return converted
    # 단순 정수/한 글자 숫자는 수식 개체로 만들 필요 없음(선지 "1" 등) — 평문 유지
    if s.isdigit() or (len(s) <= 2 and s.isalnum()):
        return s
    s = s.replace("$", " ")
    return f"${s}$"


def _split_top_level(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(value):
        char = value[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and value.startswith(separator, i):
            parts.append(value[start:i])
            i += len(separator)
            start = i
            continue
        i += 1
    parts.append(value[start:])
    return parts


def _strip_wrapped_condition(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("LEFT"):
        text = re.sub(r"^\s*LEFT\s*\(", "", text)
        text = re.sub(r"\s*RIGHT\s*\)\s*$", "", text)
    return text.strip()


def _plain_condition_text(value: str) -> str:
    text = _strip_wrapped_condition(value)
    text = text.replace("`", " ").replace("~", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"sqrt\s*\{\s*([^}]+?)\s*\}", r"sqrt(\1)", text)
    text = re.sub(r"\b([a-zA-Z])\s*_\{\s*([^}]+?)\s*\}", r"\1_\2", text)
    return text


def _wrap_hangul_cases_eqn(script: str) -> str:
    marker = "{cases{"
    start = script.find(marker)
    if start < 0:
        return ""
    head = script[:start].strip()
    body = script[start + len(marker) :].strip()
    while body.endswith("}"):
        body = body[:-1].strip()
    rows: list[str] = []
    if head:
        rows.append(f"${head}$")
    for case in _split_top_level(body, "#"):
        expr_cond = _split_top_level(case, "&&")
        if len(expr_cond) < 2:
            continue
        expr = re.sub(r"(?<=\})it(?=\^)", "", expr_cond[0].strip())
        cond = _plain_condition_text("&&".join(expr_cond[1:]))
        if not expr:
            continue
        rows.append(f"${expr}$ ({cond})" if cond else f"${expr}$")
    return "\n".join(rows)


def _splice_formulas(text: str, formulas: list[tuple[int, str]]) -> str:
    """문단 텍스트의 char offset 위치에 수식(EQN)을 $...$ 로 끼워 넣는다."""
    text = text or ""
    if not formulas:
        return text
    parts: list[str] = []
    cursor = 0
    for char_start, script in sorted(formulas, key=lambda item: (item[0] if item[0] is not None else 0)):
        pos = char_start if char_start is not None else len(text)
        pos = max(0, min(pos, len(text)))
        if pos > cursor:
            parts.append(text[cursor:pos])
        parts.append(_wrap_eqn(script))
        cursor = pos
    if cursor < len(text):
        parts.append(text[cursor:])
    return "".join(parts)


def _cell_blocks_text(blocks: list[Any]) -> str:
    """TableCell.blocks → text with inline EQN formulas restored.

    rhwp preserves formulas inside table cells as FormulaBlock entries, but the
    TableBlock.text/html projections drop them.  Rebuild each cell from the
    nested paragraph/list_item blocks and splice the following formulas back by
    their paragraph-local character offsets.
    """
    parts: list[str] = []
    current_text: str | None = None
    current_formulas: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal current_text, current_formulas
        if current_text is not None:
            restored = _splice_formulas(current_text, current_formulas)
            if restored.strip():
                parts.append(restored.strip())
        elif current_formulas:
            restored = "".join(_wrap_eqn(script) for _, script in current_formulas)
            if restored.strip():
                parts.append(restored.strip())
        current_text = None
        current_formulas = []

    for block in blocks or []:
        kind = str(getattr(block, "kind", "") or "")
        if kind in ("paragraph", "list_item"):
            flush()
            current_text = getattr(block, "text", "") or ""
            current_formulas = []
        elif kind == "formula":
            _, _, char_start = _prov(block)
            current_formulas.append(
                (char_start if char_start is not None else len(current_text or ""), getattr(block, "script", "") or "")
            )
        elif kind == "table":
            # A nested table's text belongs to this cell (it used to vanish).
            flush()
            nested = _table_rows(block)
            nested_text = " ".join(cell for row in nested for cell in row if str(cell).strip())
            if nested_text:
                parts.append(nested_text)
    flush()
    return " ".join(part for part in parts if part).strip()


def _cell_pictures(blocks: list[Any]) -> list[Any]:
    """Picture blocks inside a cell, including cells of nested tables."""
    found: list[Any] = []
    for block in blocks or []:
        kind = str(getattr(block, "kind", "") or "")
        if kind == "picture":
            found.append(block)
        elif kind == "table":
            for cell in getattr(block, "cells", None) or []:
                found.extend(_cell_pictures(getattr(cell, "blocks", []) or []))
    return found


def _downscale_image(blob: bytes, *, max_dim: int = 1600, max_bytes: int = 900_000) -> bytes:
    """원본 HWP 그림이 지나치게 크면(한컴 뷰어가 멈출 정도) 축소·재인코딩한다.

    영어/과탐 양식 등에는 2500px+ / 10MB+ 전면 그래픽이 들어있어 그대로 넣으면
    HWPX 가 비대해지고 한컴이 로딩 중 응답없음에 빠진다. 긴 변을 max_dim 으로,
    용량을 max_bytes 목표로 낮춘다. 실패하면 원본을 그대로 돌려준다(안전).
    """
    if len(blob) <= max_bytes:
        return blob
    try:
        import io as _io

        from PIL import Image as _Image

        with _Image.open(_io.BytesIO(blob)) as im:
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            w, h = im.size
            scale = min(1.0, max_dim / max(w, h))
            if scale < 1.0:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), _Image.LANCZOS)
            out = _io.BytesIO()
            im.save(out, format="PNG", optimize=True)
            data = out.getvalue()
        return data if len(data) < len(blob) else blob
    except Exception:
        return blob


class TableGrid(list):
    """2차원 문자열 표 + 병합 셀 정보(spans).

    표 모델(2차원 문자열 배열)은 그대로 두고, 병합 정보만 리스트 속성으로 얹는다.
    spans 원소는 [row, col, row_span, col_span](병합 시작 칸 기준, 1 초과인 것만).
    importers._import_hwp_via_ir 가 layout["table_spans"] 로 옮겨 저장한다.
    """

    spans: list[list[int]]
    pictures: list[Any]

    def __init__(
        self, rows: list[list[str]], spans: list[list[int]] | None = None, pictures: list[Any] | None = None
    ) -> None:
        super().__init__(rows)
        self.spans = list(spans or [])
        # Picture blocks found in cells; the string grid cannot hold them, so the
        # stream emits them as images right after the table.
        self.pictures = list(pictures or [])


def _table_rows(block: Any) -> list[list[str]]:
    """TableBlock → 2차원 문자열(가능하면 cells, 없으면 text 파싱). 병합 셀은 TableGrid.spans."""
    cells = getattr(block, "cells", None)
    rows = getattr(block, "rows", None)
    cols = getattr(block, "cols", None)
    if cells and rows and cols:
        try:
            grid = [["" for _ in range(int(cols))] for _ in range(int(rows))]
            spans: list[list[int]] = []
            pictures: list[Any] = []
            for c in cells:
                pictures.extend(_cell_pictures(getattr(c, "blocks", []) or []))
                r = int(getattr(c, "row", 0) or 0)
                col = int(getattr(c, "col", 0) or 0)
                if 0 <= r < len(grid) and 0 <= col < len(grid[0]):
                    cell_text = _cell_blocks_text(getattr(c, "blocks", []) or [])
                    grid[r][col] = (cell_text or getattr(c, "text", "") or "").strip()
                    # 병합 셀(row_span/col_span)을 기록한다. 원본 4×5 보기 표가 20칸으로
                    # 풀려 나가던 문제를 writer 의 cellSpan 방출로 되돌리기 위한 정보.
                    row_span = min(int(getattr(c, "row_span", 1) or 1), len(grid) - r)
                    col_span = min(int(getattr(c, "col_span", 1) or 1), len(grid[0]) - col)
                    if row_span > 1 or col_span > 1:
                        spans.append([r, col, row_span, col_span])
            if any(any(cell for cell in row) for row in grid) or pictures:
                return TableGrid(grid, spans, pictures)
        except Exception:
            pass
    text = getattr(block, "text", "") or ""
    lines = [line for line in text.split("\n") if line.strip()]
    return [[part.strip() for part in line.split("\t")] for line in lines] if lines else []


def _table_text(rows: list[list[str]]) -> str:
    return "\n".join(" ".join(str(cell or "") for cell in row) for row in rows).strip()


def _looks_like_masthead_table(rows: list[list[str]]) -> bool:
    """시험지 상단 제목/쪽번호 표를 첫 문항의 자료 표로 오인하지 않게 거른다."""
    text = _table_text(rows)
    if not text:
        return True
    has_exam_title = any(token in text for token in ("학년도", "모의고사", "모의평가", "수능"))
    has_area = any(token in text for token in ("수학영역", "수학 영역", "국어영역", "영어영역"))
    return has_exam_title and has_area


def hwp_to_paragraphs(payload: bytes, filename: str, save_image: SaveImage) -> list[ParaBlock] | None:
    """원본 HWP 바이트 → (text, images, tables) 문단 리스트. 실패 시 None(→ 레거시).

    수식은 EQN 스크립트를 `$...$` 로 인라인 삽입, 이미지는 위치 순서대로 별도 블록,
    표는 tables 블록으로. 반환 리스트는 importers._paragraphs_to_chunks 에 그대로 넘긴다.
    """
    if not available():
        return None
    try:
        doc = rhwp.parse_bytes(payload) if hasattr(rhwp, "parse_bytes") else None
        if doc is None:
            # parse 는 경로를 받는 구현이 많아 임시파일 경유
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
                tmp.write(payload)
                tmp_path = tmp.name
            try:
                doc = rhwp.parse(tmp_path)
                ir = doc.to_ir()
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            ir = doc.to_ir()
    except Exception:
        return None

    body = getattr(ir, "body", None)
    if not body:
        return None

    # 1) 문단 텍스트 + 수식(문단별 char offset) 사전 구축
    para_text: dict[tuple[int, int], str] = {}
    para_order: list[tuple[int, int]] = []
    formulas_by_para: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)

    for block in body:
        kind = str(getattr(block, "kind", "") or "")
        sec, pidx, ch = _prov(block)
        key = (sec, pidx)
        if kind in ("paragraph", "list_item"):
            if key not in para_text:
                para_text[key] = getattr(block, "text", "") or ""
                para_order.append(key)
        elif kind == "formula":
            formulas_by_para[key].append((ch if ch is not None else 0, getattr(block, "script", "") or ""))

    # 2) 블록을 문서 순서대로 순회하며 (text, images, tables) 문단 방출
    out: list[ParaBlock] = []
    seen_para: set[tuple[int, int]] = set()
    img_seq = 0
    stem_name = filename.rsplit(".", 1)[0] if "." in filename else filename

    for block in body:
        kind = str(getattr(block, "kind", "") or "")
        sec, pidx, _ = _prov(block)
        key = (sec, pidx)
        if kind in ("paragraph", "list_item"):
            if key in seen_para:
                continue
            seen_para.add(key)
            text = _splice_formulas(para_text.get(key, ""), formulas_by_para.get(key, []))
            if text.strip():
                out.append((text, [], []))
        elif kind == "picture":
            try:
                blob = doc.bytes_for_image(block)
            except Exception:
                blob = None
            if blob:
                img_seq += 1
                rel = save_image(f"{stem_name}_img{img_seq}.png", bytes(blob))
                if rel:
                    out.append(("", [rel], []))
        elif kind == "table":
            rows = _table_rows(block)
            if rows:
                out.append(("", [], [rows]))
        # formula 블록은 문단에 splice 되었으므로 건너뛴다

    return out or None


def _ordered_stream(payload: bytes, filename: str, save_image: SaveImage):
    """to_ir 블록을 문서 순서대로 (kind, value) 스트림으로. kind∈{text,image,table}.

    반환: (list[(kind, value)], ok). 실패 시 (None, False).
    """
    if not available():
        return None
    try:
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        try:
            doc = rhwp.parse(tmp_path)
            ir = doc.to_ir()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        return None

    body = getattr(ir, "body", None)
    if not body:
        return None

    para_text: dict[tuple[int, int], str] = {}
    formulas_by_para: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
    for block in body:
        kind = str(getattr(block, "kind", "") or "")
        sec, pidx, ch = _prov(block)
        key = (sec, pidx)
        if kind in ("paragraph", "list_item"):
            para_text.setdefault(key, getattr(block, "text", "") or "")
        elif kind == "formula":
            formulas_by_para[key].append((ch if ch is not None else 0, getattr(block, "script", "") or ""))

    stem_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    stream: list[tuple[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    img_seq = 0
    # Endnotes go just before the paragraph holding their mark: in exam files
    # that mark (문3）) is the visible question number.
    notes_by_anchor: dict[tuple[int, int], list[tuple[str, list[str]]]] = defaultdict(list)
    for anchor, note in _endnote_lines(ir):
        notes_by_anchor[anchor].append(note)
    for block in body:
        kind = str(getattr(block, "kind", "") or "")
        sec, pidx, _ = _prov(block)
        key = (sec, pidx)
        if kind in ("paragraph", "list_item"):
            if key in seen:
                continue
            seen.add(key)
            stream.extend(("endnote", note) for note in notes_by_anchor.pop(key, []))
            text = _splice_formulas(para_text.get(key, ""), formulas_by_para.get(key, []))
            stream.append(("text", text))
        elif kind == "picture":
            try:
                blob = doc.bytes_for_image(block)
            except Exception:
                blob = None
            if blob:
                img_seq += 1
                rel = save_image(f"{stem_name}_img{img_seq}.png", _downscale_image(bytes(blob)))
                if rel:
                    stream.append(("image", rel))
        elif kind == "table":
            rows = _table_rows(block)
            if rows and any(any(str(cell).strip() for cell in row) for row in rows):
                stream.append(("table", rows))
            for picture in getattr(rows, "pictures", None) or []:
                try:
                    blob = doc.bytes_for_image(picture)
                except Exception:
                    blob = None
                if blob:
                    img_seq += 1
                    rel = save_image(f"{stem_name}_img{img_seq}.png", _downscale_image(bytes(blob)))
                    if rel:
                        stream.append(("image", rel))
    for notes in notes_by_anchor.values():
        stream.extend(("endnote", note) for note in notes)
    return stream


def _endnote_lines(ir: Any) -> list[tuple[tuple[int, int], tuple[str, list[str]]]]:
    """``(anchor paragraph, (number, text lines))`` per endnote.

    Formulas are spliced into the lines as ``$script$``.

    rhwp keeps endnotes in ``furniture.endnotes``. Each note's formula block
    follows its paragraph and gives a character offset into that paragraph.
    The note mark itself (``문3）``) is an auto number and is not in the text.
    """
    furniture = getattr(ir, "furniture", None)
    notes = getattr(furniture, "endnotes", None) or []
    result: list[tuple[tuple[int, int], tuple[str, list[str]]]] = []
    for note in notes:
        lines: list[tuple[str, list[tuple[int, str]]]] = []
        for block in getattr(note, "blocks", None) or []:
            kind = str(getattr(block, "kind", "") or "")
            if kind in ("paragraph", "list_item"):
                lines.append((getattr(block, "text", "") or "", []))
            elif kind == "formula" and lines:
                _, _, offset = _prov(block)
                lines[-1][1].append((offset if offset is not None else len(lines[-1][0]), getattr(block, "script", "") or ""))
            elif kind == "table":
                rows = _table_rows(block)
                if rows:
                    lines.append((_table_text(rows), []))
        number = getattr(note, "number", None)
        marker = getattr(note, "marker_prov", None)
        anchor = (
            (int(getattr(marker, "section_idx", 0) or 0), int(getattr(marker, "para_idx", 0) or 0))
            if marker is not None
            else _prov(note)[:2]
        )
        result.append(
            (
                anchor,
                (str(number) if number is not None else "", [_splice_formulas(text, formulas) for text, formulas in lines]),
            )
        )
    return result


def _looks_like_choices(text: str) -> bool:
    stripped = (text or "").lstrip()
    return bool(stripped) and stripped[0] in _CIRCLED and sum(stripped.count(c) for c in _CIRCLED) >= 2


def _looks_like_answer_section_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    compact = re.sub(r"\s+", "", stripped)
    return (
        bool(_ANSWER_SECTION_TEXT_RE.match(stripped))
        or stripped.count("[\uc815\ub2f5]") >= 3
        or "\ube60\ub978\uc815\ub2f5" in compact
        or compact.endswith("(\ud574\uc124)")
        or compact in {"\ud574\uc124", "\ud480\uc774"}
    )


def _looks_like_answer_section_table(rows: list[list[str]]) -> bool:
    text = " ".join(str(cell or "") for row in rows for cell in row)
    return _looks_like_answer_section_text(text)


def _marker_parts(unit: str) -> tuple[str, int, int] | None:
    match = _MARKER_DETAIL_RE.match(str(unit or "").strip())
    if not match:
        return None
    raw_number = match.group("number")
    return match.group("section").strip(), int(raw_number), len(raw_number)


def _replace_marker_number(unit: str, number: int, width: int) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"{match.group('head')}{number:0{width}d}{match.group('tail')}"

    return re.sub(
        r"(?P<head>^\s*\[\d{1,2}\s*점\]\s*\[.*?)(?P<number>\d{1,3})"
        r"(?P<tail>\s*(?:번)?\]\s*$)",
        repl,
        str(unit or ""),
        count=1,
    )


def _repair_problem_marker_sequence(problems: list[dict[str, Any]]) -> None:
    """Repair one-off duplicate/missing marker typos inside a consecutive exam section."""
    start = 0
    while start < len(problems):
        parts = _marker_parts(str(problems[start].get("unit") or ""))
        if parts is None:
            start += 1
            continue
        section = parts[0]
        end = start + 1
        entries: list[tuple[int, int, int]] = [(start, parts[1], parts[2])]
        while end < len(problems):
            next_parts = _marker_parts(str(problems[end].get("unit") or ""))
            if next_parts is None or next_parts[0] != section:
                break
            entries.append((end, next_parts[1], next_parts[2]))
            end += 1

        numbers = [number for _, number, _ in entries]
        if len(numbers) >= 3:
            expected = list(range(numbers[0], numbers[0] + len(numbers)))
            missing = [number for number in expected if number not in numbers]
            duplicate_numbers = [number for number in set(numbers) if numbers.count(number) > 1]
            if len(missing) == 1 and len(duplicate_numbers) == 1:
                target = missing[0]
                for offset, (problem_index, number, width) in enumerate(entries):
                    expected_here = expected[offset]
                    if number == duplicate_numbers[0] and expected_here == target:
                        problems[problem_index]["number"] = str(target)
                        problems[problem_index]["unit"] = _replace_marker_number(
                            str(problems[problem_index].get("unit") or ""),
                            target,
                            width,
                        )
                        break
        start = end


def _problems_from_trailing_source_stream(
    stream: list[tuple[str, Any]],
    *,
    split_choices: Callable[[str], tuple[str, list[str]]],
    split_stem_choices: Callable[[str], tuple[str, list[str]]] | None,
) -> list[dict[str, Any]] | None:
    """후행 ``[... N번]`` 편집본을 문항 단위로 묶는다.

    개인/학교 편집본에는 점수가 본문 끝에 있고, 선지 뒤의 출처 문단이 문항을 닫은 뒤
    ``[출제의도]``가 따라오는 변형이 있다. 결합 마커 경로와 순서가 반대이므로 별도
    상태기계로 처리한다. 출처 마커가 확인된 문항만 확정해 뒤쪽 정답·해설이 새 문항으로
    섞이지 않게 한다.
    """
    problems: list[dict[str, Any]] = []
    text_parts: list[str] = []
    images: list[str] = []
    tables: list[list[list[str]]] = []

    def reset() -> None:
        text_parts.clear()
        images.clear()
        tables.clear()

    def flush(marker_text: str, marker: re.Match[str]) -> None:
        raw_text = "\n".join(part for part in text_parts if part.strip()).strip()
        score_match = _INLINE_SCORE_RE.search(raw_text)
        score = score_match.group("score") if score_match else ""
        body = _INLINE_SCORE_RE.sub("", raw_text, count=1).strip()

        if split_stem_choices is not None:
            stem, choices = split_stem_choices(body)
        else:
            stem, choices = split_choices(body)
        if not choices:
            remainder, inline_choices = split_choices(body)
            if inline_choices:
                stem, choices = remainder, inline_choices

        inner_source = marker_text.strip()[1:-1].strip()
        unit = f"[{score}점][{inner_source}]" if score else marker_text.strip()
        if stem or choices or images or tables:
            problems.append(
                {
                    "number": str(int(marker.group("number"))),
                    "unit": unit,
                    "score": score,
                    "source_marker": marker_text.strip(),
                    "intent": "",
                    "marker_style": "trailing_source",
                    "stem": stem,
                    "choices": choices[:5],
                    "image_paths": list(images),
                    "tables": list(tables),
                }
            )
        reset()

    for kind, value in stream:
        if kind == "image":
            images.append(value)
            continue
        if kind == "table":
            if _looks_like_answer_section_table(value):
                break
            if not text_parts and not images and _looks_like_masthead_table(value):
                continue
            tables.append(value)
            continue

        text = str(value or "").strip()
        if not text:
            continue
        if _looks_like_answer_section_text(text):
            break

        intent_match = _INTENT_RE.match(text)
        if intent_match and problems and not text_parts and not images and not tables:
            problems[-1]["intent"] = intent_match.group("intent").strip()
            continue

        marker = _trailing_source_match(text)
        if marker:
            flush(text, marker)
            continue

        text_parts.append(text)

    return problems or None


def _problems_from_answer_endnotes(
    stream: list[tuple[str, Any]],
    note_fields: Callable[[list[str]], tuple[str, str]],
) -> list[dict[str, Any]] | None:
    """Split questions at answer endnotes (numbered 1..N, >=80% with answers).

    Exam files from education offices draw each question number with the
    endnote mark and keep the answer/explanation in the note, so the body has
    no number text to chunk on. Mirrors the HWPX endnote split in importers.
    """
    positions = [index for index, (kind, _) in enumerate(stream) if kind == "endnote"]
    if len(positions) < 2:
        return None
    notes = [stream[index][1] for index in positions]
    if [number for number, _ in notes] != [str(index) for index in range(1, len(notes) + 1)]:
        return None
    fields = [note_fields(lines) for _, lines in notes]
    if sum(bool(answer) for answer, _ in fields) < len(fields) * 0.8:
        return None
    problems: list[dict[str, Any]] = []
    for order, start in enumerate(positions):
        end = positions[order + 1] if order + 1 < len(positions) else len(stream)
        segment = stream[start + 1 : end]
        if order == 0:
            segment = stream[:start] + segment
        texts: list[str] = []
        images: list[str] = []
        tables: list[list[list[str]]] = []
        for kind, value in segment:
            if kind == "text" and str(value).strip():
                if _looks_like_answer_section_text(str(value)):
                    break
                texts.append(str(value))
            elif kind == "image":
                images.append(value)
            elif kind == "table":
                if _looks_like_answer_section_table(value):
                    break
                tables.append(value)
        if not texts and not images and not tables:
            return None
        answer, explanation = fields[order]
        problems.append(
            {
                "number": notes[order][0],
                "stem": "\n".join(texts).strip(),
                "choices": [],
                "image_paths": images,
                "tables": tables,
                "answer": answer,
                "explanation": explanation,
            }
        )
    return problems


def hwp_to_problems(
    payload: bytes,
    filename: str,
    save_image: SaveImage,
    split_choices: Callable[[str], tuple[str, list[str]]],
    chunk_paragraphs: Callable[[list[ParaBlock]], list[dict[str, Any]]] | None = None,
    split_stem_choices: Callable[[str], tuple[str, list[str]]] | None = None,
    endnotes_out: list[tuple[str, list[str]]] | None = None,
    note_fields: Callable[[list[str]], tuple[str, str]] | None = None,
) -> list[dict[str, Any]] | None:
    """원본 HWP → 편집형 문항 dict 리스트. 실패 시 None(→ 레거시).

    to_ir 의 구조를 직접 그룹핑한다. 두 가지 과목 포맷을 다룬다:
    - 수학/과학 편집본: [stem...][마커 "[N점][...NN]"][선지][빈줄]* → 마커 기반 그룹핑.
    - 국어/영어: 선두 번호("1.") + 공유 지문([1~3]) → 마커가 없으므로 기존 문단-청킹
      (chunk_paragraphs = importers._paragraphs_to_chunks) 로 폴백.
    split_choices 는 인라인 원문자 선지 분리 콜백(importers._split_inline_circled_choices).
    """
    stream = _ordered_stream(payload, filename, save_image)
    if not stream:
        return None
    # Endnotes (answer/explanation in exam files) are not body content.
    notes = [value for kind, value in stream if kind == "endnote"]
    noted_stream = stream
    stream = [(kind, value) for kind, value in stream if kind != "endnote"]
    if endnotes_out is not None:
        endnotes_out.extend(notes)

    has_trailing_source_markers = any(
        kind == "text" and _trailing_source_match(str(val).strip())
        for kind, val in stream
    )
    if has_trailing_source_markers:
        trailing = _problems_from_trailing_source_stream(
            stream,
            split_choices=split_choices,
            split_stem_choices=split_stem_choices,
        )
        if trailing:
            _repair_problem_marker_sequence(trailing)
            return trailing

    has_markers = any(kind == "text" and _MARKER_RE.match(str(val).strip()) for kind, val in stream)
    if not has_markers and note_fields is not None:
        noted = _problems_from_answer_endnotes(noted_stream, note_fields)
        if noted:
            return noted
    if not has_markers and chunk_paragraphs is not None:
        # 국어/영어 등 트레일러 마커가 없는 포맷 → (text,images,tables) 문단으로 기존 청킹.
        blocks: list[ParaBlock] = []
        for kind, val in stream:
            if kind == "text":
                for line in str(val).split("\n"):
                    blocks.append((line, [], []))
            elif kind == "image":
                blocks.append(("", [val], []))
            elif kind == "table":
                blocks.append(("", [], [val]))
        chunks = chunk_paragraphs(blocks)
        if len(chunks) <= 1:
            return None  # 청킹도 못 나눔 → 레거시로
        out_probs: list[dict[str, Any]] = []
        for c in chunks:
            raw = c.get("text", "")
            text = (raw if isinstance(raw, str) else "\n".join(raw)).strip()
            text, trailing_passage, trailing_label = _extract_trailing_passage(text)
            # 공유 지문이 문두에 붙어 있으면 독립 블록으로 분리(원본 레이아웃과 편집성 둘 다 개선).
            passage, question, label = _extract_leading_passage(text)
            if passage:
                out_probs.append(
                    {
                        "number": label,
                        "stem": passage,
                        "choices": [],
                        "image_paths": [],
                        "tables": [],
                        "is_passage": True,
                    }
                )
                text = question
            if text or c.get("images") or c.get("tables"):
                out_probs.append(
                    {
                        "number": str(c.get("number_hint") or ""),
                        "stem": text,
                        "choices": [],  # 선지 분리는 importers._import_hwp_via_ir 에서 수행
                        "image_paths": c.get("images", []),
                        "tables": c.get("tables", []),
                    }
                )
            if trailing_passage:
                out_probs.append(
                    {
                        "number": trailing_label,
                        "stem": trailing_passage,
                        "choices": [],
                        "image_paths": [],
                        "tables": [],
                        "is_passage": True,
                    }
                )
        return out_probs or None

    problems: list[dict[str, Any]] = []
    stem_parts: list[str] = []
    images: list[str] = []
    tables: list[list[list[str]]] = []
    number = ""
    marker_text = ""
    marker_seen = False
    choice_parts: list[str] = []
    pending_choices: list[str] = []

    def split_choice_text(text: str) -> tuple[str, list[str]]:
        if split_stem_choices is not None:
            return split_stem_choices(text)
        _, choices = split_choices(text.strip())
        return "", choices

    def flush(choices: list[str] | None = None) -> None:
        nonlocal stem_parts, images, tables, number, marker_text, marker_seen, choice_parts, pending_choices
        final_choices = choices if choices is not None else pending_choices
        if not final_choices and choice_parts:
            _, parsed_choices = split_choice_text("\n".join(choice_parts))
            final_choices = parsed_choices[:5]
        stem = "\n".join(s for s in stem_parts if s.strip()).strip()
        if stem or images or tables or final_choices:
            problems.append(
                {
                    "number": number,
                    "unit": marker_text,
                    "stem": stem,
                    "choices": final_choices or [],
                    "image_paths": list(images),
                    "tables": list(tables),
                }
            )
        stem_parts, images, tables, number, marker_text, marker_seen, choice_parts, pending_choices = (
            [],
            [],
            [],
            "",
            "",
            False,
            [],
            [],
        )

    for kind, value in stream:
        if kind == "image":
            images.append(value)
            continue
        if kind == "table":
            if _looks_like_answer_section_table(value):
                if marker_seen:
                    flush()
                break
            if not marker_seen and not stem_parts and not images and _looks_like_masthead_table(value):
                continue
            tables.append(value)
            continue
        text = str(value or "")
        if not text.strip():
            continue
        if _looks_like_answer_section_text(text):
            if marker_seen:
                flush()
            break
        marker = _MARKER_RE.match(text.strip())
        if marker:
            if marker_seen:
                flush()
            number = marker.group(2).lstrip("0") or marker.group(2)
            marker_text = text.strip()
            marker_seen = True
            continue

        if marker_seen and (any(char in text for char in _CIRCLED) or (choice_parts and not pending_choices)):
            choice_parts.append(text)
            remainder, choices = split_choice_text("\n".join(choice_parts))
            if remainder.strip() and not pending_choices:
                stem_parts.append(remainder.strip())
            if len(choices) >= 5:
                pending_choices = choices[:5]
            continue
        if marker_seen:
            # 마커 뒤인데 선지가 아님 → 이전 문항(선지 없음) 확정하고 새 stem 시작
            flush()
        stem_parts.append(text)
    flush()

    if problems:
        _repair_problem_marker_sequence(problems)
    return problems or None
