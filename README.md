# HWP Make

HWP Make는 PDF, HWP/HWPX, DOCX, 이미지, 텍스트, CSV/SQLite 자료를 문항 단위로 가져오고, 평가원/교육청 시험지 스타일의 편집 가능한 HWPX/DOCX로 내보내는 로컬 앱입니다.

현재 개발의 최우선 목표는 수학 시험지 기준입니다. 즉, 문항 번호 싱크, 네이티브 한글 수식, 실제 시험지 타이포그래피, 2단 레이아웃, 겹침 없는 렌더링을 동시에 만족하는 HWPX를 만드는 것입니다. Product B의 세부 기준과 폐기한 옛 기준은 `docs/product_b_bottleneck_specs.md`를 canonical 문서로 봅니다.

## 문서 역할

- [모의고사 HWP/HWPX 웹 조사·실물·앱 동작 연구](docs/audits/2026-09-21/exam_hwp_web_app_research.md): 19개 구조 계측과 공개 4종 가져오기에서 미주·문항 분리 실패를 재현했습니다. 한글 GUI 편집은 창 활성화 오류로 미검증이며, 재개 절차와 개발 우선순위를 정리했습니다.
- [최신 격자 안내문 문단 편집·엄격 재평가](docs/audits/2026-09-23/grid-frame-paragraphs-progress.md): 영어 27번 안내문의 글머리표 5개를 독립 문단으로 복원하고 편집·재저장을 확인했습니다. 36쪽 엄격 배치 평균은 **87.06**, 최저 **72.85**로 **93점 미달**입니다. 전체 회귀는 **103 통과·11 생략·1 실패**이며 영어 25번 그래프 라벨 배치 오류가 남아 있습니다.
- [이전 PDF→한글 개발·5분야 평가](docs/audits/2026-09-23/native-graph-annotations-progress.md): 그래프 표기 10개의 중복을 제거하고 편집 가능한 글자·수식으로 묶었습니다. 국어·수학·영어 36쪽 엄격 배치 평균은 같은 환경 기준 **86.85 → 87.04**, 전체 회귀는 **102 통과·11 생략·1 실패**, 정상 패키지 35개 유효입니다. 본문 10줄의 한 문단·790자 추가 편집과 그래프 앞 문단 244자 추가·재저장을 통과했습니다. **93점 미달입니다.** 과거 렌더 점수의 재현성, 원본 글꼴·일부 좌표와 실제 한컴 GUI 편집 검증이 남았습니다.
- [이전 문단·편집성 엄격 평가](docs/audits/2026-09-21/strict-paragraph-assessment.md): 실제 문단 연결·편집 재저장·문항 소속·그림·원본 배치를 함께 검사한 결과입니다.
- [이전 기능 평가 및 개선](docs/audits/2026-09-21/functional-assessment.md): 표 경계 그림·업로드 제한·검증 도구 수정과 당시 회귀 결과입니다.

- [PDF 편집성 검증 기준](docs/native_pdf_editability.md): 본문 크롭 우회 차단, 문항당 하나의 편집 가능한 글상자, 지구과학 3종 검증과 남은 배치 한계입니다.
- [로컬·웹 속도와 변환 품질 점검](docs/audits/2026-09-09/local-web-conversion.md): 같은 입력의 두 경로 실측, 결과물 동일성, 품질 한계와 검수 필터 최적화 실험입니다.
- [변환 품질·속도 개선 결과](docs/audits/2026-09-09/conversion-fixes.md): 수식·지문·삽화 보존 수정, 조판 보완, 검수 최적화 및 최종 검증 기록입니다.
- [웹 프로토타입 실행](docs/web_prototype.md): 로그인·내 파일 업로드·백그라운드 변환·다운로드를 실제 엔진으로 시험하는 별도 로컬 서버입니다. `pip install -r requirements.web.txt` 후 `python run_web_prototype.py`로 시작합니다.
- [웹 서비스 전환 기획](docs/web_service_plan.md): 비공개 베타 범위, 사용자별 자료 보호, 변환 대기열, 배포 구성, 개발 순서와 출시 관문을 정리한 구현 전 제안입니다.
- `README.md`: 실행 방법, 주요 경로, 현재 판정 기준, 검증 명령을 빠르게 확인하는 입구입니다.
- `docs/product_b_bottleneck_specs.md`: Product B의 현재 기준과 폐기한 옛 기준을 관리하는 canonical 문서입니다.
- `docs/priority_work_queue.md`: 지금 막아야 하는 P0/P1/P2 작업 큐입니다.
- `docs/current_self_assessment.md`: 실제 검증 결과를 기준으로 세분화한 현재 완성도와 다음 개발 순서입니다.
- `docs/full_subject_qa_2026_06.md`: 2026년 6월 고1 전과목 PDF와 사용자 제공 HWP의 과목별 경향 QA입니다.
- `docs/subject_conversion_performance_2026_07.md`: 국어·영어·수학·사회·과학·한국사의 문항 인식/레이아웃 변환시간과 벡터 밀집 PDF 최적화 결과입니다.
- `docs/subject_flow_layout_assessment_2026_07.md`: 전과목 원본 레이아웃의 여백·머리말·문단·표·수식 배치 편법을 점검하고 개선한 결과입니다.
- `docs/ui_reorder_layout_assessment_2026_07.md`: UI 문항 이동·드래그 뒤 예상 페이지·단과 실제 HWPX 경계 안전성을 검증한 결과입니다.
- `docs/reference_samples_manifest.md`: 로컬 레퍼런스 시험지 목록과 사용 목적만 기록합니다. 파일 자체는 커밋하지 않습니다.
- `docs/hwp_open_probe_checklist.md`: 한글 GUI 광고/수정권한/보호보기 이슈를 구분하는 체크리스트입니다.

