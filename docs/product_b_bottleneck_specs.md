# 제품 B 병목 해결 스펙팩 (2026-07-08)

제품 B = **입력 PDF/이미지 → 원본과 같은 레이아웃의 편집형 HWPX**(흐름기반 재구성, writer=`app/hwpx_writer_v2.py`). 절대좌표 글상자는 한컴이 거부→폐기. 아래는 5개 병목의 **바로 적용 가능한** 해결 스펙(서브에이전트 정밀조사 근거). 저장소가 병렬 편집 중이라 핫파일은 **append-only + 신규키/컬럼 가드**로 3-way merge 충돌을 최소화한다.

> ⚠️ **최우선 블로커(코드 아님):** 이 저장소엔 **실제 평가원/학평 PDF가 없다**(현존 PDF는 전부 fitz 합성본, PUA 없음·표준폰트). 그래서 (a) 병목 #2(E0xx 수식복원)는 실물 샘플 없이는 매핑표를 못 뽑고 검증도 불가, (b) **제품 B 레이아웃 충실도 전체가 실제 타깃 PDF로 한 번도 검증된 적 없다.** → 실제 평가원 수학/과탐/국어 born-digital PDF 2~3부 확보가 다음 단계의 전제.

상태 범례: ✅완료 / 🔧코덱스 적용대기(스펙 확정) / ⛔블로커

---

## #6 마스트헤드 하드코딩 — ✅완료(파서+writer 배선)

**근본원인:** `hwpx_writer_v2.py:1103` `para(template.masthead_title or title, ...)` — 템플릿 상수가 문서 title을 무조건 덮음. 인식은 `pdf_segment.py`에서 상단 헤더를 마커 배제용으로만 쓰고 텍스트 폐기.

- ✅ **완료:** `app/exam_header.py`(`parse_exam_header`/`masthead_from_meta`/`masthead_from_text`) + `scripts/verify_exam_masthead.py`(파서 6케이스 + writer 스모크 green).
- ✅ **배선:** `pdf_segment.py`가 상단 13% 헤더를 `header_text`로 보존, `pipeline.py`가 `RecognitionResult.exam_title` 산출, `importers.py`가 반환 dict/notice에 `exam_title` 포함, `hwpx_writer_v2.py`/`hwpx_writer.py`가 `title or template.masthead_title` 우선순위로 출력.

---

## #1 인식 레이아웃 정보 소실 (컬럼·bbox·읽기순서) — ✅1차 완료

**근본원인:** 인식은 이미 앎(`pdf_segment.py:644` `page.metadata["column_count"]`, `pipeline.py:42,44` `RecognizedProblem.column_index/box`) → 그러나 `importers.py:222-235` sink.add dict에 안 실어 평면 storage에서 전량 소실 → writer가 `hwpx_writer_v2.py:466` `min(template.columns,2)`로 원본 무관하게 2단 재추론.

- ✅ **1차(문서 단수만, 최소 침습):**
  - `pipeline.py` `RecognizedProblem`에 `column_count/page_width_px/page_height_px` 필드 추가, 생성부에서 `page.metadata["column_count"]`·`page.width_px/height_px`로 채움.
  - `importers.py`가 `layout` dict(`column_count/column_index/page/bbox_px/block_type`)를 문제 dict에 포함.
  - `storage.py`: `layout_json` 마이그레이션, create/update/row_to_problem 왕복 보존.
  - `app/layout_model.py`: `recognized_column_count(problems)`·`column_break_before(prev,cur)`·`px_to_hwpunit`.
  - `hwpx_writer_v2.py`: `recognized_column_count(problems)`가 있으면 템플릿 기본 단수보다 우선.
- 🔧 **2차(완전):** 동일 `layout_json`에 `column_index/reading_order/page geometry/bbox_px/block_type/stem_group` 확장(스키마 변경 없음). writer는 `column_break_before`로 원본 컬럼 경계에서만 단 넘김(layout 없으면 기존 추정 폴백). 지문↔문항 링크 = `stem_group` 공유 규약.
- **인수 테스트:** `scripts/verify_layout_model.py`, `scripts/verify_layout_wiring.py` green. `layout=1`이 `kice_math` 기본 2단을 이기고, `layout=2`는 2단 `colPr`를 유지.

---

## #2 born-digital 수식 PUA(E0xx) 미복원 → ✅해결 (실물 18부 91.8% 커버리지, 배선 완료)

