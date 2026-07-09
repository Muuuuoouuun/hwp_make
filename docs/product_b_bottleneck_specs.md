# Product B 기준 정리

Updated: 2026-07-09

Product B는 입력 PDF/HWP/HWPX를 평가원/교육청 시험지에 가까운 편집형 HWPX로 복원하는 작업입니다. 이 문서는 예전 병목 조사 메모를 현재 개발 기준으로 정리한 canonical 문서입니다.

핵심 목표는 보기만 비슷한 문서가 아닙니다. 문항 번호가 싱크되고, 수식이 네이티브 수식으로 살아 있고, 폰트/간격이 시험지 기준에 맞으며, 렌더링에서 겹침과 overflow가 없어야 합니다.

## 문서 정리 원칙

- 현재 기준은 이 문서의 `현재 Canonical 기준`과 `기준 적용 체크리스트`를 우선합니다.
- 날짜가 지난 조사 메모, 코드 주석, 임시 QA 결과가 이 문서와 충돌하면 이 문서를 기준으로 업데이트합니다.
- 옛 기준은 조용히 되살아나지 않도록 `삭제 또는 폐기한 옛 기준`에 명시하고, 필요하면 코드 주석과 사용자 notice도 함께 고칩니다.
- README에는 실행과 검증 입구만 남기고, 제품 판단 기준은 이 문서에 모읍니다.

## 현재 상태 스냅샷

- 수학 PDF/HWP 복원은 수식 구현과 레이아웃 겹침 방지를 최우선으로 둡니다.
- 네 개 로컬 수학 PDF 샘플 기준으로 선택지 분수 placeholder는 제거되었고, 단순 stem stacked fraction, log-base residue, 확정 split vector residue까지 복원되었습니다.
- 현재 로컬 baseline은 `stem□` 48개, malformed equation 0, render overflow 0입니다. residual bucket은 fraction 13, root 7, vector/arrow 6, cases/grouping 13, adjacent script/structure 9입니다.
- 남은 핵심 병목은 mixed fraction, root, super/subscript, cases, bbox 기반 vector base 추론입니다. QA 리포트는 실제 출력 잔여 placeholder와 원본 PDF 구조 힌트를 분리해서 기록합니다.
- PDF 원본 레이아웃 HWPX는 흐름 기반 writer가 canonical입니다. 절대좌표 글상자 방식은 한컴 호환성과 편집성 문제가 있어 실험 기준으로만 둡니다.
- 폰트/간격 기본 profile은 평가원형 `신명조/HY신명조/신명 중명조 + Times New Roman + 돋움/중고딕`, 본문 10-11pt, 줄간격 160-170%, 장평 약 95, 자간 약 -5입니다.

## 현재 Canonical 기준

### 1. 입력 경로는 두 개로 분리한다

- 문제은행 편집 경로: `/api/import` -> recognition/storage -> `hwpx_writer_v2`
- 원본 레이아웃 복원 경로: `/api/pdf-layout-export` -> `pdf_layout_writer.write_pdf_flow_hwpx`

두 경로를 한 성공 기준으로 섞지 않습니다. 문제은행 경로는 문항 단위 재구성이 목표이고, PDF 원본 레이아웃 경로는 원본 시험지 흐름과 배치를 유지하는 것이 목표입니다.

### 2. PDF 수학은 OCR-first가 아니다

Born-digital 평가원/학평 PDF는 텍스트, PUA, 글리프 좌표가 남아 있습니다. 현재 기준은 PyMuPDF 기반 텍스트/좌표 추출, Hancom PUA 복원, bbox 기반 구조 재조립입니다. OCR은 스캔본이나 신뢰도 낮은 영역의 fallback입니다.

### 3. 전체 페이지 이미지 fallback은 성공이 아니다

`/api/pdf-layout-export` 경로에서 full-page raster fallback은 금지 기준입니다. 편집 가능한 텍스트와 네이티브 수식이 우선이고, 그림/도표/복원 불확실 영역만 지역 이미지 fallback으로 보존합니다.

### 4. 수식은 Hancom EQN 네이티브로 유지한다

- `hp:equation` 개수와 malformed equation 0을 검증합니다.
- HyhwpEQ PUA 매핑은 `app/hancom_pua_map.py`에서 관리합니다.
- `app/math_text.py`는 선형 치환뿐 아니라 벡터, 루트, 분수지수 등 고신뢰 패턴을 복원합니다.
- 남은 square placeholder는 무조건 삭제하지 않고, 구조 힌트로 분류한 뒤 bbox와 함께 판단합니다.

### 5. 렌더 결과가 최종 판정이다