## 실행

PowerShell에서:

```powershell
pip install -r requirements.txt
.\run_local.ps1
```

검증된 환경을 그대로 재현하려면 `pip install -r requirements.lock.txt`를 사용하세요 (버전 고정 스냅샷, 원본은 `requirements.txt`).

브라우저에서 `http://127.0.0.1:8787`을 엽니다.

## 현재 사용 경로

### 1. 문제은행 가져오기

`/api/import` 경로입니다. PDF/HWP/HWPX/DOCX/TXT/CSV/SQLite/이미지/웹 자료를 문항 DB로 가져오고, 사용자가 문항을 골라 새 시험지를 구성하는 흐름입니다.

- PDF는 단순 `pypdf` 텍스트 추출 기준이 아닙니다. 현재 기준은 PyMuPDF 기반 인식, 문항 번호 분리, 컬럼/페이지/bbox 메타데이터, 수식 PUA 복원, 필요한 경우 지역 이미지 폴백입니다.
- HWP/HWPX/DOCX는 텍스트, 표, 이미지, 수식 구조를 가능한 한 보존해서 문항화합니다.
- 이미지나 스캔 문서는 OCR 또는 이미지 폴백을 사용할 수 있지만, born-digital PDF 수학 시험지는 OCR-first가 아니라 PDF 텍스트와 좌표 정보 복원이 우선입니다.

### 2. PDF 원본 레이아웃 HWPX

`/api/pdf-layout-export` 경로입니다. PDF 한 부를 실제 문단·표·수식과 원본 그림으로 구성한 HWPX로 복원합니다. 과학 등 네이티브 본문 변환에서는 문항마다 하나의 실제 글상자(`hp:rect/hp:drawText`) 안에 해당 문항의 내용을 모아 함께 편집하고 이동할 수 있습니다. `structured`와 호환용 `coordinate` 요청 모두 이 경로를 사용하며, 원본과 달라진 배치는 품질 미달로 표시합니다.