**근본원인:** `math_text.py:275` `_symbol_pua_map()`이 F0xx(Adobe Symbol)만 매핑, E000–EFFF(한컴 임베디드 수식 서브셋) 키 0개 → `is_recoverable_pua_math_char`=False → `pipeline.py:105` `_pua_ratio`가 E0xx를 복구불가로 세어 0.12 초과 → `text_reliable=False` → `importers.py:199` 문항 전체 이미지, stem/choices 폐기 → **편집 불가**.

**fitz 실측 조사결과(복원 API는 모두 존재):** span에 `'font'` 존재(폰트 스코프 판별 가능), `doc.xref_get_key(font_xref,"ToUnicode")`+`xref_stream` 파싱, `get_texttrace()`=(unicode,gid,bbox), `extract_font(xref)`. **단 `get_text`는 이미 ToUnicode 적용 후라 E0xx가 나온다는 것 자체가 ToUnicode 채널 복원 불가를 의미** → 남는 결정론 채널 = **폰트별 정적 E0xx→유니코드 표**(문서 독립 고정 코드페이지일 때만 100% 결정론).

- ✅ **매핑표 완료:** 실물 평가원 PDF 18부(사용자 제공)에서 각 E0xx 글리프를 렌더·육안 확정 → `app/hancom_pua_map.py`(신규). 인코딩이 완전 순차적(대문자 A–Z=U+E000+offset, 소문자 a–z=U+E0E5+offset, 숫자 1–9=E034–E03C·0=E03D)임을 확인 → **문서 독립 100% 결정론**. `scripts/verify_hancom_pua_map.py`가 매핑 + 실물 커버리지(**12025/13097 = 91.8%**)를 검증.
- ✅ **배선 완료:** `math_text.py`에서 `SYMBOL_PUA_MAP = {**_symbol_pua_map(), **HANCOM_PUA_MAP}` 한 곳 병합 → `is_recoverable_pua_math_char`/정규화 전 함수에 자동 전파(단일 지점). 실물 `26-6월 수학` 재검증: **before 문항46/수식0/이미지46 → after 문항46/수식185/이미지25/reopen=True**(21문항이 이미지→편집텍스트, 복원 수식이 hp:equation 185개로 방출).
- ✅ **2026-07-08 추가 보강:** `E07A`는 케이스 큰 중괄호 하단 구조 조각으로 확인되어 텍스트에서는 제거 처리. `E06D`는 분수선/근호/윗줄 구조 힌트로 유지하되, 선택지 전용 재조립을 추가했다. 지원 패턴: `분자열 → ①2□/②2□3... → 분모열` 지수분수, `①□/②□ → 분자열 → 분모열` 분수, 선택지 단독 `□n`/`-□n` → `\frac{1}{n}`. `math_text` 쪽은 선택지 라인을 개별 지수로 선변환하지 않도록 가드해 그룹 복원이 우선된다.
- ✅ **실물 PDF QA 현재값:** `scripts/verify_real_pdf_math_samples.py` 기준 4종 모두 문항 46개, overflow 0, native equation malformed 0. 남은 `□`는 stem의 복잡한 2D 구조(큰 분수/극한/도형식) 중심이며 choice 잔여는 `25수능 10`, `26-6월 12`, `수학 2교시 2`, `2025 홀수형 0`까지 축소.
- 🔧 **후속(2D 구조 복원):** 선형 치환이라 위/아래첨자·분수·근호는 평탄화(x²→x2, 삼각·방정식·부등식은 100% 정확). 글리프 bbox y-offset으로 super/subscript·fraction 재구성이 다음 단계(pdf_segment의 bbox 활용).

### 곁다리: 그리스문자 커버리지 4곳 동기화 — ✅완료
`math_text.py`(감지), `hwpx_writer.py`(LaTeX→EQN 변환), `hwpx_writer.py` 유니코드 그리스→EQN 매핑, `static/app.js`(프론트 배지)를 동기화. 소문자 `epsilon,zeta,eta,iota,kappa,nu,xi,rho,tau,upsilon,phi,chi,psi`, 대문자 `Gamma,Theta,Lambda,Xi,Pi,Sigma,Upsilon,Phi,Psi,Omega`, 변형 `varepsilon,vartheta,varpi,varrho,varsigma,varphi` 포함. `scripts/verify_hwpx_native_math.py`와 `scripts/verify_frontend_math.js`에 회귀 케이스 고정.

### 곁다리: Hancom EQN `sqrt` 약식 정규화 — ✅완료
HWP 추출 수식에서 `sqrt5`, `sqrt(n)`, `sqrt{a_{n}...}`, `sqrt{{x+1} over {...}}`처럼 들어오는 root 스크립트를 `sqrt {...}` 형태로 정규화. `scripts/verify_hwpx_native_math.py`에 직접 케이스를 고정했고, `scripts/qa_hwp_math_samples.py`는 malformed `sqrt` 스크립트가 실제 샘플 출력에 남으면 실패한다.

