**점수: 62/100**

수정 의도(본문 소실 40%→0.35%)는 맞고 편집형 변환 경로는 안전합니다. 하류 코드를 읽어 보니 라이브러리 가져오기 → 저장 → 간단 변환 폴백 경로가 새 산출을 감당하지 못하는 곳이 있습니다. 주된 원인은 두 가지입니다. 하나는 상자 안 글이 이제 `stem`에 들어오는데 선지 분리기는 그것이 상자 글인지 모르는 것입니다. 다른 하나는 지문 사본이 문항마다 붙는데 그것을 하류에서 걸러 주는 곳이 없는 것입니다. 이번 변경으로 새로 드러난 결함은 아래 1·4·5번이고, 나머지는 기존 구조가 새 산출 규모에서 문제가 되는 경우입니다.

모든 지적은 코드를 읽어서 확인한 것입니다. 실제 시험지로 재현한 것은 없습니다. 판단이 갈리는 곳은 '추정'이나 '미확인'으로 표시했습니다.

확인해서 문제가 없었던 것은 아래와 같습니다.
- 편집형 작성기(`pdf_native_content.py`)는 `problem.text`, `figure_pngs`, `figure_boxes`를 읽지 않습니다.
- `render=False`의 영향을 받는 소비자는 `pdf_layout_writer.py:10356` 이후의 도달 불가 블록뿐입니다.
- `text_reliable`은 렌더와 무관하게 계산됩니다(`pipeline.py:509`).
- 작성기와 검수가 인식 결과 객체를 공유해도 작성기가 그 객체를 고치는 곳은 없었습니다(대입·정렬 grep으로 확인).

---

## 치명

### 1. 상자 안 글이 선지로 오인되어 선지에 섞이고 본문에서 사라진다
**위치**: `importers.py:1962-1981`(`_split_stem_and_choices`), `importers.py:802-824`(`_choice_line_body`), `importers.py:744-760`(`_split_inline_numeric_choices`), 호출부 `importers.py:416-417`

```python
if number is None:
    return match.group("body").strip()   # importers.py:817-818
...
matches = list(INLINE_NUMERIC_CHOICE_RE.finditer(line))   # importers.py:745
if labels[:3] != [1, 2, 3] ...
```

**문제**: 이전에는 테두리 상자 안 줄이 통째로 버려졌기 때문에 선지 분리기가 상자 글을 볼 일이 없었습니다. 이제 상자 글이 `text`에서 발문과 선지 사이에 들어옵니다. 분리기는 줄 위치와 무관하게 아래 줄을 선지로 취급합니다.
- ①~⑨, `A.`, `a)`처럼 숫자가 아닌 라벨로 시작하는 줄은 선지 시작 여부와 상관없이 무조건 선지입니다(`importers.py:817-818`, 정규식 `importers.py:62-64`).
- `1 2 3 4`처럼 숫자가 줄 안에 나란히 있고 1·2·3으로 시작하는 줄도 인라인 선지로 쪼개집니다(`importers.py:744-760`). 이번 한계 목록의 "가로선만 있는 표는 글만 본문에 남는다"가 정확히 이 입력입니다. 가로선만 있는 도수분포표나 확률분포표의 숫자 행이 선지가 됩니다.

선지 개수가 5를 넘고, 표나 보기의 글이 `stem`에서 빠집니다. 기하 분리기(`importers.py:1582-1673`)도 같은 영향을 받습니다. 라벨 줄을 `used`에 넣어 `stem`에서 빼기 때문입니다(`importers.py:1617`, `1667-1671`).

**근거**: 영어는 `_english_embedded_choice_markers`(`importers.py:1690`)로 막아 두었지만 영어 밖에는 같은 방어가 없습니다. 영어 외 과목의 `_split_stem_and_choices` 호출(`importers.py:416`)에는 상자 여부 정보가 전달되지 않습니다.
- 확인: 코드 경로.
- 미확인: 실제 시험지에서 몇 문항이 걸리는지.