- 결과는 `data/exports/pdf_layout/<날짜>_<파일명>/` 아래에 원본 PDF, HWPX, `layout_report.json`, 렌더 비교 PNG(`fidelity_renders/`)와 함께 저장됩니다.
- 리포트에는 편집 가능 텍스트 보존율, 전체 페이지 레이아웃 기준 `layout_view_sync_ratio`(목표 0.94), 원본 전체 페이지 `whole_page_visual_sync_ratio`, content-crop `visual_sync_ratio`, 페이지 수/비율/전경 겹침 리뷰 플래그가 포함됩니다.
- `quality.objective_score`는 구조 항목의 가중 점수와 실제 렌더의 엄격 배치 점수 중 **낮은 값**입니다. 현재 API의 기존 통과 기준은 98점이며, 이번 개발 목표 93점과 구분합니다. 글꼴 이름·수식 존재·패키지 유효성만으로 실제 배치 실패를 상쇄하지 않습니다.
- 화면은 **1. 자료 넣기 → 2. 문제 고르기 → 3. 병합 만들기** 순서로 배치됩니다.
- 가운데 문제 고르기 영역에서 `병합 추가`를 누르거나 전체 추가를 사용한 뒤, 오른쪽 병합 만들기 영역에서 끌어서(또는 ▲▼) 순서를 정하면 그 순서대로 문서가 만들어집니다.
- 편집 패널에서 문항별 이미지를 추가/삭제할 수 있습니다.
- **미리보기**: 내보내기 전에 한컴 없이도 페이지 모습(PNG 렌더링)을 확인할 수 있습니다. rhwp 엔진 기반이며, 공개 수학·영어 HWPX의 2단 표시는 이번 조사에서 확인했습니다. 파일별 한글 표시·편집·인쇄 결과와의 일치는 별도 검증이 필요합니다.
- 내보내기 양식은 기본 문항 모음 외에 첨부한 기존 양식을 참고한 **평가원 국어/국어 화작/국어 언매/수학/영어/사탐/과탐**, **학교 기출 시험지**, **레거시 객관식 1~5**, **레거시 주관식 괄호** 프리셋을 고를 수 있습니다. 평가원/학교/레거시 시험지형 프리셋은 실제 문제지처럼 머리말·교시·유형·선택 과목/수험 정보란 또는 옛 선지/답란 양식을 넣고 정답/해설은 본문에서 제외합니다.
- **정답·해설지**: 상단의 "정답·해설지"를 체크하면 문서 끝에 새 페이지로 빠른 정답표(5문항씩 한 줄)와 문항별 해설이 붙습니다. 원형 선지 양식에서는 정답 `2`를 `②`처럼 자동 변환합니다. 시험지형 프리셋과 함께 쓰면 문제지+해설지가 한 파일로 나옵니다.

- 텍스트는 HWPX 문단/표 셀로 넣고, 수식은 가능한 한 `hp:equation` 네이티브 수식으로 만듭니다.
- 전체 페이지 래스터 이미지를 본문에 깔아두는 방식은 이 경로의 성공 기준이 아닙니다.
- 이미지는 출처와 영역을 확인할 수 있는 원본 그림·도표만 허용합니다. 본문·수식을 잘게 크롭해 덮는 방식도 금지합니다.
- 출력은 평가원/교육청 시험지처럼 2단, 중간 분할선, 좁은 여백, 실제 본문 폰트와 줄간격을 맞추는 방향으로 검증합니다.
- 글상자는 문항당 하나이며, 내부 텍스트는 의미 문단으로 이어집니다. 시각적 줄마다 별도 글상자나 문단을 만들지 않습니다. 보기·데이터 표, 수식, 원본 그림도 해당 문항 글상자 안에 보존하고 공동지문·확인사항은 별도로 둡니다.
- 원본 비트맵과 별도의 PDF 텍스트층으로 구성된 일부 그래프는 그림·편집 가능한 점 이름·네이티브 함수식을 같은 문항 내부 그룹에 담습니다. 원본 표기와 좌표를 독립 대조하며 그래프 앞 문단이 늘어나면 함께 이동합니다.
- 프로그램의 문단 편집·저장 경로는 같은 문단의 줄 캐시와 글상자 높이를 다시 계산합니다. 실제 한컴 UI의 자동 높이 조절·편집 동작은 아직 검증하지 않았습니다.
- 복원한 분수는 네이티브 수식으로, 한글 문구 분수는 본문 글꼴을 사용하는 편집 가능한 위아래 셀과 분수선으로 만듭니다. 글상자 안의 표는 분수가 사라지는 중첩 구조를 피하고, 실제 렌더 텍스트도 대조합니다. 복원 누락은 독립 원문 대조에서 거부합니다.
- 시험지 구성 UI는 문항 높이·선지·표·이미지를 반영한 예상 페이지와 단을 표시하며, 긴 문항의 분할과 이어짐을 경고합니다.

### 3. HWPX/DOCX 내보내기

선택한 문항은 HWPX 또는 DOCX로 내보낼 수 있습니다. `.hwp` 바이너리 직접 저장은 한컴오피스 COM 자동화가 필요하므로 기본 출력은 HWPX입니다. 한컴오피스가 설치된 PC에서는 HWPX를 열어 `.hwp`로 저장할 수 있습니다.

## 현재 판정 기준 요약

