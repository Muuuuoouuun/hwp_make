# 이번 변경 점수 76/100

`50cd57c` → `eefba30`은 테두리 상자 안의 본문 보존, 표지가 있는 문서의 편집형 변환, 인식 결과 재사용을 개선했다. 가장 큰 결함은 공통 지문의 소속이 확정되기 전에 기존 문항에서 줄을 제거하는 점과, 중앙 세로선 하나로 본문 열을 확정하는 점이다. 두 경우 모두 정상적으로 읽히던 원문이 문항 가져오기 결과에서 빠질 수 있다. 정적 감사 점수이며, 아래 합성 PDF의 실제 실행 결과와 시간 효과는 **미확인**이다. 코드와 파일은 수정하지 않았다.

## 치명

### 1. 연결할 문항이 없으면 지문으로 분류한 본문이 사라진다

**위치** `app/recognition/pdf_segment.py:1036` · `app/recognition/pipeline.py:250` · `app/recognition/pipeline.py:600`

```python
if not selected or (following is not None and marker_lines[id(following)] != start):
    continue
shared_ids.update(id(candidate) for candidate in selected)
```

**문제와 근거** 시험지 일부만 발췌해서 8번과 그 아래 `[9~10]` 지문은 있지만 9번이 없는 경우, 지문 줄을 8번에서 제거한 뒤 연결에 실패한다. 8번에 그림이나 깨진 수식 글리프가 없다면 해당 쪽은 렌더 대상도 아니어서 폴백이 `None`을 반환한다. `render=False`에서도 같은 본문이 빠진다. 새 검사는 시작 문항이 실제로 있는 경우만 검사한다. `app/recognition/pipeline.py:250–275`, `app/recognition/pipeline.py:333–340`, `app/recognition/pipeline.py:565–605`, `scripts/verify_recognition_content.py:178–194`

**최소 수정** 약 15줄. 같은 쪽에서 시작 번호가 확인된 줄만 즉시 제거한다. 열린 지문의 줄 ID와 기존 소유 문항을 보존하고, 연결이 성립하면 그때 기존 문항에서 제거한다. 소유 문항이 없는 미연결 지문은 편집 가능한 문서 메모로 보존한다.

```python
if following is not None:
    shared_ids.update(id(candidate) for candidate in selected)
```

**효과·위험·검증** 연결 실패로 사라지는 문장을 0개로 줄인다. 제거를 지연하는 경로에서 중복이 생길 수 있으므로, 그림 없는 8번 아래 `[9~10]`과 `ORPHAN_SENTINEL`을 둔 한 쪽에서 문장이 한 번 보존되는지 확인한다. 9번을 추가한 대조본에서는 같은 문장이 8번에서 빠지고 9번 지문에 한 번 연결되어야 한다.

### 2. 중앙 세로선이 있는 단일 단 시험지에서 본문이 잘린다

**위치** `app/recognition/pdf_segment.py:1051` · `app/recognition/pdf_segment.py:1302` · `app/recognition/pdf_segment.py:801`

```python
or ((bool(range_sides) or subject != Subject.ENGLISH)
    and _english_has_column_divider(page, scale, float(width_px), float(height_px)))
```

**문제와 근거** 문항 번호가 모두 왼쪽에 있고 본문은 전폭으로 인쇄되지만, 풀이·답안 작성란에 긴 중앙 세로선이 있는 시험지다. 세로선이 쪽 높이의 25% 이전부터 75% 이후까지 이어지면 2단으로 강제한다. 왼쪽에서 시작한 긴 본문 줄도 줄의 중심이 오른쪽 반쪽에 있으면 왼쪽 문항에서 통째로 제외된다. 반대쪽에는 문항이 없어 그 줄을 받을 곳이 없다. `app/recognition/pdf_segment.py:1051–1064`, `app/recognition/pdf_segment.py:1291–1312`, `app/recognition/pdf_segment.py:791–807`

**최소 수정** 약 7줄. 세로선 단독 판정에는 본문 줄이 중앙 여백을 가로지르지 않는다는 증거를 함께 요구한다.

```python
gutter = width_px * .05
crossing_body = any(
    b.top > height_px * .13 and b.left < middle - gutter and b.right > middle + gutter
    for b in (line["box"] for line in text_lines)
)
# 비영어의 세로선 단독 판정에 `and not crossing_body`를 추가한다.
```

