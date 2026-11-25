# 문항 인식 알고리즘 82/100 — 추정

`50cd57c`의 정적 감사 점수다. 문항 검출 35/40, 텍스트·좌표 보존 23/30, 읽기 순서·페이지 간 연결 12/15, 처리 비용 12/15로 평가했다. 일반적인 번호형 시험지와 영어 교차 단 지문에는 결정론적 처리와 합성 회귀 검사가 있다. 가장 큰 손실은 마커를 찾은 뒤에도 발생한다. 자료 상자 안의 편집 가능한 줄이 삭제되고, 가까운 두 문항이 같은 줄을 가져가며, 첫 줄의 120자 이후가 잘린다. 같은 PDF에서도 DPI나 도형 그리기 순서에 따라 그림 귀속이 달라질 수 있다. 아래 재현 결과와 개선 폭은 코드에서 도출한 **추정**이다. PDF 생성, 테스트 실행, 코드 수정은 하지 않았으며 실문서 발생률과 초 단위 개선 폭은 **미확인**이다.

## 치명

### 1. 국어·수학·사회 자료 상자 안의 편집형 줄 소실

1. **위치** [app/recognition/pdf_segment.py:1289](<<repo>/app/recognition/pdf_segment.py:1289>), `app/recognition/pdf_segment.py:747`, `app/recognition/pipeline.py:221`
2. **현재 동작**
   ```python
   label_figures = chart_figures if subject == Subject.ENGLISH else figures
   if _line_inside_figure(line, label_figures, desc["box"]):
       continue
   ```
3. **문제** 국어 문항 아래에 사각 테두리와 24자 이상의 `<보기>`가 있다. 테두리는 `figures`에 들어가고 내부 줄은 본문에서 빠진다. 같은 상자는 문자 수 때문에 지역 그림 후보에서도 제외될 수 있어 텍스트와 PNG 양쪽에서 사라진다.
4. **수정안** 약 20~30줄. 이미지·차트·일반 벡터 영역의 출처를 유지한다. 짧은 라벨 텍스트와 실제 그림 내부 위치가 함께 확인된 줄에만 삭제를 적용하고, 본문·표·수식 줄은 보존한다.
5. **예상 효과** 합성 fixture에서 상자 안 3줄 중 0→3줄 보존 추정. 문항 개수 검사만으로는 잡히지 않는 손실이다.
6. **회귀 위험** 그림 속 축 라벨이 본문에도 중복될 수 있다. 실제 차트와 한두 글자짜리 꼭짓점 라벨을 대조군으로 둔다.
7. **검증** 한 문항 아래 벡터 사각형, 24자 이상인 산문 3줄, 별도의 라벨 있는 도형을 삽입한다. 산문 3줄은 `text`와 `line_geometries`에 각 1회, 도형 라벨은 해당 도형에만 남는지 확인한다.

### 2. 인접 문항이 다음 문항의 제목과 본문을 중복 소유

1. **위치** [app/recognition/pdf_segment.py:1193](<<repo>/app/recognition/pdf_segment.py:1193>), `app/recognition/pdf_segment.py:735`, `app/recognition/pdf_segment.py:1280`
2. **현재 동작**
   ```python
   if i + 1 < len(ordered):
       next_top = ordered[i + 1]["box"].top
       initial_bottom = max(top + 40.0, next_top - max(8.0, height_px * 0.004))
   ```
3. **문제** 짧은 영어 문항 `12.`와 `13.`이 같은 단에서 약 12pt 간격으로 이어지면, 기본 150 DPI에서 앞 문항의 최소 높이 40px이 다음 마커보다 아래까지 뻗을 수 있다. 자식 줄 생성 시 현재 문항 자신의 마커만 제외하므로 `13.` 줄이 `12.`에도 들어간다.
4. **수정안** 약 15~25줄. 확정 마커 사이에 줄 소유 경계를 한 번 계산한다. 마커 줄은 해당 문항에 고정하고 경계에 겹치는 일반 줄은 기준선으로 한 번만 배정한다. 컷아웃 여백은 별도로 유지한다.
5. **예상 효과** fixture 한 쪽에서 다음 제목의 중복 1건→0건 추정. 번호 목록이 `[12, 13]`으로 맞아도 발생할 수 있다.
6. **회귀 위험** 윗첨자나 수식 분자가 이전 문항의 마지막 줄 위로 튀어나오는 경우다. 제목 고정과 일반 줄 배정을 나눠 검증한다.
7. **검증** 영어 PDF에 12pt 간격의 짧은 두 문항과 두 번째 문항의 고유 문구를 넣는다. 각 제목과 고유 문구가 자기 문항에만 있고, 앞 문항의 마지막 수식 줄도 유지되는지 확인한다.