1. 문항 번호는 원본 순서와 싱크가 맞아야 하며 누락/중복이 없어야 합니다.
2. 수식은 가능한 한 Hancom EQN 네이티브 수식으로 내보냅니다. 텍스트로 보이는 흉내나 무조건 이미지화는 최종 목표가 아닙니다.
3. 레이아웃은 렌더 결과 기준입니다. XML 유효성만으로 통과시키지 않고 overflow 0, column crossing 0, 겹침 없음까지 봅니다.
4. PDF 원본 레이아웃 경로는 full-page raster fallback을 성공 기준으로 보지 않습니다. 편집 가능한 텍스트/수식이 우선입니다.
5. 레퍼런스 시험지 PDF/HWP는 기본적으로 로컬 자료입니다. 저장소에는 샘플 파일 자체 대신 검증 스크립트, manifest, 분석 요약을 둡니다.
6. `/api/pdf-layout-export`의 현재 품질 통과 기준은 `objective_score` 98점 이상과 독립 편집성·실제 표시·열기 안전성 검사입니다. 변환·다운로드 HTTP 200이나 출력 쪽수 일치가 이 품질 통과를 의미하지 않습니다. 개발 목표 93점의 최신 진척과 남은 실패는 위의 5분야 평가를 따릅니다.

## 수식 기준

- 수학 변수(`x`, `y`, `n`, `a`, `f` 등)는 Times New Roman 이탤릭 계열로 보이도록 맞춥니다.
- 분수, 루트, 첨자, 벡터, 극한, 케이스 같은 수학 구조는 일반 텍스트로 흉내 내지 않고 Hancom EQN 기반 네이티브 수식으로 유지하는 것이 목표입니다.
- HyhwpEQ 계열 PDF PUA 문자는 `app/hancom_pua_map.py`와 `app/math_text.py`에서 복원합니다.
- 남은 square placeholder는 무조건 깨진 글자가 아니라, 분수선/루트/벡터/케이스 같은 2D 구조 힌트일 수 있습니다. 좌표 기반 재조립 대상으로 분류합니다.

## 레이아웃 기준

- 문항 번호는 누락/중복 없이 원본 순서와 싱크가 맞아야 합니다.
- 렌더 기준은 XML 유효성만이 아니라 overflow 0, 컬럼 침범 0, 문항/선지/수식 겹침 없음입니다.
- PDF 라인의 문자/스팬 좌표는 `pdf_line_chars`, `pdf_line_spans` 메타데이터로 보존합니다. 이 좌표는 분수, 루트, 첨자, 케이스 복원에 사용합니다.
- full-page image fallback으로 보기만 비슷한 결과는 성공으로 보지 않습니다. 편집 가능한 텍스트와 수식이 우선입니다.

## 폰트와 간격 기준

- 한글 본문: `신명조`, `HY신명조`, 또는 실제 평가원 계열인 `신명 중명조`를 우선합니다.
- 영어 지문/영문 표기: `Times New Roman`을 우선합니다.
- 문항 번호, 과목명, 안내 문구: `돋움` 또는 `중고딕` 계열을 우선합니다.
- 수식: 변수는 Times New Roman 이탤릭, 나머지 구조는 한글 수식 편집기 기본 수식 폰트 체계를 따릅니다.
- 문제은행 writer의 초기값은 본문 10-11pt, 줄간격 160-170%, 장평 약 95, 자간 약 -5입니다. PDF flow writer는 원본 글자 크기를 유지하고 장평 86, 자간 -5, 줄간격 150%를 사용합니다.

## 데이터와 레퍼런스 자료

앱 데이터는 기본적으로 `data/` 폴더에 저장됩니다 (`HWP_MAKE_DATA_DIR`로 변경 가능).

- `data/problems.sqlite3`: 문제 DB
- `data/uploads/`: 업로드 원본 및 이미지
- `data/exports/`: 내보내기 결과

`data/`는 git에 올리지 않는 로컬 작업 영역입니다. 평가원/교육청 PDF/HWP 레퍼런스 파일도 저작권과 용량 때문에 기본적으로 저장소에 커밋하지 않습니다. 필요하면 파일명/출처/검증 상태를 문서화하고, 별도 사설 스토리지나 Git LFS 정책을 정한 뒤 추가합니다.

로컬 레퍼런스 샘플의 이름, 용도, 검증 상태는 `docs/reference_samples_manifest.md`에 기록합니다. 이 manifest는 파일 자체를 추적하지 않고, 재현에 필요한 맥락만 남깁니다.