**고친 코드(최소, 약 8줄)**: 인식 단계에서 상자 안 줄에 표시를 달고, 분리기가 그 줄은 선지 검사를 건너뜁니다.
```python
# pdf_segment.py ~1429, 줄을 본문에 남기는 분기 (모든 크롭되지 않은 figure 안 줄)
boxed = _line_inside_figure(line, figures, desc["box"])   # 크롭 대상 아닌 상자 포함
# 해당 블록 metadata 와 pipeline._problem_line_geometries(pipeline.py:152) 가 "boxed": True 를 line geometry 에 실어 보낸다
```
```python
# importers.py: 분기 호출 전에
boxed = {str(g.get("text") or "").strip() for g in pdf_line_geometries
         if isinstance(g, dict) and g.get("boxed")}
stem_text, choices = _split_stem_and_choices(source_text, protect=boxed)

# _split_stem_and_choices(text, protect=frozenset()) 루프 맨 앞에
if line in protect:
    stem_lines.append(raw_line.rstrip()); continue
```
`_split_stem_and_choices` 호출처가 여러 곳(`importers.py:2043` 등)이므로 `protect`는 기본값을 두고 PDF 경로에서만 넘깁니다. 나머지 호출처는 바뀌지 않습니다.

**임시 방어(표시 없이 2줄)**: 영어 밖에서 `len(choices) > 5`이면 앞쪽 초과분을 `stem`으로 되돌립니다. 라벨은 잃지만 글은 보존됩니다.

---

## 중요

### 2. 같은 PDF를 다시 가져오면 중복 문항이 생긴다(재변환 멱등이 깨짐)
**위치**: `storage.py:249-264`(`_content_hash`), `storage.py:267-285`(`_matching_duplicate_row`), `importers.py:463`

```python
parts = [str(normalized_data.get("stem") or "")]
...
"SELECT * FROM problems WHERE source_name = ? AND content_hash IN (?, ?) ..."
```

**문제**: 해시는 `stem + choices + answer + 이미지`로 만듭니다. 이번 변경으로 같은 PDF의 `stem`이 길어졌습니다(상자 글과 지문이 붙음). 이전 버전으로 가져온 문항은 다른 해시이므로 `existing`으로 인식되지 않고 새 행이 만들어집니다. 라이브러리에 같은 출처의 문항이 두 벌 생깁니다.

**근거**: 확인: 코드 경로. `_matching_duplicate_row`는 해시 일치(또는 소문자 정규화한 옛 해시와 같은 내용)만 중복으로 봅니다.

**고친 코드(약 6줄)**: 인식기 버전을 `layout`에 심고, 같은 출처에 낮은 버전의 행이 있으면 알려 줍니다.
```python
# layout_payload(importers.py:328) 에
"recognizer_version": 2,
# 가져오기 끝(importers.py:500 직전)
older = [p for p in storage.list_problems_by_source(filename)   # 신규 헬퍼 또는 기존 조회
         if int((p.get("layout") or {}).get("recognizer_version") or 1) < 2]
if older:
    notices.append(f"이전 인식 결과 {len(older)}개가 있습니다. 새 결과와 중복될 수 있으니 이전 문항을 정리해 주세요.")
```
자동 삭제는 하지 않고 알림까지만 합니다. 사용자의 편집이 들어간 행이 있을 수 있습니다.

### 3. 지문 사본이 문항마다 붙어 DB·응답·AI 호출·전체 내보내기가 부풀고 지문이 반복 출력된다
**위치**: `importers.py:344-352`, `importers.py:461-463`, `storage.py:312-323`(`_json_object`, 크기 제한 없음), `main.py:270-286`(`_export_problems`의 basic 분기), `hwpx_writer_v2.py:1987`

