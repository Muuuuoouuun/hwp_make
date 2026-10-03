# 기본 변환 수정 작업 정리 (2026-10-02~03)

> 관련 커밋: `86aa7d8` 기본 변환 수정 1~5단계 + 품질·속도 개선, `31de978` 수리 R1, `5bbf11b` 원격 브랜치(kordoc 수식 변환·HWPX 가져오기 보강) 병합. `tmp/` 아래 경로는 로컬 산출물(gitignore)이며 재현 절차는 5절을 따른다.

작성일: 2026-10-03. 브랜치 `codex/premium-reorder-numbering`, 시작 HEAD `3f04bb6`. 이 문서는 감사·수정·수리·전 과목 매트릭스·오픈소스 조사의 결과를 한곳에 모은다. 원자료는 저장소의 `tmp/` 아래에 있고 `tmp/`는 git 무시 대상이다. 따라서 아래 경로는 작업한 PC에서만 열린다.

| 단계 | 기간 | 결과물 | 커밋 |
| --- | --- | --- | --- |
| 전체 감사 | 10-02 | `tmp/audit-2026-10-02/00_종합.md`, `00_기본기능_핵심.md` 외 3종 | 없음(조사) |
| 수정 1~5b단계 + 품질(Q) + 속도(S) | 10-03 | `tmp/fix-2026-10-03/REPORT.md`, `followups_verifier_findings.md` | `86aa7d8` |
| 수리 R1 | 10-03 | `tmp/repair-2026-10-03/R1/`, `verifyR1/` | `31de978` |
| 수리 R2('□' 보존) | 10-03 | `tmp/repair-2026-10-03/R2/` | 미커밋(진행 중) |
| 2026 수능 36책자 1차 매트릭스 | 10-03 | `tmp/coverage-2026-10-03/01_전과목_매트릭스_1차.md` | 없음(측정) |
| 오픈소스 조사·PoC | 10-03 | `tmp/oss-2026-10-03/REPORT.md`, `POC_REPORT.md` | 없음(조사) |

커밋 묶음상 신규 모듈 `app/host_guard.py`·`app/user_errors.py`·`app/pdf_export_review.py`와 검증 스크립트 일부(`verify_answer_key_import.py`, `verify_choice_prefix.py`, `verify_error_messages_ko.py`, `verify_pdf_semantics_false_positives.py`, `verify_pdf_title_subject.py`, `verify_simple_template.py`)는 `31de978`에 들어 있다. 기능상으로는 1~5단계 소속이다.

## 1. 범위와 결론

2026-10-02 전체 감사는 기본 기능(교사가 시험지 파일을 넣으면 한글에서 편집되는 HWPX가 나온다)을 '부분 동작'으로 판정했다. 실물 평가원 PDF 일부는 편집성 검증이 문서 전체를 422로 거부해 파일을 받지 못했다. 간단 모드에는 대체 경로가 없었다. PDF 외 입력은 파일은 나왔지만 미주형 시험지의 정답·해설과 '파일명 #N' 제목줄이 본문에 인쇄됐다. 10-03에는 감사가 정한 순서(검증기 오탐 → 422 완화 → 폴백 → simple 양식 → 오류 문구·보안)대로 고쳤고, 품질·속도 개선과 수리 R1을 더했다. 그 결과 실물 PDF 16건은 모두 파일을 받는다(10/16 → 16/16). 결함 문항은 거부 대신 '확인 필요' 경고로 표시된다. 미주형 비PDF의 본문 정답·해설 노출은 46 → 0, 40쪽 국어 PDF 변환은 88.4 → 47.1초가 됐다. 통합 게이트에는 기존 FAIL 1건 외 새 실패가 없다. 다만 파일을 받는 것과 내용이 맞는 것은 다르다. 경고 없이 나간 결과에도 원본 '□' 소실이 있었고(R2 진행 중), HWP 원본의 병합 셀·미주 매핑, 배치 점수 목표, 한컴 실제 열기는 아직 확인되지 않았다. 기본 기능 판정은 여전히 '부분 동작'이다. 다만 막힘의 중심이 '파일을 못 받음'에서 '받은 파일의 내용 충실도'로 옮겨 갔다.

## 2. 수치 전후표