---

## #3 밀도/컬럼 충전율 — 🔧 부분 개선

**근본원인(정량 규명):** paraPr가 Skeleton base의 **줄간격 160%를 deepcopy 상속**(`_document_impl.py:4896`)하는데 추정기 `_STYLE_LINE_HEIGHTS['body']`는 125%(`hwpx_writer_v2.py:81` =1250)로 모델링 → **real/est=1600/1250=1.28**. 여기에 줄바꿈 한계 관대(+16~23%)가 겹쳐 est가 실제 rhwp 렌더보다 낮게 잡힘. `column_body_height=38000`은 안전하지만 컬럼 하단을 과도하게 비웠고, 물리 본문 높이(약 65762)를 그대로 쓰면 하단 overlap 위험이 있었다.

- ✅ **현재 적용:** `app/hwpx_writer_v2.py`에 `KICE_MATH_COLUMN_BODY_HEIGHT = 46000` 상수화. 실제 HWP 수학 샘플 4종 기준 46문항/선택지/표/그림/수식 싱크 유지, rhwp overflow 0, 출력 페이지 11/13/11/11쪽.
- ✅ **회귀 테스트:** `scripts/verify_density_regression.py` 추가. 합성 KICE-math 46문항(선택형 33 + 단답형 13, native 수식 344개, 표 포함)을 HWPX로 쓰고 rhwp 렌더까지 검사한다. 기준: 수식 객체/lineseg 이상 0, 문항·source marker·선택지·표·수식 inventory sync 0, 컬럼 침범 0, overflow 0, 8~18쪽 범위.
- 🔧 **남은 캘리브레이션:** `_STYLE_LINE_HEIGHTS` 125→실제 160% 반영, 줄바꿈 한계 재산정, 선지 그리드/표 셀 높이 보정이 필요하다. 이 추정기가 실제 렌더와 맞아진 뒤에만 63000대 물리 본문 높이 접근을 다시 시도한다.
- 참고: 원본 HWP 샘플은 “편집본”이라 원본 렌더 페이지가 30~37쪽으로 길다. 따라서 source/output 페이지 비율은 참고 플래그로만 보고, 현재 합격 기준은 시험지형 2단 출력의 수식·문항 싱크와 overflow 없음이다.

---

## #3a 평가원/학평 폰트·간격 기준 — 📌 지침 추가

**목표:** HWP/PDF → HWPX 변환 결과가 “텍스트가 들어간 문서”가 아니라 실제 평가원·교육청 시험지 편집본처럼 보이도록, 폰트/크기/줄간격/장평/자간을 템플릿 기준값으로 관리한다. 수식 구현과 레이아웃 겹침 검증은 이 타이포그래피 기준을 전제로 다시 캘리브레이션해야 한다.

- **한글 본문(국어·탐구·수학 지문):** 기본값은 `신명조` 또는 `HY신명조`. 일반 바탕체나 함초롬바탕은 폭과 획감이 달라 원본 대체값으로 보지 않는다. 폰트가 없는 환경의 preview fallback은 허용하되, HWPX 내부 스타일명은 원본 계열을 유지한다.
- **영어 지문 및 영문 표기:** `Times New Roman`을 기본값으로 한다. 영어 과목 지문, 선택지 내 영문, 타 과목의 영문 단위/기호 표기에 적용한다.
- **수학 과목 및 수식:** 변수(`x`, `y`, `n`, `a`, `f` 등)는 `Times New Roman` 이탤릭체 기준. 그 외 연산자·괄호·분수·루트·첨자·기호는 한글 수식 편집기 기본 수식 폰트 체계를 우선한다. 즉, 일반 텍스트 스타일로 수식을 흉내 내지 않고 `hp:equation`/Hancom EQN의 네이티브 수식으로 유지한다.
- **문항 번호·타이틀·안내 문구:** 문항 번호, 과목명, 상단 안내, 구역 제목은 `돋움` 또는 `중고딕` 계열을 기본값으로 한다. 본문 명조 계열과 섞일 때 번호/타이틀만 고딕으로 분리되어야 한다.
- **평가원/교육청 차이:** 과거 일부 교육청 편집본은 바탕체 또는 시스템 기본 서체 흔적이 있을 수 있으나, 현재 목표 템플릿은 평가원 시각 기준에 맞춘 `신명조` + `Times New Roman` 조합으로 통일한다.
- **초기 실무값:** 본문 크기 10~11pt, 줄간격 160~170%, 자간/장평은 HWP 샘플에서 추출한 값으로 보정한다. 장평은 특히 신명조의 좁은 폭감을 재현하는 핵심이므로, 임의 기본값으로 고정하지 않는다.