```python
"pdf_lines": [*shared_passage_lines, *pdf_lines],           # importers.py:344
stem_text = f"{shared_passage_text}\n{stem_text}".strip()   # importers.py:463
if payload.workspace == "basic":
    return problems                                          # main.py:284
```

**문제**: 국어 한 책자에서 112문항 중 106문항이 지문 전체와 그 줄별 좌표를 각자 사본으로 갖습니다. 줄 좌표에는 글자별 좌표와 폰트 정보(`pdf_line_chars`, `pdf_line_spans`)가 들어 있습니다(`pdf_segment.py:377-380`, `962`). 같은 지문에 문항이 3~5개면 지문이 3~5벌 저장되고 `/api/import` 응답으로도 그만큼 나갑니다. 간단 변환의 폴백은 `workspace=basic`으로 전체 문항을 내보내는데(`app.js:4171-4177`), basic에는 번호 검증도 중복 제거도 없습니다(`main.py:284-285`). 폴백 HWPX에 같은 지문이 문항 수만큼 반복됩니다. 수식 AI를 쓰는 경우 문항마다 `stem`에 지문이 들어가므로 호출 비용도 늘어납니다(`ai_api.py:30`의 한도는 20만 자입니다).

**근거**: 확인: 코드 경로. `hwpx_writer_v2.py`에는 지문 중복 제거 로직이 없습니다. 같은 파일의 `passage` 관련 코드는 지문 라벨 처리뿐입니다. 영어는 이전에도 같은 구조였으나 지문이 짧아 눈에 띄지 않았습니다.
- 미확인: 실제 레이아웃 JSON 크기와 응답 크기(수치로 재지 않았습니다).

**고친 코드**:
```python
# (a) 저장량: 지문 줄 좌표에서 글자 상세를 뺀다. 지문 줄은 중첩 사본이므로 text+bbox 만 남긴다
shared_passage_lines = [{"text": l.get("text"), "bbox_px": l.get("bbox_px")}
                        for l in shared_passage_lines]            # importers.py:326 직후
```
```python
# (b) basic 내보내기: 같은 출처의 같은 지문 범위가 연속되면 2번째부터 지문을 뺀다
from .exam_numbering import _shared_number_marker
def _collapse_repeated_passage(problems):
    seen = None
    for p in problems:
        sp = (p.get("layout") or {}).get("shared_passage")
        key = (p.get("source_name"), tuple(sp["range"])) if sp else None
        if key and key == seen and (m := _shared_number_marker(p)):
            p["stem"] = p["stem"][m[0].start():]
        seen = key
    return problems
# main.py:284
if payload.workspace == "basic":
    return _collapse_repeated_passage(problems)
```
(b)는 첫 사본의 지문만 남기므로 라이브러리에서 문항을 개별로 꺼내 쓰는 경우에는 영향이 없습니다(그 경우 선택이 연속이 아님).

### 4. 이미지로 잘린 표·삽화 안의 글이 편집 불가라는 사실이 사용자에게 전달되지 않는다
**위치**: `importers.py:320-353`(`layout_payload`), `importers.py:370-373`, `app.js:1414-1425`(`recognitionModel`의 `parts`와 `issues`), `app.js:1372`

**문제**: `figure_is_crop_candidate`가 글자 많은 표·삽화도 이미지로 자르게 바꿨습니다. 그 안의 글은 `stem`에서 빠지고 이미지로만 남습니다. 그런데 `layout`에는 "이 문항에 글자가 이미지로 보존된 영역이 몇 개"라는 정보가 없습니다. UI는 `이미지 N개`만 표시하고 `issues`에는 이 상태를 넣지 않습니다. 교사는 본문이 완전하다고 읽습니다. 표 안의 글을 고치려다 처음 알게 됩니다. 이번 변경이 늘린 상태이므로 새 결함입니다.

**근거**: 확인: `layout_payload`에는 `figure_boxes`와 `figure_pngs` 개수가 없습니다. `recognitionModel`의 `issues`는 본문 없음·정답 미입력·좌표 없음·깨진 글자만 다룹니다.