### 3. 마커와 같은 줄에 적힌 질문이 120자에서 잘림

1. **위치** [app/recognition/pdf_segment.py:441](<<repo>/app/recognition/pdf_segment.py:441>), `app/recognition/pdf_segment.py:1281`, `app/recognition/pdf_segment.py:1328`, `app/recognition/pipeline.py:168`
2. **현재 동작**
   ```python
   "text": text[:120],
   "box": box,
   "line": line,
   ```
3. **문제** 전폭 영어 문항의 짧은 글꼴이나 가로형 시험지에서 번호와 질문이 120자를 넘는 한 줄에 들어갈 수 있다. 원래 줄은 자식 블록에서 제외되고 `TITLE.text`에는 축약본만 들어간다. 문자 좌표는 끝까지 남아 줄 텍스트와도 길이가 어긋난다.
4. **수정안** 약 4~8줄. `TITLE.text`를 원본 `marker_line["text"]`에서 채운다. `marker_text`는 미리보기용 축약값으로 유지한다.
5. **예상 효과** 150자짜리 첫 줄에서 현재 잘리는 30자 복원 추정. 문장 끝 질문 조건이나 배점 표기가 해당 위치에 있으면 함께 복원된다.
6. **회귀 위험** `TITLE.text`의 길이를 전제로 표시하는 호출부 영향은 미확인이다. 축약 메타데이터의 기존 계약을 유지한다.
7. **검증** 한 줄에 150자와 끝 식별어 `TAIL_SENTINEL`이 들어가는 PDF를 만든다. `recognize_pdf`의 문항 텍스트와 첫 줄 geometry의 `text`에 식별어가 1회씩 있고 문자 좌표가 끝까지 대응하는지 확인한다.

### 4. 앞 시험지의 공통 지문이 다음 시험지의 같은 번호에 연결

1. **위치** [app/recognition/pipeline.py:562](<<repo>/app/recognition/pipeline.py:562>), `app/recognition/pipeline.py:576`
2. **현재 동작**
   ```python
   for problem in result.problems
   if problem.number == int(passage["start"])
   and problem.page_number >= int(passage["page_number"])
   ```
3. **문제** 홀수형의 `[41~42]` 지문 쪽 뒤에서 해당 문항 쪽이 빠지고, 이어 붙인 짝수형에 `41`, `42`가 있다. 첫 대상 탐색은 시험 형식 경계를 확인하지 않으므로 홀수형 지문이 짝수형 문항들에 붙는다.
4. **수정안** 약 25~35줄. 상단의 명시적 홀수형·짝수형 표기나 새 시험 머리글로 구간 경계가 확인되면 그 경계까지만 시작 번호를 찾는다. 미연결 지문은 원본 쪽의 편집 가능한 텍스트와 좌표로 유지한다.
5. **예상 효과** fixture에서 다른 시험 형식으로의 지문 오연결 2건→0건 추정.
6. **회귀 위험** 반복 머리글을 매 쪽마다 구간 변경으로 해석하면 정상 이월이 끊긴다. 동일 표기가 반복되는 대조군과 표기가 없는 기존 이월을 검증한다.
7. **검증** 1쪽에 `English`, `Odd Form`, `[41~42]`와 고유 지문을, 2쪽에 `English`, `Even Form`, `41.`, `42.`를 넣는다. 짝수형 문항에 지문이 없고 원본 지문이 보존되는지 확인한다.

### 5. 마커가 없는 born-digital 쪽의 전면 PNG 생성

1. **위치** [app/recognition/pipeline.py:262](<<repo>/app/recognition/pipeline.py:262>), `app/recognition/pipeline.py:351`, `app/recognition/pipeline.py:449`, `app/importers.py:363`
2. **현재 동작**
   ```python
   if not page.problems:
       return any_problems
   ```
   ```python
   page_box = Box.from_points(0.0, 0.0, float(page.width_px), float(page.height_px))
   try:
       image_png = cutout.problem_cutout_png(page_img, page_box, pad=0, trim=False)
   ```