| 지표 | 전 | 후 | 기준·출처 |
| --- | --- | --- | --- |
| 실물 PDF 결과 수령(`/api/pdf-layout-export` 200) | 10/16 | **16/16** | 16건(정답지 합본 1건 포함). 후는 기본값 `strict=false`. `tmp/fix-2026-10-03/step1/matrix_before.json`, `verify5a/matrix_retry.json`. R1 뒤 재검 `tmp/repair-2026-10-03/verifyR1/r3/matrix.log`도 16/16 |
| 그중 422 거부 | 6 | **0** | 현재 경고와 함께 제공 4건: 수학 2025(4문항), 수학 2교시(7문항), 국어 20쪽(문서 단위 2건), 정답지 합본(문서 단위 3건). 물리는 품질 단계에서 경고 0이 됐다 |
| 미주형 비PDF(web_math.hwpx 46문항) 간단 변환의 '정답:'·'해설:' 줄 | 46·46 | **0·0** | '#N' 제목줄 46 → 0, 정답은 문서 끝 정답표 1개. `tmp/fix-2026-10-03/step4/summary_after_r3.json` |
| 40쪽 국어 PDF 변환 시간 | 88.4초 | **47.1초**(-47%) | 전 = 속도 단계 직전 트리. HEAD 기준선은 98.2초. 서버 없이 같은 경로를 재생, 2회 중 최소, CPU 경합 중 참고값. 산출물 정규화 해시 동일 |
| 수식 중괄호 불균형 | 46 | **0** | 전 = 1~5단계 뒤·품질 단계 직전. 46은 수정 보고서 요약의 집계값이다. 같은 보고서 §3 표의 PDF 샘플별 값(수학 5종 7·7·9·14·2)을 더하면 39이며, 차이는 재확인하지 못했다. 후는 17샘플 모두 0 |
| 수식 '$' 유출 | 5 | 0 | 같은 보고서 §3 |
| 통합 게이트(`run_all_verify.py`) | PASS 103 · SKIP 11 · FAIL 1 | **PASS 112 · SKIP 11 · FAIL 1** | 전 = 10-02 감사(HEAD), 후 = 속도 단계 뒤 전체 124개. FAIL은 둘 다 `verify_external_exam_detail_quality.py`(2026-09-23부터 있던 품질 미달). R1 뒤에는 관련 106개만 다시 돌려 PASS 99 · SKIP 6 · FAIL 1(같은 항목) |
| 2026 수능 36책자 1차 매트릭스 | 측정 없음 | **36/36 수령, 문항 번호 1,064/1,064 일치** | 1~3단계 스냅숏 기준. 경고 없이 제공 17, 경고와 함께 제공 19, 폴백 0, 실패 0. 구조 결함 0. 최종 코드 2차 실행은 아직 없다 |

바뀌지 않은 지표도 적는다.

- 원본 배치 점수 목표(96·98)를 넘은 샘플·책자는 없다. 최고 89.75(한국사).
- 36책자 출력 쪽수는 원본 232쪽 → 284쪽이고, 28책자가 원본과 다르다.
- 6월 고1 3과목 36쪽 가혹 평균은 감사 시점 87.47이다(목표 93). 수정 뒤 다시 재지 않았다.
- e2e 핀 3건은 문항·이미지·reopen이 그대로다.

## 3. 변경 내용(기능별)

### ① 검증기 오탐 3종

- 분수 operand에 지수 꼬리 글리프를 포함한다. ⓐ~ⓩ 예문 표지를 LABEL에 넣고 `[A-Z]` 표지 제거를 양쪽에 대칭으로 적용한다. 수식 예약어(LEQ 등)가 첨자 base로 흡수되지 않게 `_RESERVED`를 분리한다.
- 주요 파일: `app/pdf_source_semantics.py`, `app/pdf_paragraph_flow.py`, `app/pdf_script_attachments.py`, `docs/reference_samples_manifest.md`(kor20 등록).
- 효과: math26_6 422 → 200, kor20 플래그 14 → 1(실제 결함 1건만 남음). 기존 200 10건은 점수·문항·수식 수 동일.
- 회귀 픽스처: `scripts/verify_pdf_semantics_false_positives.py`(실물 2건이 없으면 exit 2, `--synthetic-only` 지원).

### ② 422 → review 경고 제공(strict 옵션)