**효과·위험·검증** 이 배치에서 잃는 전폭 줄을 보존한다. 실제 2단의 전폭 공통 안내문이 판정을 방해할 수 있으므로 본문과 확인된 안내문을 구분한다. 595×842pt 쪽에 x=297.5, y=160–750 세로선과 x=60–550을 차지하는 문항 본문을 두고, `column_count == 1`과 본문 보존을 확인한다. 기존 `divider()` 교차 쪽 표본은 계속 2단이어야 한다.

## 중요

### 3. 문항 번호가 없는 중간 쪽에서 지문 연결이 끊긴다

**위치** `app/recognition/pdf_segment.py:1252` · `app/recognition/pipeline.py:462`

```python
leading = page.metadata.get("leading_passage")
if leading and open_passage is not None and open_passage["page_number"] == page_index:
    open_passage["text"] = "\n".join([open_passage["text"], leading["text"]])
```

**문제와 근거** 1쪽에 `[12~13]` 머리와 지문 앞부분, 2쪽에 지문 중간 부분만, 3쪽에 마지막 문단과 12·13번이 있는 배치다. 마커가 없는 2쪽은 `leading_passage`를 만들기 전에 반환한다. 파이프라인은 2쪽에서 지문 상태를 지운다. 12·13번은 1쪽 지문만 받고, 기본 가져오기에서 2쪽이 별도 번호 0 항목으로 나와도 문항을 단독 선택하면 필요한 중간 부분이 빠진다. `app/recognition/pdf_segment.py:1252–1289`, `app/recognition/pdf_segment.py:1377–1384`, `app/recognition/pipeline.py:458–492`

**최소 수정** 약 15줄. 마커 없는 쪽의 정렬된 블록도 연속 후보로 기록하고, 지문 시작 쪽과 마지막으로 받은 쪽을 따로 추적한다. 이어지는 첫 문항이 지문 시작 번호와 일치하고 중간 쪽에 새 과목·시험지 머리가 없을 때 연결을 확정한다.

```python
if continuation and open_passage["last_page"] == page_number - 1:
    extend_passage(open_passage, continuation)
    open_passage["last_page"] = page_number
```

**효과·위험·검증** 중간 쪽과 마지막 쪽의 지문을 모두 문항에 포함한다. 삽입된 표지나 안내문이 붙을 수 있으므로 별도 머리를 가진 중간 쪽을 음성 대조군으로 둔다. 합성 3쪽에서는 각 쪽의 고유 문장이 12·13번에 모두 한 번씩 있어야 한다. 기존 검사는 문항이 있는 두 쪽만 쓴다. `scripts/verify_recognition_content.py:119–135`

### 4. 13% 머리글 밴드 안의 첫 문항을 지나쳐 문항 본문을 공통 지문에 넣는다

**위치** `app/recognition/pdf_segment.py:942`

```python
body = [line for line in text_lines if line["box"].top > height_px * 0.13]
```

**문제와 근거** 앞 쪽에 열린 `[12~13]` 지문이 있고 다음 쪽 12번 번호 줄의 bbox 상단이 쪽 높이의 10%, 12번의 두 번째 줄은 16%에 있는 경우다. 번호 줄이 정렬 후보에서 먼저 제거된다. 이어서 13번을 만날 때까지 12번의 본문이 공통 지문에 붙어 13번에도 복제된다. 상단 13% 안에 인쇄된 실제 지문 계속 줄도 같은 필터에서 빠진다. `app/recognition/pdf_segment.py:942–954`, `app/recognition/pipeline.py:462–467`

**최소 수정** 약 7줄. 첫 문항·지문 머리 검사를 모든 줄에 적용하고, 머리글 제거는 수집 시점에 확인된 머리글에만 적용한다.

```python
if id(line) in marker_ids or _range_heading(line["text"], anchored):
    return leading
if line["box"].top <= height_px * .13 and is_running_header(line["text"]):
    continue
leading.append(line)
```