3. **문제** 문항이 있는 PDF에 번호 없는 보충 자료 쪽이 섞이면, 추출 가능한 원문이 있어도 전면 PNG가 반환된다. 가져오기 경로는 이 항목의 편집형 본문을 비운다. 정상 연결될 공통 지문 쪽도 연결 판정 전에 일단 렌더한다.
4. **수정안** 약 25~40줄. 번호 없는 쪽의 지문 연결과 텍스트 유무를 먼저 판정한다. born-digital 미분류 쪽은 정렬된 텍스트·줄 좌표로 보존하고 그림이 확인된 경우에만 해당 영역을 자른다. 텍스트 없는 쪽은 기존 라우팅에 표시한다.
5. **예상 효과** 합성 문서의 텍스트 전용 미분류 쪽 1개당 전면 렌더와 전면 PNG 인코딩 각 1회 제거 추정. 앞쪽에 별도 공통 지문 쪽이 있으면 그 쪽의 선행 렌더도 1회 줄어든다. 초 단위 미확인.
6. **회귀 위험** 기존 검사는 혼합 문서에서 전면 폴백 PNG를 명시적으로 기대한다. 해당 검사의 보존 조건을 편집형 원문·좌표로 갱신하고, 정상 문항의 지역 그림 PNG는 계속 확인해야 한다. `scripts/verify_lazy_pdf_raster.py:65`
7. **검증** 일반 문항, 연결되는 공통 지문, 번호 없는 편집형 자료, 실제 도형이 있는 문항을 각각 한 쪽씩 만든다. 지문과 자료에 전면 PNG가 없고 문구·좌표가 보존되며 도형만 지역 PNG로 남는지 확인한다.

## 중요

### 6. 비대칭 2단에서 오른쪽 본문이 왼쪽 문항으로 이동

1. **위치** [app/recognition/pdf_segment.py:700](<<repo>/app/recognition/pdf_segment.py:700>), `app/recognition/pdf_segment.py:717`, `app/recognition/pdf_segment.py:737`
2. **현재 동작**
   ```python
   split_x = width_px / 2.0
   left_col = [m for _, m in pairs[: split_index + 1]]
   right_col = [m for _, m in pairs[split_index + 1:]]
   return [left_col, right_col], [(0.0, split_x), (split_x, width_px)]
   ```
3. **문제** 595pt 쪽에서 실제 단 사이 여백이 x≈225pt이고 오른쪽 단이 x=245pt에서 시작하면, 중심이 x=297.5pt 이전인 짧은 오른쪽 줄은 왼쪽 문항에 들어갈 수 있다. 클러스터 자체도 번호가 아니라 질문 전체 줄의 중심을 쓰므로 길이가 다른 제목의 영향을 받는다.
4. **수정안** 약 20~30줄. 번호 시작 x로 마커를 묶는다. 양쪽 본문 줄들이 반복해서 비워 둔 x 구간이 확인되면 그 구간 중앙을 단 경계로 쓴다.
5. **예상 효과** fixture에서 잘못 귀속된 오른쪽 짧은 줄 2개→0개 추정. 마커 수와 별도로 자식 줄의 소유를 검증할 수 있다.
6. **회귀 위험** 우측으로 들여쓴 한 단 자료가 두 번째 단처럼 보일 수 있다. 독립적인 번호군과 여러 줄에서 반복되는 여백을 함께 요구한다.
7. **검증** x=45pt와 x=245pt에서 번호를 시작하고 두 단의 같은 높이에 서로 다른 짧은 식별어를 둔다. 오른쪽 식별어 2개와 그 bbox가 오른쪽 문항에만 있는지 확인한다.

### 7. 붙여 쓴 번호·100번대·날짜처럼 보이는 질문 첫머리 누락

1. **위치** [app/recognition/pdf_segment.py:54](<<repo>/app/recognition/pdf_segment.py:54>), `app/recognition/pdf_segment.py:59`, `app/recognition/pdf_segment.py:424`
2. **현재 동작**
   ```python
   if _looks_like_date_header(text):
       continue
   match = _MARKER_RE.match(text)
   if not match:
       continue
   ```
