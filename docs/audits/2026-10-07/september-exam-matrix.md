# 2026년 9월 실물 시험지 검증 매트릭스

이 작업의 원본은 **2026-09-02 시행** 시험이다. 고1·고2는 인천교육청 전국연합학력평가, 고3는 **2027학년도** 평가원 9월 모의평가다. 다른 연도의 2026학년도 9월 자료로 대체하지 않는다. EBSi 공식 목록·원본 URL·다운로드 해시·학년도·선택과목을 각 데이터셋 manifest에 고정한다. 원본 파일과 원문이 들어간 결과 JSON/PNG는 로컬 `data/`와 `tmp/`에 둔다.

현재 활성 범위는 사용자의 최신 지시에 따라 **기본 PDF 원본 배치 native HWPX 변환**이다. 프리미엄 템플릿·순서에 관한 추가 구현과 검증은 보류한다. 앞서 수집한 프리미엄 결과는 별도 증거로 보존하며 기본 변환의 완료 근거로 혼용하지 않는다.

| 학년 | 필수 시험지 | 수 |
|---|---|---:|
| 고1 | 국어·수학·영어·한국사·통합사회·통합과학 | 6 |
| 고2 | 국어·수학·영어·한국사·통합사회·통합과학 | 6 |
| 고3 | 국어 2, 수학 3, 영어 1, 한국사 1, 사탐 9, 과탐 8, 직탐 6, 제2외국어·한문 9 | 39 |
| 전체 | 고3 공통+선택 합권을 각 선택 시험지로 따로 검사 | **51** |

등록 시 실제 원본은 총 **312쪽·1,355문항**, 각 시험지는 번호가 재시작하지 않는 단일 run이다. 고3 국어·수학에서 여러 시험지의 공통 번호가 같다는 이유로 서로 삭제하거나 합치지 않는다. 최신 원본 실측과 manifest가 다르면 검증을 다시 등록하기 전에는 통과하지 않는다.

## 실행

```powershell
python scripts/verify_september_exam_matrix.py --output-dir tmp/september-exam-matrix/english-baseline
python scripts/verify_september_exam_matrix.py --all --output-dir tmp/september-exam-matrix/full-baseline
python scripts/verify_september_exam_matrix.py --all --inventory-only --output-dir tmp/september-exam-matrix/source-proof
python scripts/verify_september_exam_matrix.py --case 2026_september_high1__eng_1 --mode both --output-dir tmp/september-exam-matrix/alias-probe
python scripts/verify_september_matrix_runner.py
```

`--case`의 ID는 실제 manifest를 따른다. 기본 실행은 영어 3부만 선택한 **부분 검사**다. `--all`만 51부 전체의 완료 판정을 요청한다. `--mode both`는 기본 structured 요청과 호환 coordinate 요청을 각각 실제 API로 검사한다. 두 요청 모두 현재 같은 native structured writer를 사용한다.

모든 원본의 바이트 SHA-256·크기·물리 쪽수·학년/과목/선택·원본 질문 번호 목록을 앱 import 전에 `source_inventory.json`에 고정한다. 문항 번호는 실제 PDF의 큰 첫 스팬과 word 토큰을 다시 읽어 대조한다. 이 corpus의 문항 번호는 12pt 이상이라는 등록 증거를 사용하며 작은 본문 번호 목록을 문항으로 세지 않는다. 원본에 있는 문항 들여쓰기를 고정 레일로 제거하지 않는다. 번호 run이나 두 추출기의 합의가 불확실하면 미완료로 남긴다.

선택한 시험지/모드마다 별도 subprocess·DB·설정·출력 경로에서 `/api/pdf-layout-export`를 `strict=True`, `native_math=True`, `math_ai_recognition=False`, `variant_policy='all'`, 페이지 제한 없이 호출한다. 앱 제품 코드는 변경하지 않는다. 케이스마다 `api_result.json`, `evidence.json`, `worker.log`를 보존하며 `report.json`을 진행 중에도 갱신한다. 실제 출력 ZIP/XML과 원본을 독립 편집성 검사로 다시 읽고, 실제 출력의 open safety와 native render를 재검사한다.

케이스 시작·종료의 앱 Python 파일 SHA-256과 Python/렌더러/패키지 버전도 기록한다. 검사 중 제품 코드가 바뀐 케이스는 그 사실을 표시하고 품질 통과를 최종 완료로 집계하지 않는다. 별도 실행 ID로 이전 `evidence.json`을 새 worker의 결과로 재사용하지 않는다. 실행 시간이 다른 코드의 결과를 한 최종 품질 측정으로 묶지 않도록 최종에는 안정된 코드에서 새 결과 폴더를 사용한다.

## 통과 조건과 수치의 의미