**구현 메모**

- ✅ `scripts/analyze_hwp_templates.py` 추가: 원본 `.hwp`를 `rhwp.export_hwpx()`로 풀고 `header.xml`/`section0.xml`에서 font face, charPr, paraPr, 줄간격, 장평, 자간, 수식 EQN 패턴, 표/그림/컬럼 정보를 리포트한다.
- ✅ `hwpx_writer_v2.py` KICE writer 반영: `kice_*` 템플릿은 `신명 중명조`/`한양신명조`/`HY신명조`/`Times New Roman`/`돋움`/`중고딕`/`HancomEQN` font face를 header에 보장하고, 본문 11pt, 장평 95, 자간 -5, 줄간격 165%를 적용한다. `kice_english` 본문은 `Times New Roman`을 우선한다.
- ✅ `scripts/verify_kice_typography.py` 추가: 생성 HWPX의 font face, charPr 장평/자간, 165% paraPr, native equation `HancomEQN`을 XML 레벨에서 검증한다.
- HWP 샘플 분석 스크립트는 문단/글자 모양에서 font family, point size, line spacing, char scale(장평), letter spacing(자간), `raw_style_id`를 같이 뽑아야 한다.
- writer 쪽에는 `kice_math`, `kice_korean`, `kice_english`, `kice_social_science` 같은 템플릿별 style map을 두고, 본문/영문/수식/번호/타이틀의 폰트 역할을 분리한다.
- 레이아웃 높이 추정기는 줄간격 160~170%와 실제 장평/자간을 반영한 뒤 다시 조정한다. 지금처럼 수식/선택지 싱크가 맞아도 폰트 폭이 달라지면 줄바꿈과 column overflow가 다시 변할 수 있다.
- HWP 샘플을 “까는” 다음 단계에서는 텍스트만 추출하지 말고, `rhwp.to_ir()` 기반으로 표/셀/문단/스타일/수식 EQN/이미지의 구조와 스타일을 함께 비교한다.

**검증 관문**

- 샘플 HWP 4종 분석 리포트에 본문/번호/타이틀/영문/수식별 font family, size, line spacing, 장평, 자간 요약을 출력한다.
- 생성 HWPX를 다시 열어 같은 항목을 추출하고, 샘플 기준과 diff를 낸다.
- 수식 회귀 테스트는 `hp:equation` 개수와 EQN 문자열뿐 아니라 수식 주변 줄바꿈, 선택지 위치, column overflow 0을 같이 확인한다.

---

## #3b 인식-입력 알고리즘 병합 기준 — 🔧진행중

**현재 결론:** PDF/HWP 입력은 목적이 다른 두 경로를 명확히 분리해서 병합한다. 문제은행 편집용은 기존 `/api/import` → recognition/storage → `hwpx_writer_v2` 경로를 유지하고, 실물 시험지 싱크용은 `/api/pdf-layout-export` → `pdf_layout_writer.write_pdf_flow_hwpx()` 경로로 바로 HWPX를 만든다. 두 경로를 한 버튼에 섞으면 “문항 DB 편집”과 “원본 시험지 복원”의 성공 기준이 달라져 회귀 원인을 추적하기 어렵다.

- **문제 인식/DB 입력 경로:** PDF를 문항 단위로 분리해 stem/choice/image/layout metadata를 저장한다. 이후 사용자가 문항을 골라 새 시험지를 재구성한다.
- **원본 레이아웃 HWPX 경로:** PDF 한 부를 그대로 편집 가능한 HWPX로 재생성한다. 텍스트는 문단/표 셀로 넣고, 전체 페이지 이미지 폴백은 금지한다. 표·도표·그림처럼 구조화가 위험한 일부 영역만 지역 이미지로 보존한다.
- **HWP 템플릿 캘리브레이션:** `scripts/analyze_hwp_templates.py`로 실제 `.hwp` 샘플을 HWPX로 export 후 header/section 스타일을 분석한다. 2026-07-08 실행 결과, 평가원 양식은 본문 `신명 중명조`/영어 `Times New Roman`, 장평 95, 자간 -5 계열이 반복 확인됐다. 교육청 국어 샘플은 `한컴바탕`, 장평 95, 자간 -3 계열이라 평가원 양식과 별도 profile로 다뤄야 한다.
- **앱 진입점:** 파일 업로드 영역에서 `가져와서 편집`은 DB 입력, `PDF 원본 레이아웃 HWPX`는 직접 HWPX 복원으로 동작한다.

