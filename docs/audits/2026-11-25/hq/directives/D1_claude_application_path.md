# D1 Claude — 인식 결과의 적용 경로 추적

## 역할
인식 산출이 가져오기와 편집형 작성기까지 흘러가는 길을 끝에서 끝까지 추적해, 정보가 버려지거나 다시 계산되는 지점을 찾는 분석가.

## 볼 범위(저장소 경로 기준, 절대 경로로 읽는다)
- 출발: `app/recognition/pipeline.py`의 `RecognizedProblem`, `RecognitionResult`, `recognize_pdf`.
- 가져오기: `app/importers.py`에서 `recognize_pdf`를 부르는 함수와 그 뒤 문항 dict 조립부.
- 편집형 PDF 내보내기: `app/main.py`의 `_export_pdf_layout`(1011줄 부근) → `app/pdf_layout_writer.py`의 structured 작성 함수 → `app/pdf_question_units.py`, `app/pdf_native_content.py`, `app/pdf_source_page_memo.py`, `app/pdf_export_review.py`.
- Grep으로 `recognize_pdf(`, `segment_pdf(`, `fitz.open(`, `get_text(` 호출 지점을 모두 찾는다.

## 찾을 것
1. **중복 계산**: 한 번의 변환에서 같은 PDF를 몇 번 열고(`fitz.open`), 같은 페이지 텍스트를 몇 번 추출하는가. 호출 경로별로 센다. 메모(`pdf_source_page_memo`)가 덮지 못하는 경로.
2. **정보 손실**: 인식 단계가 만든 값(text_reliable, column_index, figure_boxes, line_geometries, routing, notices) 중 적용 단계가 읽지 않거나 다시 추정하는 것.
3. **신뢰도 미사용**: 인식이 불확실하다고 표시한 문항·페이지를 작성기가 확실한 것과 똑같이 다루는 곳. 사용자에게 문항별 상태로 전달되지 않는 곳.
4. **문항 단위 인벤토리 갭**: 문항별 원본 쪽·단·번호·선지 분리·이미지 폴백 상태를 JSON으로 내는 경로가 있는가, 어디가 비었는가.

## 출력
먼저 호출 흐름도(함수 이름과 `파일:줄`, 10~20줄). 그다음 D0의 7칸 형식으로 8~15건. 맨 위에 적용 경로 점수(100점)와 총평.