| 기준 | 뜻과 현행 임계치 | 근거 |
|---|---|---|
| 기본 API 객관 품질 | `objective_score >=98`; 구조 가중 점수와 실제 harsh 배치 점수 중 낮은 값. API 목표 판정·review·open safety도 참이어야 함 | `app/main.py`의 `_pdf_structured_objective_score`, `verify_pdf_layout_export_api.py` |
| 개발 진척 | 93점 이상인지 별도로 기록. 98점 통과를 대신하지 않음 | 최신 README 및 9월/10월 감사의 개발 목표 |
| 외부 실물 엄격 배치 | harsh 평균 >=97, 최저 페이지 >=95; 원시 strict alignment >=0.96, foreground overlap >=0.97 | `verify_external_exam_detail_quality.py`, `verify_unseen_exam_quality.py` |
| 레이아웃 전체 화면 | `overall_layout_view_sync_ratio >=0.94`; 원본 물리 쪽수=출력=비교=렌더 쪽수, 잘린 비교 없음 | 현행 API 계약 |
| 독립 편집성 | `inspect_pdf_editability.ok`; 원본 본문 조각 커버리지 >=0.98, 원본 질문 ID/순서 정확, 본문 이미지 덮개 없음 | `docs/native_pdf_editability.md` |
| 실제 출력 | 독립 open safety와 `inspect_question_rendering.ok`; 전체 페이지 렌더 완료 | 현행 native API 계약 |

위 조건은 동시에 적용한다. 변환 HTTP 200, 원본과 같은 쪽수, XML 글자 존재, 93점 또는 생성 통계만으로 통과하지 않는다. 공백·첨자·수식 의미·문항 소속·그림 출처·의미 문단은 기존 독립 편집성 검사도 통과해야 한다. 본문 조각 커버리지 98%는 모든 의미·중복·읽기 순서나 모든 glyph 모양을 증명하는 지표가 아니므로 기존 실물/합성 회귀와 실패 페이지의 시각 검토를 함께 유지한다.

`verify_detection_quality_97.py`의 97점은 **별도의 감지 100점 rubric**이다. 원본 페이지/형, 문항 inventory, 수식, 그림/벡터 채널에 가중치를 주며 실제 한컴 저장 PDF가 필요하다. 국어/영어 원본이 출력의 두 배라는 옛 패키지 전제도 있어 이번 단일형 51부에 그대로 적용할 수 없다. `verify_final_output_quality_96.py`의 96점 역시 별도의 옛 최종 출력 rubric이며 생성 보고서의 기대 개수와 HY신명조 전용·옛 2단 표 구조에 의존한다. 이를 최신 native 문항 글상자 출력의 최종 배치 점수로 바꾸어 부르지 않는다. `verify_pdf_layout_real_subjects_96.py`는 파일명과 달리 현행 기본 목표가 **98점**이다.

기준 문서 `product_b_bottleneck_specs.md`에는 95점·좌표 기반 writer·옛 가중치 설명이 남아 현재 README/API/회귀와 충돌한다. 이 러너는 기준을 내리거나 문서를 조용히 다시 해석하지 않고, 현재 실행 계약의 **98점**과 독립 엄격 검사 수치를 고정한다. 이 문서/러너에서 기존 gate 임계치를 수정하지 않는다.

## 결과 판정

- `PASS`: `--all`에서 51개 required 시험지의 선택한 모드가 모두 실제 통과.
- `PASS_SUBSET`: 명시한 영어/ID 부분 검사만 실제 통과. `full_matrix_passed=false`; 나머지는 `NOT_RUN`.
- `INCOMPLETE`/exit 2: 원본 또는 manifest 부재, source inventory 불확실, 검사 미실행. `--inventory-only`도 품질 통과가 아니다.
- `FAIL`/exit 1: 해시/쪽수/필수 과목 mismatch, API 거절, 품질 목표 미달, 독립 검사 실패, worker 오류/timeout/결과 JSON 부재.
- exit 0은 선택 범위만 실제 통과했다는 뜻이다. 전체 목표는 `full_matrix_passed=true`를 별도로 확인한다. 같은 결과 폴더의 이전 성공 파일로 새 worker 실패를 덮지 않는다.

## 별도로 유지할 기능 검사

이 러너는 **기본 PDF 원본 레이아웃 native HWPX 경로**를 검증한다. 프리미엄은 `/api/import`로 문항 DB에 가져온 뒤 `/api/preview`, `/api/export`에서 템플릿으로 재구성하는 경로다. 원본과 같은 페이지 좌표를 요구하는 기본 점수를 프리미엄 템플릿에 혼용하지 않는다. 다음 기본 변환 회귀를 함께 유지한다. 프리미엄 항목은 현재 보류된 별도 범위의 설명이다.