3. **문제** 현재 패턴은 `12.Which ...`, `(12) ...`, `012. ...`, `100. ...`를 받지 않는다. 본문의 `12. 2026. ...`도 날짜 패턴이 `2026`을 `20`과 `26`으로 나눠 일치시킬 수 있어, 헤더 밖에서도 탈락한다.
4. **수정안** 약 20~30줄. 기존 후보를 먼저 확정한 후 변형 번호 후보를 검사한다. 같은 단의 번호 정렬·이웃 번호와 번호 뒤 글자 간격 또는 별도 span이 맞을 때만 채택한다. 날짜 제거는 본문 밖 머리글 위치 또는 별도의 날짜 줄 구조로 확인한다.
5. **예상 효과** `11.`, `12.Which`, `13.` 및 `99.`, `100.`, `101.` fixture에서 각각 문항 1개 복원 추정. 날짜처럼 보이는 본문 첫머리 검증을 별도로 둔다.
6. **회귀 위험** `1.5`, 날짜, `(1)`형 선지, 표 속 번호가 문항이 될 수 있다. 변형 번호는 문자 패턴과 기하 증거를 모두 요구한다.
7. **검증** 변형별로 이웃 번호와 같은 x에 놓고, 들여쓴 `1.5` 및 상단 인쇄일을 함께 넣는다. 합성 PDF의 `rawdict`에서 의도한 공백 유무를 확인한 후 번호 목록과 대조군 미검출을 검사한다.

### 8. 같은 쪽의 국어 공통 지문이 관련 문항에 연결되지 않음

1. **위치** [app/recognition/pdf_segment.py:1242](<<repo>/app/recognition/pdf_segment.py:1242>), `app/recognition/pipeline.py:467`, `app/recognition/pdf_segment.py:871`
2. **현재 동작**
   ```python
   if subject == Subject.ENGLISH:
       base_metadata["shared_passages"] = _english_shared_regions(
           text_lines, markers, descriptors, float(width_px), float(height_px), len(columns))
   ```
3. **문제** 국어 한 단 시험지의 `[12~13]` 안내와 지문이 첫 마커 `12.` 위에 있으면 어느 문항 박스에도 속하지 않는다. 파이프라인의 별도 지문 탐색은 문항이 없는 쪽에만 적용된다.
4. **수정안** 약 15~25줄. 독립된 범위 안내 줄, 같은 단의 지문 위치, 바로 다음 실제 마커의 번호 일치가 확인된 경우에 공통 지문 추출을 과목 공통으로 적용한다. 영어 전용 읽기 순서와 교차 단 처리는 별도 조건을 유지한다.
5. **예상 효과** fixture에서 누락된 지문 1개와 대응 줄 좌표를 복원해 첫 문항에서 편집 가능하게 연결할 수 있다.
6. **회귀 위험** 수학의 `[1-3]` 표현이나 인용문 안 범위가 지문 안내로 잘못 해석될 수 있다. 독립 안내 줄과 바로 뒤 시작 번호를 둘 다 확인한다.
7. **검증** 같은 쪽에 국어 지문, `[12~13]` 안내, `12.`, `13.`을 넣고 `Subject.KOREAN`으로 인식한다. 번호 목록 `[12, 13]`과 첫 문항의 공통 지문 범위·텍스트·좌표를 확인한다. 별도의 본문 중간 `[1-3]`은 본문에 남겨 둔다.

### 9. 번호형 선지 억제가 들여쓰기와 섹션 번호 재시작에 취약

1. **위치** [app/recognition/pdf_segment.py:218](<<repo>/app/recognition/pdf_segment.py:218>), `app/recognition/pdf_segment.py:249`, `scripts/verify_marker_regression.py:76`
2. **현재 동작**
   ```python
   if isinstance(choice_next, int) and near_previous and number == choice_next:
       reject_as_choice = True
   elif near_previous and number <= last_problem:
       reject_as_choice = True
   ```