- 편집성 검증 실패를 문서 거부 대신 200 + `review`(문항 단위 표시, flag_count, 문서 단위 항목)로 내려준다. 치명 조건(`no_editable_content`, `package_integrity`)과 `strict:true` 요청만 예전처럼 422다.
- 주요 파일: `app/main.py`, `app/pdf_export_review.py`(신규), `app/desktop_convert.py`, `static/app.js`, `static/styles.css`.
- 회귀 픽스처: `scripts/verify_pdf_layout_export_api.py`의 `check_review_contract`, `scripts/verify_frontend_conversion_behavior.js`. 기존 엄격 검사 스크립트 6개에는 `strict=True`를 명시했다.

### ③ 간단 모드 PDF 폴백·즉시 변환

- 편집형 변환이 4xx면 인식 문항으로 `/api/export`를 실행해 재구성형 HWPX를 준다. 오류 문구에서 서버 경로 조각을 제거한다.
- 속도 단계에서 PDF는 선택 즉시 변환한다. 인식은 폴백이나 '문항 편집' 진입 때만 한다(이중 처리 제거).
- 주요 파일: `static/app.js`.
- 효과: 정답표 붙은 합성 PDF·스캔 합성 PDF도 폴백으로 HWPX를 받는다.
- 회귀 픽스처: `scripts/verify_frontend_conversion_behavior.js`(경로 제거 8종, 폴백 5경우), `scripts/verify_frontend_simple_converter.js`(PDF 계약 핀 6개), `scripts/verify_progressive_entry.js` 갱신.

### ④ simple 양식

- 간단 변환 전용 양식이다. 정답·해설은 문서 끝 정답표로 보내고, 파일명 제목줄을 없애고, 원문자 선지를 유지한다. 원본 번호는 발문 첫 줄에 한 번만 붙인다. Windows 기본 앱·웹 체험판도 이 양식을 쓴다. basic 양식 출력은 전후 동일하다.
- 주요 파일: `app/exam_templates.py`, `app/hwpx_writer_v2.py`, `app/hwpx_writer.py`, `app/docx_writer.py`, `app/main.py`, `app/preview.py`, `app/desktop_convert.py`, `app/web_convert.py`, `static/app.js`.
- 효과: 입력 5종(HWPX 2·DOCX·TXT·국어 HWP)에서 '정답:'·'해설:'·'#N'·'1)' 선지 0, 번호 원본 일치. 국어 HWP DOCX의 지문 묶음 번호 중복 11 → 0.
- 회귀 픽스처: `scripts/verify_simple_template.py`.

### ⑤ 백엔드 묶음

- 한국어 오류 코드: 실패 응답을 `{code, message, hint}`로 통일하고 영문 진단·절대경로를 내보내지 않는다(`app/user_errors.py`, 코드 21종). 스캔 PDF는 `scan_only`, 정답표 섞인 PDF는 `unsupported_structure`로 안내한다.
- Host/Origin 가드: 순수 ASGI 미들웨어다. 허용 목록 밖 Host는 400, 다른 출처의 변경 요청은 403이다(`app/host_guard.py`, `app/local_auth.py`의 `same_origin_problem`). DNS 리바인딩 지적(P1)을 막는다.
- 선지 접두 정규식: '0.5', '3.5', '2 cm', '1 : 2', '12.5%'가 잘리지 않는다(`app/hwpx_writer.py` `CHOICE_PREFIX_RE`, `app/docx_writer.py`).
- 정답표 차단: 문서 끝 정답표를 가짜 문항으로 만들지 않고 정답 칸에 기입한다. 미주 정답도 문항에 붙인다(`app/importers.py`).
- `/api/collect`가 항상 400이던 문제(블록 원소 수 불일치)를 고쳤다(`app/collector.py`).
- 회귀 픽스처: `scripts/verify_error_messages_ko.py`, `scripts/verify_api_hardening.py`(Host·교차 출처), `scripts/verify_choice_prefix.py`, `scripts/verify_answer_key_import.py`, `scripts/verify_importers.py` 갱신.

### ⑥ 프런트 묶음

- 422 목록과 hint를 한국어로 보여 준다. 0바이트·확장자 없는 파일은 서버에 보내기 전에 막는다(서버 요청 2회 → 0회).
- 다운로드 파일명: `filename*=utf-8''` 소문자 처리와 '%' 디코드로 'URI malformed' 실패를 없앴다.
- 0문항이면 서버 notices[0]을 사유로 보여 준다. 결과 카드 안내는 접고, 품질 줄 중복을 없앴다.
- 주요 파일: `static/app.js`.
- 회귀 픽스처: `scripts/verify_frontend_error_notices.js`.

