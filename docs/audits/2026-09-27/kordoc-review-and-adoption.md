# kordoc 검토와 적용 결과 (2026-09-27)

[kordoc](https://github.com/chrisryugj/kordoc)(MIT, TypeScript)은 HWP·HWPX·PDF 등 한국 문서를 마크다운으로 바꾸는 파서다. HWPX 생성과 한컴 조판 예측 도구도 들어 있다. 이 앱과 겹치는 수식, HWP/HWPX 가져오기, HWPX 생성·조판 세 분야의 코드를 직접 대조했다. 1순위(작고 효과가 확실한 것)를 모두 적용했고, 2순위 가운데 이 환경에서 검증할 수 있는 것도 적용했다.

kordoc을 그대로 호출하지는 않는다. 우리 산출물의 핵심인 2단 조판과 수식 렌더링을 kordoc이 지원하지 않기 때문이다. 옮긴 코드와 규칙의 출처는 `app/third_party_licenses/NOTICE.md`에 적었다.

## 적용한 것

| 분야 | 문제(수정 전) | 수정 | 검증 |
| --- | --- | --- | --- |
| LaTeX→한컴 수식 | `\left(\frac12\right)`가 크기가 고정된 괄호가 됨. `\left\{…\right.`는 짝 없는 `{`가 되어 스크립트가 깨짐 | `LEFT ( … RIGHT )`로 출력하고, 한쪽 중괄호는 `cases{}`로 바꿈 | `verify_hwpx_native_math.py` 14건 추가 |
| LaTeX→한컴 수식 | `\{1,2\}`, `a \over b`, `\overset{\frown}{AB}`, `\Vert` 등 약 50개 명령이 나오면 식 전체가 LaTeX 원문 글자로 남음 | 해당 명령 대응 추가, 호는 `arch`로 출력 | 같은 스크립트 |
| LaTeX→한컴 수식 | `\text{int}`가 적분 기호로 렌더됨, `\text{이면 }`의 공백이 사라짐 | 한컴 따옴표 문자열 `"…"`로 출력하고, LaTeX 안의 예약어 글자열도 따옴표로 감쌈 | 같은 스크립트 |
| LaTeX→한컴 수식 | `\overbrace{a+b}^{n}`의 라벨이 위첨자로 새어 나감 | 한컴 라벨 인자 `OVERBRACE {a+b} {n}`로 출력 | 같은 스크립트 |
| PDF 수식 글꼴 | HyhwpEQ 그리스 문자가 9자만 복원됨 | 대문자 U+E085–E09C, 소문자 U+E09D–E0B4를 순서대로 채움. 육안 확정 9자와 kordoc의 별도 확인 3자가 모두 이 순서와 일치 | `verify_hancom_pua_map.py` |
| HWPX 가져오기 | `<hp:t>a<hp:tab/>b</hp:t>`에서 `b`가 사라짐 | hp:t 안 탭·줄바꿈·빈칸 요소 뒤의 글을 보존 | `verify_hwpx_import_semantics.py`(신규) |
| HWPX 가져오기 | `hp:switch` 캡션이 두 번 나옴. 숨은 설명과 입력 전 누름틀 안내문이 문항 본문에 섞임 | 한 갈래만 읽고, 숨은 설명과 입력 전 안내문은 제외 | 같은 스크립트 |
| HWPX 가져오기 | `문3） ④`형 미주(번호는 autoNum, 첫 글자가 정답)는 정답이 비어 80% 기준에 걸려 **미주 분할이 취소됨** | 첫 줄 선두의 원문자·숫자를 정답으로 인식 | 같은 스크립트 |
| HWPX 가져오기 | 병합 셀을 무시해 행 길이가 들쭉날쭉함. 중첩 표가 별도 표로 한 번 더 들어감 | `cellAddr`·`cellSpan` 격자로 배치하고 바깥 표만 사용 | 같은 스크립트 |
| HWPX 가져오기 | section 파일을 문자열 정렬해 section10이 section2보다 앞에 옴 | content.hpf spine 순서를 따르고, spine이 없으면 숫자 정렬 | 같은 스크립트 |
| HWPX 가져오기 | 한글 자동 문단번호로 매긴 문항 번호가 사라지고 문항 분리에 실패함 | paraPr heading NUMBER와 paraHead 서식(`^1.`, 가나다, 원문자 등)으로 번호를 복원 | 같은 스크립트 |
| HWP 가져오기 | 배포용 문서는 미리보기 앞부분만 가져오면서 이유를 알리지 않음 | 배포용 플래그(0x4)를 감지해 안내 | 같은 스크립트 |
| DOCX 내보내기 | HWP/HWPX에서 가져온 한컴 수식이 Word에 `{1} over {2}`, `LEFT`, `sqrt` 같은 **글자 그대로** 들어감 | `app/hancom_eqn_latex.py`(kordoc `equation.ts` 포팅, 원류 hml-equation-parser Apache-2.0)로 LaTeX를 거쳐 OMML로 변환. OMML 변환기의 기호·`\text`·`\binom`·호 지원도 넓힘 | `verify_hancom_eqn_latex.py`(신규) |
| 한컴 열기 도구 | 원본 경로로 열면 보안 팝업이 뜸. 한글 조판 결과를 받아 올 경로가 없음 | `probe_hwp_open.ps1 -CopyToTemp`(%TEMP% 복사본을 열어 팝업 회피), `-ExportHwpxDirectory`(한글이 저장한 HWPX)를 추가. 둘 다 선택 옵션 | **Windows에서 미실행**(아래 참고) |
| 조판 판독 | 한글 쪽 수를 확인하려면 GUI 스크린샷이 필요함(9월 23일 영어: rhwp 8쪽, 한글 10쪽) | `app/hwpx_lineseg_layout.py`와 `scripts/inspect_hancom_layout.py`: 한글 저장본의 linesegarray로 쪽·단·문항 위치를 OS와 무관하게 판정 | `verify_hancom_layout_inspection.py`(신규, 합성 2단 구역) |

## 적용하지 않은 것과 이유

- **줄바꿈 예측(`simulateWrap`)과 글꼴 폭표**: 알고리즘은 이식할 만하다. 하지만 폭표를 만들려면 우리 본문 글꼴(HY신명조 등) 파일이 있어야 하고, 이 환경에는 없다. Windows에서 글꼴 hmtx를 한 번 추출해 JSON으로 커밋한 뒤 진행해야 한다.
- **한글 조판 판독의 실물 검증**: 우리 생성본에는 한 줄짜리 자리표시 lineseg만 들어 있다(도구가 "판독 불가"로 보고한다). rhwp로 다시 저장해도 자리표시가 그대로 남는다. 실제 판정은 Windows에서 `-ExportHwpxDirectory`로 받은 파일이 있어야 가능하다.
- **한글에서만 확인할 수 있는 것**: 수식 출력 가운데 `LEFT/RIGHT`, `cases`, 따옴표 문자열은 실제 한글 파일 어휘(`scripts/verify_importers.py`의 실물 스크립트)나 kordoc의 되읽기 어휘를 따랐다. 반면 `arch`, `OVERBRACE {…} {…}`, 빈 라벨 `{}`가 한글에서 어떻게 렌더되는지는 한글에서 확인해야 한다. 그리스 PUA 미관측 글자도 실물 수학 PDF로 한 번 렌더해 봐야 한다.
- **가져오지 않음(우리가 더 나음)**: PDF 수식 글리프 구조 복원, LaTeX→한컴 변환 범위, HWPX 패키지 검증, SVG 렌더(kordoc은 수식을 생략하고 다단을 모름), 수식 OCR 모델(숫자 하나짜리 식을 버리는 규칙이 시험지에 해로움).

## 회귀

같은 환경에서 `scripts/run_all_verify.py`를 수정 전 커밋(3f04bb6)과 수정 후에 각각 실행했다. 이 컨테이너는 rhwp가 시스템 FreeType과 맞지 않아 `LD_PRELOAD`로 최신 libfreetype을 지정했고, 깨진 시스템 `cryptography`를 다시 설치했다.

| | PASS | SKIP | FAIL |
| --- | ---: | ---: | ---: |
| 수정 전 | 86 | 20 | 9 |
| 수정 후 | 89 | 20 | 9 |

늘어난 PASS 3개는 신규 검증 스크립트 3개다. FAIL 9개는 수정 전과 같은 항목이고 실패 메시지도 동일하다. 원인은 개인 샘플 PDF 부재(`data/uploads/25수능 수학.pdf` 등), pytest 미설치, OCR 키 없음 같은 환경 문제다. 기존 기대값 가운데 `\left(x+1\right)` → `(x+1)` 계열 8건과 `verify_importers.py`의 1건은 새 출력(`LEFT ( x+1 RIGHT )` 등)으로 갱신했다.

## Windows에서 이어서 할 일

1. `powershell -File scripts/probe_hwp_open.ps1 -Path <생성본.hwpx> -CopyToTemp -ExportHwpxDirectory <폴더>`로 한글 저장본을 받는다. 이어서 `python scripts/inspect_hancom_layout.py <폴더>/<이름>.hancom.hwpx --expect <예상.json>`으로 쪽·단·문항 위치를 판정한다. UI의 예상 쪽·단을 `--expect` 형식으로 내보내면 스크린샷 없이 비교할 수 있다.
2. 한글에서 `arch`, `OVERBRACE {a+b} {n}`, `"이면 "`, `LEFT { 1,2,3 RIGHT }`이 들어간 수식을 연다. 렌더 결과와 편집 가능 여부를 기록한다.
3. 본문 글꼴 폭표를 추출한 뒤 `hwpx_writer_v2`의 글자 수 기반 줄 나눔(`_visual_units`)을 폭 기반 줄바꿈 예측으로 바꿀지 검토한다.