## HWP 열기 관련 기준

- 한글 실행 시 뜨는 광고 탭은 설치된 제품, 계정, 라이선스, 업데이트 채널 영향이 크므로 생성 HWPX 내부에서 안정적으로 끌 수 있는 대상이 아닙니다.
- 수정 권한, 보호 보기, 읽기 전용 탭은 일부 제어 가능합니다. 생성 파일의 문서 보호 플래그, 읽기 전용 속성, Mark-of-the-Web, temp/download 경로, 잠긴 출력 파일 여부를 점검합니다.
- 개발 중 GUI 열기 검증은 보조 게이트입니다. 기본 검증은 HWPX XML, rhwp 렌더, 필요 시 제한 시간 있는 HWP COM open probe로 진행합니다.
- Computer Use가 필요한 검증은 최소화합니다. 광고/수정권한 탭 때문에 자동화가 막히는 경우, 먼저 XML/rhwp/스크립트 검증으로 좁히고 GUI는 최종 확인이나 open-probe 체크리스트 용도로만 사용합니다.
- GUI 열기 이슈를 기록할 때는 `docs/hwp_open_probe_checklist.md`의 editable/read-only/protected/ad prompt 구분을 사용합니다.

## 검증

통합 검증:

```powershell
python scripts/run_all_verify.py
```

전체 회귀에는 웹 테스트도 포함됩니다. `pip install -r requirements.web.txt pytest`로 준비합니다.
실행별 전체 stdout/stderr와 시간·판정 JSON은 `data/verification/<실행시각>/`에 보관합니다.
특정 검사만 재실행하려면 `python scripts/run_all_verify.py --only verify_api_hardening.py`를 사용합니다.
`--output-dir <폴더>`로 결과 경로를 지정할 수 있습니다. 수동 산출물이 필요한 검사는 사유와 함께 SKIP이며, 미검증 항목입니다.

주요 개별 검증:

- `python scripts/verify_importers.py`
- `python scripts/verify_math_exam_pipeline.py`
- `python scripts/verify_pdf_math_pipeline.py`
- `python scripts/verify_real_pdf_math_samples.py`
- `python scripts/verify_real_pdf_math_samples.py --mode import|write|render|all`
- `python scripts/qa_hwp_math_samples.py`
- `python scripts/verify_pdf_layout_export_api.py`
- `python scripts/verify_pdf_flow_performance.py`
- `node scripts/verify_frontend_layout.js`
- `python scripts/verify_reorder_layout.py`
- `python scripts/benchmark_subject_conversion.py --runs 3 --output-dir data/subject_conversion_benchmark/current`
- `python scripts/pdf_layout_hwpx_probe.py "data/uploads/sample.pdf" "data/exports/sample_flow.hwpx" --flow --max-pages 1`
- `python scripts/verify_pdf_layout_hwpx.py "data/exports/sample_flow.hwpx" --render`
- `python scripts/verify_kice_typography.py`
- `powershell -ExecutionPolicy Bypass -File scripts/probe_hwp_open.ps1`

실제 샘플이 없는 환경에서는 일부 검증이 SKIP으로 끝날 수 있습니다. SKIP은 실패가 아니라 로컬 레퍼런스 파일이 없다는 신호입니다.

## 주요 모듈

- `app/main.py`: API 진입점
- `app/recognition/pdf_segment.py`: PDF 페이지/블록/문항/좌표 인식
- `app/recognition/pipeline.py`: 인식 결과를 문항 모델로 변환
- `app/importers.py`: 파일별 import 배선
- `app/math_text.py`: 수식 텍스트 감지와 Hancom EQN 변환 보조
- `app/hancom_pua_map.py`: HyhwpEQ PUA 매핑
- `app/hwpx_writer_v2.py`: 문항 DB 기반 시험지형 HWPX writer
- `app/pdf_layout_writer.py`: PDF 원본 레이아웃 직접 HWPX writer
- `scripts/analyze_hwp_templates.py`: 실제 HWP 샘플 스타일 분석
- `docs/priority_work_queue.md`: 현재 우선순위 작업 큐
- `docs/product_b_bottleneck_specs.md`: Product B 기준과 폐기한 옛 기준 정리
- `docs/reference_samples_manifest.md`: 로컬 레퍼런스 샘플 목록과 사용 목적
- `docs/hwp_open_probe_checklist.md`: 한글 GUI 열기/광고/수정권한 탭 진단 체크리스트