### ⑦ 품질(수식 구조·제목·영역 판별)

- 수식: 중괄호 균형 게이트, √ 피연산자 흡수, 첨자 기준선·중첩 지수·집합 중괄호 복원, '$' 유출 제거. 효과는 중괄호 불균형 46 → 0, '$' 유출 5 → 0, `sqrt{□}` 40 → 0. 점수 하락은 최대 -0.13이다.
- 제목: 업로드 저장 파일명('날짜_시각_uuid_…')이 수식으로 조립되던 것을 원래 파일명 일반 텍스트로 바꿨다.
- 영역 판별: 1쪽 '○○ 영역' 줄 → 교시 → 판별 불가면 비움 순서다. 국어·영어 PDF의 '수학 영역' 머리말과 과탐의 수학 양식이 바로잡혔다.
- 주요 파일: `app/math_text.py`, `app/hwpx_writer.py`, `app/hwpx_writer_v2.py`, `app/pdf_native_content.py`, `app/pdf_layout_writer.py`(`detect_source_subject`), `app/pdf_source_line_cache.py`, `app/main.py`.
- 회귀 픽스처: `scripts/verify_math_structure_repairs.py`(6핀 추가), `scripts/verify_pdf_title_subject.py`.

### ⑧ 속도(pdf_source_page_memo, 락 범위)

- PDF 쪽 단위 `get_text`·레이아웃 결과를 파일 내용 SHA-256 + 쪽 번호 키로 메모한다. 호출자는 복사본을 받는다. 64쪽 초과 문서는 메모하지 않고, 변환이 끝나면 해제한다. 읽기 전용 호출 17곳(10개 모듈)을 메모로 바꿨다.
- `_EXPORT_LOCK`은 run_dir·파일명·원본 사본 구간만 잡는다. writer는 락 밖에서 돈다.
- 효과: 40쪽 국어 -47%, 16쪽 국어 -57%, 16쪽 영어 -44%. 산출물은 section·header·BinData 정규화 해시가 같다. 40쪽 피크 메모리는 865 → 992MB(+127MB).
- 주요 파일: `app/pdf_source_page_memo.py`(신규), `app/pdf_layout_writer.py`, `app/main.py`, PyMuPDF 호출 모듈 10개.
- 회귀 픽스처: `scripts/verify_pdf_source_page_memo.py`, `scripts/verify_pdf_export_lock_scope.py`.

### ⑨ R1 수리(`31de978`)

수정 단계 검증자가 남긴 미해결 지적을 고쳤다.

- 정답표 휴리스틱 회귀 제거(`app/importers.py`): 5a단계의 '[정답]' 3개 이상 규칙이 정상 문항 쪽·블록을 정답 구간으로 오인했다. 이제 머리글 정규식만으로 정답 구간을 판정한다. 첫 줄이 문항 번호인 블록은 정답 구간이 아니다. PDF는 첫 3줄을 줄마다 따로 본다. 앞쪽보다 큰 번호만 있는 쪽은 문제 쪽으로 본다. 숫자 선지 목록('① 1 ② 2 …')은 번호-정답 짝으로 읽지 않는다. R1 1차에서 평가원 공식 정답표 첫 쪽 인식이 36/36 → 0/36으로 떨어진 것을 2차에서 36/36으로 되돌렸다.
  - 효과(합성 재현 F1~F3): 인라인 '[정답]' PDF의 지어낸 정답·거짓 안내 제거, DOCX 한 문단 3문항 잘림(2문항) → HEAD와 같은 4문항, '정답표'로 끝나는 발문 + 숫자 선지의 선지 소실·지어낸 정답 제거. 정답지 합본 PDF 20문항 + 정답 20, 합성 정답표 PDF 10 + 10은 유지.
  - 회귀 픽스처: `scripts/verify_answer_key_import.py`(재현 케이스 추가).