- 프리미엄: 모든 source 문항·공동지문·선지·표·그림/수식을 해당 문항에 보존, 선택과목별 common 번호 보존, 정순/역순/부분 선택, preserve/sequential 번호, preview/export 일치, 실제 HWPX/DOCX. 실제 원문 기대값으로 검사하며 이미지 alt text는 본문 증거로 세지 않는다.
- 영어: `verify_english_content_integrity.py`, `verify_english_choices.py`, native 빈칸/그래프·안내문·지문 틀·마지막 쪽 glyph, literal contraction/통화, 머리말 및 선택지 rail 회귀 유지.
- 수학·과학: 첨자/분수 피연산자·근호·합/수식 원본 글꼴·혼합 문단·표 의미·그림 소속 및 편집 후 재흐름. 수식 개수만으로 모양이나 의미를 판정하지 않음.
- 국어·공통 기능: 공통지문·시의 행/연·병합 표·인라인 표지·그림 둘러싸기·여백·문단 들여쓰기. 본문 증가/삭제 뒤 저장·재열기·렌더·뒤 문항 비겹침.
- 실제 macOS 실행·native renderer wheel/글꼴 fallback·한글/NFD 경로·UI 다운로드·편집 재저장 증거. Windows 성공이나 정적 Mac 경로 검사는 실제 Mac 실행의 통과가 아님.

외부 detail gate는 원본 일부가 없어도 가용 케이스만 통과시킬 수 있고, unseen gate는 원본보다 짧은 출력의 첫 형만 잘라 비교하는 경로가 있다. 기존 `evaluate_pdf_subjects.py`는 품질 목표 미달도 변환 성공으로 종료할 수 있으며 거절을 exit 2로 기록한다. 따라서 이 러너는 그 exit code를 품질 통과나 source 부재로 해석하지 않는다. 통합 `run_all_verify.py`의 SKIP도 미검증으로 보존한다.

신규 원본을 수정에 사용하면 그 원본은 더 이상 untouched holdout이 아니다. 수정 전 결과·실패 glyph/geometry·소스 해시를 보존하고 작은 회귀를 추가한 후 해당 케이스를 다시 실행한다. 최종에는 한 번의 fresh 전체 matrix와 기존 대표 회귀를 실행하며, 같은 원본 반복 점수만으로 미지 문서 일반화를 주장하지 않는다.

## 최초 전체 실행 보존

`tmp/september-exam-matrix/baseline-all-51.json`에 영어 3부와 나머지 48부의 최초 실행을 합쳤다. 전체 51부가 실제 실행됐으며 HTTP 200은 9부, 422는 37부, 400은 4부, 500은 1부였다. HTTP 200인 결과도 동시 품질 조건을 모두 만족하지 않아 목표 통과는 0부다. 실행 중 앱 코드의 서로 다른 스냅샷 11개가 관측됐으므로 이 결과는 **UNSTABLE 최초 진단**이며 최종 품질 측정이 아니다. 원래 worker 증거와 `report-original-attempt.json`을 보존했고 최종에는 안정된 코드에서 재검사한다.

## 안정 코드 전체 실행 보존

`tmp/september-exam-matrix/stable-all-51-20261007-final/report.json`에 전체 51부를 새로 실행했다. 동일 제품 SHA-256 `7b63c82ddc00b5ff3cbfebe5c06fe0b34f5c26a7aeab0f1865a250bc68a0b916`으로 시작·종료했고 각 worker도 같았다. 두 격리 batch의 51부 원본 inventory·전체 고유 case ID·fresh worker ID·원본 SHA-256을 다시 대조한 뒤 병합했다. snapshot 1개/`STABLE`, manifest 오류·미실행·incomplete 이유 0개다.

원본 51부·312쪽·1,355문항·100,039,478바이트를 모두 검사했다. HTTP200 10부, 엄격 검증 실패/422 32부, 구조 분석 거절/400 9부이며 예외/500은 없었다. **품질 목표 통과는 0부, 전체51부 FAIL/exit1**이다. HTTP200과 안정된 실행은 품질 통과를 뜻하지 않는다. 거절 코드·편집성 문제·개별 실패 gate와 영어 세 부의 독립 체크는 같은 폴더 `findings.json`에 있다.

영어 고1/고2/고3은 모두 8쪽/45문항/원문1.0, 독립 open safety·editability·전체 render를 통과했다. 엄격 평균/최저는 93.21/90.68, 92.12/85.79, 87.05/78.58이고 API 객관 점수는89.75,89.75,87.05다. 원본 인쇄 번호와 source page 범위는 정확하며 본문 raster·전면 이미지·텍스트/수식 overlay는 없다. 세 부 모두 엄격 평균97/최저95·raw alignment96%/foreground97%·API98 목표에 미달하고 고3은 layout-view94%도 미달한다.

이 안정 실행 후 별도 고2 source-proven field/continuation 들여쓰기 수정을 시작했다. 그 이후 코드의 결과와 이 기준 실행을 혼합하지 않는다. 남은 absolute geometry·실제 PDF glyph·font painting 문제 및 후속 검사는 `september-basic-english.md`, `english-basic-remaining-causes.md`에서 이어서 기록한다. 프리미엄/순서 변경과 실제 Mac 실행은 이번 전체 실행 범위에 포함되지 않는다.