3. **문제** A4에서 x=72pt의 `12.` 아래 x=112pt의 `1)`~`5)`는 기본 DPI의 동일 레인 허용폭을 벗어난다. 새 레인에서는 증가하는 선지 번호가 모두 문항으로 채택될 수 있다. 같은 x에서는 `12.` 바로 뒤 섹션의 실제 `1)`, `2)`가 감소 번호와 선지 연속 상태 때문에 사라질 수 있다.
4. **수정안** 약 25~40줄. 문항 시작 x는 채택된 제목으로만 갱신한다. 번호형 선지는 부모 문항 단 안에서 공통 들여쓰기와 `1`부터의 연속 배치가 확인되면 억제한다. 별도 섹션 제목과 정렬된 번호 재시작이 함께 확인되면 레인 상태를 초기화한다.
5. **예상 효과** 들여쓴 선지 fixture에서 문항 6→1개, 섹션 재시작 fixture에서는 실제 문항 2개 복원 추정.
6. **회귀 위험** 문제 번호와 선지가 같은 x에서 시작하는 기존 양식, 선지가 2개뿐인 문항, 다른 단의 작은 번호가 동시에 나오는 경우다.
7. **검증** 두 쪽짜리 합성 PDF에 깊은 들여쓰기 선지와 섹션 제목 뒤 번호 재시작을 각각 만든다. 예상 번호가 `[12]`, `[12, 1, 2]`인지 확인하고 기존 번호형 선지 케이스도 유지한다.

### 10. 3단 또는 한 쪽 안의 1단·다단 혼합을 전역 2분할로 처리

1. **위치** [app/recognition/pdf_segment.py:707](<<repo>/app/recognition/pdf_segment.py:707>), `app/recognition/pdf_segment.py:1240`, `app/recognition/pipeline.py:553`
2. **현재 동작**
   ```python
   largest_gap, split_index = max(gaps, key=lambda item: item[0])
   if largest_gap < max(80.0, width_px * 0.18):
       # 단일 컬럼
       return [[m for _, m in pairs]], [(0.0, width_px)]
   ```
3. **문제** 위쪽에 전폭 문항, 아래쪽에 3단 문항이 있는 교사 편집 시험지는 한 쪽 전체에서 최대 간격 하나만 선택한다. 가운데 단이 옆 단에 합쳐져 문항 순서가 섞이고, 전폭 줄은 중심 x가 가리키는 단의 줄로 분류될 수 있다.
4. **수정안** 약 40~60줄. 두 개의 지속적인 단 사이 여백과 독립 번호군이 확인되는 구간에만 3단을 적용한다. 위쪽의 전폭 번호·본문은 별도 수직 구간으로 배정하고, 구간→단→y 순서를 파이프라인 최종 정렬까지 전달한다.
5. **예상 효과** 상단 1개와 하단 3단에 2개씩 배치한 fixture에서 7개 문항의 원본 순서와 소유를 복원하는 것이 목표다. 적용 빈도는 미확인이다.
6. **회귀 위험** 전폭 표, 3열 선지, 머리글을 레이아웃 전환으로 오인할 수 있다. `column_count=3`의 작성기 소비도 미확인이다.
7. **검증** x≈200·400pt에 아래쪽 단 사이 여백을 만들고 각 단에 번호 2개를 넣는다. 위에는 가운데 경계를 넘는 긴 문항 줄을 둔다. `segment_pdf`와 `recognize_pdf` 모두에서 번호 순서와 문항별 식별어를 확인한다.

### 11. DPI에 따라 같은 그림의 검출 여부가 달라짐

1. **위치** [app/recognition/pipeline.py:221](<<repo>/app/recognition/pipeline.py:221>), `app/recognition/pdf_segment.py:665`, `app/recognition/pdf_segment.py:1391`
2. **현재 동작**
   ```python
   if figure.area >= _MIN_FIGURE_AREA_PX
   and figure.width >= 60.0
   and figure.height >= 60.0
   and (counts[index] < 24 or index in chart_indexes)
   ```
