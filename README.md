# HWP Make

HWP Make는 PDF, HWP/HWPX, DOCX, 이미지, 텍스트, CSV/SQLite 자료를 문항 단위로 가져오고, 평가원/교육청 시험지 스타일의 편집 가능한 HWPX/DOCX로 내보내는 로컬 앱입니다.

현재 개발의 최우선 목표는 수학 시험지 기준입니다. 즉, 문항 번호 싱크, 네이티브 한글 수식, 실제 시험지 타이포그래피, 2단 레이아웃, 겹침 없는 렌더링을 동시에 만족하는 HWPX를 만드는 것입니다. Product B의 세부 기준과 폐기한 옛 기준은 `docs/product_b_bottleneck_specs.md`를 canonical 문서로 봅니다.

## 문서 역할

- `README.md`: 실행 방법, 주요 경로, 현재 판정 기준, 검증 명령을 빠르게 확인하는 입구입니다.
- `docs/product_b_bottleneck_specs.md`: Product B의 현재 기준과 폐기한 옛 기준을 관리하는 canonical 문서입니다.
- `docs/priority_work_queue.md`: 지금 막아야 하는 P0/P1/P2 작업 큐입니다.
- `docs/current_self_assessment.md`: 실제 검증 결과를 기준으로 세분화한 현재 완성도와 다음 개발 순서입니다.
- `docs/full_subject_qa_2026_06.md`: 2026년 6월 고1 전과목 PDF와 사용자 제공 HWP의 과목별 경향 QA입니다.
- `docs/reference_samples_manifest.md`: 로컬 레퍼런스 시험지 목록과 사용 목적만 기록합니다. 파일 자체는 커밋하지 않습니다.
- `docs/hwp_open_probe_checklist.md`: 한글 GUI 광고/수정권한/보호보기 이슈를 구분하는 체크리스트입니다.

## 실행

PowerShell에서:

```powershell
pip install -r requirements.txt
.\run_local.ps1
```

브라우저에서 `http://127.0.0.1:8787`을 엽니다.

## 현재 사용 경로

### 1. 문제은행 가져오기

`/api/import` 경로입니다. PDF/HWP/HWPX/DOCX/TXT/CSV/SQLite/이미지/웹 자료를 문항 DB로 가져오고, 사용자가 문항을 골라 새 시험지를 구성하는 흐름입니다.

- PDF는 단순 `pypdf` 텍스트 추출 기준이 아닙니다. 현재 기준은 PyMuPDF 기반 인식, 문항 번호 분리, 컬럼/페이지/bbox 메타데이터, 수식 PUA 복원, 필요한 경우 지역 이미지 폴백입니다.
- HWP/HWPX/DOCX는 텍스트, 표, 이미지, 수식 구조를 가능한 한 보존해서 문항화합니다.
- 이미지나 스캔 문서는 OCR 또는 이미지 폴백을 사용할 수 있지만, born-digital PDF 수학 시험지는 OCR-first가 아니라 PDF 텍스트와 좌표 정보 복원이 우선입니다.

### 2. PDF 원본 레이아웃 HWPX

`/api/pdf-layout-export` 경로입니다. PDF 한 부를 문항 DB에 넣기보다, 원본 시험지 흐름을 유지하는 편집 가능한 HWPX로 직접 복원합니다.

- 텍스트는 HWPX 문단/표 셀로 넣고, 수식은 가능한 한 `hp:equation` 네이티브 수식으로 만듭니다.
- 전체 페이지 래스터 이미지를 본문에 깔아두는 방식은 이 경로의 성공 기준이 아닙니다.
- 도표, 그림, 복원 불확실한 복잡 수식 영역만 지역 이미지 폴백 대상으로 둡니다.
- 출력은 평가원/교육청 시험지처럼 2단, 중간 분할선, 좁은 여백, 실제 본문 폰트와 줄간격을 맞추는 방향으로 검증합니다.

### 3. HWPX/DOCX 내보내기

선택한 문항은 HWPX 또는 DOCX로 내보낼 수 있습니다. `.hwp` 바이너리 직접 저장은 한컴오피스 COM 자동화가 필요하므로 기본 출력은 HWPX입니다. 한컴오피스가 설치된 PC에서는 HWPX를 열어 `.hwp`로 저장할 수 있습니다.

## 현재 판정 기준 요약

1. 문항 번호는 원본 순서와 싱크가 맞아야 하며 누락/중복이 없어야 합니다.
2. 수식은 가능한 한 Hancom EQN 네이티브 수식으로 내보냅니다. 텍스트로 보이는 흉내나 무조건 이미지화는 최종 목표가 아닙니다.
3. 레이아웃은 렌더 결과 기준입니다. XML 유효성만으로 통과시키지 않고 overflow 0, column crossing 0, 겹침 없음까지 봅니다.
4. PDF 원본 레이아웃 경로는 full-page raster fallback을 성공 기준으로 보지 않습니다. 편집 가능한 텍스트/수식이 우선입니다.
5. 레퍼런스 시험지 PDF/HWP는 기본적으로 로컬 자료입니다. 저장소에는 샘플 파일 자체 대신 검증 스크립트, manifest, 분석 요약을 둡니다.

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
- 초기 실무값은 본문 10-11pt, 줄간격 160-170%, 장평 약 95, 자간 약 -5입니다. 실제 HWP 샘플 분석 결과에 맞춰 조정합니다.

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

주요 개별 검증:

- `python scripts/verify_importers.py`
- `python scripts/verify_math_exam_pipeline.py`
- `python scripts/verify_pdf_math_pipeline.py`
- `python scripts/verify_real_pdf_math_samples.py`
- `python scripts/verify_real_pdf_math_samples.py --mode import|write|render|all`
- `python scripts/qa_hwp_math_samples.py`
- `python scripts/verify_pdf_layout_export_api.py`
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