**효과·위험·검증** 다른 문항으로 복제되는 12번 본문을 0줄로 줄인다. 머리글 필터를 좁히면 새 유형의 머리말이 수집될 수 있으므로, 842pt 쪽의 y=100에 12번, y=140에 `QUESTION_ONLY`, y=280에 13번을 두고 공통 지문에 `QUESTION_ONLY`가 없는지 검사한다. 여백 안 실제 지문 줄과 반복 머리말도 각각 추가해 보존·제외가 구분되는지 확인한다.

### 5. 번호가 범위 안에서 다시 시작하면 앞 시험지 지문이 다음 유형으로 넘어간다

**위치** `app/recognition/pipeline.py:583`

```python
for problem in result.problems[start_index:]:
    if not int(passage["start"]) <= problem.number <= int(passage["end"]):
        break
    targets.append(problem)
```

**문제와 근거** 첫 유형 발췌본에 `[12~15]` 지문과 12·13번만 있고, 뒤에 둘째 유형의 12–15번이 이어지면 처리 순서는 `12, 13, 12, 13, 14, 15`다. 여섯 번호가 모두 범위 안이라 첫 유형 지문을 둘째 유형에도 붙인다. 비영어의 같은 쪽 지문에서 이번 변경으로 이 경로가 생겼다. 네이티브 문항 그룹은 이미 번호가 같거나 감소하면 새 유형으로 본다. `app/recognition/pipeline.py:565–598`, `app/pdf_native_content.py:644–646`

**최소 수정** 2줄. 시작 문항 이후 첫 번호 재시작에서 범위 확장을 멈춘다.

```python
if targets and problem.number <= targets[-1].number:
    break
```

**효과·위험·검증** 예시에서 둘째 유형 4문항의 오연결을 막는다. 실제 중복 번호도 여기서 경계로 처리되므로 기존 유형 판정과 같은 규칙을 적용한다. 합성 PDF 두 쪽에 위 순서를 만들고 첫 유형의 고유 문구가 앞 두 문항에만 있는지 확인한다. 번호를 키로 쓰는 검사 헬퍼는 중복을 덮어쓰므로 결과 리스트와 쪽 번호를 직접 검사한다. `scripts/verify_recognition_content.py:65`

### 6. 공통 자료의 글은 범위 문항에 붙고 그림은 앞 문항에 붙는다

**위치** `app/recognition/pdf_segment.py:1040` · `app/recognition/pdf_segment.py:1341` · `app/recognition/pipeline.py:526`

```python
figure_boxes = [
    figure
    for figure in text_light_figures
    if _box_intersection_area(figure, box) >= figure.area * 0.6
]
```

**문제와 근거** 11번 아래 `[12~13]`과 삽화가 있고, 그 아래 같은 단에서 12번이 시작되는 과학 시험지다. 삽화와 그 아래 설명이 11번의 최초 영역 안에 있으면, 지문 줄은 12·13번에 연결되지만 11번의 기존 박스는 그대로다. 그림은 그 박스로 결정되어 11번에만 저장된다. 결과적으로 12번을 가져와 단독 선택하면 지문이 참조하는 그림이 빠진다. 네이티브 일괄 작성기는 별도로 원본을 추출하므로 이 지적의 범위는 문항 가져오기다. `app/recognition/pdf_segment.py:1040–1048`, `app/recognition/pdf_segment.py:1341–1376`, `app/recognition/pipeline.py:524–535`, `app/importers.py:370–373`, `app/pdf_native_content.py:1940–1951`

**최소 수정** 약 20줄. 확인된 지문 머리와 첫 문항 사이의 같은 단 영역에 완전히 들어가는 삽화를 지문에 귀속한다. 그림 후보를 이전 문항에서 제외하고 기존 지역 잘라내기를 공유 지문에도 사용한다.

```python
if passage_region.contains(figure):
    shared["figure_boxes"].append(figure)
    continue  # 앞 문항의 그림 후보에서는 제외
```

**효과·위험·검증** 삽화 하나가 앞 문항에서 빠지고 관련 두 문항에 각각 보존된다. 경계에 걸친 그림은 이전 문항의 그림일 수 있으므로 영역에 완전히 포함된 경우부터 적용한다. 합성 PDF에서 11번 아래에 지문 머리, 벡터 삽화, 설명 줄을 차례로 두고 11번의 PNG는 0개, 12·13번은 각각 1개인지 검사한다.

### 7. 테두리와 세로 칸막이를 한 벡터 경로로 그린 표를 놓친다