**고친 코드(약 5줄)**:
```python
# layout_payload 에
"image_text_regions": len(getattr(prob, "figure_pngs", []) or []),
```
```js
// app.js:1425 근처
if (Number(layout.image_text_regions) > 0) issues.push(`표·그림 ${layout.image_text_regions}개는 이미지로 보존됨(안의 글자는 편집 불가)`);
```
수식 `parts`의 이미지 항목 `detail`에도 같은 문구를 쓰면 `이미지 N개 첨부 또는 보존`보다 정확해집니다(`app.js:1417`).

### 5. 지문 줄이 두 쪽의 좌표를 한 목록에 섞어 인식 계층 오버레이가 어긋난다
**위치**: `pipeline.py:462-468`(선두 줄 이어 붙이기), `pipeline.py:597`, `importers.py:344-352`, `app.js:1462-1468`

```python
open_passage["line_geometries"] = [*open_passage["line_geometries"], *leading["line_geometries"]]
problem.shared_passage_line_geometries.extend(passage.get("line_geometries") or [])
```

**문제**: 앞 쪽(P) 끝에서 시작한 지문의 줄은 P쪽 좌표이고, 이어 붙은 선두 줄은 문항이 있는 P+1쪽 좌표입니다. 한 목록으로 `layout.pdf_lines`에 들어가는데 줄마다 쪽 번호가 없고 `shared_passage.source_page`는 하나(P)뿐입니다. `app.js`는 문항이 있는 쪽 크기로 전부 그리므로 P쪽 줄이 엉뚱한 위치에 그려집니다. `pdf_lines`의 소비자는 `app.js`뿐이라(`importers.py` 외 grep 결과 없음) 데이터 오염은 아니고 표시 문제입니다.

**근거**: 확인: `pdf_lines` 소비자가 `app.js:1402` 한 곳뿐입니다. 영어는 이전에도 쪽을 넘는 지문이 같은 증상이었으나 국어는 지문이 쪽을 넘는 일이 훨씬 잦습니다.

**고친 코드(약 4줄)**:
```python
# pipeline.py: 합치기 전에 줄마다 쪽 번호를 단다
for g in leading["line_geometries"]: g.setdefault("page", page_index + 1)
for g in open_passage["line_geometries"]: g.setdefault("page", open_passage["page_number"])
```
```js
// app.js:1402 의 filter 에
if (line.page && Number(line.page) !== Number(page.number)) return false;
```

### 6. 번호 줄을 찾는 로직이 지문 안의 같은 번호 줄에 속는다
**위치**: `exam_numbering.py:26-29`, `exam_numbering.py:172-175`, `exam_templates.py:288`, `exam_templates.py:330-341`

```python
r"(?m)^[ \t]*(?:문제[ \t]*)?(?P<number>" + re.escape(number) + r")[ \t]*[.)]..."   # exam_numbering.py:28
for position in range(1, len(lines)):
    match = _STEM_NUMBER_RE.match(lines[position])
    if match and match.group(1) == label:     # exam_templates.py:336
```

**문제**: 두 곳 모두 지문 전체 안에서 자기 번호와 같은 번호로 시작하는 줄을 찾습니다. 지문에 `3.`이나 `3)`으로 시작하는 줄(번호 붙은 문단, 단계 목록)이 있고 문항 번호도 3이면 두 번 걸립니다.
- 순서 변경 모드: 번호 마커가 2개라 `_can_renumber_shared`가 False, 이어서 `ambiguous_shared_number` 422가 나고 전체 내보내기가 막힙니다(`exam_numbering.py:172-175`).
- 간단 템플릿: 지문 줄이 발문 제목으로 올라가고 진짜 발문은 본문이 됩니다(`exam_templates.py:336-341`).

