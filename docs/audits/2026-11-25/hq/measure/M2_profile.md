# M2 프로파일 — PDF→편집형 HWPX 변환(structured) 시간 분해

측정 2026-11-25 · 브랜치 `claude/recognition-develop-1125`(HEAD `50cd57c`) · 코드 무수정(실행 중 함수 감싸기와 cProfile만 사용) · 측정 스크립트·원자료: `<scratchpad>\measure\m2`

## 0. 요약

| 책자 | 쪽 | 총 초(최소 / 반복 범위) | 가장 큰 단계 | 반복 파싱 핵심 수치 |
|---|---:|---|---|---|
| 국어 | 40 | **95.0** (95.0–200.0, 2회) | 충실도 렌더 (_pdf_export_fidelity) 36.0s (38%) | 원본 fitz.open 101회 · get_text 539회 중 같은 (쪽,옵션) 재추출 299회 = 7.50s · 같은 (쪽,옵션) 최대 4회 · recognize_pdf 2회 · find_tables 쪽당 2회 |
| 수학 | 40 | **52.0** (52.0–98.2, 3회) | 충실도 렌더 (_pdf_export_fidelity) 30.5s (59%) | 원본 fitz.open 69회 · get_text 513회 중 같은 (쪽,옵션) 재추출 285회 = 3.32s · 같은 (쪽,옵션) 최대 4회 · recognize_pdf 2회 · find_tables 쪽당 2회 |
| 과학탐구 지구과학Ⅰ | 4 | **12.5** (12.5–58.8, 4회) | 작성 (writer - 인식) 4.2s (34%) | 원본 fitz.open 64회 · get_text 66회 중 같은 (쪽,옵션) 재추출 40회 = 1.67s · 같은 (쪽,옵션) 최대 4회 · recognize_pdf 2회 · find_tables 쪽당 2회 |

핵심:

1. **충실도 렌더가 최대 단계다.** 국어 36.0s, 수학 30.5s, 과학 3.8s. 그중 rhwp `render_png`가 국어 29.0s, 수학 24.1s, 과학 3.1s다. 쪽마다 한 번만 렌더하므로 중복은 아니다. 별도 측정에서 `render_png` 1회는 배율(0.25~1.0)과 `render_all_png` 여부에 관계없이 약 0.7~1.1초가 걸렸다. 픽셀 수에 비례하지 않고 호출마다 드는 고정비용이다. 같은 쪽 `render_svg`는 1~9ms였다(§5).
2. **같은 일을 두 번 하는 곳 가운데 큰 것은 세 가지다.** (a) `recognize_pdf` 전체가 2회 돈다(작성 1회 + 편집성 검수 1회). 국어 4.2s, 수학 2.2s, 과학 1.0s. (b) `find_tables`가 쪽마다 2회 돈다(작성 1회 + 검수 1회). 국어 4.2s, 수학 0.9s, 과학 0.4s. (c) 쪽 텍스트층 `dict`는 쪽마다 4회, `rawdict`는 3회 추출된다. 인식은 PDF를 메모리 스트림으로 열기 때문에 쪽 메모를 비켜 간다. (a)를 빼고도 국어 4.3s가 남는다.
3. **원본 PDF를 여는 횟수는 많지만 비용은 작다.** 국어 101회, 수학 69회, 과학 64회 연다. 그래도 여는 시간은 모두 합쳐 0.10s / 0.07s / 0.05s다. 비용은 열기가 아니라 다시 파싱하는 데서 나온다.
4. **검증 단계는 산출 HWPX를 바꾸지 않는다.** 모든 실행에서 작성 직후 HWPX의 sha256과 최종 sha256이 같았다. 작성 뒤 단계(범위·편집성·충실도·문항 렌더·보고서)는 국어 59.5s(63%), 수학 38.8s(75%), 과학 7.3s(58%)다. 이 단계들을 줄이거나 미뤄도 파일은 그대로다. 대신 보고서의 품질 지표가 비거나 늦어진다.
5. **절대 시간은 경합 때문에 크게 흔들렸다.** 같은 입력·같은 코드인데 과학 12.5~58.8s(4회), 수학 52.0~98.2s(3회), 국어 95.0~200.0s(2회)였다. CPU 시간도 부풀었다(수학 2회차 CPU 84.0s > 1회차 벽시계 52.0s). 표의 절대 초는 최소값 실행을 기준으로 하고, 비율과 호출 횟수를 근거로 삼는다. 호출 횟수는 같은 옵션의 모든 반복 실행에서 같았다.

## 1. 측정 조건

- 진입점: `app.main._export_pdf_layout(PdfLayoutExportPayload)`를 직접 호출했다(`app/main.py:1011`). API 핸들러 `export_pdf_layout`(`main.py:1004`)는 변환 슬롯 세마포어(`_conversion_slot`)만 더하므로 같은 경로다. 서버는 띄우지 않았다.
- 페이로드는 간단 변환 화면 기본값이다(`static/app.js:2767-2774`). `boxed_passages=true`, `layout_mode="structured"`, `variant_policy="all"`, `native_math=true`이고, `math_ai_recognition`은 보내지 않았다(None). PDF 바이트는 base64로 넣었다.
- 격리: 앱 모듈을 import하기 전에 `HWP_MAKE_DATA_DIR`를 실행마다 새로 만든 scratchpad 폴더(`runs/<label>/data`)로 지정했다. `GEMINI_API_KEY`/`OPENAI_API_KEY` 등은 프로세스 환경에서 제거했고, `HWP_MATH_AI_RECOGNITION=0`으로 두었다. 네트워크·GUI·서버·설치는 쓰지 않았다. 실행마다 별도 python 프로세스로 돌렸다(모듈 캐시·쪽 메모 오염 없음).
- 계측: `pymupdf.Document.__init__`, `Page.get_text`(옵션 문자열, clip·flags·sort·textpage 표시), `Page.get_textpage`, `get_drawings`/`get_cdrawings`, `get_pixmap`, `find_tables`, `get_images`/`get_image_info`, `rhwp.Document`(경로 파싱)·`from_bytes`·`render_png`·`render_svg`, `pdf_source_page_memo.page_memo`(적중/미스), 단계 함수 26개(벽시계와 이후 실행부터 process CPU)를 감쌌다. 원본 PDF는 내용 sha1로 판별했다(경로로 열든 스트림으로 열든 `SRC`).
- 환경: Windows 11, 논리 CPU 8, Python 3.14, PyMuPDF 1.27.2.2, rhwp 0.7.0+nativecell5(core 0.7.13), numpy 2.4.4, Pillow 12.3.0.
- **경합 경고:** 다른 측정(M1 인식 매트릭스 등)이 같은 PC에서 동시에 돌고 있었다. 같은 실행을 반복하면 벽시계가 최대 4.7배까지 흔들렸고, rhwp `render_png` 1쪽 비용도 0.60~1.85s로 흔들렸다(기본 옵션 반복 실행 기준). 절대 초는 부풀 수 있으니 실행별 비율과 호출 횟수(모든 반복에서 같음)를 근거로 쓴다. cProfile을 붙인 실행은 붙이지 않은 실행의 1.3~2.3배였다. 그래서 상위 함수 표는 순위와 비율만 본다.
- **작업 트리 변경(외부):** 측정 도중 01:44:16에 다른 작업자가 `app/recognition/pdf_segment.py`·`pipeline.py`를 고쳤다(미커밋, 이 측정은 손대지 않음). 그 뒤에 시작한 7회(`math_first2`, `math_nomath4`, `math_plain4`, `sci_nomath3`, `sci_nomath4`, `sci_plain5`, `sci_plain6`)는 HEAD가 아닌 트리에서 돌았다. 그래서 모든 표와 최소값에서 뺐다. 참고로 이 7회의 산출물도 정규화 비교로 HEAD 실행과 같았고, 호출 수도 같거나 거의 같았다(수학 get_pixmap 1320→1324). 그 밖의 실행(렌더 단가 측정 포함)은 모두 01:44 전에 시작했다.
- 산출물 동일성: 같은 옵션으로 반복한 실행끼리는 HWPX 바이트가 달랐다. 원인은 무작위 `id`·`instid`·`name="fraction:<난수>:…"` 값이다. 이 셋을 정규화하면 section XML이 같고, 정규화 없이 본문 텍스트만 비교해도 같다. 아래 '산출물 변화'는 이 정규화 비교 결과다(`m2_hwpx_diff.py`).

## 2. 단계 목록 (코드 근거)