XML 유효성만으로는 충분하지 않습니다. 합격 기준은 rhwp 렌더 또는 HWP open probe에서 overflow 0, column crossing 0, 문항/선지/수식 겹침 없음, 문항 번호 누락/중복 없음입니다.

### 6. 평가원/교육청 타이포그래피를 기준값으로 둔다

- 한글 본문: `신명조`, `HY신명조`, `신명 중명조` 계열
- 영어/라틴: `Times New Roman`
- 문항 번호/타이틀/안내: `돋움`, `중고딕` 계열
- 수식 변수: Times New Roman 이탤릭
- 기본 실무값: 본문 10-11pt, 줄간격 160-170%, 장평 약 95, 자간 약 -5

교육청 옛 편집본에 바탕체나 시스템 기본 서체 흔적이 있어도, 현재 목표 profile은 평가원 시각 기준에 맞춘 `신명조 + Times New Roman` 조합입니다. 단, 샘플 분석 결과가 분명한 경우에는 별도 profile로 분리합니다.

### 7. 레퍼런스 시험지는 로컬 자료로 둔다

실제 평가원/교육청 PDF/HWP 파일은 `data/` 또는 사용자 Downloads에 두고, 기본적으로 git에 올리지 않습니다. 저작권, 용량, 사설 샘플 여부가 해결되기 전까지 저장소에는 샘플 자체 대신 검증 스크립트, manifest, 분석 요약만 둡니다.

### 8. HWP GUI 열기는 보조 검증이다

한글 광고 탭은 환경/제품/계정/라이선스 영향이므로 문서 생성 코드의 책임 범위 밖입니다. 수정권한/보호보기/읽기전용 문제는 생성 파일 속성, 보호 플래그, Mark-of-the-Web, 출력 경로를 점검합니다. GUI open은 제한 시간 있는 probe로 다루고, 기본 검증은 XML/rhwp/render 기반으로 둡니다. GUI 이슈를 기록할 때는 `docs/hwp_open_probe_checklist.md`의 구분을 사용합니다.

## 기준 적용 체크리스트

작업을 커밋하기 전에 아래 질문에 모두 답합니다.

1. 이 변경이 `/api/import` 문제은행 경로인지, `/api/pdf-layout-export` 원본 레이아웃 경로인지 분리되어 있는가?
2. 수식이 텍스트 흉내나 전체 이미지가 아니라 가능한 네이티브 `hp:equation`으로 남는가?
3. 렌더 기준에서 overflow, column crossing, 겹침이 악화되지 않는가?
4. PDF 좌표/스팬 정보가 사라지지 않고 다음 수식 복원에 계속 사용 가능한가?
5. 폰트/간격 변경은 평가원형 기본 profile 또는 명명된 별도 profile로 설명되는가?
6. 레퍼런스 PDF/HWP 파일 자체를 저장소에 추가하지 않았는가?

## 완료되어 유지할 작업

- 마스트헤드 파싱: `app/exam_header.py`
- PDF header 보존 및 writer title 우선순위 정리
- 문항 layout metadata 보존: `layout_json`, column/page/bbox 계열
- Hancom PUA 매핑과 복원: `app/hancom_pua_map.py`, `app/math_text.py`
- 그리스문자와 `sqrt` 정규화 회귀 케이스
- 혼합 PDF의 마커 없는 페이지 지역 fallback
- KICE writer의 폰트 face, 장평, 자간, 165% 줄간격 적용
- `pdf_segment` rawdict 기반 `pdf_line_chars`, `pdf_line_spans` 보존
- PDF layout export API 검증과 typography XML 검증

## 삭제 또는 폐기한 옛 기준

1. `PDF import = pypdf 텍스트 추출` 기준은 폐기합니다.
   현재 PDF 기준은 PyMuPDF 인식, 좌표 보존, 수식 PUA 복원, layout metadata입니다.

2. `실제 평가원/학평 샘플이 저장소에 없으므로 검증 불가`라는 블로커 문구는 현재 기준에서 제거합니다.
   실물 샘플은 로컬에서 사용하고, 저장소에는 커밋하지 않는 것이 새 기준입니다.

3. `full-page raster fallback이면 충분` 기준은 폐기합니다.
   특히 원본 레이아웃 HWPX 경로에서는 편집 가능한 텍스트/수식이 핵심입니다.

4. `절대좌표 글상자 writer를 canonical로 부활`시키는 기준은 폐기합니다.
   한컴 호환성과 편집성을 위해 흐름 기반 writer가 canonical입니다. 절대좌표 접근은 별도 실험으로만 남깁니다.

5. `GUI에서 열리면 통과` 기준은 폐기합니다.
   GUI open은 보조이고, 수식/레이아웃/겹침/overflow 검증이 우선입니다.