이번 변경 전에는 영어에서만 가능했고, 이제 국어와 탐구에서 가능해졌습니다.

**근거**: 확인: 코드 경로. 실제 지문에 번호 줄이 얼마나 있는지는 미확인입니다.

**고친 코드(약 5줄)**: 가져오기 때 자기 번호 줄의 위치를 기록해 두고 두 곳이 그것만 봅니다.
```python
# importers.py:463 직후
passage_lines = len(shared_passage_text.splitlines())
# layout_payload 의 shared_passage 에 "own_line_start": passage_lines 추가 (importers.py:348)
```
```python
# exam_numbering._shared_number_marker 에서 시작 오프셋 이후 매치만 사용
start = sum(len(l) + 1 for l in stem.splitlines()[:layout["shared_passage"].get("own_line_start", 0)])
return [m for m in re.finditer(..., stem) if m.start() >= start]
```
`exam_templates.py:334`의 `range(1, len(lines))`도 같은 시작점부터 돌게 합니다(`prepared` 경로는 이미 `_numbering_prepared` 검증이 있으므로 영향 적음).

---

## 사소

### 7. 빠른 변환(`quality_check="fast"`)이 UI에서 선택되지 않고, 선택해도 "목표 미달"로 보인다
**위치**: `app.js:2767-2778`(요청 본문), `main.py:1140-1145`, `main.py:1196-1198`, `app.js:3887`, `app.js:3894`

**문제**: `exportPdfLayoutFiles`는 `quality_check`를 보내지 않으므로 서버 기본값 `"full"`이 항상 쓰입니다. 38~59% 단축은 API를 직접 호출하는 경우에만 적용됩니다. UI를 연결하면 또 하나가 걸립니다. `visual_sync_requires_human_review`가 항상 True이고(`main.py:1196-1198`), 점수가 목표보다 낮으면 "목표 미달 · 결과 검수가 필요합니다"(`app.js:3887`)가 붙습니다. 빠른 변환은 시각 대조가 없어 점수가 낮을 수 있습니다(`_pdf_layout_objective_score`가 `fidelity.skipped`를 어떻게 반영하는지는 미확인).

**고친 코드**:
```js
// app.js:2774 이후
if (els.simpleQualityFast?.checked) payload.quality_check = "fast";
// simpleQualityMessages 의 3887 앞에
const fast = quality.quality_check === "fast";
if (!brief && !fast && target != null && Number(score) < Number(target)) messages.push("목표 미달 · 결과 검수가 필요합니다");
```
체크박스 DOM 요소(`simpleQualityFast`)는 `index.html`에 따로 추가해야 합니다.

### 8. 수식 AI 체크박스가 아무 일도 하지 않는데 UI는 성공으로 안내한다
**위치**: `app.js:2775-2778`, `app.js:4182`, `main.py:1286-1287`, `pdf_layout_writer.py:10215-10217`

**문제**: UI는 체크가 켜지면 `math_ai_recognition=true`와 모델명을 보냅니다. 서버는 이를 무시하고 안내문을 `notices`의 맨 끝에 추가합니다. 토스트는 "편집형 HWPX를 만들었습니다"만 말합니다(`app.js:2798`). 서버는 `stats["math_ai_applied"]=False`를 돌려주지만 UI가 읽지 않습니다.

**고친 코드(2줄)**:
```js
// app.js:2796 전에
if (payload.math_ai_recognition && result.stats?.math_ai_applied === false) toast("수식 AI 인식은 편집형 변환에 아직 연결되어 있지 않아 기본 수식 복원으로 변환했습니다.");
```
근본적으로는 `els.simpleMathAi`를 PDF 편집형 변환에서 비활성화하는 편이 정직합니다.

### 9. 이어 붙는 선두 줄의 종료 조건이 "다음 마커·머리"뿐이다(추정)
**위치**: `pdf_segment.py:928-955`(`_page_leading_lines`), `pipeline.py:462-468`