| # | 단계 | 코드 | 비고 |
|---:|---|---|---|
| 1 | 업로드 디코드·저장, 실행 폴더·원본 복사 | `main.py:1014`, `1026`(importers.save_upload), `1062-1070` | 수 ms |
| 2 | **작성(writer)** `write_pdf_structured_hwpx` | `main.py:1074` → `pdf_layout_writer.py:10111` | AI 꺼짐이면 `10195`에서 `write_native_content`로 분기 |
| 2a | 인식 `recognize_pdf` (스트림으로 열어 `segment_pdf`, `_source_literal_english_pages`, `cutout.render_selected_page_images`) | `pdf_layout_writer.py:10139` → `recognition/pipeline.py:414`, `431`, `437`, `456` | 1회차 |
| 2b | 과목 판별 `detect_source_subject` | `pdf_layout_writer.py:10146` |  |
| 2c | 본문 추출 `extract_native_content` | `pdf_native_content.py:1940`(정의 `1358`) | 쪽별 줄·표·그림·분수·첨자 복원 |
| 2d | 문항 묶기 `annotate_question_groups` | `pdf_native_content.py:1948` |  |
| 2e | HWPX 쓰기 `hwpx_writer_v2.write_hwpx` | `pdf_native_content.py:1953` | `_save_hwpx_with_hancom_compat` → `apply_native_typography` |
| 2f | 머리글·선택지 탭(rhwp SVG)·배경 행 분할 | `pdf_native_content.py:1968`, `1970`, `1972` | 선택지 탭은 rhwp `render_svg`(`pdf_choice_measurement.py:108,114`) |
| 2g | 구조 집계·평문·□ 개수 | `pdf_native_content.py:1973-1975`, `2003` |  |
| 3 | 범위 `_pdf_export_scope` | `main.py:1100`(정의 `961`) | fitz.open 1회 |
| 4 | 패키지 검사 `_hwpx_package_problem` | `main.py:1104`(정의 `408`) | zip testzip |
| 5 | **검수: 편집성** `inspect_pdf_editability` | `main.py:1111` → `pdf_editability.py:168` | `inspect_question_units`(`:286`)가 **`recognize_pdf` 재실행**(`pdf_question_inspection.py:339`), `inspect_paragraph_flow`(`:296`), `inspect_source_images`(`:318`), 분수 복원(`:405`) |
| 6 | **충실도 렌더** `_pdf_export_fidelity` | `main.py:1130`(정의 `980`) → `pdf_layout_fidelity.py:652` | rhwp 파싱(`:693`), 쪽마다 `render_png`(`:708`→`:57`), PDF 쪽 `get_pixmap`(`:709`→`:241`), `_page_metrics`(`:722`) |
| 7 | **검수: 문항 렌더** `inspect_question_rendering` | `main.py:1135` → `pdf_question_rendering.py:435` | rhwp 파싱(`:525`) + 쪽마다 `render_svg`(`:531`) |
| 8 | 검수 종합 `build_export_review` | `main.py:1143` | ~0s |
| 9 | 보고서: 그림 참조·양식 프로필·열기 안전성·목표 점수·JSON 기록 | `main.py:1145`, `1146`, `1147`(`validate_editor_open_safety`), `1186`, `1233` |  |
| 10 | 정리: 쪽 메모 해제 | `main.py:1234`(`forget_file`) |  |

아래 표의 묶음은 다음과 같다. **인식** = 2a. **작성** = 2 − 2a. **검수** = 5(그 안의 `recognize_pdf` 재실행은 따로 표시) + 7 + 8. **충실도** = 6. **기타** = 1·3·4·9·10과 계측되지 않은 틈.

## 3.1 국어 — `2026_csat/문제지/국어/국어.pdf`

쪽수 많음(40쪽, 홀·짝형 2벌 합본), 문항 112, 그림 28, 수식 0. 표는 반복 실행 중 가장 빠른 `kor_plain`(총 95.03s) 기준이다. 결과는 objective_score 64.51, layout_view_sync 0.9333, review_ok False다. 작성 직후와 최종 HWPX의 sha256이 같았다: True.

### 단계 시간

| 단계 | 초 | 비중 |
|---|---:|---:|
| 인식 (writer 안 recognize_pdf) | 4.14 | 4.4% |
| 작성 (writer - 인식) | 31.42 | 33.1% |
| 검수: 편집성 검사 중 recognize_pdf 재실행 | 4.17 | 4.4% |
| 검수: 편집성 검사 나머지 | 14.22 | 15.0% |
| 검수: 문항 렌더 검사 + review | 3.26 | 3.4% |
| 충실도 렌더 (_pdf_export_fidelity) | 36.04 | 37.9% |
| 기타 (scope·package·보고서·open_safety·정리·미계측) | 1.77 | 1.9% |
| **합계** | **95.03** | 100% |

<details><summary>단계 타임라인(0.05s 미만 하위 단계 생략)</summary>

| 단계(시작 순) | 깊이 | 시작 s | 소요 s |
|---|---:|---:|---:|
| WRITER(total) | 0 | 0.04 | 35.56 |
|   recognize_pdf | 1 | 0.06 | 4.14 |
|     segment_pdf | 2 | 0.06 | 1.94 |
|   writer.detect_source_subject | 1 | 4.20 | 0.06 |
|   writer.write_native_content | 1 | 4.26 | 31.34 |
|     writer.native.extract_native_content | 2 | 4.26 | 19.14 |
|     writer.native.hwpx_writer_v2.write_hwpx | 2 | 23.40 | 9.97 |
|     writer.native.refresh_choice_tab_widths | 2 | 33.37 | 0.13 |
|     writer.native.split_background_frame_rows | 2 | 33.50 | 1.89 |
|     writer.native._source_box_glyph_count | 2 | 35.48 | 0.10 |
| scope | 0 | 35.60 | 0.02 |
| package_check | 0 | 35.62 | 0.01 |
| REVIEW.inspect_pdf_editability | 0 | 35.63 | 18.39 |
|   recognize_pdf | 1 | 37.37 | 4.17 |
|     segment_pdf | 2 | 37.37 | 1.94 |
| FIDELITY(_pdf_export_fidelity) | 0 | 54.02 | 36.04 |
| REVIEW.inspect_question_rendering | 0 | 90.07 | 3.26 |
| REVIEW.build_export_review | 0 | 93.33 | 0.00 |
| report.attach_fidelity_refs | 0 | 93.33 | 0.01 |
| report.inspect_layout_template_profile | 0 | 93.33 | 0.08 |
| report.open_safety | 0 | 93.42 | 1.57 |
| report.objective_score | 0 | 94.99 | 0.00 |
| cleanup.forget_file | 0 | 94.99 | 0.04 |

(importers.save_upload 29회는 표에서 생략)

</details>

### 호출 횟수

| 항목 | 값 |
|---|---|
| 원본 PDF fitz.open | 101회 (경로 95 / 메모리 6), 총 0.10s |
| 기타 fitz.open (이미지·새 문서 등) | 0회 |
| Page.get_text 총 | 539회, 10.74s |
| get_text 옵션별 | dict 159, rawdict 120, rawdict+tp 80, rawdict+flags195 52, dict+clip+flags195 52, text 40, words+clip 36 |
| get_text 옵션별 초 | dict 5.82, rawdict 4.44, rawdict+tp 0.16, rawdict+flags195 0.13, text 0.10, dict+clip+flags195 0.05, words+clip 0.03 |
| 같은 (문서,쪽,옵션) 최대 반복 | 4회 (('SRC', 1, 'dict')); 고유 키 240; 초과 호출 299회 = 7.50s |
| 같은 (문서,쪽,옵션 clip 무시) 최대 반복 | 8회; 초과 401회 = 7.70s |
| 반복 횟수 분포 (반복수:키 수) | {'1': 68, '2': 88, '3': 41, '4': 43} |
| Page.get_textpage (실제 텍스트층 생성) | 771회, 2.09s, 같은 쪽 최대 24회; API별 [['get_text', 371], ['find_tables', 320], ['get_image_info', 80]] |
| 쪽 메모(page_memo) 요청/적중 | 1012 / 839 |
| get_drawings | 945회 3.00s, 같은 쪽 최대 40회, 초과 2.90s |
| get_cdrawings | 945회 2.17s, 같은 쪽 최대 40회, 초과 2.11s |
| get_pixmap | 260회 3.43s, 같은 쪽·크기 최대 4회 |
| find_tables | 80회 8.22s, 같은 쪽 최대 2회, 초과 4.17s |
| rhwp 파싱 | 2회 0.08s, 같은 내용 최대 2회 |
| rhwp render_png | 40회 28.99s |
| rhwp render_svg | 44회 0.33s, 같은 쪽(문서 무관) 최대 1회 |
| recognize_pdf / segment_pdf | 2회 / 2회 |

단계별로 나눈 호출 수(초):