**위치** `app/recognition/pdf_segment.py:643` · `app/recognition/pdf_segment.py:690`

```python
if all(hugs):
    continue  # 테두리 사각형·바탕
```

**문제와 근거** PDF가 2×2 표의 테두리와 칸막이를 한 경로로 그리면 검사에 들어가는 것은 그 전체 경로의 `rect` 하나다. 병합된 영역과 네 변이 같아서 통째로 건너뛰며, 실제 내부 세로선은 검사되지 않는다. 셀 글자가 24자 이상이면 인식 결과에서 표가 일반 텍스트로 풀리며 격자와 셀 대응이 사라진다. 기존 표 검사는 테두리와 칸막이를 별도 호출로 그린다. `app/recognition/pdf_segment.py:618–622`, `app/recognition/pdf_segment.py:637–658`, `app/recognition/pdf_segment.py:690–709`, `scripts/verify_recognition_content.py:83–96`

**최소 수정** 약 8줄. 후보 병합에는 기존 경로 bbox를 사용하고, 그림 여부를 판정할 때는 경로 내부 선분도 넘긴다.

```python
for item in drawing.get("items", ()):
    if item[0] == "l":
        a, b = item[1:3]
        if rule := _scaled_drawing_box((a.x, a.y, b.x, b.y), scale):
            drawings.append(rule)
```

**효과·위험·검증** 같은 표에서 PDF 경로 묶음 방식에 따른 판정 차이를 없앤다. 쪼개진 테두리 세로획을 칸막이로 세지 않도록 기존 양 가장자리 제외 조건을 유지한다. `table_pdf()`의 벡터 세 요소를 `new_shape()` 하나에 넣고 한 번에 커밋한 뒤, 기존 표와 같은 그림 판정을 받는지 확인한다. 편집형 일괄 작성기의 네이티브 표 추출은 별도 경로다.

### 8. 8% 바깥에 인쇄된 날짜가 새 문항 번호가 된다

**위치** `app/recognition/pdf_segment.py:87` · `app/recognition/pdf_segment.py:427`

```python
if (box.top < margin_band or box.bottom > height_px - margin_band) and _looks_like_date_header(text):
    continue
```

**문제와 근거** 842pt 시험지에서 `24. 11. 7. PM 3:21`이 y=90, 실제 10·11번이 y=200·300에 배치된 경우다. 날짜 전체 형식은 기존 판별식에 맞지만, 작은 글꼴로 그린 y=90 날짜는 8% 밴드 밖이다. 마커 정규식이 `24.`를 받아들여 인식 목록에 24번이 추가된다. 현재 검사는 날짜를 y=30에만 둔다. `app/recognition/pdf_segment.py:54–60`, `app/recognition/pdf_segment.py:87–96`, `app/recognition/pdf_segment.py:419–437`, `scripts/verify_recognition_content.py:148–154`

**최소 수정** 약 5줄. 날짜와 시각 전체가 맞는 엄격한 인쇄일 형식을 별도로 두고, 기존의 느슨한 AM/PM 판정은 8% 밴드에서만 적용한다.

```python
if _PRINT_TIMESTAMP_RE.fullmatch(text.strip()):
    continue
if in_margin and _looks_like_date_header(text):
    continue
```

**효과·위험·검증** 예시의 유령 문항 24번을 제거하면서 `11. AM 9 and PM 3 readings were 12 degrees.`는 유지한다. 날짜 자체가 시험 내용일 수 있으므로 문자열 전체 일치에 더해 반복 머리말이나 여백 위치를 증거로 활용할 수 있다. 합성 사례에서 인쇄일을 y=30과 y=90에 각각 두고 번호가 모두 `[10, 11]`인지 확인한다.

## 사소

### 9. 전각 대괄호를 쓰는 공통 지문을 인식하지 못한다

**위치** `app/recognition/pdf_segment.py:56` · `app/recognition/pdf_segment.py:922` · `app/recognition/pipeline.py:373`

```python
_PASSAGE_RANGE_RE = re.compile(r"\[\s*(\d{1,2})\s*[~～∼\-–]\s*(\d{1,2})\s*\]")
```

