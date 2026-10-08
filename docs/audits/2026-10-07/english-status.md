# 영어 로직 상태 점검 — 2026-10-07

기준 커밋: `62a8994`. 점검 시작 시 작업 트리는 깨끗했다. 제품 코드는 변경하지 않았다.

**판정: 기본 PDF 변환은 문항 수를 보존하지만 원본 배치 품질이 미달이다. 프리미엄 편집용 가져오기는 영어의 제시문·공통 지문을 누락하며, 실제 HWPX/DOCX 재출력에도 누락이 이어진다. 영어 편집 기능을 완료 상태로 판단할 수 없다.**

## 검사 범위와 현재 경로

- 기본 변환: `export_pdf_layout()` → `write_pdf_structured_hwpx()` → 영어·국어 전용 텍스트 흐름 재구성 → 원문·편집성·패키지·렌더 검사. `strict=false`, `variant_policy=all`, AI 수식 인식 끔.
- 프리미엄 편집: `/api/import` → PDF 인식 결과의 문항 블록 → stem/choices 저장 → 로그인 세션에서 `/api/export`, `workspace=premium`, `template_key=kice_english`, `numbering_mode=preserve`로 HWPX/DOCX 출력.
- 원본을 보존하고 `tmp/english-status-2026-10-07/engine`에 DB·계정·변환 결과를 격리했다. 사용자 작업 DB와 계정을 사용하지 않았다.
- 실물 PDF 2개·원본 24쪽을 변환하고 전체 출력 쪽을 자동 비교했다. 고1 원본 4·7·8쪽, 기본 출력 4·7쪽과 편집 출력의 공통 지문 문항 쪽은 이미지로 직접 확인했다. 한컴 GUI와 스캔 PDF는 검사하지 않았다.

## 기본 변환 실측

| 자료 | 원본→출력 쪽수 | 원본→출력 문항 | 평균 배치 점수 | 최저 쪽 배치 점수 | 패키지·재열기 |
| --- | --- | --- | --- | --- | --- |
| 2026년 6월 고1 영어 | 8→8 | 45→45 | 87.49 | 73.89 | 통과 |
| 2026학년도 수능 영어 홀수·짝수형 합본 | 16→17 | 90→90 | 62.55 | 56.24 | 통과 |

- 두 자료 모두 `template_key=kice_english`, 문항 소속 검사 통과, 전체 페이지 이미지 0, 편집 가능한 원문 텍스트 검사 비율 1.0이었다. 이 비율은 배치나 프리미엄 문항별 내용 완전성을 뜻하지 않는다.
- 두 자료 모두 API 종합 품질 기준 98점에 미달했다. 개발 목표 93점에도 미달한다. 표의 점수는 이번 환경에서 측정한 가혹 배치 점수이며 과거 환경의 점수와 개선율로 비교하지 않는다.
- 고1 25번 그래프의 국가·축·범례 라벨이 막대와 분리된다. 28번 안내문은 글머리표와 삽화 전후로 테두리·내용이 갈라진다. 출력 4쪽에서 기존 문제가 재현됐다.
- 기본 변환의 `review.flag_count=0`은 로컬 편집성 결함을 검출하지 않았다는 뜻이다. 배치 품질은 별도 `quality.meets_objective_score_target=false`이고 원본 배치 확인 안내가 반환된다.
- API 호출부터 검증 완료까지 고1 15.962초, 합본 29.880초였다. 회귀 검사와 일부 시간이 겹쳤으므로 성능 기준선으로 사용하지 않는다.

## P1 — 프리미엄에서 풀이에 필요한 내용 누락

고1 자료를 45문항으로 가져왔지만, 아래 내용은 **전체 가져오기 문항의 stem/choices 어디에도 없고, 해당 문항에 이미지도 붙지 않았다.** 12문항(29·30·36~45)을 실제 로그인된 격리 계정으로 출력한 HWPX/DOCX에도 동일하게 없었다. 두 출력 API 응답은 모두 200이다.

| 문항 | 누락 내용 | 기본 PDF 변환 | 편집 가져오기·HWPX·DOCX |
| --- | --- | --- | --- |
| 36·37 | 순서 배열의 최초 제시문 | 존재 | 누락 |
| 38·39 | 삽입해야 할 제시 문장 | 존재 | 누락 |
| 40 | 요약 대상 지문과 요약 문장 | 존재 | 누락 |
| 41~42 | 두 문항의 공통 지문 | 존재 | 누락 |
| 43~45 | 공통 이야기 지문 | 존재 | 누락 |

추가로 `[36~37]` 지시문은 35번 끝에, `[43~45]` 지시문과 `(A)` 표지는 42번 끝에 들어갔다. 문항 수가 맞는 것만으로 문항 소속·내용 완전성을 보증할 수 없다.

코드에서 확인한 단서:

- [pipeline.py:421](C:/Projects/Class_project/hwp_make/app/recognition/pipeline.py:421)는 **문항이 없는 쪽에서만** `_page_shared_passage()`를 호출한다. 실제 영어처럼 같은 쪽에 지문과 문항이 함께 있으면 이 공통 지문 연결 경로를 사용하지 않는다.
- [pipeline.py:447](C:/Projects/Class_project/hwp_make/app/recognition/pipeline.py:447)는 문항에 배정된 stem/choice 블록만 합친다. 텍스트가 많은 그림 후보는 [pipeline.py:165](C:/Projects/Class_project/hwp_make/app/recognition/pipeline.py:165)에서 이미지 후보에서도 제외한다. 상자 안의 제시문·지문이 최종 문항으로 이어지지 않는 경로는 추가 추적이 필요하다.
- 기본 변환은 [pdf_layout_writer.py:10418](C:/Projects/Class_project/hwp_make/app/pdf_layout_writer.py:10418) 이후 원본 PDF 텍스트 흐름을 다시 구성하므로 이번에 확인한 누락 내용을 보존했다. 편집 가져오기와 보존 결과가 다른 이유를 설명하는 경로 차이다.

## P1 — 본문 표지를 독립 선지로 오인

- 고1 29번의 본문 `⑤ reflected ...` 줄이 별도 선지 1개로 분리됐다. 해당 문구가 본문에서 빠져 문장이 끊긴다.
- 고1 30번의 본문 `② focus or organise ...` 줄도 별도 선지 1개로 분리됐다.
- 고1 40번은 ③의 `analytical`과 `confirm`, ④의 `detailed`와 `explain`이 각각 선지/본문으로 흩어져 A/B 선지 쌍을 보존하지 못했다.
- [importers.py:776](C:/Projects/Class_project/hwp_make/app/importers.py:776)의 `_choice_line_body()`는 원문자 표지로 시작하는 본문 줄을 일반 선지로 받아들이며, 영어의 본문 내 표지와 독립 선지 구별이 부족하다. 전체 분리는 [importers.py:1664](C:/Projects/Class_project/hwp_make/app/importers.py:1664)에서 수행된다.

## P2 — 과목 힌트와 합본 가져오기 정책

- `infer_subject('english.pdf')`와 `infer_subject('영어.pdf')`는 영어다. 그러나 `English.pdf`·`ENGLISH.pdf`는 unknown, `대학수학능력시험_영어.pdf`는 math다. [pipeline.py:81](C:/Projects/Class_project/hwp_make/app/recognition/pipeline.py:81)의 대소문자 구분 및 수학 키워드 우선순위 때문이다.
- 기본 출력 양식은 1쪽 영역명 우선 판별이 있어 두 실물 모두 영어 양식을 선택했다. 위 결과를 곧바로 “기본 출력이 수학 양식으로 생성된다”는 오류로 해석하지 않는다. 인식 레이어 힌트의 불일치다.
- 수능 합본의 기본 변환은 90문항을 보존했지만 편집 가져오기는 중복 43개를 제거해 47문항이 됐다. 16번·41번만 두 개씩 남는다. 문제은행의 중복 제거 기능으로 설명되며, 홀수·짝수형을 모두 재편집할 때 기대하는 정책과 맞는지는 별도 정리가 필요하다.

## 회귀 검사와 검증 공백

관련 회귀 10개: **PASS 10 / SKIP 0 / FAIL 0**. 전체 130개 게이트를 이번 점검에서 실행한 것은 아니다.

검사: `verify_choice_prefix.py`, `verify_kice_typography.py`, `verify_native_background_frame_flow.py`, `verify_native_figure_labels.py`, `verify_native_grid_frame_fragments.py`, `verify_pdf_passage_page.py`, `verify_pdf_question_markers.py`, `verify_pdf_title_subject.py`, `verify_question_source_boundaries.py`, `verify_raster_chart_table_boundary.py`.

- 27번 안내문의 글머리표 5개, 50→60 students 수정·재저장, 원본 이미지 유지, 8쪽 유지 검사는 통과했다.
- 편지 지문에 316·474·790자를 추가하고 재저장하는 편집 검사도 통과했다.
- `verify_pdf_passage_page.py`는 “지문 전용 쪽 → 뒤 문항 쪽”을 검사한다. 이번에 드러난 “같은 쪽의 공통 지문·상자 제시문 → 편집 가져오기·재출력”을 검증하지 않는다.
- 따라서 기존 테스트 통과와 이번 내용 누락 재현은 모순되지 않는다. 영어 실물 유형별 누락 검사가 먼저 추가되어야 한다.

권장 수정 순서: **제시문·공통 지문 소속 복원 → 본문 표지/선지·A/B 쌍 분리 보강 → 편집 내보내기 원문 누락 검사 → 그래프·안내문 배치 → 과목 힌트·합본 정책 정리**.

## 재현 근거

- [실물 변환 요약](C:/Projects/Class_project/hwp_make/tmp/english-status-2026-10-07/summary.json)
- [원문·기본 변환·편집 내보내기 내용 대조](C:/Projects/Class_project/hwp_make/tmp/english-status-2026-10-07/content_audit.json)
- [관련 회귀 결과](C:/Projects/Class_project/hwp_make/tmp/english-status-2026-10-07/regression/report.json)
- 재현 스크립트: `tmp/english-status-2026-10-07/probe.py`, `content_audit.py`. 해당 경로는 로컬 전용이며 Git 추적 대상이 아니다.
- 고1 원본 SHA-256: `0ee4701af2d11eff464eb1ccaa4bc04bb741c81c8c451ffac3a25f054e90c588`.
- 수능 합본 원본 SHA-256: `788830081bb2a3adef1014c1625b7cc9562ad0af4438edafb8449782595af88a`.