| 단계 | fitz_open_SRC | get_text | memo_hit | memo_miss | get_drawings | get_pixmap | find_tables | rhwp_parse | rhwp_render_png | rhwp_render_svg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WRITER(total) > recognize_pdf | 3 (0.00s) | 80 (2.92s) |  |  | 40 (0.09s) | 10 (0.41s) |  |  |  |  |
| WRITER(total) > writer.detect_source_subject | 1 (0.00s) | 2 (0.01s) | 2 (0.00s) | 3 (0.09s) | 1 (0.02s) |  |  |  |  |  |
| WRITER(total) > writer.write_native_content | 51 (0.05s) | 242 (3.15s) | 442 (0.36s) | 158 (6.88s) | 572 (1.84s) | 120 (1.24s) | 40 (4.04s) |  |  |  |
| scope | 1 (0.02s) |  |  |  |  |  |  |  |  |  |
| REVIEW.inspect_pdf_editability | 41 (0.03s) | 135 (1.65s) | 395 (0.29s) | 12 (0.51s) | 292 (0.96s) | 80 (0.88s) | 40 (4.17s) |  |  |  |
| REVIEW.inspect_pdf_editability > recognize_pdf | 3 (0.00s) | 80 (3.00s) |  |  | 40 (0.08s) | 10 (0.43s) |  |  |  |  |
| FIDELITY(_pdf_export_fidelity) | 1 (0.00s) |  |  |  |  | 40 (0.47s) |  | 1 (0.04s) | 40 (28.98s) |  |
| REVIEW.inspect_question_rendering |  |  |  |  |  |  |  | 1 (0.04s) |  | 44 (0.33s) |

get_text 호출 위치(첫 app 프레임, 쪽 메모 프레임 제외) 상위:

| 호출 위치 | 회 | 초 |
|---|---:|---:|
| `app/recognition/pdf_segment.py:388(_extract_text_lines)` | 80 | 3.02 |
| `app/recognition/pipeline.py:116(_source_literal_english_pages)` | 80 | 2.90 |
| `app/pdf_running_heading_audit.py:21(inspect_running_header_fields)` | 39 | 1.49 |
| `app/pdf_source_characters.py:69(restore_bitmap_characters)` | 40 | 1.43 |
| `app/pdf_inline_labels.py:25(source_inline_labels)` | 39 | 1.41 |
| `app/pdf_source_semantics.py:417(source_grid_cells)` | 84 | 0.13 |
| `app/pdf_native_content.py:1429(extract_native_content)` | 84 | 0.11 |
| `app/pdf_layout_writer.py:2488(_iter_text_lines_uncached)` | 40 | 0.11 |
| `app/pdf_layout_writer.py:161(<genexpr>)` | 40 | 0.10 |
| `app/pdf_editability.py:423(inspect_pdf_editability)` | 12 | 0.02 |
| `app/pdf_masthead_visibility.py:44(visible_masthead_lines)` | 1 | 0.01 |

### cProfile 누적 시간 상위 25 (`kor_prof`, 총 215.9s, 내장·측정 래퍼 제외)

| # | 함수 | 위치 | 호출 | tottime | cumtime |
|---:|---|---|---:|---:|---:|
| 1 | `_export_pdf_layout` | `app/main.py:1011` | 1 | 0.00 | 215.93 |
| 2 | `_pdf_export_fidelity` | `app/main.py:980` | 1 | 0.01 | 99.58 |
| 3 | `analyze_pdf_hwpx_fidelity` | `app/pdf_layout_fidelity.py:652` | 1 | 0.04 | 99.58 |
| 4 | `_render_hwpx_page` | `app/pdf_layout_fidelity.py:56` | 40 | 0.01 | 84.81 |
| 5 | `render_png` | `site-packages/rhwp/document.py:259` | 40 | 0.00 | 84.29 |
| 6 | `write_pdf_structured_hwpx` | `app/pdf_layout_writer.py:10111` | 1 | 0.00 | 62.34 |
| 7 | `write_native_content` | `app/pdf_native_content.py:1924` | 1 | 0.00 | 56.98 |
| 8 | `extract_native_content` | `app/pdf_native_content.py:1358` | 1 | 0.11 | 38.41 |
| 9 | `inspect_pdf_editability` | `app/pdf_editability.py:168` | 1 | 0.36 | 37.98 |
| 10 | `inspect_question_units` | `app/pdf_question_inspection.py:181` | 1 | 0.16 | 16.12 |
| 11 | `write_hwpx` | `app/hwpx_writer_v2.py:1092` | 1 | 0.13 | 15.21 |
| 12 | `find_tables` | `site-packages/pymupdf/table.py:2593` | 80 | 0.06 | 14.73 |
| 13 | `find_tables` | `site-packages/pymupdf/__init__.py:11389` | 80 | 0.00 | 14.73 |
| 14 | `_page_metrics` | `app/pdf_layout_fidelity.py:581` | 40 | 0.23 | 12.27 |
| 15 | `__init__` | `site-packages/pymupdf/__init__.py:14600` | 3725655 | 2.98 | 11.88 |
| 16 | `get_text` | `site-packages/pymupdf/__init__.py:12150` | 539 | 0.00 | 11.24 |
| 17 | `get_text` | `site-packages/pymupdf/utils.py:459` | 539 | 0.01 | 11.24 |
| 18 | `inspect_question_rendering` | `app/pdf_question_rendering.py:435` | 1 | 0.30 | 11.05 |
| 19 | `_save_hwpx_with_hancom_compat` | `app/hwpx_writer_v2.py:620` | 1 | 0.09 | 10.52 |
| 20 | `recognize_pdf` | `app/recognition/pipeline.py:414` | 2 | 0.01 | 10.40 |
| 21 | `_textpage_dict` | `site-packages/pymupdf/__init__.py:16420` | 463 | 0.00 | 10.31 |
| 22 | `_getNewBlockList` | `site-packages/pymupdf/__init__.py:16417` | 463 | 0.00 | 10.30 |
| 23 | `JM_make_textpage_dict` | `site-packages/pymupdf/__init__.py:20733` | 463 | 0.00 | 10.30 |
| 24 | `JM_make_textpage_dict` | `site-packages/pymupdf/extra.py:200` | 463 | 0.17 | 10.29 |
| 25 | `_semantic_line_groups` | `app/pdf_native_content.py:183` | 428 | 0.05 | 9.73 |

자기 시간(tottime) 상위:

| # | 함수 | 위치 | 호출 | tottime |
|---:|---|---|---:|---:|
| 1 | `handle_args` | `site-packages/pymupdf/__init__.py:24011` | 3725655 | 3.68 |
| 2 | `_visible_svg_text` | `app/pdf_question_rendering.py:325` | 44 | 3.56 |
| 3 | `deepcopy` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:110` | 14338996 | 3.38 |
| 4 | `__init__` | `site-packages/pymupdf/__init__.py:14600` | 3725655 | 2.98 |
| 5 | `_deepcopy_tuple` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:181` | 1631656 | 1.86 |
| 6 | `_deepcopy_dict` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:198` | 843980 | 1.78 |
| 7 | `util_make_rect` | `site-packages/pymupdf/__init__.py:23972` | 3725655 | 1.62 |
| 8 | `make_tuple` | `site-packages/pymupdf/__init__.py:24001` | 3661163 | 1.27 |
| 9 | `_max_filter` | `app/pdf_layout_fidelity.py:253` | 1120 | 1.27 |
| 10 | `_compile` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\re\__init__.py:330` | 3402303 | 1.22 |
| 11 | `__init__` | `site-packages/pymupdf/__init__.py:14154` | 1340756 | 1.20 |
| 12 | `_binary_runs` | `app/pdf_layout_writer.py:6152` | 128960 | 1.12 |
| 13 | `include_rect` | `site-packages/pymupdf/__init__.py:14707` | 876558 | 1.12 |
| 14 | `_set_paragraph_space` | `app/pdf_source_spacing.py:70` | 1152 | 1.12 |
| 15 | `JM_rect_from_py` | `site-packages/pymupdf/__init__.py:21309` | 1879411 | 1.06 |

내장(C 확장) tottime 상위: `<method 'render_png' of 'rhwp._rhwp._Document' objects>` 84.29s/40회, `<built-in method pymupdf._extra.JM_make_textpage_dict>` 10.13s/463회, `<built-in method builtins.isinstance>` 2.96s/32350067회, `<method 'encode' of 'ImagingEncoder' objects>` 2.62s/25961회, `<built-in method pymupdf._mupdf.fz_run_display_list>` 2.51s/260회, `<built-in method builtins.len>` 2.14s/25062675회, `<built-in method pymupdf._extra.get_cdrawings>` 2.12s/945회, `<built-in method pymupdf._extra.page_get_textpage>` 2.08s/771회, `<method 'reduce' of 'numpy.ufunc' objects>` 1.91s/50373회, `<method 'get' of 'dict' objects>` 1.73s/15565913회

## 3.2 수학 — `2026_csat/문제지/수학/수학.pdf`

수식 많음(40쪽, 홀·짝형 2벌 합본), 문항 92, 편집 수식 710. 표는 반복 실행 중 가장 빠른 `math_plain`(총 51.97s) 기준이다. 결과는 objective_score 67.9, layout_view_sync 0.9837, review_ok True다. 작성 직후와 최종 HWPX의 sha256이 같았다: True.

### 단계 시간

