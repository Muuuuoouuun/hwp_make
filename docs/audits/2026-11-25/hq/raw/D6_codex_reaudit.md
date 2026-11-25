**76/100 · 배포 보류**

`d6bfcfc` → `b3d0c41` 변경분에서 치명 3건, 중요 2건을 확인했다. 글자 선지 사이의 빈 줄과 원문자 한 개는 더 이상 선지를 지우지 않는다. 영어도 `_shared_passage_regions`에서 `open`을 받는다. 정상 단 배치에서는 같은 쪽의 다른 단에 있는 시작 문항도 찾아 `open=False`가 되고, 다음 쪽 첫 문항이 범위 시작 번호면 앞쪽 지문이 연결된다. 영어에서 다음 쪽 선두의 지문 본문을 수집하지 않는 조건은 이전 커밋에도 있었다. 점수는 정적 감사 판단이다. 합성 PDF 실행 결과, 실제 책자에서의 빈도, 속도 효과는 **미확인**이다. [D6 변경분](https://github.com/Muuuuoouuun/hwp_make/compare/d6bfcfc...b3d0c41) · [영어 지문 메타데이터](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L1051-L1079) · [D5의 다음 쪽 선두 처리](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L1419-L1428)

## 치명

### 1. 첫 번호가 같으면 홀·짝형 경계를 넘고, 지문 속 번호 목록이면 정상 연결이 끊긴다

**위치** `app/recognition/pipeline.py:574` · `app/recognition/pdf_segment.py:265`

```python
following = next((problem for problem in result.problems
                  if problem.page_number > passage_page and problem.number > 0), None)
target = following if following is not None and following.number == int(passage["start"]) else None
```

**깨지는 입력** 홀수형 발췌가 11번과 `[12~13]` 지문에서 끝나고, 다음 쪽에 `Even Form` 머리글과 짝수형 12·13번이 바로 나오면 두 문항에 홀수형 지문이 붙는다. 반대로 같은 유형의 다음 쪽에서 지문이 왼쪽 단의 들여쓴 `1) …`, `2) …` 목록으로 이어지고 오른쪽 단에 실제 12·13번이 있으면, 기존 마커 필터가 왼쪽 단의 첫 목록 번호를 남긴다. D5는 12번을 찾아 앞쪽 지문을 연결했지만 D6는 1번에서 연결을 포기한다. 새 검사는 다음 유형의 첫 번호가 1번인 경우를 다룬다. [대상 선택 및 범위 연결](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pipeline.py#L569-L605) · [번호 필터](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L233-L285) · [기존 합본 검사](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/scripts/verify_recognition_content.py#L365-L369)

**고친 코드** 약 20~30줄 추정. 상단 머리글 밴드의 독립된 홀·짝형 표지를 쪽 메타데이터에 남기고, `if form_boundary: break`를 쪽 선두 결합, 첫 문항 탐색, 범위 전파에 적용한다. 같은 유형 안에서는 `1)`, `2)`처럼 연속된 목록 표기와 지문 내부의 들여쓰기·줄간격이 함께 확인된 후보만 `if is_confirmed_passage_list_item: continue`로 넘긴다. 그다음 실제 문항에는 시작 번호 일치를 요구한다. [쪽 메타데이터](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L1193-L1212) · [쪽 선두 결합](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pipeline.py#L451-L473)

**효과·위험·검증** 합성 영어 PDF 두 개에서 각각 짝수형 오부착 2건 제거와 같은 유형의 지문 연결 2건 복구를 기대한다. 실제 1·2번 문항을 넘길 위험이 있으므로, 같은 번호를 정상 문항 들여쓰기와 간격으로 배치한 대조본에서는 연결을 거부하는지 검사한다. [합성 PDF 검사 기반](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/scripts/verify_recognition_content.py#L119-L134)

### 2. 오른쪽 단의 짧은 번호 줄이 왼쪽으로 분류되면 같은 쪽 지문이 끊긴다

**위치** `app/recognition/pdf_segment.py:1028` · `app/recognition/pdf_segment.py:1079` · `app/recognition/pipeline.py:575`

```python
box = line["box"]
column = int(two_columns and box.left + box.width / 2 >= width_px / 2)
return column, box.top, box.left
```

**깨지는 입력** 폭 595pt인 영어 시험지에서 왼쪽 문항과 지문은 x=45, 좁은 여백 쪽으로 당겨진 오른쪽 단 문항은 x=265에 둔다. 왼쪽 단 끝에 `[12~13]`, 오른쪽 단 위에 짧은 `12. Why?`, `13. How?`를 두면 마커 클러스터는 문항을 두 단으로 나누지만, 두 번호 줄의 bbox 중심은 페이지 중앙보다 왼쪽에 남는다. 지문 검출은 두 번호를 지문보다 앞에 읽고 `open=True`를 붙인다. D5는 같은 쪽 12번을 찾아 연결했다. D6는 같은 쪽을 건너뛰고, 받을 문항이 없으면 지문을 마지막 문항의 본문에 합친다. [마커 클러스터](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L782-L812) · [지문 읽기 순서와 `open`](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L1028-L1079) · [D5 대상 선택](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pipeline.py#L564-L579) · [D6 미연결 처리](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pipeline.py#L569-L618)

**고친 코드** 약 6~10줄 추정. `marker_columns = {id(d["marker_line"]): d["column_index"] - 1 for d in descriptors}`를 만들고, `key()`에서 `column = marker_columns.get(id(line), geometry_column)`을 사용한다. 확정된 번호 줄의 단을 문항과 지문에서 동일하게 읽는다. [문항 단 정보](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L1408-L1425)

**효과·위험·검증** 위 좌표의 합성 PDF에서 `open=False`, 12·13번 모두에 지문 연결, 11번 본문에 지문 없음, 13번 본문에 지문 중복 없음이 기대값이다. 문항 마커 클러스터가 오판하면 지문 순서도 따라 바뀌므로, 정상 중앙 여백의 두 단과 실제 다음 쪽으로 이어지는 지문을 대조한다. [공통 지문 회귀 검사 기반](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/scripts/verify_recognition_content.py#L315-L331)

### 3. 본문에서 원문자를 세 번 참조하면 A–E 선지 전체가 본문으로 들어간다

**위치** `app/importers.py:824` · `app/importers.py:1985`

```python
if label[0].isalpha() and sum(
        char in CIRCLED_CHOICE_MARKERS for other in lines for char in other) >= 3:
```

**깨지는 입력** 자료 해석 문항에서 `At ① the valve opens.`, `At ② the pressure rises.`, `At ③ the cycle ends.`처럼 본문 세 줄에서 자료의 번호를 한 번씩 참조하고, 아래에 `A.`~`E.` 선지가 인쇄된 경우다. 빈 줄 없이 각 참조를 줄 중간에 두면 D5는 선지 5개를 분리한다. D6는 세 원문자를 합산해 5개를 모두 본문에 남긴다. 줄당 원문자가 하나라 인라인 분리도 작동하지 않는다. [D5 선지 판정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/importers.py#L808-L830) · [D6 선지 판정](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/importers.py#L808-L835) · [PDF 가져오기 호출부](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/importers.py#L418-L426)

**고친 코드** 약 10~16줄 추정. `if label[0].isalpha() and index in confirmed_example_items: return None`으로 바꾼다. 별도의 원문자 선지 묶음은 나중에 나오는 독립 행 또는 연속 행에서 중복 없이 순서가 맞는 번호로 확인한다. PDF에서는 선지 행 정렬과 글자 항목과의 간격도 확인한다. [현재 인라인 판정](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/importers.py#L734-L747) · [좌표를 넘기는 호출부](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/importers.py#L388-L426)

**효과·위험·검증** 예시의 저장 결과에서 선지 5개와 본문의 원문자 참조 3개를 보존한다. 짧은 실제 원문자 선지 묶음을 놓치면 `<보기>`의 글자 항목이 선지로 섞일 수 있다. 합성 과학 PDF의 본문 참조 3개＋A–E와, 글자 항목 2개＋독립 원문자 선지 행을 함께 검사한다. [기존 선지 대조본](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/scripts/verify_recognition_content.py#L394-L406)

## 중요

### 4. 실제 2단 시험지의 전폭 안내문이 구분선보다 위에 있어도 1단으로 처리된다

**위치** `app/recognition/pdf_segment.py:1347` · `app/recognition/pdf_segment.py:1356`

```python
or ((bool(range_sides) if subject == Subject.ENGLISH else not crosses_middle)
    and _english_has_column_divider(page, scale, float(width_px), float(height_px)))
```

**깨지는 입력** 국어 시험지에서 전폭 안내문은 y=135, 중앙 구분선은 y=180~760에 둔다. 왼쪽 단에 11번과 단 끝의 `[12~13]` 머리, 오른쪽 단 위에 이어지는 본문을 두고, 12번은 다음 쪽에서 시작한다. 안내문 한 줄 때문에 `crosses_middle=True`가 되어 D6는 1단으로 처리한다. 오른쪽 단의 본문을 다음 단 대신 지문 머리보다 앞에 읽어 공통 지문에서 빠뜨린다. D5는 범위 머리와 구분선으로 이 쪽을 2단으로 처리했다. [D5 단 판정](https://github.com/Muuuuoouuun/hwp_make/blob/d6bfcfc/app/recognition/pdf_segment.py#L1325-L1354) · [D6 단 판정](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L1333-L1362) · [지문 순서](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L1028-L1079)

**고친 코드** 약 8~12줄 추정. 검출한 구분선의 세로 범위를 반환하고, `crosses_divider = any(crosses_x(line, divider) and overlaps_y(line, divider) for line in body_lines)`로 실제 선을 가로지르는 본문만 1단 보호의 근거로 쓴다. [구분선 좌표 판정](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L1085-L1099)

**효과·위험·검증** 합성 2단 PDF의 오른쪽 단 고유 문구가 12·13번 공통 지문에 남는지 확인한다. 구분선이 짧은 1단 시험지를 과분할할 수 있으므로, 기존 중앙 답안선 대조본에서는 `column_count == 1`과 전폭 본문 보존을 함께 확인한다. [기존 1단 보호 검사](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/scripts/verify_recognition_content.py#L371-L374)

### 5. 테두리와 한 경로로 그린 꺾은선 그래프가 그림에서 빠진다

**위치** `app/recognition/pdf_segment.py:726` · `app/recognition/pdf_segment.py:674`

```python
if item and item[0] == "l" and len(item) >= 3 and abs(item[1].x - item[2].x) <= 1.0:
    segment = _scaled_drawing_box((item[1].x, item[1].y, item[2].x, item[2].y), scale)
    if segment is not None:
        drawings.append(segment)
```

**깨지는 입력** 과학 시험지에서 230×140pt 테두리와 내부의 꺾은선을 한 PDF 경로로 그리고, 안에 24자 이상의 축·범례 텍스트를 둔다. D5에서는 내부 사선의 bbox 면적이 그림 판정에 기여한다. D6에서는 사선이 모두 빠지고 전체 경로 bbox는 테두리로 처리된다. 인식 결과에 범례 텍스트만 남고 그래프 PNG가 제공되지 않는다. [선분 수집](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L706-L729) · [그림 면적 판정](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L629-L674) · [인식 그림 후보](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pipeline.py#L202-L209)

**고친 코드** 약 6~10줄 추정. `if segment is not None and (is_vertical or strictly_inside(segment, box, edge)):`로 세로 칸막이와 테두리 네 변에서 충분히 떨어진 내부 사선을 전달한다. 기존 면적 기준을 적용한다. [테두리 여유와 면적 기준](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/app/recognition/pdf_segment.py#L648-L674)

**효과·위험·검증** 합성 PDF에 테두리 `(60,135)–(290,275)`와 내부 꺾은선 `(85,245)–(175,160)–(265,245)`를 한 경로로 그려 그래프 PNG 1개를 확인한다. 내부 장식선이 많은 글상자는 그림으로 오인될 수 있으므로, 기존 모서리 사선 상자에서는 PNG 0개와 편집 가능한 본문 보존을 확인한다. [기존 사선 테두리 검사](https://github.com/Muuuuoouuun/hwp_make/blob/b3d0c41/scripts/verify_recognition_content.py#L239-L254)

## 사소

별도 지적 없음.

=== 끝 ===