- 조건 줄 번호 오인(`app/exam_templates.py` `numbered_stem_paragraphs`): 둘째 줄부터는 '.' 구분자만 번호로 인정한다. 발문 아래 '1) 2)' 조건 줄이 'N.' 번호 줄로 바뀌지 않는다. 회귀 픽스처: `scripts/verify_simple_template.py`(v2·v1·DOCX 단언).
- 검증자 잔여:
  - `verify_math_structure_repairs.py`의 비raw `"\f"` 픽스처를 raw 문자열로 고쳤다.
  - `verify_pdf_title_subject.py`의 변환 실패 'SKIP-ish' 경로를 명시적 실패로 바꿨다.
  - `_hancom_eqn_script` 변경에 맞춰 v1 텍스트 런·PDF 텍스트 런 호출부도 수식 밖 '{'·'}'를 본문으로 돌려준다(조용한 소실 방지).
  - 근호 때문에 같은 줄에서 둘로 갈라진 수식 조각과 그 사이 '+'·'−'를 한 수식으로 합친다(`app/pdf_layout_writer.py` `_join_adjacent_recovered_math_spans`). 25수능 수학 수식 수가 738 → 710으로 줄었다(조각 병합). 회귀 픽스처: `scripts/verify_native_radical_join.py`.
- 독립 재검(`tmp/repair-2026-10-03/verifyR1/r2/`, `r3/`): 실물 매트릭스 16/16 200, review 플래그는 품질 단계 뒤와 동일. HWP·HWPX 5종 가져오기 문항·정답 수 R1 전후 동일. e2e 기준선 일치.

## 4. 알려진 미해결·후속

### 내용 결함

- **원본 '□' 소실(R2 진행 중)**: 1차 매트릭스에서 5책자 45개가 모두 사라졌다(국어 6, 정치와 법 24, 프랑스어Ⅰ 5, 일본어Ⅰ 6, 베트남어Ⅰ 4). 미복원 수식 자리표시자 '□'를 지우는 처리가 원본 글리프 '□'까지 지웠다. review는 이를 잡지 못했다(국어·일본어Ⅰ은 경고 없이 제공). R2 편집(`app/pdf_layout_writer.py`, `app/pdf_native_content.py`, `scripts/verify_box_symbol_preserved.py`)은 작업 트리에만 있다. R2 편집 뒤 7개 파일 측정에서 원본에 '□'가 있는 6개(위 5책자 45개, kor20 14개)는 원본 수만큼 본문에 남았다(`tmp/repair-2026-10-03/R2/after.log`). 수학 2종 재측정과 게이트는 끝나지 않았다.
- 1차 매트릭스의 다른 결함: 제2외국어/한문 9책자 머리 영역 오표기('수학 영역' 7, '국어 영역' 2), 아랍어Ⅰ 업로드 저장명 누출. 품질 단계의 영역 판별·제목 수정 뒤 2차 매트릭스를 돌리지 않아 해소 여부를 모른다.
- 품질 단계 미구현 4건: 적분 상·하한 분리, 중첩 첨자 그룹, 문항 간 조각 누출(수학 2교시), 25수능 수학 머리말·쪽번호(검사기 거짓 ok).
- 정답지 합본 PDF를 편집형으로 변환하면 정답표가 문항 글상자에 섞인 채 나간다(문서 단위 경고 3건).
- kor20 '화면에 보이지 않는 그림' 1개는 위치를 특정하지 못했다.

### HWP IR 완전 매핑

rhwp IR에는 있지만 가져오기가 쓰지 않는 정보가 있다(`tmp/oss-2026-10-03/REPORT.md` §9 P1).

- 국어 HWP 병합 셀 97개: 출력 `cellSpan>1`이 0이다.
- 국어 HWP 셀 안 그림 9개와 중첩 표 2개: 소실된다.
- 수학 HWP 미주 46개(문항별 정답·해설): answer/explanation 0/46이다.
- 짧은 수식 86개가 평문으로 바뀐다(`_wrap_eqn` 규칙).
- 국어 HWP의 rhwp 491쪽(원본 17쪽) 원인은 IR이 아니다. 가져오기가 공유 지문 본문을 1×1 표 하나로 합성해 셀 높이가 쪽을 넘는다(`app/importers.py`의 지문 표 합성). 지문은 문단 테두리나 쪽 높이 기준 분할로 내보내야 한다.
- 글상자와 문단 모양은 IR 자체에 없다(rhwp 한계).

### 오픈소스 PoC 채택 과제

PoC 결론은 즉시 채택 0, 조건부 채택 4, 참조 전용 2다(`tmp/oss-2026-10-03/POC_REPORT.md` §1·§4).