| 단계 | 초 | 비중 |
|---|---:|---:|
| 인식 (writer 안 recognize_pdf) | 2.19 | 4.2% |
| 작성 (writer - 인식) | 10.96 | 21.1% |
| 검수: 편집성 검사 중 recognize_pdf 재실행 | 2.16 | 4.2% |
| 검수: 편집성 검사 나머지 | 4.73 | 9.1% |
| 검수: 문항 렌더 검사 + review | 0.65 | 1.2% |
| 충실도 렌더 (_pdf_export_fidelity) | 30.51 | 58.7% |
| 기타 (scope·package·보고서·open_safety·정리·미계측) | 0.76 | 1.5% |
| **합계** | **51.97** | 100% |

<details><summary>단계 타임라인(0.05s 미만 하위 단계 생략)</summary>

| 단계(시작 순) | 깊이 | 시작 s | 소요 s |
|---|---:|---:|---:|
| WRITER(total) | 0 | 0.03 | 13.15 |
|   recognize_pdf | 1 | 0.04 | 2.19 |
|     segment_pdf | 2 | 0.04 | 0.83 |
|   writer.write_native_content | 1 | 2.27 | 10.90 |
|     writer.native.extract_native_content | 2 | 2.27 | 6.50 |
|     writer.native.hwpx_writer_v2.write_hwpx | 2 | 8.77 | 3.41 |
|     writer.native.refresh_choice_tab_widths | 2 | 12.18 | 0.15 |
|     writer.native.split_background_frame_rows | 2 | 12.33 | 0.69 |
|     writer.native._source_box_glyph_count | 2 | 13.08 | 0.09 |
| scope | 0 | 13.18 | 0.02 |
| package_check | 0 | 13.20 | 0.00 |
| REVIEW.inspect_pdf_editability | 0 | 13.20 | 6.90 |
|   recognize_pdf | 1 | 13.85 | 2.16 |
|     segment_pdf | 2 | 13.85 | 0.80 |
| FIDELITY(_pdf_export_fidelity) | 0 | 20.10 | 30.51 |
| REVIEW.inspect_question_rendering | 0 | 50.61 | 0.65 |
| REVIEW.build_export_review | 0 | 51.26 | 0.00 |
| report.attach_fidelity_refs | 0 | 51.26 | 0.00 |
| report.inspect_layout_template_profile | 0 | 51.26 | 0.04 |
| report.open_safety | 0 | 51.31 | 0.65 |
| report.objective_score | 0 | 51.95 | 0.00 |
| cleanup.forget_file | 0 | 51.96 | 0.01 |

(importers.save_upload 17회는 표에서 생략)

</details>

### 호출 횟수

| 항목 | 값 |
|---|---|
| 원본 PDF fitz.open | 69회 (경로 63 / 메모리 6), 총 0.07s |
| 기타 fitz.open (이미지·새 문서 등) | 0회 |
| Page.get_text 총 | 513회, 4.81s |
| get_text 옵션별 | dict 159, rawdict 120, rawdict+tp 80, rawdict+flags195 54, text 40, dict+clip+flags195 36, words+clip 24 |
| get_text 옵션별 초 | dict 2.62, rawdict 1.97, text 0.09, rawdict+tp 0.07, rawdict+flags195 0.05, dict+clip+flags195 0.02, words+clip 0.01 |
| 같은 (문서,쪽,옵션) 최대 반복 | 4회 (('SRC', 1, 'dict')); 고유 키 228; 초과 호출 285회 = 3.32s |
| 같은 (문서,쪽,옵션 clip 무시) 최대 반복 | 8회; 초과 381회 = 3.38s |
| 반복 횟수 분포 (반복수:키 수) | {'1': 66, '2': 80, '3': 41, '4': 41} |
| Page.get_textpage (실제 텍스트층 생성) | 709회, 0.79s, 같은 쪽 최대 27회; API별 [['get_text', 373], ['find_tables', 256], ['get_image_info', 80]] |
| 쪽 메모(page_memo) 요청/적중 | 998 / 823 |
| get_drawings | 653회 1.30s, 같은 쪽 최대 31회, 초과 1.28s |
| get_cdrawings | 653회 1.07s, 같은 쪽 최대 31회, 초과 1.05s |
| get_pixmap | 1320회 2.47s, 같은 쪽·크기 최대 15회 |
| find_tables | 80회 1.66s, 같은 쪽 최대 2회, 초과 0.88s |
| rhwp 파싱 | 3회 0.04s, 같은 내용 최대 2회 |
| rhwp render_png | 40회 24.07s |
| rhwp render_svg | 118회 0.06s, 같은 쪽(문서 무관) 최대 2회 |
| recognize_pdf / segment_pdf | 2회 / 2회 |

단계별로 나눈 호출 수(초):

| 단계 | fitz_open_SRC | get_text | memo_hit | memo_miss | get_drawings | get_pixmap | find_tables | rhwp_parse | rhwp_render_png | rhwp_render_svg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WRITER(total) > recognize_pdf | 3 (0.00s) | 80 (1.34s) |  |  | 40 (0.03s) | 14 (0.39s) |  |  |  |  |
| WRITER(total) > writer.detect_source_subject | 1 (0.00s) | 2 (0.01s) | 2 (0.00s) | 3 (0.06s) | 1 (0.01s) |  |  |  |  |  |
| WRITER(total) > writer.write_native_content | 33 (0.03s) | 228 (1.39s) | 428 (0.16s) | 158 (2.96s) | 368 (0.74s) | 486 (0.71s) | 40 (0.78s) | 1 (0.01s) |  | 78 (0.01s) |
| scope | 1 (0.02s) |  |  |  |  |  |  |  |  |  |
| REVIEW.inspect_pdf_editability | 27 (0.02s) | 123 (0.75s) | 393 (0.12s) | 14 (0.17s) | 204 (0.49s) | 766 (0.60s) | 40 (0.88s) |  |  |  |
| REVIEW.inspect_pdf_editability > recognize_pdf | 3 (0.00s) | 80 (1.32s) |  |  | 40 (0.03s) | 14 (0.43s) |  |  |  |  |
| FIDELITY(_pdf_export_fidelity) | 1 (0.00s) |  |  |  |  | 40 (0.34s) |  | 1 (0.01s) | 40 (24.07s) |  |
| REVIEW.inspect_question_rendering |  |  |  |  |  |  |  | 1 (0.01s) |  | 40 (0.06s) |

get_text 호출 위치(첫 app 프레임, 쪽 메모 프레임 제외) 상위:

| 호출 위치 | 회 | 초 |
|---|---:|---:|
| `app/recognition/pdf_segment.py:388(_extract_text_lines)` | 80 | 1.34 |
| `app/recognition/pipeline.py:116(_source_literal_english_pages)` | 80 | 1.33 |
| `app/pdf_running_heading_audit.py:21(inspect_running_header_fields)` | 39 | 0.67 |
| `app/pdf_source_characters.py:69(restore_bitmap_characters)` | 40 | 0.62 |
| `app/pdf_inline_labels.py:25(source_inline_labels)` | 39 | 0.62 |
| `app/pdf_layout_writer.py:161(<genexpr>)` | 40 | 0.08 |
| `app/pdf_source_semantics.py:417(source_grid_cells)` | 70 | 0.07 |
| `app/pdf_layout_writer.py:2488(_iter_text_lines_uncached)` | 40 | 0.03 |
| `app/pdf_native_content.py:1429(extract_native_content)` | 70 | 0.03 |
| `app/pdf_editability.py:423(inspect_pdf_editability)` | 14 | 0.01 |
| `app/pdf_masthead_visibility.py:44(visible_masthead_lines)` | 1 | 0.01 |

### cProfile 누적 시간 상위 25 (`math_prof`, 총 69.7s, 내장·측정 래퍼 제외)

