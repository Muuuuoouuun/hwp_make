# 기본 변환의 source-cell 분수 오류 수정과 남은 실패

2026-10-07. 프리미엄 양식/순서 변경은 보류하며 기본 PDF→native HWPX만 다룬다. HTTP 변환 성공과 원본 배치/품질 통과를 구분한다.

## 실제 중단 원인과 수정

- 고3 화학Ⅰ은 실제 source grid의 세로 병합 header cell 안에 있는 editable word fraction을 `flatten_source_cell_fractions`가 지원하지 않아 중단했다. 새 경로는 완전하고 겹치지 않는 grid를 먼저 확인하고, fraction의 local operand rows를 **전체 merged cell 높이**에 매핑한다. 원래 source row 경계를 보존하며 필요한 내용 높이 증가만 마지막 covered row에 더한다. 분수/본문/수식/그림을 raster나 overlay로 바꾸지 않는다.
- 고3 지구과학Ⅱ는 보기 안 word fraction의 estimated preferred width 합계가 `24684 > 22961 HWPUNIT`이라 중단했다. 기존 너비에 들어가는 경로는 유지한다. 초과하는 경우에만 native equation/fixed inline object/Latin word의 indivisible 최소 폭을 계산하고, 그 위의 가용 폭을 각 column에 분배한다. operand는 기존 editable paragraph로 자연스럽게 줄바꿈한다. indivisible content 자체가 source view보다 넓거나 geometry/style가 유효하지 않으면 계속 거절한다.
- 독립 리뷰에서 처음 발견한 fixed picture/rectangle/container 최소 폭 누락을 수정했다. 실제 inline object 크기와 좌우 outMargin을 포함하며, floating/누락/0/NaN geometry는 거절한다. 글꼴 크기나 source frame 폭을 줄이거나 늘리는 우회는 사용하지 않았다.

수정 파일은 `app/pdf_source_cell_fractions.py`, `app/pdf_question_tables.py`다. raw source PDF를 다시 읽는 독립 source inventory와 실제 strict API를 소비자 검사로 유지한다.

## 확인한 결과와 한계

실제 두 source 모두 writer가 중단하지 않고 20문항을 만든다. writer의 `pages=4`는 원본/목표 쪽수 메타데이터이며 실제 renderer 쪽수로 해석하지 않는다.

| 실제 strict API | 이전 | 이번 실행 | 남은 실제 실패 |
|---|---|---|---|
| 화학Ⅰ | HTTP400 unsupported_structure | HTTP422 strict_check_failed | Q13 H 아래첨자1 네 개 누락 등 source script/semantics 검사 실패 |
| 지구과학Ⅱ | HTTP400 unsupported_structure | HTTP200, source text1.0/20문항/독립 open·editability·render 기능 검사 PASS | **실제5쪽 vs 원본4쪽**, objective52.73, 배치/품질 FAIL |

`tmp/september-exam-matrix/fraction-root-api/report.json`은 2부 subset이고 STABLE/snapshot1, code SHA `13ea9f8e75cef9b9bd62ec6dd03b8eabd86833708a28066a348962d0041de191`다. 두 case 모두 품질 FAIL이며 전체51부 baseline을 대체하지 않는다. 이후 fixed-object/finite metric guard를 보강했으므로 해당 API 수치를 최신 전체 코드 점수로 재사용하지 않는다.

초기 지구과학Ⅱ의 native operand wrapping/수식 예약 폭과 누적 flow가 원본 페이지보다 커지는 원인은 후속 수정 대상이다. HTTP200을 4쪽 복원이나 목표98 달성으로 표시하지 않는다. 화학Ⅰ의 source attachment 손실도 이번 flat-grid 지원만으로 해결된 것으로 집계하지 않는다.

## 편집 및 회귀 근거

- `scripts/verify_native_source_fraction_cells.py`: 실제 pre-normalization source-grid 2개에서 모든 text character/equation script 보존, complete non-overlapping flat grid, source width22961 보존, 두 번째 처리 무변경 PASS. oversized pic/rect/container/table/equation, floating/missing/0/NaN geometry 및 merged overlap/hole/span/size **12개 negative** 거절. fixture가 없으면 SKIP/exit2다.
- 실제 public `add_run`으로 해당 numerator에 84개의 가시 Korean glyph를 추가했다. 화학Ⅰ Q13 표 높이15469→28847, 지구과학Ⅱ Q18 높이11381→15805HWP, 원래 모든 equation script/그림 bytes/semantic paragraph 소속 보존, owning question geometry PASS. 실제 PDF 84glyph가 printable area 안에 있고 fresh reopen XML/PNG가 동일하다. 의미 있는 편집 후 두 문서는 자연스럽게5쪽이며 원본 초기 쪽수 PASS 근거로 사용하지 않는다.
- 기존 `verify_fraction_operand_scripts.py`, `verify_native_merged_table_reflow.py`, `verify_native_math_layout_heights.py` PASS. 수식 attachment를 임의로 면제하지 않았다.
- product 및 dedicated test diff의 독립 리뷰 완료. `git diff --check` PASS(CRLF 안내만 출력).

근거는 `tmp/september-exam-matrix/fraction-root/{cells-regression.json,2027_kice_september_high3__g_che1/edit-report.json,2027_kice_september_high3__g_ear2/edit-report.json}` 및 `fraction-root-api`다. 수학5종/상업경제/통합사회 진단은 `september-unsupported-structure.md`에서 별도로 관리한다.