1. `colPr sameSz="true"` 표기: 36/36 산출물이 해당한다. python-hwpx 6.7과 HwpForge가 거부한다. 실제 한컴 산출 HWPX의 표기를 먼저 대조하고 `"1"/"0"`으로 바꾼다.
2. python-hwpx 6.7 수식 측정 이식: 산출 수식 `hp:sz` height·baseLine이 1766/1766 모두 0이다. `hwpx/equation/{measure,eqedit,tokens}.py`(stdlib만, Apache-2.0)를 벤더로 들여와 실측값을 넣는다.
3. 자체 수식 게이트 패턴 2종: U+20D7 결합 화살표를 `vec`로 복구, 조각 수식(괄호 불균형·연산자로 끝남) 진단 플래그. 외부 파서(pylatexenc·latex2mathml)는 런타임 의존성으로 들이지 않는다.
4. rhwp CLI 0.8.6 `export-hwpx --verify --verify-pages`: HWP를 '원본 그대로' HWPX로 받는 보조 모드 후보다. PoC에서 쪽수 17→17·35→35, 다단·그림·수식이 보존됐다. 바이너리는 저장소에 넣지 않고 경로 설정으로 받는다. 한컴 열기는 미확인이다.

### 그 밖의 후속

- **36쪽 93점 목표 미달**: 이번 작업은 점수 상향을 범위로 두지 않았다. `verify_external_exam_detail_quality.py` FAIL이 그대로 남아 있다. 영어 그래프 라벨·안내문, 국어 1쪽 겹침, 25수능 수학 머리말·꼬리말이 대상이다.
- **한컴 실제 열기 미검증**: 이번 산출물은 rhwp 렌더와 패키지 구조 검사까지만 했다. 중괄호를 본문 런으로 돌린 출력의 실제 모양도 모른다. 한글 2024는 설치돼 있으나 자동화 시 오류 모달이 떴으므로 사람이 먼저 수동으로 연다.
- **취소 구현 미병합**: 비동기 취소 구현 `b2bffac`(브랜치 `claude/nervous-chatelet-232e20`)는 아직 가져오지 않았다. 감사 시점에는 두 번 취소하면 약 165초 동안 429가 났다. 락 범위 축소 뒤 이 증상을 다시 재지 않았다. 충돌이 있어 수동 포팅이 필요하다.
- 속도 미처리 핫스팟: `inspect_source_images`, `find_tables` 2회, `recognize_pdf` 2회, `deepcopy`, fidelity 렌더(42쪽 합성에서 64%). 64쪽 초과 문서와 200쪽 1.4GB 사례는 다루지 않았다.
- 일부 verify 스크립트가 `HWP_MAKE_DATA_DIR`를 무시하고 저장소 `data/`에 산출물을 쓴다. 출력 경로를 데이터 디렉터리 설정이나 tmp 기준으로 옮겨야 한다.
- master 병합: fast-forward가 가능하다. `tmp/oss-2026-10-03/REPORT.md` §2-3은 `--no-ff` 병합을 권한다. 그 전제였던 검증 지적 6건은 4단계와 R1에서 해소됐다. known-fail 처리 결정과 병합 전 게이트 재실행이 남았다.

### 사용자 결정 항목

1. 경고가 붙은 결과를 내려받기 전에 고지(확인 절차)할지. 지금은 자동으로 내려받고 결과 카드에만 표시한다. `strict:true`로 예전 거부 동작은 유지된다.
2. 정답지 합본 PDF에서 정답 쪽을 떼어낼지, 지금처럼 경고와 함께 둘지.
3. 동시 변환 메모리: 락 축소로 2건 동시 변환 시 writer 피크가 두 배가 될 수 있다. `_CONVERSION_SLOTS`를 1로 낮출지.
4. `verify_external_exam_detail_quality.py`를 known-fail(사유·만료일)로 명시할지, 병합 전에 해소할지.
5. 감사 `02_디자인_단순화.md` §8의 디자인 결정 9건.
6. 감사가 만든 DB 백업 사본(§6)을 지울지.

## 5. 검증 방법과 재현