| # | 함수 | 위치 | 호출 | tottime | cumtime |
|---:|---|---|---:|---:|---:|
| 1 | `_export_pdf_layout` | `app/main.py:1011` | 1 | 0.00 | 69.71 |
| 2 | `_pdf_export_fidelity` | `app/main.py:980` | 1 | 0.00 | 31.91 |
| 3 | `analyze_pdf_hwpx_fidelity` | `app/pdf_layout_fidelity.py:652` | 1 | 0.07 | 31.91 |
| 4 | `_render_hwpx_page` | `app/pdf_layout_fidelity.py:56` | 40 | 0.01 | 25.39 |
| 5 | `render_png` | `site-packages/rhwp/document.py:259` | 40 | 0.00 | 25.24 |
| 6 | `write_pdf_structured_hwpx` | `app/pdf_layout_writer.py:10111` | 1 | 0.00 | 23.57 |
| 7 | `write_native_content` | `app/pdf_native_content.py:1924` | 1 | 0.00 | 20.86 |
| 8 | `extract_native_content` | `app/pdf_native_content.py:1358` | 1 | 0.04 | 12.77 |
| 9 | `inspect_pdf_editability` | `app/pdf_editability.py:168` | 1 | 0.10 | 11.90 |
| 10 | `inspect_question_units` | `app/pdf_question_inspection.py:181` | 1 | 0.09 | 7.13 |
| 11 | `write_hwpx` | `app/hwpx_writer_v2.py:1092` | 1 | 0.01 | 6.67 |
| 12 | `_page_metrics` | `app/pdf_layout_fidelity.py:581` | 40 | 0.09 | 5.98 |
| 13 | `recognize_pdf` | `app/recognition/pipeline.py:414` | 2 | 0.01 | 5.48 |
| 14 | `_save_hwpx_with_hancom_compat` | `app/hwpx_writer_v2.py:620` | 1 | 0.05 | 5.06 |
| 15 | `get_text` | `site-packages/pymupdf/__init__.py:12150` | 513 | 0.00 | 5.03 |
| 16 | `get_text` | `site-packages/pymupdf/utils.py:459` | 513 | 0.01 | 5.03 |
| 17 | `_textpage_dict` | `site-packages/pymupdf/__init__.py:16420` | 449 | 0.00 | 4.33 |
| 18 | `_getNewBlockList` | `site-packages/pymupdf/__init__.py:16417` | 449 | 0.00 | 4.32 |
| 19 | `JM_make_textpage_dict` | `site-packages/pymupdf/__init__.py:20733` | 449 | 0.00 | 4.32 |
| 20 | `JM_make_textpage_dict` | `site-packages/pymupdf/extra.py:200` | 449 | 0.08 | 4.32 |
| 21 | `_detailed_geometry_metrics` | `app/pdf_layout_fidelity.py:472` | 280 | 0.09 | 4.18 |
| 22 | `find_tables` | `site-packages/pymupdf/table.py:2593` | 80 | 0.01 | 3.19 |
| 23 | `find_tables` | `site-packages/pymupdf/__init__.py:11389` | 80 | 0.00 | 3.19 |
| 24 | `apply_native_typography` | `app/pdf_native_typography.py:350` | 1 | 0.14 | 3.18 |
| 25 | `recover_stacked_fractions` | `app/pdf_native_content.py:842` | 108 | 0.30 | 2.86 |

자기 시간(tottime) 상위:

| # | 함수 | 위치 | 호출 | tottime |
|---:|---|---|---:|---:|
| 1 | `deepcopy` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:110` | 4174886 | 0.98 |
| 2 | `_binary_runs` | `app/pdf_layout_writer.py:6152` | 128960 | 0.76 |
| 3 | `handle_args` | `site-packages/pymupdf/__init__.py:24011` | 727076 | 0.72 |
| 4 | `_mask_array` | `app/pdf_layout_fidelity.py:306` | 560 | 0.69 |
| 5 | `__init__` | `site-packages/pymupdf/__init__.py:14600` | 727076 | 0.60 |
| 6 | `_deepcopy_dict` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:198` | 218557 | 0.53 |
| 7 | `__init__` | `site-packages/pymupdf/__init__.py:14154` | 735628 | 0.48 |
| 8 | `_max_filter` | `app/pdf_layout_fidelity.py:253` | 1120 | 0.46 |
| 9 | `_deepcopy_tuple` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:181` | 411064 | 0.44 |
| 10 | `diff` | `site-packages/numpy/lib/_function_base_impl.py:1402` | 158722 | 0.38 |
| 11 | `util_make_rect` | `site-packages/pymupdf/__init__.py:23972` | 727076 | 0.34 |
| 12 | `_serialize_xml` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\xml\etree\ElementTree.py:860` | 86786 | 0.33 |
| 13 | `recover_native_scripts` | `app/pdf_native_content.py:1108` | 2358 | 0.31 |
| 14 | `make_tuple` | `site-packages/pymupdf/__init__.py:24001` | 712536 | 0.30 |
| 15 | `recover_stacked_fractions` | `app/pdf_native_content.py:842` | 108 | 0.30 |

내장(C 확장) tottime 상위: `<method 'render_png' of 'rhwp._rhwp._Document' objects>` 25.24s/40회, `<built-in method pymupdf._extra.JM_make_textpage_dict>` 4.24s/449회, `<built-in method pymupdf._mupdf.fz_run_display_list>` 1.44s/1320회, `<method 'copy' of 'numpy.ndarray' objects>` 1.30s/5600회, `<built-in method pymupdf._extra.get_cdrawings>` 1.08s/653회, `<built-in method pymupdf._mupdf.fz_new_display_list_from_page>` 0.94s/1320회, `<built-in method pymupdf._extra.page_get_textpage>` 0.84s/709회, `<built-in method builtins.isinstance>` 0.76s/8331021회, `<built-in method builtins.len>` 0.60s/7450450회, `<method 'get' of 'dict' objects>` 0.59s/5567174회

## 3.3 과학탐구 지구과학Ⅰ — `2026_csat/문제지/과학탐구/04 지구과학Ⅰ_문제.pdf`

그림·표 많음(4쪽, 원본 이미지 24개), 문항 20. 표는 반복 실행 중 가장 빠른 `sci_plain`(총 12.47s) 기준이다. 결과는 objective_score 63.29, layout_view_sync 0.9562, review_ok True다. 작성 직후와 최종 HWPX의 sha256이 같았다: True.

### 단계 시간

| 단계 | 초 | 비중 |
|---|---:|---:|
| 인식 (writer 안 recognize_pdf) | 1.00 | 8.0% |
| 작성 (writer - 인식) | 4.18 | 33.5% |
| 검수: 편집성 검사 중 recognize_pdf 재실행 | 1.00 | 8.0% |
| 검수: 편집성 검사 나머지 | 1.88 | 15.0% |
| 검수: 문항 렌더 검사 + review | 0.27 | 2.1% |
| 충실도 렌더 (_pdf_export_fidelity) | 3.84 | 30.8% |
| 기타 (scope·package·보고서·open_safety·정리·미계측) | 0.29 | 2.4% |
| **합계** | **12.47** | 100% |

<details><summary>단계 타임라인(0.05s 미만 하위 단계 생략)</summary>

| 단계(시작 순) | 깊이 | 시작 s | 소요 s |
|---|---:|---:|---:|
| WRITER(total) | 0 | 0.02 | 5.18 |
|   recognize_pdf | 1 | 0.04 | 1.00 |
|     segment_pdf | 2 | 0.04 | 0.38 |
|   writer.detect_source_subject | 1 | 1.04 | 0.13 |
|   writer.write_native_content | 1 | 1.17 | 4.03 |
|     writer.native.extract_native_content | 2 | 1.17 | 2.54 |
|     writer.native.hwpx_writer_v2.write_hwpx | 2 | 3.71 | 1.28 |
|     writer.native.refresh_choice_tab_widths | 2 | 4.99 | 0.07 |
|     writer.native.split_background_frame_rows | 2 | 5.06 | 0.10 |
| scope | 0 | 5.21 | 0.02 |
| package_check | 0 | 5.22 | 0.00 |
| REVIEW.inspect_pdf_editability | 0 | 5.22 | 2.88 |
|   recognize_pdf | 1 | 5.36 | 1.00 |
|     segment_pdf | 2 | 5.36 | 0.38 |
| FIDELITY(_pdf_export_fidelity) | 0 | 8.10 | 3.84 |
| REVIEW.inspect_question_rendering | 0 | 11.95 | 0.27 |
| REVIEW.build_export_review | 0 | 12.21 | 0.00 |
| report.attach_fidelity_refs | 0 | 12.21 | 0.00 |
| report.inspect_layout_template_profile | 0 | 12.21 | 0.01 |
| report.open_safety | 0 | 12.23 | 0.23 |
| report.objective_score | 0 | 12.46 | 0.00 |
| cleanup.forget_file | 0 | 12.46 | 0.00 |

(importers.save_upload 23회는 표에서 생략)

</details>

### 호출 횟수

| 항목 | 값 |
|---|---|
| 원본 PDF fitz.open | 64회 (경로 58 / 메모리 6), 총 0.05s |
| 기타 fitz.open (이미지·새 문서 등) | 0회 |
| Page.get_text 총 | 66회, 2.38s |
| get_text 옵션별 | dict 15, rawdict 13, dict+clip+flags195 12, rawdict+flags195 8, rawdict+tp 8, words+clip 6, text 4 |
| get_text 옵션별 초 | dict 1.27, rawdict 1.04, text 0.02, rawdict+flags195 0.01, rawdict+tp 0.01, dict+clip+flags195 0.01, words+clip 0.01 |
| 같은 (문서,쪽,옵션) 최대 반복 | 4회 (('SRC', 0, 'rawdict')); 고유 키 26; 초과 호출 40회 = 1.67s |
| 같은 (문서,쪽,옵션 clip 무시) 최대 반복 | 8회; 초과 52회 = 1.69s |
| 반복 횟수 분포 (반복수:키 수) | {'1': 4, '2': 11, '3': 4, '4': 7} |
| Page.get_textpage (실제 텍스트층 생성) | 102회, 0.24s, 같은 쪽 최대 30회; API별 [['find_tables', 54], ['get_text', 40], ['get_image_info', 8]] |
| 쪽 메모(page_memo) 요청/적중 | 117 / 96 |
| get_drawings | 76회 0.22s, 같은 쪽 최대 21회, 초과 0.22s |
| get_cdrawings | 76회 0.19s, 같은 쪽 최대 21회, 초과 0.19s |
| get_pixmap | 87회 1.25s, 같은 쪽·크기 최대 4회 |
| find_tables | 8회 0.81s, 같은 쪽 최대 2회, 초과 0.43s |
| rhwp 파싱 | 3회 0.02s, 같은 내용 최대 2회 |
| rhwp render_png | 4회 3.10s |
| rhwp render_svg | 25회 0.02s, 같은 쪽(문서 무관) 최대 2회 |
| recognize_pdf / segment_pdf | 2회 / 2회 |