6. `샘플 PDF/HWP를 저장소에 같이 푸시` 기준은 폐기합니다.
   레퍼런스 파일은 기본적으로 로컬/사설 자산이며, 공개 저장소에는 올리지 않습니다.

7. `페이지 수를 원본과 정확히 맞추는 것`을 1차 합격 기준으로 보지 않습니다.
   우선순위는 46문항 싱크, 네이티브 수식, overflow 0, column crossing 0, 읽을 수 있는 배치입니다. 페이지 수는 이후 밀도 캘리브레이션 지표입니다.

8. `PUA 문자 매핑만 끝나면 수식 문제가 끝난다`는 기준은 폐기합니다.
   PUA 매핑은 1차 관문이고, 남은 핵심은 분수/루트/첨자/케이스의 2D 구조 복원입니다.

9. `교육청 옛 폰트 흔적을 기본 profile로 삼는다`는 기준은 폐기합니다.
   기본 목표는 평가원 기준에 가까운 신명조/Times New Roman 조합입니다. 교육청 특이 profile은 샘플 근거가 있을 때 분리합니다.

10. `한 버튼, 한 파이프라인으로 모든 입력/출력을 해결`하는 기준은 폐기합니다.
    문제은행 import와 PDF 원본 레이아웃 복원은 서로 다른 제품 동작으로 유지합니다.

11. `verify_pdf_layout_hwpx.py --render`만 실행하면 PDF 레이아웃 검증이 끝난다는 기준은 폐기합니다.
    이 스크립트는 이미 생성된 HWPX 경로가 필요합니다. 먼저 `pdf_layout_hwpx_probe.py`나 API export로 HWPX를 만든 뒤, 그 산출물을 검증합니다.

12. `한글 GUI 광고/계정 탭을 생성 파일에서 제거해야 통과` 기준은 폐기합니다.
    광고 탭은 환경 변수에 가깝고, 개발 기준은 생성 파일의 편집 가능성, 보호 플래그, Mark-of-the-Web, 렌더/구조 검증입니다.

13. `수학/과학 PDF는 문항 전체 이미지로 가져오면 충분` 기준은 폐기합니다.
    문제은행 import에서 텍스트 신뢰도가 낮은 일부 문항은 임시 이미지 fallback을 가질 수 있지만, Product B 성공 기준은 편집 가능한 텍스트, 네이티브 수식, 좌표 기반 구조 복원입니다.

14. `사용자 notice나 코드 주석에 남은 옛 설명은 동작과 무관하므로 방치` 기준은 폐기합니다.
    개발 판단을 흐리므로 현재 기준과 충돌하는 설명은 구현 변경과 별개로 즉시 정리합니다.

## 다음 우선순위

1. 실제 PDF QA의 import, HWPX write, render phase 분리와 샘플별 시간 기록을 regression gate로 유지합니다.
2. residual square placeholder report를 기준으로 새 복원 규칙을 만들고, 대표 케이스를 `scripts/verify_importers.py` fixture로 승격합니다.
3. bbox 기반 복원은 choice fraction, 단순 stem stacked fraction, 확정된 split vector residue까지 구현되었습니다. 다음은 mixed fraction, root index/radicand, super/subscript, cases, bbox 기반 vector base 추론입니다.
4. 문항 inventory report를 강화해 원본 페이지/컬럼/문항 번호/choice split/image fallback 상태를 비교합니다.
5. HWP open probe checklist를 추가해 editable/read-only/protected/ad prompt를 구분해서 기록합니다.
6. 코드 주석과 사용자 notice에서 폐기된 기준이 다시 보이면 이 문서에 맞춰 업데이트합니다.

## 검증 관문

통합:

```powershell
python scripts/run_all_verify.py
```

수식/레이아웃 핵심:

```powershell
python scripts/verify_math_exam_pipeline.py
python scripts/verify_pdf_math_pipeline.py
python scripts/verify_real_pdf_math_samples.py
python scripts/qa_hwp_math_samples.py
python scripts/verify_pdf_layout_export_api.py
python scripts/pdf_layout_hwpx_probe.py "data/uploads/sample.pdf" "data/exports/sample_flow.hwpx" --flow --max-pages 1
python scripts/verify_pdf_layout_hwpx.py "data/exports/sample_flow.hwpx" --render
python scripts/verify_kice_typography.py
```

HWP 설치 환경이 있을 때:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/probe_hwp_open.ps1
```

샘플이 없는 환경에서 exit 2 또는 SKIP은 실패가 아닙니다. 로컬 레퍼런스 자료가 없다는 의미로 보고, CI의 필수 실패 조건과 분리합니다.
