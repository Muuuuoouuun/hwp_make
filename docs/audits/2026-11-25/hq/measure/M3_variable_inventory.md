# M3 변수 인벤토리 (하위 에이전트 보고의 본부 요약)

원문은 세션 대화 기록에 있다. 여기는 판정에 쓰는 핵심만 옮겼고, 본부가 코드로 다시 확인한 항목에 [확인]을 붙였다. 나머지는 [보고].

## 변환 호출 경로
`main.py:1004 export_pdf_layout` → `_conversion_slot` → `_export_pdf_layout(1011)` → `write_pdf_structured_hwpx(pdf_layout_writer.py:10111)` → `recognize_pdf(10139)` → `write_native_content(pdf_native_content.py:1924)`. 그 뒤 `inspect_pdf_editability(main.py:1111)`, `analyze_pdf_hwpx_fidelity(1130)`, `inspect_question_rendering(1135)`가 항상 이어진다. [보고]

## 속도·품질에 실제로 닿는 변수
| 이름 | 위치 | 기본값 | 노출 | 비고 |
|---|---|---|---|---|
| `max_pages` | main.py:139 | None(1~200) | API만 | 인식은 전 쪽을 돌린 뒤 걸러낸다(10139, 10200). 인식 시간은 안 줄어든다. [보고] |
| `variant_policy` | main.py:145 | "all" | API만(UI는 항상 all) | 홀·짝 형이 겹치면 절반만 변환(8쪽 이상 짝수쪽, 겹침 0.80 이상). [보고] |
| `native_math` | main.py:142 | True | API·UI | False면 수식이 텍스트로 남는다. [보고] |
| `strict` | main.py:148 | False | API만 | 검사 결과로 422를 낼지만 정한다. 속도 무관. [보고] |
| `math_ai_recognition` | main.py:143 | None | API·UI 체크박스 | **Gemini를 부르지 않는다.** 수학 양식에서 구 작성 경로로 보낼 뿐이다(10195). 구 경로 10207~10778에 수식 AI 참조 0건. [확인] |
| `math_ai_model` | main.py:144 | None | API | API 경로에 소비처 없음. [보고] |
| `boxed_passages`, `layout_mode`, `high_fidelity_math` | main.py:140·141, writer 10118 | - | API | 소비처 없는 죽은 옵션. [보고] |
| 인식 dpi | pdf_segment.py:1370, pipeline.py:418, cutout.py:27 | 150 | 미노출 | 리터럴 세 곳. 그림 PNG 해상도가 같은 dpi에 묶여 있다. [보고] |
| PUA 비율 | pipeline.py:32 | 0.12 | 미노출 | 래스터 트리거와 text_reliable 판정에 함께 쓴다. [보고] |
| `_CONVERSION_SLOTS` | main.py:52 | 2 | 미노출 | 초과 요청은 즉시 429. [보고] |
| 페이지 메모 | pdf_source_page_memo.py:38-47 | 64쪽 초과 시 비활성, 총 192MiB | 미노출 | 텍스트 dict만 공유. 인식 결과는 캐시하지 않는다. [보고] |
| 검수 3단계 생략 스위치 | main.py:1111·1130·1135 | 없음 | - | 편집성 검사·충실도 렌더·문항 렌더 검사를 끌 수 없다. [보고] |
| `artifact_mode` | fidelity:660, main.py:985 | API는 "failures" | 미노출 | 유효값 검증 없음. [보고] |

## 본부가 주목한 불일치·위험
1. **인식이 변환 한 번에 두 번 돈다**: 작성기(writer:10139)와 검수(pdf_question_inspection.py:339). 인식 결과 캐시 없음. [확인 — 호출 지점 두 곳 직접 읽음]
2. **수식 AI 체크박스가 이름과 다르게 동작**(위 표). [확인]
3. `_ai_available()`이 `recognize_pdf`마다 호출되고 키가 없으면 `build_ocr_backend("auto")`까지 간다(pipeline.py:293-314). 비용 미측정. [보고]
4. dpi를 바꾸면 깨지는 픽셀 절댓값: 42·80·70(선지 억제 하한), 8.0(그림 병합), 22000·900(그림 면적), 40, 6.0, 2.0 등. [보고]
5. 같은 개념의 임계값이 흩어져 있다: 그림 최소 면적 22000(pipeline.py:234, pdf_segment.py:665)과 900(pdf_segment.py:752, cutout.py:156), 겹침 0.6 세 곳, 머리글 밴드 0.05·0.13·0.20·0.25. [보고]
6. 쪽수 상한이 경로마다 다르다: 가져오기 500쪽, 편집형 변환 상한 없음, 웹 50쪽, 메모 64쪽. [보고]
7. `pdf_native_content.py:1642-1665`의 `bbox_px`·`page_width_px`는 이름과 달리 PDF 포인트 단위다. [보고]
8. 프런트에 요청 타임아웃이 없다. [보고]

## 미확인(에이전트가 밝힌 것)
rhwp `render_png` 해상도, `px_to_hwpunit` 호출처, paddleocr 설치 여부, 소영역 측정 렌더(Matrix 2~4배)의 호출 빈도.