3. **문제** 같은 80×80pt 도형이 72 DPI에서는 6,400px², 150 DPI에서는 약 27,778px²다. 고정 22,000px² 기준을 150 DPI에서만 통과한다. 세그멘터의 문자 수 집계에도 같은 픽셀 기준이 따로 들어 있다.
4. **수정안** 약 15~25줄. 150 DPI의 현재 기준을 PT·PT²로 환산한 공통 조건을 그림 판정과 문자 수 집계에서 사용한다. 출력 bbox는 픽셀 계약을 유지한다.
5. **예상 효과** 해당 fixture에서 72/150/300 DPI 모두 동일한 그림 후보 1개와 동일 문항 소유를 얻는 것이 목표다.
6. **회귀 위험** 저해상도에서 작은 그림이 보존되면서 컷아웃 하한이나 트림에 걸릴 수 있다. 후보 판정과 실제 PNG 생성 결과를 함께 비교한다.
7. **검증** 빈 사각형 테두리와 내부 대각선으로 80×80pt 도형을 만들고 세 DPI에서 인식한다. 그림 수와 문항 번호가 같고 PT로 환산한 bbox가 허용 오차 내에 있는지 확인한다.

### 12. 영어 원문 판정이 모든 쪽의 텍스트를 다시 추출

1. **위치** [app/recognition/pipeline.py:113](<<repo>/app/recognition/pipeline.py:113>), `app/recognition/pipeline.py:437`, `app/recognition/pdf_segment.py:388`
2. **현재 동작**
   ```python
   header_lines = ["".join(span.get("text", "") for span in line.get("spans", []))
                   for block in page.get_text("dict").get("blocks", [])
                   for line in block.get("lines", [])
                   if line["bbox"][1] <= page.rect.height * .25]
   ```
3. **문제** 세그멘터가 이미 `rawdict`에서 줄을 추출했지만, 영어 원문 판정은 문서를 다시 열고 비영어 쪽까지 `dict` 전체를 추출한 후 상단 25%를 고른다.
4. **수정안** 약 20~35줄. 첫 추출에서 상단 판정용 줄을 원본 순서대로 전달한다. 파일명 힌트와 독립적인 영어 근거, 듣기 안내, 이후 다른 과목 머리글에 의한 초기화는 기존 조건을 재사용한다.
5. **예상 효과** 40쪽 합성 문서에서 문서 재열기 1회와 `get_text("dict")` 40회 제거 추정. 영어 차트 분석의 별도 추출과 전체 절감 시간은 미확인이다.
6. **회귀 위험** 세그멘터의 y 정렬을 그대로 사용하면 여러 줄에 나뉜 안내가 원래 순서와 다르게 합쳐질 수 있다. 추출 실패 쪽의 원문 판정도 비교해야 한다.
7. **검증** 영어 제목, 제목 없이 듣기 안내만 있는 쪽, 제목 없는 후속 쪽, 수학 머리글로 바뀌는 쪽을 만든다. `source_literal_text`가 기존과 동일하고 별도 `dict` 추출 횟수가 0인지 계측한다.

### 13. 긴 지문이 깨진 핵심 수식의 PUA 비율을 희석

1. **위치** [app/recognition/pipeline.py:185](<<repo>/app/recognition/pipeline.py:185>), `app/recognition/pipeline.py:277`, `app/recognition/pipeline.py:506`, `app/math_text.py:454`
2. **현재 동작**
   ```python
   text_reliable = _pua_ratio(raw_text) < _PUA_UNRELIABLE_RATIO
   text = _clean_pua(raw_text)
   ```
3. **문제** 일반 본문 180자와 미복원 PUA 8개뿐인 독립 수식 줄이 섞이면 전체 비율은 약 4.3%다. 현재 문항 신뢰도는 높게 남지만, 정규화에서 미복원 문자의 연속 구간이 `□`로 축약될 수 있다.
4. **수정안** 약 15~25줄. 문항 전체 비율과 별도로, 미복원 PUA가 몰린 줄을 글꼴·bbox 증거와 함께 표시한다. 해당 줄의 원래 문자와 좌표를 수식 복원 경로에 전달한다. 표시 자체로 문항 전체를 이미지 처리하지 않는다.
5. **예상 효과** fixture의 깨진 수식 줄 탐지 0→1개 추정. 후속 네이티브 수식 복원 성공률은 미확인이다.
6. **회귀 위험** 장식 글리프나 복원 가능한 한컴 수식 문자가 깨진 수식으로 표시될 수 있다. 기존 매핑으로 복원되는 글리프와 미복원 글리프를 같은 fixture에 둔다.
7. **검증** 합성 PDF의 별도 수식 폰트에 `ToUnicode` 매핑을 넣어 미매핑 PUA 8개를 한 줄에 노출한다. 매핑된 수식 줄과 일반 본문을 함께 넣고, 미복원 줄만 표시되며 원래 문자 좌표가 보존되는지 확인한다.