- 통합 게이트: `PYTHONUTF8=1 python scripts/run_all_verify.py --output-dir <tmp 경로>`. 일부만 돌릴 때는 `--only <스크립트명>`을 쓴다. `--output-dir`가 없으면 `data/verification/`에 기록한다. 샘플·패키지·한컴 저장 PDF가 없는 11개는 exit 2(SKIP)다.
- e2e: `python scripts/e2e_verify.py <샘플>`이 `scripts/_e2e_baseline.json`과 비교한다. 품질 단계에서 `--update`를 1회 했다. 사유는 업로드 저장 파일명 제목과 '1. <제목>' 머리글이 수식으로 조립되던 것이 일반 텍스트가 된 것이다(수식 수 corpus 44 → 42, 국어 HWP 48 → 2). 문항·이미지·reopen은 같았다. 이후 속도 단계, 최종 게이트, R1은 갱신 없이 일치했다. fresh 워크트리에서는 e2e 핀 샘플 2건을 먼저 복사해야 한다.
- 격리 서버 규칙(모든 단계 공통):
  - `HWP_MAKE_DATA_DIR`를 `tmp/<작업>/data/<단계>`로 지정한다. 웹 프로토타입 테스트는 `HWP_WEB_DATA_DIR`도 지정한다.
  - 에이전트마다 전용 포트를 쓰고, `/api/health`의 `data_dir`이 격리 경로인지 확인한 뒤 시작한다.
  - 끝나면 프로세스를 종료하고 LISTEN이 없는지 확인한다. 서버 로그 Traceback 0을 기준으로 둔다.
  - GUI 실행 금지: Hwp.exe·COM·배포 exe·Tk. 렌더 판정은 rhwp로 한다.
- 실물 매트릭스 재현: `tmp/coverage-2026-10-03/run_matrix.py --base <서버> --out <폴더>`. 간단 모드 payload(structured, native_math, variant_policy all, boxed_passages)를 그대로 재현한다. 책자별로 순차 실행한다. 원본 PDF는 `data/external_exam_qa/2026_csat/`에 있다(git 무시).
- 산출물 위치(모두 git 무시): 감사 `tmp/audit-2026-10-02/`, 수정 `tmp/fix-2026-10-03/`(단계별 패치 `patches/`), 수리 `tmp/repair-2026-10-03/`(패치 `patches/R1*.patch`, `verifyR1*.patch`), 매트릭스 `tmp/coverage-2026-10-03/`, 오픈소스 `tmp/oss-2026-10-03/`. 시간 수치는 다른 작업과 CPU를 함께 쓴 참고값이다.

## 6. 감사 자체의 부작용과 정리 결과

| 부작용 | 원인 | 정리 결과 |
| --- | --- | --- |
| 문항 DB `data/problems.sqlite3`에 테스트 행 3개(id 151~153) | 반박 검증 스크립트 하나가 데이터 디렉터리 격리 없이 실행됨 | 백업 뒤 삭제(현재 89행, 최대 id 150). 백업 `data/problems.sqlite3.bak-20261002-audit`와 `-shm`·`-wal`은 남아 있다(사용자 문항 전체 사본, 확인 후 삭제 가능) |
| Python 3.14 사용자 레지스트리 등록이 tmp 경로로 덮임 | 에이전트가 `LOCALAPPDATA`를 tmp로 바꿔 실행하자 Windows 앱 별칭이 tmp에 Python 3.14.8을 새로 설치하고 PEP 514 등록 키(PythonCore 3.14)를 덮어씀 | `py install --refresh`로 실제 설치(3.14.3)에 재등록. 시작 메뉴 바로가기 5개 정상. 임시 설치 폴더 삭제 |
| 한글 2024 오류 모달, 배포 exe 예외 창이 사용자 화면에 뜸 | 감사 보완 단계 에이전트가 Hwp.exe와 dist 실행 파일을 직접 실행 | 남은 상태 없음. 이후 모든 단계에 GUI 실행 금지 규칙을 넣었다 |
| 게이트 QA 산출물이 `data/` 아래에 생성·덮어쓰기(신규 573, 덮어쓰기 95), `data/verification/20261002_215737_718689`, `data/uploads` 중간 이미지 203개 | 게이트와 일부 verify 스크립트의 원래 동작(`data/` 경로 하드코딩) | git 무시 대상이고 재생성 가능. 추적 파일 변경 없음(`git status -- data` 비어 있음). 수정·수리 단계 검증에서도 같은 위치에 다시 썼다. 선택 정리 대상 |
| `data/web_prototype` 폴더 수정 시각 변경 | `verify_web_prototype`을 데이터 디렉터리 지정 없이 실행 | 파일 생성·변경 없음 |
| 오픈소스 PoC 격리 venv·소스·바이너리 | PoC 실행 | `tmp/oss-2026-10-03/` 안에만 있음. 시스템 pip 차이 0. 폴더 삭제로 원복 가능 |