**문제와 근거** 일본식·동아시아 전각 문장부호를 쓰는 조판에서 `［12～13］ 다음 자료를 읽고`는 두 인식 정규식 모두에서 탈락한다. 같은 문서를 네이티브 일괄 작성기는 전각 괄호까지 받는 `SHARED_PASSAGE_START`로 분류한다. 가져오기와 일괄 작성기의 지문 소속이 달라진다. `app/pdf_question_markers.py:15–28`, `app/pdf_native_content.py:638–660`

**최소 수정** 인식과 선택 내보내기의 번호 처리까지 약 3줄. 인식용 범위 정규식 두 곳과 선택 내보내기의 `_SHARED_HEADING`에서 괄호 문자 클래스를 넓힌다. `app/exam_numbering.py:23`, `app/exam_numbering.py:172–175`

```python
r"[\[［]\s*(\d{1,2})\s*[~～∼\-–]\s*(\d{1,2})\s*[\]］]"
```

**효과·위험·검증** 표기 차이로 생기는 12·13번의 지문 누락을 막는다. 영어의 줄 중간 검색도 넓어질 수 있으므로 영어 기존 검색 정책이 필요하면 비영어의 선두 판정부터 적용한다. `same_page_passage_pdf()`에서 괄호만 전각으로 바꿔 두 문항의 지문 연결과 선택 내보내기의 연속 번호 지정을 확인한다.

### 10. 빠른 검수 응답이 미측정을 실패로 기록한다

**위치** `app/main.py:785` · `app/main.py:1140` · `app/main.py:1213`

```python
quality["meets_objective_score_target"] = bool(
    quality.get("meets_objective_score_target") and review["ok"]
    and open_safety.get("ok") and fidelity.get("available")
```

**문제와 근거** 정상 PDF를 `quality_check="fast"`로 변환하면 `objective_score`는 `None`인데 최종 `meets_objective_score_target`은 항상 `False`다. 시각 대조가 없어서 판단할 수 없는 `meets_paging_target`도 `False`다. 반면 화면의 건너뜀 안내와 `fidelity.meets_target`은 미검증을 표현한다. 응답 소비자가 `False`를 품질 미달로 판정하면 같은 파일을 실패로 집계한다. 새 회귀 검사는 안내 문구와 본문만 비교한다. `app/main.py:785–812`, `app/main.py:1140–1145`, `app/main.py:1213–1223`, `scripts/verify_recognition_content.py:256–264`

**최소 수정** 약 5줄. 화면 대조가 필요한 두 판정에 빠른 모드의 미측정값을 유지하고, 시각 검수 플래그는 실제 실패에만 추가한다.

```python
if fast_check:
    quality["meets_objective_score_target"] = None
    quality["meets_paging_target"] = None
elif quality["meets_objective_score_target"] is False:
    # 기존 시각 검수 플래그를 추가한다.
```

**효과·위험·검증** 빠른 모드에서 미평가 두 건이 실패로 집계되는 일을 막는다. 불리언만 허용하는 API 소비자는 `null` 처리가 필요하다. 기존 합성 표지 PDF로 빠른 응답의 두 값이 `null`이고 편집성·문항 렌더 검수 결과는 계속 반환되는지 확인한다.

`_extract_figures`의 저장소 내 호출은 한 곳이며 영어 도표 추가 뒤에도 `figures`, `figure_graphics`, `counts`의 길이가 맞는다. 번호 0 제외는 작성기 통계와 검수 인벤토리에 일관되게 적용된다. 도형 메모 소비 경로는 저장값을 읽기만 하고, 키는 문서 객체 대신 파일 해시와 쪽 번호를 쓴다. 빠른 검수 분기에서 `fast_check` 미정의나 `fidelity` 키 직접 접근에 의한 예외는 발견하지 못했다. 작성기의 조기 반환 뒤 블록에서도 도달 가능한 이름 해석 문제는 발견하지 못했다. `app/recognition/pdf_segment.py:717–749`, `app/recognition/pdf_segment.py:1192–1222`, `app/pdf_native_content.py:1950`, `app/pdf_native_content.py:2020–2024`, `app/pdf_question_inspection.py:340–345`, `app/pdf_source_frame_geometry.py:116–143`, `app/pdf_source_page_memo.py:87–116`, `app/main.py:1140–1223`, `app/pdf_layout_writer.py:10205–10221`

=== 끝 ===