**검증 관문**

- `scripts/verify_pdf_layout_export_api.py`: 앱 API에서 PDF 원본 레이아웃 HWPX를 생성하고 기존 HWPX 구조 검증기를 통과해야 한다.
- `scripts/verify_pdf_layout_hwpx.py --render`: 결과 HWPX가 rhwp 렌더링 가능하고 full-page raster fallback이 없어야 한다.
- `scripts/probe_hwp_open.ps1`: 설치된 한글 `HWPFrame.HwpObject` COM으로 결과물을 직접 열 수 있어야 한다.

---

## #4 혼합문서 부분폴백 부재 (파일단위 all-or-nothing) — ✅완료(결정론 이미지 폴백)

**근본원인:** `pipeline.py:227` `any_problems=any(...)` + `importers.py:191` `if not result.found: return None`(found=문항>0). 혼합문서면 인식이 파일 전체 소유 → `pipeline.py:246` `if not page.problems: continue`에서 마커 없는 페이지 콘텐츠 통째 소실(레거시도 인식도 처리 안 함). `empty_page_numbers`엔 판정만 기록.

- ✅ **구현:** `pipeline.py`가 `any_problems=True`인 혼합문서에서 마커 없는 페이지를 `_page_fallback_problem`으로 전체 페이지 이미지 문항에 병합. 순수 스캔/문항0 PDF는 여전히 `found=False`로 레거시/OCR 경로가 소유.
- OCR 실행부(`ocr_backend.build_ocr_backend`)는 훅 지점만 표시(키 필요, 별 PR). `_ai_available()` 게이팅 재사용, 키 없으면 no-op.
- **인수 테스트:** `scripts/verify_mixed_page_fallback.py` green. fitz 합성 [마커 페이지 + 마커0 페이지]에서 page 2 콘텐츠가 이미지-only 문항으로 보존됨.

---

## #5 pdf_layout_writer.py (절대좌표 부활) — 🔧판정 필요
폐기 확정된 hp:rect+drawText 접근이 호환패치와 함께 부활, 미배선·한컴 미검증(rhwp만 통과). **한컴 실개봉으로 수용/거부 판정 후 배선 or 삭제 재확정**(어느 쪽이 canonical인지 메모리 명문화). 흐름기반이 canonical인 현 방향에선 폐기 유력.

---

## 이번 세션에 적용 완료(내 저충돌 레인)
- ✅ `scripts/verify_marker_regression.py` — 마커 vs `1)2)3)` 선지 과분할 회귀핀(코덱스 수정 검증).
- ✅ `scripts/verify_recognition_schema.py` — IR 계약 불변식(병목 #1 확장 가드).
- ✅ `scripts/e2e_verify.py` + `_e2e_baseline.json` — import→export→reopen 골든 스냅샷.
- ✅ `scripts/run_all_verify.py` — 통합 회귀 게이트(서브프로세스+UTF-8강제, 0=green). **현재 9 PASS·1 SKIP·0 FAIL.**
- ✅ `app/exam_header.py` + `scripts/verify_exam_masthead.py` — 병목 #6 파서(배선만 코덱스 대기).
- ✅ `app/layout_model.py` + `scripts/verify_layout_model.py` — 병목 #1 격리 헬퍼(recognized_column_count/column_break_before/px_to_hwpunit) 완료. **코덱스는 hwpx_writer_v2:466에서 이걸 호출만** 하면 됨(재작성 불필요).
- ✅ `scripts/verify_mixed_page_fallback.py` — 병목 #4 인수 테스트(PASS, 페이지 폴백 배선 완료).
- ✅ `scripts/probe_kice_pua.py` — 병목 #2 매핑표 추출 프로브(실물 PDF 오는 즉시 가동).
- ✅ `run_local.ps1` — uvicorn 설치된 파이썬 선택(번들 결함 우회) + `-CheckOnly`.

## ✅ 최신 게이트 상태 (2026-07-08)
`python scripts/run_all_verify.py` 기준 **PASS 12 · SKIP 1 · FAIL 0**. `verify_math_exam_pipeline.py` 포함 전체 수식/실제 HWP 샘플 렌더 게이트도 green.

## 검증 관례
- 통합 게이트: `python scripts/run_all_verify.py`. 신규 `scripts/verify_*.py`는 자동 편입.
- exit 0=PASS, 2=SKIP(개인샘플 없음), 그 외=FAIL. 스크립트 상단 UTF-8 하드닝 관용구 필수.