**문제**: 앞 쪽에 열린 지문이 있으면 이 쪽의 첫 마커나 `[N~M]` 머리 앞의 모든 본문 줄(머리글 13% 아래)이 지문 뒤에 붙습니다. 쪽 상단에 지문이 아닌 안내문이나 저작권 문구, 다른 박스가 있으면 같이 붙을 수 있습니다. 문항이 없는 왼쪽 단 전체를 모으는 경로도 같은 조건입니다. 실물에서 발생하는지는 미확인입니다.

**고친 코드(약 3줄)**: 이어 붙이는 줄의 `bbox_px[0]`이 앞 쪽 지문 줄들의 좌우 범위 안인 것만 허용합니다.
```python
left = min(g["bbox_px"][0] for g in open_passage["line_geometries"])
leading_lines = [g for g in leading["line_geometries"] if g["bbox_px"][0] >= left - 20]
```

### 10. 2단 판정 변경으로 `column_count`가 바뀌는 쪽의 영향(영향 범위는 좁음)
**위치**: `layout_model.py:32-44`, `hwpx_writer_v2.py:1195-1200`, `exam_numbering.py:120-123`

**확인**: 좌표를 쓰는 하류는 `column_break_before`뿐이고, 같은 쪽 안에서 열 번호가 커질 때만 나눕니다. 오른쪽 단에만 문항이 있는 쪽은 열 번호가 1로 일정하므로 줄바꿈이 새로 생기지 않습니다. `exam_numbering`의 좌표 거부는 `block_type != "problem"`일 때만 걸리는데 지문이 붙은 문항은 자기 포함형이면 면제됩니다(`exam_numbering.py:120`의 `not self_contained_shared`). 따라서 이 변경은 큰 문제가 아닙니다. 다만 `source_layout_flow`(원본 좌표 보존) 문서에서 한 쪽이 갑자기 2단이 되는지는 미확인입니다.

---

## 본부가 가장 싸게 막을 수 있는 방어(우선순위)
1. 영어 밖 `len(choices) > 5`이면 초과분을 `stem`으로 되돌립니다(1번 임시 방어, 2줄).
2. basic 내보내기의 연속 같은-범위 지문 중복 제거(3번(b), 약 10줄).
3. `layout_payload`에 `recognizer_version`과 `image_text_regions`를 넣습니다(2번과 4번, 각 1줄).
4. 지문 줄 좌표에서 `pdf_line_chars`와 `pdf_line_spans`를 뺍니다(3번(a), 1줄).
5. `pipeline.py:462-468`에서 줄마다 쪽 번호를 답니다(5번, 2줄).

## 본부가 실물로 확인할 5가지
1. 국어 책자와 가로선만 있는 표가 있는 수학 책자를 `/api/import`로 가져와서 `len(choices) != 5`인 문항 수와, 그 `stem`에서 상자 안 글이 사라졌는지 확인합니다.
2. 같은 국어 PDF를 이전 빌드와 이 빌드로 순서대로 두 번 가져옵니다. 두 번째가 `existing`인지 `created`인지, 같은 출처 행 수가 2배가 되는지 봅니다.
3. `1)` 번호 형식 PDF(편집형 422 → 폴백)에서 basic 전체 내보내기를 합니다. 지문이 문항 수만큼 반복되는지와 HWPX 쪽 수를 봅니다.
4. 같은 책자에서 `/api/import` 응답 크기, 저장된 `layout_json` 합계, `/api/problems` 목록 응답 시간을 잽니다(3번의 미확인 해소).
5. 지문이 쪽을 넘는 국어 문항 1건의 `layout.pdf_lines`를 인식 계층 화면에서 열어 줄 상자가 제 위치에 그려지는지, `exam_numbering`의 순서 변경 모드(`sequential`)에서 `ambiguous_shared_number`가 나는 문항이 있는지 확인합니다.

=== 끝 ===
