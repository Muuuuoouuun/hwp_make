# 최종 점수 74/100 · 배포 보류

`50cd57c` → `d6bfcfc` 정적 감사에서 치명 3건, 중요 4건, 사소 1건을 확인했다. 빈 줄 하나로 정상 선지가 전부 본문으로 이동하고, 앞 시험지의 지문이 다음 유형에 붙으며, 중앙 세로선이 있는 1단 시험지에서 전폭 본문이 빠질 수 있다. 빠른 검수의 두 판정은 `None`으로 반환된다. 지문 좌표의 `page` 표기와 저장 필드 축소가 적용됐고, `owner.line_geometries.extend`가 다른 문항의 리스트를 변형하는 경로는 발견하지 못했다. 점수는 배포 감사 판단이며, 34항목의 실행 결과와 속도 효과는 **미확인**이다. [최종 커밋](https://github.com/Muuuuoouuun/hwp_make/commit/d6bfcfc20f19be48fa4dbe4437e94daff58b78ea) · [빠른 검수 응답](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/main.py#L1213-L1227) · [지문 좌표와 리스트 생성](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L502-L556) · [가져오기 저장 필드](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/importers.py#L320-L332)

## 치명

### 1. 빈 줄 또는 원문자 한 개가 정상 알파벳 선지를 없앤다

**위치** `app/importers.py:824` · `app/importers.py:2579` · `app/importers.py:3433`

```python
if label[0].isalpha() and any(other.lstrip()[:1] in CIRCLED_CHOICE_MARKERS for other in lines):
    # 원문자 선지(①~⑤)가 따로 있는 문항의 "a." "b." 줄은 <보기> 항목이지 선지가 아니다.
    return None
```

**깨지는 입력** `A.`~`E.` 선지 사이에 빈 줄 하나가 있는 문항. 빈 줄에서 `other.lstrip()[:1]`은 `""`이고, 파이썬에서 `"" in 문자열`은 참이므로 선지 5개가 모두 본문으로 이동한다. 빈 줄이 없어도 `A.`, `B.`, `③`, `D.`, `E.`처럼 라벨이 섞이면 알파벳 선지 4개가 빠진다. DOCX·텍스트 가져오기와 HWP의 본문에서 선지를 분리하는 경로가 같은 함수를 호출한다. [선지 판정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/importers.py#L808-L827) · [공용 파서와 호출부](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/importers.py#L2568-L2582) · [DOCX](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/importers.py#L2687) · [HWP](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/importers.py#L3425-L3435)

**수정안** 약 8~12줄. 공용 파서는 기존 선지 판정을 사용하고, PDF에서 `<보기>`의 글자 줄과 별도의 완전한 원문자 선지 묶음이 텍스트·좌표로 확인될 때만 `if line_index in confirmed_item_lines: return None`을 적용한다. 원문자 확인에는 `other.lstrip().startswith(tuple(CIRCLED_CHOICE_MARKERS))`를 쓴다.

**예상 효과·위험·검증** 예시에서 각각 5개와 4개의 선지를 복구한다. 좌표 근거를 좁히면 `<보기>` 머리가 없는 일부 PDF에서는 기존 과다 추출이 남을 수 있다. 합성 PDF로 혼합 라벨 5개와 `<보기>` 항목 두 줄＋원문자 선지 5개를 각각 검사한다. 빈 줄은 TXT·DOCX·HWP 공용 파서 입력에서도 검사한다. 현재 검사는 빈 줄 없는 알파벳 전용과 알파벳 항목＋완전한 원문자 묶음만 다룬다. [현재 검사](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/scripts/verify_recognition_content.py#L317-L325)

### 2. 번호 재시작 방어가 지문의 첫 연결에는 적용되지 않는다

**위치** `app/recognition/pipeline.py:568` · `app/recognition/pipeline.py:586`

```python
problem
for problem in result.problems
if problem.number == int(passage["start"])
and problem.page_number >= int(passage["page_number"])
```

**깨지는 입력** 홀수형 발췌가 11번과 `[12~13]` 지문에서 끝나고, 뒤에 짝수형 1~13번이 이어지는 PDF. 첫 대상 탐색이 짝수형 1~11번을 건너뛰어 짝수형 12번을 고른다. 이후 반복문에는 `12, 13`만 들어가므로 새 재시작 방어를 통과한다. 다음 쪽 선두 줄도 첫 문항의 번호를 확인하기 전에 열린 지문에 붙인다. [첫 대상과 범위 탐색](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L564-L602) · [쪽 선두 결합](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L451-L476)

**수정안** 약 12~18줄. 지문 머리의 쪽·단·세로 위치를 보존해 읽기 순서상 바로 다음 문항을 찾는다. `if first is None or first.number != passage["start"] or form_boundary: ...`에서 미연결 처리한다. 다음 쪽 선두 줄도 이 검증이 끝난 뒤 확정한다.

**예상 효과·위험·검증** 예시에서 짝수형 2문항의 잘못된 지문을 제거한다. 번호 없는 중간 쪽을 허용하려면 같은 유형의 지문이 이어진다는 증거가 필요하다. 합성 PDF에서 홀수형 고유 문구가 짝수형에 0번 나타나는지 확인하고, 짝수형 대신 다음 쪽에서 12번이 바로 이어지는 대조본에서는 정상 연결을 확인한다. 현재 검사는 앞 유형에 시작 문항 12번이 이미 있는 경우만 다룬다. [현재 검사](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/scripts/verify_recognition_content.py#L156-L167)

### 3. 같은 쪽에 범위 머리가 있으면 1단 보호 조건이 무력해진다

**위치** `app/recognition/pdf_segment.py:1338` · `app/recognition/pdf_segment.py:1348` · `app/recognition/pdf_segment.py:825`

```python
or ((bool(range_sides) or (subject != Subject.ENGLISH and not crosses_middle))
    and _english_has_column_divider(page, scale, float(width_px), float(height_px)))
```

**깨지는 입력** 문항과 `[12~13]` 머리가 모두 왼쪽에서 시작하는 1단 시험지에 긴 중앙 답안선이 있는 경우. 같은 쪽에 범위 머리가 하나라도 있으면 `bool(range_sides)`가 참이어서 `crosses_middle`이 참이어도 2단으로 강제된다. 595pt 폭에서 x=60~560을 차지하는 본문 줄은 중심이 오른쪽에 있어 왼쪽 문항에서 빠진다. 오른쪽에는 받을 문항이 없다. [단 판정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L1325-L1354) · [줄 배정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L816-L834)

**수정안** 약 4줄. 세로선 분기의 자격 조건을 `divider_eligible = bool(range_sides) if subject == Subject.ENGLISH else not crosses_middle`로 분리한다. 반대쪽의 범위 머리가 주는 독립 증거는 기존 분기에 둔다.

**예상 효과·위험·검증** 예시의 전폭 줄이 원래 문항에 남는다. 실제 2단 시험지에 전폭 안내 줄이 있으면 1단으로 남을 수 있으므로 대조본도 필요하다. 기존 중앙 답안선 합성 PDF에 같은 쪽 범위 머리를 추가하고 1단 판정과 전폭 줄 보존을 확인한다. 현재 검사는 범위 머리가 없는 경우만 다룬다. [현재 검사](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/scripts/verify_recognition_content.py#L189-L197)

## 중요

### 4. 미연결 지문을 복구하면서 앞 문항의 선지가 바뀐다

**위치** `app/recognition/pipeline.py:609` · `app/importers.py:1965`

```python
owner.text = "\n".join(part for part in (owner.text, str(passage.get("text") or "").strip()) if part)
owner.line_geometries.extend(passage.get("line_geometries") or [])
```

**깨지는 입력** 8번의 선지 5개 뒤에 `[9~10]` 고립 지문이 있고, 그 지문에 `① 관찰 결과`, `② 비교 자료`가 별도 줄로 인쇄된 발췌본. 복구한 지문을 `owner.text`에 합치기 때문에 가져오기 파서가 지문의 항목 2개를 8번 선지로 읽는다. 좌표 리스트는 문항별로 새로 생성되므로 원인은 공유 리스트 변형이 아니라 본문 합치기다. [복구 코드](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L605-L619) · [문항별 좌표 생성](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L502-L505) · [선지 분리](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/importers.py#L1959-L1992)

**수정안** 약 12~18줄. 원래 문항 영역에서 떼어낸 줄은 제거 전 소유 문항과 줄 순서를 기록한다. 선택 문항이 없는 독립 지문은 `result.unlinked_passages.append(passage)`로 보존하고, 가져오기에서 번호 없는 편집형 지문 항목으로 저장한다.

**예상 효과·위험·검증** 예시의 오인 선지 2개를 제거한다. 독립 지문을 저장할 때 기존 본문과 중복될 수 있으므로 원문 줄 ID로 한 번만 남았는지 확인한다. 합성 PDF에서 8번의 `choices` 5개와 독립 지문의 고유 문구 1회를 저장 결과에서 확인한다. 현재 검사는 인식 문자열에 문구가 있는지만 본다. [현재 검사](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/scripts/verify_recognition_content.py#L283-L286)

### 5. 날짜 머리글 필터가 이미 인식한 첫 문항을 지문 경계에서 지운다

**위치** `app/recognition/pdf_segment.py:443` · `app/recognition/pdf_segment.py:1041` · `app/recognition/pdf_segment.py:1065`

```python
if not (line["box"].top <= height_px * .13
        and (running_header.fullmatch(str(line["text"]).strip())
             or _looks_like_header_band_line(line["text"])
             or _looks_like_date_header(line["text"])))
```

**깨지는 입력** 왼쪽 단 말미에 `[12~13]` 지문이 있고, 오른쪽 단의 높이 10%에 `12. AM 9 and PM 3 readings ...`가 있는 시험지. 마커 추출은 8% 밖에서 엄격 판정을 하므로 12번을 인정한다. 지문 필터는 기본값 `loose=True`를 13%까지 적용해 그 줄을 제거한다. 다음 경계가 13번이 되면서 `[12~13]` 연결이 거부된다. 기존 호출의 느슨한 판정은 유지됐지만, 변경된 마커 판정과 공존할 때 두 경로가 충돌한다. [날짜 판정 기본값](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L93-L111) · [마커 판정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L433-L445) · [지문 경계](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L1031-L1069)

**수정안** 약 4줄. 머리글 필터 전에 `marker_ids = {id(marker["line"]) for marker in markers}`를 만들고, `id(line) in marker_ids or ...`로 확인된 경계 줄을 유지한다.

**예상 효과·위험·검증** 예시에서 12·13번의 지문 연결을 복구한다. 상류에서 잘못 인정한 마커도 경계에 남으므로 인쇄 타임스탬프 대조본을 유지한다. 합성 2단 PDF에서 12번의 bbox 상단을 8~13%에 두고, 두 문항에 지문이 붙으며 인쇄일은 문항 목록에 없는지 검사한다. [현재 날짜 검사](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/scripts/verify_recognition_content.py#L224-L231)

### 6. 한 경로로 그린 사선 테두리가 편집형 본문을 이미지로 바꾼다

**위치** `app/recognition/pdf_segment.py:673` · `app/recognition/pdf_segment.py:722` · `app/recognition/pdf_segment.py:1471`

```python
if item and item[0] == "l" and len(item) >= 3:
    segment = _scaled_drawing_box((item[1].x, item[1].y, item[2].x, item[2].y), scale)
    if segment is not None:
        drawings.append(segment)
```

**깨지는 입력** 230×140pt 상자의 네 모서리를 45×45pt씩 사선으로 자른 `<보기>` 테두리. 각 사선은 면적이 있는 박스로 들어간다. 박스 면적 합은 전체의 약 25%로 15% 기준을 넘는다. 글자가 24자 이상이어도 그림 후보가 되어, 문항 영역에 들어 있는 상자 글이 가져오기에서 문단 대신 PNG로 저장된다. [선분 추가](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L716-L727) · [면적 판정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L647-L674) · [본문 제외](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L1463-L1472)

**수정안** 약 5줄. 경로에서 새로 꺼낸 선분은 `if abs(a.x - b.x) > 1.0: continue`로 세로선 후보만 넘긴다. 전체 경로의 기존 박스 판정은 유지한다.

**예상 효과·위험·검증** 예시의 상자 한 개를 편집 가능한 본문으로 보존한다. 기울어진 내부 칸막이는 그래픽 증거에서 빠질 수 있다. 단일 경로의 사선 테두리 합성 PDF는 `figure_pngs == []`와 본문 보존을, 기존 단일 경로 2×2 표는 칸막이 검출을 확인한다. 현재 표 검사는 PNG 저장을 성공으로 정의하므로 네이티브 표 보존은 **미확인**이다. [현재 표 검사](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/scripts/verify_recognition_content.py#L292-L294)

### 7. 영어 듣기 지시문 판정의 입력 순서가 바뀌었다

**위치** `app/recognition/pdf_segment.py:424` · `app/recognition/pdf_segment.py:1191` · `app/recognition/pipeline.py:124`

```python
base_metadata["top_quarter_lines"] = [
    str(line["text"]) for line in text_lines if line["box"].top <= float(height_px) * 0.25
]
```

**깨지는 입력** 영어 영역명이 이미지이고, 듣기 지시문의 첫 문장이 PDF 추출 순서에서 연속한 두 줄로 저장된 혼합 시험지. 지시문 두 줄 사이 높이에 오른쪽 단의 별도 문구를 배치하면, 새 상단 목록은 `(top, left)`로 정렬한 뒤 이어 붙이므로 지시문의 고정 문자열 가운데 별도 문구가 들어간다. 이전 판정은 추출 순서로 이어 붙였다. 파일명과 과목에서 영어를 확인하지 못하는 문항은 이 플래그에 따라 수식 처리 경로로 들어갈 수 있다. 96책자 밖의 실제 영향은 **미확인**이다. [추출 줄 정렬](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L399-L425) · [이전 판정](https://github.com/Muuuuoouuun/hwp_make/blob/eefba30/app/recognition/pipeline.py#L101-L137) · [현재 판정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L113-L130) · [가져오기 분기](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/importers.py#L365-L368)

**수정안** 약 5줄. `rawdict` 순회 중 상단 줄을 별도 목록에 모아 메타데이터에 넘긴다. 문항 배정용 목록은 기존대로 정렬한다.

**예상 효과·위험·검증** PDF를 다시 열지 않고 예시 한 쪽의 영어 판정을 유지한다. 추출 순서와 시각 순서가 다른 경우에도 기존 판정과 동일한 결과를 기준으로 삼는다. 합성 PDF에서 듣기 문장을 두 줄로 먼저 삽입하고 두 줄 사이 높이의 오른쪽 문구를 나중에 삽입해 `source_literal_text`를 비교한다.

## 사소

### 8. 전각 지문을 가져올 수 있지만 연속 번호 내보내기는 거절된다

**위치** `app/exam_numbering.py:23` · `app/exam_numbering.py:37` · `app/exam_numbering.py:172`

```python
heading = _SHARED_HEADING.match(str(problem.get("stem") or ""))
return bool(heading and [int(heading[2]), int(heading[3])] == list(layout["shared_passage"]["range"])
            and len(_shared_number_marker(problem)) == 1)
```

**깨지는 입력** `［12～13］`을 가져온 뒤 12번만 골라 1번으로 내보내기. 인식과 저장은 성공하지만 `_SHARED_HEADING`이 반각 괄호만 받아 `ambiguous_shared_number`가 발생한다. [정규식과 사전 판정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/exam_numbering.py#L23-L39) · [내보내기 거절](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/exam_numbering.py#L167-L181)

**수정안** 1줄. `_SHARED_HEADING`의 여닫는 괄호를 각각 `[\[［]`, `[\]］]`로 넓힌다. 메타데이터 범위 일치와 독립 문항 번호 1개 검사는 그대로 적용한다.

**예상 효과·위험·검증** 예시의 선택 내보내기 1건이 완료된다. 괄호 혼용도 허용되므로 범위 불일치 거절을 대조한다. 기존 전각 합성 PDF를 인식에서 끝내지 않고 `prepare_export_problems`까지 통과시켜 지문 머리와 문항 번호가 각각 `[1]`, `1.`인지 확인한다. [현재 전각 검사](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/scripts/verify_recognition_content.py#L308-L314)

D4에서 보류한 두 경로도 남아 있다. 문항 번호가 없는 중간 쪽을 지나면 열린 지문 연결이 끊기고, 공통 자료의 그림은 여전히 문항 박스와의 겹침으로 배정한다. [쪽 간 지문 상태](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L451-L495) · [그림 배정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L518-L538)

=== 끝 ===