단계별로 나눈 호출 수(초):

| 단계 | fitz_open_SRC | get_text | memo_hit | memo_miss | get_drawings | get_pixmap | find_tables | rhwp_parse | rhwp_render_png | rhwp_render_svg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WRITER(total) > recognize_pdf | 3 (0.00s) | 8 (0.67s) |  |  | 4 (0.01s) | 4 (0.18s) |  |  |  |  |
| WRITER(total) > writer.detect_source_subject | 1 (0.00s) | 2 (0.08s) | 2 (0.02s) | 3 (0.27s) | 1 (0.02s) |  |  |  |  |  |
| WRITER(total) > writer.write_native_content | 27 (0.02s) | 28 (0.65s) | 47 (0.05s) | 14 (1.13s) | 46 (0.12s) | 39 (0.43s) | 4 (0.39s) | 1 (0.00s) |  | 20 (0.00s) |
| scope | 1 (0.01s) |  |  |  |  |  |  |  |  |  |
| REVIEW.inspect_pdf_editability | 28 (0.02s) | 20 (0.30s) | 47 (0.03s) | 4 (0.11s) | 21 (0.08s) | 36 (0.37s) | 4 (0.43s) |  |  |  |
| REVIEW.inspect_pdf_editability > recognize_pdf | 3 (0.00s) | 8 (0.68s) |  |  | 4 (0.00s) | 4 (0.18s) |  |  |  |  |
| FIDELITY(_pdf_export_fidelity) | 1 (0.00s) |  |  |  |  | 4 (0.10s) |  | 1 (0.01s) | 4 (3.10s) |  |
| REVIEW.inspect_question_rendering |  |  |  |  |  |  |  | 1 (0.01s) |  | 5 (0.02s) |

get_text 호출 위치(첫 app 프레임, 쪽 메모 프레임 제외) 상위:

| 호출 위치 | 회 | 초 |
|---|---:|---:|
| `app/recognition/pdf_segment.py:388(_extract_text_lines)` | 8 | 0.68 |
| `app/recognition/pipeline.py:116(_source_literal_english_pages)` | 8 | 0.67 |
| `app/pdf_source_characters.py:69(restore_bitmap_characters)` | 4 | 0.32 |
| `app/pdf_running_heading_audit.py:21(inspect_running_header_fields)` | 3 | 0.28 |
| `app/pdf_inline_labels.py:25(source_inline_labels)` | 3 | 0.22 |
| `app/pdf_masthead_visibility.py:44(visible_masthead_lines)` | 1 | 0.08 |
| `app/pdf_masthead_typography.py:187(measure_source_masthead)` | 1 | 0.07 |
| `app/pdf_layout_writer.py:161(<genexpr>)` | 4 | 0.02 |
| `app/pdf_native_content.py:1429(extract_native_content)` | 13 | 0.01 |
| `app/pdf_source_semantics.py:417(source_grid_cells)` | 13 | 0.01 |
| `app/pdf_editability.py:423(inspect_pdf_editability)` | 4 | 0.01 |
| `app/pdf_layout_writer.py:2488(_iter_text_lines_uncached)` | 4 | 0.01 |

### cProfile 누적 시간 상위 25 (`sci_prof`, 총 16.4s, 내장·측정 래퍼 제외)

| # | 함수 | 위치 | 호출 | tottime | cumtime |
|---:|---|---|---:|---:|---:|
| 1 | `_export_pdf_layout` | `app/main.py:1011` | 1 | 0.00 | 16.44 |
| 2 | `write_pdf_structured_hwpx` | `app/pdf_layout_writer.py:10111` | 1 | 0.00 | 8.04 |
| 3 | `write_native_content` | `app/pdf_native_content.py:1924` | 1 | 0.00 | 6.69 |
| 4 | `extract_native_content` | `app/pdf_native_content.py:1358` | 1 | 0.01 | 4.42 |
| 5 | `inspect_pdf_editability` | `app/pdf_editability.py:168` | 1 | 0.04 | 3.97 |
| 6 | `_pdf_export_fidelity` | `app/main.py:980` | 1 | 0.00 | 3.49 |
| 7 | `analyze_pdf_hwpx_fidelity` | `app/pdf_layout_fidelity.py:652` | 1 | 0.01 | 3.49 |
| 8 | `_render_hwpx_page` | `app/pdf_layout_fidelity.py:56` | 4 | 0.00 | 2.73 |
| 9 | `render_png` | `site-packages/rhwp/document.py:259` | 4 | 0.00 | 2.70 |
| 10 | `get_text` | `site-packages/pymupdf/utils.py:459` | 66 | 0.00 | 2.41 |
| 11 | `get_text` | `site-packages/pymupdf/__init__.py:12150` | 66 | 0.00 | 2.41 |
| 12 | `inspect_question_units` | `app/pdf_question_inspection.py:181` | 1 | 0.03 | 2.38 |
| 13 | `recognize_pdf` | `app/recognition/pipeline.py:414` | 2 | 0.00 | 2.29 |
| 14 | `_textpage_dict` | `site-packages/pymupdf/__init__.py:16420` | 56 | 0.00 | 2.25 |
| 15 | `_getNewBlockList` | `site-packages/pymupdf/__init__.py:16417` | 56 | 0.00 | 2.25 |
| 16 | `JM_make_textpage_dict` | `site-packages/pymupdf/__init__.py:20733` | 56 | 0.00 | 2.25 |
| 17 | `JM_make_textpage_dict` | `site-packages/pymupdf/extra.py:200` | 56 | 0.00 | 2.25 |
| 18 | `write_hwpx` | `app/hwpx_writer_v2.py:1092` | 1 | 0.00 | 2.03 |
| 19 | `_save_hwpx_with_hancom_compat` | `app/hwpx_writer_v2.py:620` | 1 | 0.02 | 1.46 |
| 20 | `find_tables` | `site-packages/pymupdf/__init__.py:11389` | 8 | 0.00 | 1.32 |
| 21 | `find_tables` | `site-packages/pymupdf/table.py:2593` | 8 | 0.00 | 1.32 |
| 22 | `get_pixmap` | `site-packages/pymupdf/__init__.py:11822` | 87 | 0.00 | 1.24 |
| 23 | `extractDICT` | `site-packages/pymupdf/__init__.py:16477` | 27 | 0.00 | 1.23 |
| 24 | `page_memo` | `app/pdf_source_page_memo.py:87` | 117 | 0.00 | 1.07 |
| 25 | `extractRAWDICT` | `site-packages/pymupdf/__init__.py:16563` | 29 | 0.00 | 1.01 |

자기 시간(tottime) 상위:

| # | 함수 | 위치 | 호출 | tottime |
|---:|---|---|---:|---:|
| 1 | `deepcopy` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:110` | 1178439 | 0.28 |
| 2 | `handle_args` | `site-packages/pymupdf/__init__.py:24011` | 294508 | 0.27 |
| 3 | `__init__` | `site-packages/pymupdf/__init__.py:14600` | 294508 | 0.24 |
| 4 | `util_make_rect` | `site-packages/pymupdf/__init__.py:23972` | 294508 | 0.15 |
| 5 | `_deepcopy_dict` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:198` | 64732 | 0.14 |
| 6 | `_deepcopy_tuple` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\copy.py:181` | 122753 | 0.13 |
| 7 | `make_tuple` | `site-packages/pymupdf/__init__.py:24001` | 280273 | 0.11 |
| 8 | `_serialize_xml` | `<home>\AppData\Local\Python\pythoncore-3.14-64\Lib\xml\etree\ElementTree.py:860` | 29940 | 0.11 |
| 9 | `_visible_svg_text` | `app/pdf_question_rendering.py:325` | 5 | 0.11 |
| 10 | `_binary_runs` | `app/pdf_layout_writer.py:6152` | 12897 | 0.10 |
| 11 | `JM_rect_from_py` | `site-packages/pymupdf/__init__.py:21309` | 141763 | 0.08 |
| 12 | `__init__` | `site-packages/pymupdf/__init__.py:14154` | 109326 | 0.07 |
| 13 | `_mask_array` | `app/pdf_layout_fidelity.py:306` | 56 | 0.07 |
| 14 | `JM_char_quad` | `site-packages/pymupdf/__init__.py:18815` | 42524 | 0.07 |
| 15 | `JM_rects_overlap` | `site-packages/pymupdf/__init__.py:21332` | 42524 | 0.06 |

내장(C 확장) tottime 상위: `<method 'render_png' of 'rhwp._rhwp._Document' objects>` 2.70s/4회, `<built-in method pymupdf._extra.JM_make_textpage_dict>` 2.24s/56회, `<built-in method pymupdf._mupdf.fz_new_display_list_from_page>` 0.61s/87회, `<built-in method pymupdf._mupdf.fz_run_display_list>` 0.58s/87회, `<built-in method _io.open>` 0.42s/151회, `<built-in method builtins.isinstance>` 0.25s/2977439회, `<built-in method pymupdf._extra.page_get_textpage>` 0.23s/102회, `<built-in method pymupdf._extra.get_cdrawings>` 0.18s/76회, `<built-in method builtins.len>` 0.17s/2030806회, `<built-in method builtins.compile>` 0.16s/79회

## 4. 옵션 on/off

`PdfLayoutExportPayload`(`main.py:136-148`)의 필드를 코드에서 확인한 결과:

| 옵션 | 기본값(UI) | 코드상 효과 | 시간 영향 |
|---|---|---|---|
| `max_pages` | None | writer page_limit(`pdf_layout_writer.py:10200`), 충실도 쪽 수(`main.py:984`) | 쪽 수에 비례해 준다. **뒤쪽을 버린다**(측정 안 함, 품질·범위 손실이 자명하다) |
| `boxed_passages` | true | `_export_pdf_layout`에서 어디에도 전달되지 않는다(`main.py:1074-1081`). 쓰는 곳은 레거시 `write_pdf_flow_hwpx`(`pdf_layout_writer.py:7891`)뿐이다 | 없음(코드 근거) |
| `layout_mode` | "structured" | coordinate도 같은 writer로 간다(`main.py:1072-1074`). 보고서 필드에만 기록된다 | 없음(측정) |
| `native_math` | true | writer와 HWPX 쓰기에 전달된다(`pdf_native_content.py:1953`, `:1995`) | 측정 |
| `math_ai_recognition`/`math_ai_model` | None | kice_math이고 참일 때만 AI 경로를 탄다(`pdf_layout_writer.py:10195`). 네트워크가 필요하다 | **측정 금지(네트워크)** |
| `variant_policy` | "all" | "first"는 8쪽 이상·짝수 쪽·뒷절반 번호 재시작·겹침 80% 이상일 때 앞 절반만 출력한다(`pdf_layout_writer.py:10159-10193`). 충실도는 선택 쪽만 비교한다(`main.py:987-997`) | 측정 |
| `strict` | false | 통과하면 작업이 같다. 실패하면 `main.py:1124`/`1137`에서 422가 난다(충실도 전에 중단될 수 있다) | 없음(측정) |
| (페이로드 밖) 충실도·문항 렌더·열기 안전성 | 항상 실행 | 끄는 플래그가 없다. `artifact_mode="failures"`로 고정되어 있다(`main.py:985`) | 이 단계들은 HWPX를 바꾸지 않는다(§0-4) |

측정 결과(벽시계·CPU는 반복 실행의 **최소값**이다. 경합 잡음이 ±2배라 작은 차이는 판정하지 않는다. '작업량'은 결정적인 호출 수다):

| 책자 | 옵션 | 기본 벽시계 최소(n) | 옵션 벽시계 최소(n) | 기본 CPU 최소(n) | 옵션 CPU 최소(n) | 작업량 변화(get_text / render_png / find_tables / recognize) | 산출물 변화 | 품질 지표 (쪽, 문항, 편집 수식, objective, review_ok) 기본 → 옵션 | 판정 |
|---|---|---:|---:|---:|---:|---|---|---|---|
| sci | native_math=false | 12.5 (4) | 14.0 (2) | 14.4 (2) | 12.8 (1) | 66→66 / 4→4 / 8→8 / 2→2 | 다름(4개 항목): header.xml, section0.xml, section1.xml, PrvText.txt | [4, 20, 20, 63.29, True] → [4, 20, 0, 58.5, False] | 품질을 깎음 |
| sci | variant_policy=first | 12.5 (4) | 14.6 (2) | 14.4 (2) | 12.8 (1) | 66→66 / 4→4 / 8→8 / 2→2 | 동일(무작위 id·instid·fraction 이름만 다름) | [4, 20, 20, 63.29, True] → [4, 20, 20, 63.29, True] | 효과 없음(작업·산출물 같음) |
| sci | strict=true | 12.5 (4) | 16.0 (2) | 14.4 (2) | 13.4 (1) | 66→66 / 4→4 / 8→8 / 2→2 | 동일(무작위 id·instid·fraction 이름만 다름) | [4, 20, 20, 63.29, True] → [4, 20, 20, 63.29, True] | 효과 없음(작업·산출물 같음) |
| sci | layout_mode=coordinate | 12.5 (4) | 15.6 (2) | 14.4 (2) | 13.3 (2) | 66→66 / 4→4 / 8→8 / 2→2 | 동일(무작위 id·instid·fraction 이름만 다름) | [4, 20, 20, 63.29, True] → [4, 20, 20, 63.29, True] | 효과 없음(작업·산출물 같음) |
| math | native_math=false | 52.0 (3) | 67.0 (3) | 63.6 (2) | 62.0 (2) | 513→513 / 40→40 / 80→80 / 2→2 | 다름(4개 항목): header.xml, section0.xml, section1.xml, PrvText.txt | [40, 92, 710, 67.9, True] → [40, 92, 0, 63.5, False] | 품질을 깎음 |
| math | variant_policy=first | 52.0 (3) | 52.5 (1) | 63.6 (2) | 43.3 (1) | 513→372 / 40→20 / 80→40 / 2→2 | 다름(5개 항목, 한쪽에만 8개): content.hpf, header.xml, section0.xml, section1.xml … | [40, 92, 710, 67.9, True] → [20, 46, 355, 68.24, True] | 빨라지지만 뒷형(짝수형) 쪽을 버림 = 범위 축소 |
| kor | variant_policy=first | 95.0 (2) | 70.0 (1) | 151.3 (1) | 63.2 (1) | 539→389 / 40→20 / 80→40 / 2→2 | 다름(5개 항목, 한쪽에만 14개): content.hpf, header.xml, section0.xml, section1.xml … | [40, 112, 0, 64.51, False] → [20, 56, 0, 71.2, False] | 빨라지지만 뒷형(짝수형) 쪽을 버림 = 범위 축소 |

해석:

- `native_math=false`: 시간 이득을 확인하지 못했다. 최소값 비교에서 과학은 벽시계 12.5→14.0s, CPU 14.4→12.8s였고, 수학은 벽시계 52.0→67.0s, CPU 63.6→62.0s였다. 벽시계와 CPU의 방향이 엇갈리고 차이가 잡음 폭 안이다. 작업량(get_text·render·find_tables·recognize 호출 수)도 같다. 그런데 편집 수식이 0이 되고 review_ok가 False로 바뀌며 objective가 내려간다(위 표). **품질을 깎고 빨라지지도 않는 옵션**이다.
- `variant_policy=first`: 국어·수학은 홀·짝형 2벌 합본이라 감지가 걸려 앞 20쪽만 출력한다. 충실도 렌더도 20쪽이다. 결정적 작업량은 확실히 준다(render_png 40→20, find_tables 80→40, get_text 수학 513→372·국어 539→389). 시간은 경합 때문에 깨끗하지 않다. 수학 벽시계 52.0→52.5s(옵션 1회), CPU 63.6→43.3s. 국어 벽시계 95.0→70.0s(각 1~2회). 제외된 HEAD 밖 실행 `math_first2`는 41.5s였다. 대신 뒷형을 버리므로 '품질 손실 없이'가 아니라 '범위를 줄여서' 빨라지는 것이다. 사용자가 명시적으로 고를 때만 맞다. 인식(`recognize_pdf`)은 이때도 40쪽 전체를 2회 돈다. get_text가 절반으로 줄지 않는 이유다(수학 513→372).
- `strict`, `layout_mode=coordinate`: 통과하는 과학 책자에서는 작업량과 산출물이 같다. 시간 차이는 잡음이다.
- 국어 기본값의 CPU 최소(151.3s)는 경합이 심했던 1회분(`kor_plain2`)뿐이라 비교에 쓰지 않는다. 국어 `variant_policy=first`의 효과는 작업량(render_png 40→20, find_tables 80→40)과 벽시계로 판단한다.

## 5. rhwp 렌더 단가 (충실도 단계의 본체)

작성된 HWPX를 rhwp로 다시 파싱해 앞 5~6쪽을 렌더한 1쪽당 초(`m2_render_bench.py`):

```
/sci_plain/output.hwpx pages 5 {'png_1.0': 0.844, 'png_0.5': 1.059, 'svg': 0.006, 'png_1.0_again': 0.915} s/page
/math_plain/output.hwpx pages 6 {'png_1.0': 0.715, 'png_0.5': 0.939, 'svg': 0.001, 'png_1.0_again': 0.864} s/page
/kor_plain/output.hwpx pages 6 {'png_1.0': 0.95, 'png_0.5': 1.032, 'svg': 0.009, 'png_1.0_again': 0.961} s/page
과학 5쪽 추가 확인: 첫 render_png 0.731s, 같은 쪽 반복 0.811s, render_all_png 1쪽당 0.807s, scale 0.25 0.861s, 새로 파싱한 문서 0.866s
```

`render_png`는 배율 0.25~1.0과 일괄 렌더 여부에 관계없이 쪽당 약 0.7~1.1초로 거의 같다(0.5배율이 오히려 느린 경우도 있다). 픽셀 수가 아니라 호출마다 드는 고정비용이다(rhwp 내부 원인은 확인하지 않았다). 같은 쪽 `render_svg`는 1~9ms다. 충실도 단계의 벽시계 대부분이 이 고정비용 × 쪽 수다. 배율을 낮추는 것으로는 줄지 않는다. 줄이려면 렌더 횟수를 줄이거나(예: 미달 의심 쪽만, 뒤로 미루기), SVG 기반 래스터처럼 다른 렌더 경로를 써야 한다. 그 경로의 정확도는 측정하지 않았다.

## 6. 중복 제거 후보

예상 절약은 cProfile을 붙이지 않은 최소 실행(국어 / 수학 / 과학)에서 해당 호출이 실제로 쓴 벽시계 합이다. 서로 겹치지 않게 나눴다. 3번은 1번(인식 2회차)을 없앤 뒤에도 남는 몫만 셌다. 경합 아래 수치이므로 상한에 가까운 참고값이다.

| 순위 | 후보 | 같은 일을 다시 하는 위치(호출 스택 근거) | 반복 형태(호출 수) | 예상 절약 초 국어 / 수학 / 과학 | 주의 |
|---:|---|---|---|---|---|
| 1 | **`recognize_pdf` 2회** | 1회차 `pdf_layout_writer.py:10139`(작성). 2회차 `pdf_question_inspection.py:339` ← `pdf_editability.py:286` ← `main.py:1111`(검수) | 같은 PDF 바이트를 처음부터 다시 인식한다(segment_pdf 2회, 쪽 래스터 `cutout.py:76` 2회 포함) | 4.17 / 2.16 / 1.00 | 결과 재사용 시 writer가 인식 결과 객체를 변경하는지 확인 필요(미확인) |
| 2 | **`find_tables` 쪽당 2회** | `pdf_native_content.py:1429`(작성, extract_native_content) 그리고 `pdf_source_semantics.py:417` ← `pdf_question_inspection.py:464`(검수) | 같은 쪽에서 기본 인자로 2회 호출한다(40쪽 → 80회). 내부 get_textpage 쪽당 8회, get_text `rawdict+tp`·`dict+clip`·`words+clip`도 함께 반복된다 | 4.17 / 0.88 / 0.43 | Table 객체가 page를 참조한다. 문서를 닫은 뒤 공유할 수 있는지는 미확인. 검수 쪽 `source_grid_cache`(`pdf_editability.py:285`)는 이미 있지만 작성과 공유하지 않는다 |
| 3 | **텍스트층 재추출('dict' 쪽당 4회, 'rawdict' 3회)** | 쪽마다 순서는 이렇다. 'dict': ①`pipeline.py:116`(인식 1회차, 스트림) → ②메모 채우기 `pdf_source_characters.py:69` → ③`pipeline.py:116`(인식 2회차) → ④`pdf_running_heading_audit.py:21`(메모 없이 직접). 'rawdict': ①`pdf_segment.py:388`(인식) → ②메모 채우기 `pdf_inline_labels.py:25` → ③`pdf_segment.py:388`(인식 2회차) | 인식은 `fitz.open(stream=…)`(`pdf_segment.py:1394`, `pipeline.py:113`)이라 쪽 메모 키(`pdf_source_page_memo.py:49-56`, 파일 경로 기반 digest)를 쓰지 못한다 | 메모 재충전 2.85 / 1.25 / 0.62 + 감사 직접 호출 1.49 / 0.67 / 0.34 | ③은 1번 후보에 포함. 인식 안에서도 segment가 rawdict를 뽑은 뒤 `_source_literal_english_pages`가 같은 쪽 dict를 또 뽑는다(1.44 / 0.67 / 0.33s, 머리 25%만 쓴다) |
| 4 | **배경 표 후보마다 전 쪽 `get_drawings`** | `pdf_source_frame_geometry.py:110-113`(후보 표 1개마다 PDF를 다시 열고 모든 쪽을 훑는다) ← `pdf_background_geometry.py:19` ← `pdf_frame_rows.py:56`(작성) / `pdf_editability.py:236`(검수) | 국어 518회, 수학 252회, 과학 6회. 같은 쪽 get_drawings 최대 40회(국어) | 1.88 / 0.69 / 0.06 (get_drawings 중복 전체는 2.90 / 1.28 / 0.22) | cProfile 국어 기준 이 함수 누적은 3.9s(58회)로, 쪽 훑기 외 계산도 있다 |
| 5 | **`recover_stacked_fractions` 쪽당 2회** | `pdf_native_content.py:1474`(작성) 그리고 `pdf_editability.py:405`(검수, `page.get_drawings()`를 새로 불러 넘김) | 쪽마다 1회씩, 40쪽 → 80회(+표 셀 48회) | cProfile 누적: 국어 작성 2.84s + 검수 5.41s, 수학 1.36s + 1.49s(cProfile 부풀림 포함, plain 환산 미측정) | 두 호출의 입력(grid_regions 등)이 달라 결과를 그대로 재사용할 수 있는지 미확인. 분수가 없는 국어에서도 이 비용이 든다 |
| 참고 | 원본 `fitz.open` 다회 | `pdf_source_image_validation.py:28`(그림 자르기 1개마다 열기: 국어 56 / 수학 32 / 과학 44회), `pdf_source_frame_geometry.py:110` 등 | 국어 101 / 수학 69 / 과학 64회 | 0.10 / 0.07 / 0.05 | 여는 것 자체는 1회 약 1ms라 후보가 아니다 |
| 참고 | 최종 HWPX rhwp 파싱 2회 | `pdf_layout_fidelity.py:693`, `pdf_question_rendering.py:525` | 같은 내용 2회 | 0.01~0.04 | 무시 가능 |

1~4번만 합쳐도(겹침 없이) 절약 추정은 다음과 같다. 국어 약 14.6s(총 95.0s의 15%), 수학 약 5.7s(11%), 과학 약 2.5s(20%). 중복 제거는 모두 '같은 입력 → 같은 결과'인 계산을 대상으로 하므로 원칙적으로 산출물 무변화 후보다. 단, 위 '주의' 칸의 미확인 사항은 수정 전에 검증해야 한다. 중복이 아닌 최대 비용은 충실도 `render_png`(국어·수학 약 24~29s)다. 이것은 렌더 횟수나 렌더 경로를 바꾸는 문제다(§5).

## 7. 확인하지 못한 것

- `math_ai_recognition=true` 경로(네트워크 금지로 측정하지 않음)
- `max_pages` on/off(자명한 범위 축소라 측정하지 않음)
- 후보 1·2·5의 결과 재사용이 실제로 같은 출력을 내는지(코드를 수정하지 않는 측정이라 검증하지 않음)
- rhwp `render_png` 고정비용의 내부 원인
- 경합 없는 조건의 절대 시간(이 측정 중 다른 측정이 계속 돌고 있었다)

## 8. 원자료

- 실행별 `runs/<label>/summary.json`(단계·호출 수·상위 함수), `events.json`(호출 단위 원자료), `profile.pstats`(cProfile), `output.hwpx`: `<scratchpad>\measure\m2\runs\`
- 스크립트: `m2_run.py`(계측 실행), `m2_tables.py`·`m2_seq.py`·`m2_dedup.py`·`m2_options.py`(집계), `m2_hwpx_diff.py`·`m2_cmp.py`(산출물 비교), `m2_render_bench.py`(rhwp 단가), `run_all.sh`·`run_more*.sh`(실행 순서), `progress.txt`(실행 기록)
- 실행 목록: `kor_first`, `kor_plain`, `kor_plain2`, `kor_prof`, `math_first`, `math_first2`(제외), `math_nomath`, `math_nomath2`, `math_nomath3`, `math_nomath4`(제외), `math_plain`, `math_plain2`, `math_plain3`, `math_plain4`(제외), `math_prof`, `sci_coord`, `sci_coord2`, `sci_first`, `sci_first2`, `sci_nomath`, `sci_nomath2`, `sci_nomath3`(제외), `sci_nomath4`(제외), `sci_plain`, `sci_plain2`, `sci_plain3`, `sci_plain4`, `sci_plain5`(제외), `sci_plain6`(제외), `sci_prof`, `sci_strict`, `sci_strict2`