## 사소

### 14. 그림 병합이 PDF의 도형 기록 순서에 의존

1. **위치** [app/recognition/pdf_segment.py:571](<<repo>/app/recognition/pdf_segment.py:571>), `app/recognition/pdf_segment.py:587`, `app/recognition/pdf_segment.py:651`
2. **현재 동작**
   ```python
   candidate = _union_box(current, items[j])
   if max_width is not None and candidate.width > max_width:
       continue
   if max_height is not None and candidate.height > max_height:
       continue
   ```
3. **문제** 가까운 A–B–C의 두 인접 쌍은 각각 높이 상한을 통과하지만 셋을 합치면 상한을 넘는 경우다. 동일하게 인쇄되는 벡터 도형도 저장 순서에 따라 `A+B, C` 또는 `A, B+C`가 된다. 떨어진 박스가 많을 때도 매 순회에서 모든 후속 박스와 비교한다.
4. **수정안** 약 15~30줄. 기하 정렬로 입력 순서를 고정하고, 가까운 후보만 비교하도록 구간을 제한한다. 인접한 합성 후보가 여러 개면 거리와 합성 크기로 일관되게 결정한다.
5. **예상 효과** 같은 출력 모양을 가진 두 fixture의 그림 bbox 집합이 일치한다. 겹치지 않는 박스 N개에서 첫 순회의 최대 `N(N−1)/2` 비교를 줄일 수 있다. 초 단위 미확인.
6. **회귀 위험** 떨어진 축·격자·곡선이 하나의 그래프를 이루는 경우가 분리될 수 있다. 실제 그래프 형태의 양성 대조군을 둔다.
7. **검증** 서로 3pt씩 떨어진 높이 약 160pt의 벡터 박스 세 개를 정순·역순으로 그린다. 그림 bbox 집합과 각 그림의 소유 문항을 비교하고, 격자와 곡선이 들어간 대조군은 한 영역으로 유지되는지 확인한다.

### 15. 잘라낼 줄에도 문자별 좌표 사전을 미리 생성

1. **위치** [app/recognition/pdf_segment.py:400](<<repo>/app/recognition/pdf_segment.py:400>), `app/recognition/pdf_segment.py:312`, `app/recognition/pdf_segment.py:1070`
2. **현재 동작**
   ```python
   item = {"box": box, "text": text}
   item.update(_line_geometry_payload(line, scale))
   lines.append(item)
   ```
3. **문제** 페이지 번호, 저작권 푸터, 문항 영역 밖 안내도 먼저 모든 글자에 대해 bbox와 사전을 만든다. 그 뒤에야 푸터를 지우거나 문항 소유에서 제외한다. 텍스트 추출 자체는 그대로 필요하지만, 버려질 줄의 추가 Python 객체 할당은 피할 수 있다.
4. **수정안** 약 20~35줄. 첫 단계에는 줄 텍스트·bbox와 원본 span 참조만 둔다. 푸터 판정 이후 문항·공통 지문으로 채택된 줄, 영어 빈칸·그림 문자 집계에 실제 필요한 줄에서만 좌표 페이로드를 한 번 만든다.
5. **예상 효과** 페이지당 50자짜리 제외 줄 8개가 있는 40쪽 fixture에서 최대 16,000개 문자 사전 생성을 피하는 것으로 추정한다. 초 단위 미확인.
6. **회귀 위험** 영어 빈칸이나 그림 내부 문자 수 판정 전에 좌표를 준비하지 않으면 품질이 떨어진다. 필요한 줄에서의 생성 시점과 원본 출력 동등성을 검사한다.
7. **검증** 반복 푸터와 본문 밖 안내를 여러 쪽에 삽입하고, 영어 빈칸·표·도형이 들어간 대조 쪽을 추가한다. 문자 사전 생성 횟수가 감소하는 동시에 문항, 공통 지문, 그림 귀속, 보존된 줄 좌표가 동일한지 확인한다.

=== 끝 ===
