# 한글(HWP) 파일 변환 우선 적용 (2026-10-14~15)

요청: "한글 파일로의 변환에 가장 큰 포션 두기". [Filee 검토](../2026-10-13/filee-review-and-adoption.md)에서 rhwp 명령줄 도구로 스튜디오의 HWP 내보내기를 붙였다. 이번에는 HWP 결과가 원본 HWPX와 같은지 따로 증명하도록 했다. 그리고 HWP를 앱의 모든 변환 경로에서 기본 결과로 바꿨다. 한글 프로그램 자체는 이 환경에 없다. 그래서 "같다"는 판정은 구조 대조와 같은 렌더러의 쪽 그림 비교로 한다(5절).

## 1. 결론

| | 보정 전(rhwp 그대로) | 적용 후 |
| --- | --- | --- |
| 샘플 PDF 6개의 원본 배치 출력(120쪽) → HWP | rhwp 자체 검증 거절 5/6(exit 3) | **6/6** 변환 |
| 영어 편지 상자(그림 채우기 "크기에 맞추어") | 3/3 문서에서 바둑판 반복으로 바뀜 | **유지** |
| 독립 왕복 대조(아래 2절) | 영어 3개 불일치 | **6/6 일치** |
| 같은 렌더러로 그린 HWPX와 HWP 쪽 그림 | — | **120쪽 모두 픽셀 차이 0** |
| HWP 변환 시간(문서당) | — | 0.3~4.4초 |

HWP는 이제 간단 변환, 스튜디오 내보내기, PDF 원본 배치 변환, 데스크톱 기본판에서 rhwp 도구가 있으면 기본 결과다. HWP가 HWPX와 같게 만들어지지 않으면 HWP를 내주지 않는다. 대신 검사를 마친 HWPX를 주고 그 이유를 알린다.

## 2. HWP 변환 절차 (`app/rhwp_cli.hwpx_to_hwp`)

1. **준비** (`app/hwp_fidelity.normalize_for_hwp`). 임시 사본에서 rhwp 0.8.7이 잘못 읽는 두 표기를 고친다. 원본 HWPX는 그대로 둔다.
   - `hc:imgBrush mode="TOTAL"`(그림을 영역 크기에 맞춤, HWP 5.0 그림 채우기 5)을 rhwp HWPX 판독기는 모른다. 모르는 이름은 바둑판(0)으로 쓴다. rhwp는 같은 값을 자기 이름 `FIT`으로는 5로 바르게 쓴다. 그래서 `TOTAL`을 `FIT`으로 바꾼다. 15가지 표준 이름을 모두 시험했다. rhwp가 아는 이름은 `TILE*`, `CENTER*`, `FIT`이고, `TOTAL`, `LEFT_*`, `RIGHT_*`는 모른다. 이 앱은 `TOTAL`만 쓴다(`pdf_source_backgrounds.py`).
   - run 없는 `hp:p`(빈 표 칸)에 빈 run을 넣는다. HWP 5.0 문단은 글자 모양을 최소 하나 가지며, 한컴 저장본도 항상 run을 쓴다. run이 없으면 rhwp가 글자 모양 0을 지어내고, 그 때문에 자체 검증이 IR 차이(exit 3)로 실패했다. 넣는 run의 글자 모양은 가장 가까운 다음 run(이웃 칸)의 것을 쓴다. 다음 run이 없으면 바로 앞 run을 쓴다.
2. **rhwp 자체 검증**: `rhwp convert --verify --verify-pages`가 HWP를 다시 읽어 rhwp IR과 쪽 수를 대조한다. 단, rhwp IR에는 글상자, 문단 모양, 채우기가 없다.
3. **독립 왕복 대조** (`structure_profile`, `compare_profiles`). HWP를 rhwp `export-hwpx`로 되돌린 결과를 **원래 HWPX**와 비교한다. 비교 항목은 아래와 같고, 하나라도 다르면 HWP를 지우고 거절한다.
   - 개수: 문단·표·칸·글상자·그림·수식·묶음·도형·단 정의·줄 배치·각주/미주·머리말/꼬리말·쪽 번호·자동 번호
   - 내용: 본문 글자(공백 제외), 수식 스크립트, 그림 데이터 수
   - 배치·모양: 개체 크기와 위치, 표 병합, 문단 모양 연결(쪽/단 나눔 포함), 줄 배치(lineseg 위치·크기), 그림 채우기 방식, 글자마다의 글자 모양. 글자 모양은 번호가 아니라 내용(글꼴·크기·색·굵게 등)으로 비교한다. rhwp가 모든 글자 모양에 넣는 `strikeout shape="NONE"`은 기본값이라 뺀다

처음에는 압축된 DocInfo의 채우기 바이트를 직접 고치는 방식을 만들었다. 그런데 olefile은 스트림을 원래 크기로만 다시 쓸 수 있다. 다시 압축한 결과를 정확히 같은 크기로 맞춰야 했고, 작은 문서에서는 이것이 실패했다. rhwp가 `FIT`을 바르게 읽는다는 것을 확인한 뒤 그 방식은 버렸다. 지금은 바이너리를 고치지 않는다.

## 3. 실측 (샘플 PDF 6개, 원본 배치 출력 전체 쪽)

`data/uploads`의 PDF 6개 전체를 구조 보존 경로(`structured`, 최대 200쪽)로 HWPX로 만들고, 같은 HWPX를 HWP로 바꿨다. 쪽 그림은 같은 렌더러(rhwp 0.8.7 `export-png`)로 HWPX와 HWP를 그려, 회색조 32단계 넘게 다른 화소 수를 셌다.

| 원본 PDF | 쪽 | 보정 전 rhwp | 보정 전 왕복 대조 | 준비: 채우기 / 빈 문단 | 적용 후 | 변환 시간 | 쪽 그림 차이 |
| --- | ---: | --- | --- | ---: | --- | ---: | --- |
| 25수능 국어 | 43 | exit 3 | 일치 | 0 / 2 | 통과 | 1.5초 | 0 (43쪽) |
| 25수능 영어 | 16 | exit 3 | 그림 채우기 방식 | 10 / 4 | 통과 | 0.6초 | 0 (16쪽) |
| 국어 | 22 | 통과 | 일치 | 0 / 0 | 통과 | 4.4초 | 0 (22쪽) |
| 국어영역 문제지 홀수형 2025 | 23 | exit 3 | 일치 | 0 / 16 | 통과 | 1.1초 | 0 (23쪽) |
| 영어 | 8 | exit 3 | 그림 채우기 방식 | 8 / 9 | 통과 | 0.6초 | 0 (8쪽) |
| 영어영역 문제지 홀수형 2025 | 8 | exit 3 | 그림 채우기 방식 | 5 / 1 | 통과 | 0.3초 | 0 (8쪽) |

"보정 전 rhwp"는 원래 HWPX를 `--verify`로 바로 바꾼 결과다. exit 3이어도 rhwp는 파일을 남기므로 왕복 대조는 그 파일로 했다. 보정 전 영어 HWP를 같은 렌더러로 그리면 편지 상자 쪽이 실제로 달랐다. 합성 문서 기준으로 `verify_hwp_fidelity_roundtrip.py`가 이를 고정한다.

## 4. 경로별 적용

| 경로 | HWP 동작 | HWP를 못 만들 때 |
| --- | --- | --- |
| 스튜디오 내보내기(`/api/export format=hwp`) | 형식 목록 맨 앞에 HWP를 두고, 사용자가 형식을 바꾸지 않았으면 HWP를 선택 | 500 `hwp_convert_failed`(도구 없음은 503 `hwp_unavailable`). 화면은 같은 요청을 HWPX로 다시 받아 이유와 함께 내려받음 |
| 간단 변환(PDF 외) | `format=hwp`로 요청, 버튼 "한글(HWP)로 변환" | 위와 같이 HWPX로 대신 받음 |
| PDF 원본 배치 변환(`/api/pdf-layout-export output_format=hwp`) | 검사를 마친 HWPX 옆에 HWP를 만들고 HWP를 `export`로 줌. HWPX는 `hwpx_export`로 함께 보관. 변환 기록은 둘 다 원본·보고서와 연결 | `hwp.ok=false`와 안내를 붙여 HWPX를 `export`로 줌. 도구가 없으면 처음부터 503 |
| 간단 변환 PDF 폴백(원본 배치 4xx 뒤 재구성) | 재구성 문서도 HWP로 요청. 안내는 실제로 받은 형식(HWP/HWPX)을 말함 | 위와 같음 |
| 데스크톱 기본판(`run_desktop.py`, `app/desktop_convert.py`) | 저장 형식 HWP·HWPX·DOCX 중 HWP가 기본값 | `.hwpx`로 저장하고 경고에 이유를 남김. 같은 이름의 `.hwpx`가 이미 있으면 덮어쓰지 않고 `이름 (1).hwpx`로 저장 |
| 데스크톱 설치본 | `scripts/build_desktop.ps1`가 rhwp 0.8.7 Windows 빌드를 받아(SHA-256 확인), `packaging/basic.spec`가 실행 파일과 LICENSE를 함께 넣음 | 도구가 없으면 HWP 선택지를 보이지 않음 |

웹 프로토타입(`run_web_prototype.py`, `app/web_convert.py`)은 이번에 바꾸지 않았다. 여전히 HWPX·DOCX만 만든다.

## 5. 검증

| 스크립트 | 확인 내용 |
| --- | --- |
| `verify_hwp_fidelity_roundtrip.py`(신규) | 합성 HWPX(크기에 맞춘 그림 칸 + 빈 칸)를 쓴다. 그대로 바꾸면 대조가 채우기 손실을 잡는지, 글자 크기만 바꾼 사본을 "글자 모양" 차이로 잡는지, 앱 경로가 TOTAL→FIT·빈 문단을 고치는지, 원본 HWPX가 그대로인지, HWP 채우기가 FIT인지, rhwp IR·왕복 대조가 일치하는지, 쪽 그림이 같은지(보정 전은 다른지) 본다. rhwp가 모르는 `LEFT_TOP`은 거절하고 HWP를 남기지 않는지, PDF 원본 배치→HWP와 변환 기록 연결도 확인한다 |
| `verify_desktop_hwp_output.py`(신규) | 데스크톱 작업자를 변환마다 새 프로세스로 띄워 TXT·PDF→HWP를 만든다. 가짜 rhwp(exit 3)로는 HWPX 대체 저장, 같은 이름 파일 보존, 이유 안내를 확인하고, 도구가 없을 때도 본다 |
| `verify_hwp_export_rhwp_cli.py` | 스튜디오 HWP 내보내기와 다시 가져오기, 실패·도구 없음 응답(지난 작업). 새 절차에서도 통과 |
| `verify_frontend_conversion_behavior.js`, `verify_premium_frontend.js`, `verify_progressive_entry.js` | 도구가 있으면 원본 배치 요청 `output_format=hwp`·폴백 `format=hwp`. 받은 형식대로 안내하는지, 기본 화면 시작 때 공개 `/api/health`만 읽고 HWP 가능 여부를 아는지, 도구가 없으면 HWPX 그대로인지 본다 |

`app/desktop_selftest.py`(설치본 자체 점검)도 HWP 기본값과 대체 파일 이름 검사를 넣어 고쳤다. 다만 이 컨테이너에 tkinter가 없어 실행하지 못했다. 같은 작업자 경로는 `verify_desktop_hwp_output.py`로 확인했다.

## 6. 구조 대조가 보지 않는 차이 (HWP 형식의 한계)

25수능 영어·국어 결과를 HWPX로 되돌려 원래 HWPX와 요소·속성 단위로 비교했다. 글자마다의 글자 모양(영어 57,162자, 국어 68,816자)은 모두 같았다. 남은 차이는 아래와 같고, 쪽 그림에는 드러나지 않았다.

뜻이 같은 표기 차이:
- 문단 여백의 `default` 값이 `case`의 2배로 나온다(한컴 기본 서식 파일과 같은 규칙). 줄 간격 `unit` 표기, 탭이 `hp:t` 안으로 들어가는 위치, 머리 버전·메타 태그·바이너리 목록 위치도 다르다.
- 칸·글상자의 `textWidth`·`textHeight` 힌트가 0이 되고 표 칸 `dirty`가 0이 된다. 한글이 다시 계산하는 값이다.
- 여백이 모두 0인 글상자 3개의 `textMargin` 요소가 생략된다. 투명("none") 채우기 정의 1개와 내용 없는 `hp:ctrl` 1개도 빠진다.
- 탭 위치 22곳이 1 HWPUNIT(1/7200인치) 반올림된다.

실제로 잃는 것(HWP 5.0 기록 방식 또는 rhwp 한계):
- 선 굵기는 정해진 단계 값으로만 저장된다. 0.284mm 테두리 7개가 0.3mm가 된다.
- 개요 8~10 수준의 번호 형식이 원문자 숫자로 바뀐다. 6개 문서 모두 본문은 이 수준을 쓰지 않는다. 다만 교사가 한글에서 "개요 8~10" 스타일을 적용하면 번호 모양이 다를 수 있다.
- 글상자의 `name`과 `editable`이 사라진다. `name`은 이 앱의 HWPX 후처리기만 쓴다. 한글에서 `editable`이 무엇을 바꾸는지는 확인하지 못했다.
- 그림 1개의 원본 크기(`imgDim`)가 0이 된다(한글의 "원래 크기로" 기준). 그림·다각형 3개의 개체 설명(`shapeComment`)과 `rotateimage`도 사라진다. 글상자·다각형의 캡션 번호 종류가 NONE에서 PICTURE로 바뀌지만, 캡션은 없다.
- 미주 구분선 길이 값이 바뀐다. 이 문서들에는 미주가 없다.
- rhwp가 HWP에 `RhwpHwpxOrigin` 스트림을 더한다. 한글이 이 스트림을 무시하는지는 아직 확인하지 못했다.

## 7. 남은 확인

1. 한글 실물에서 HWP 결과 열기·편집·저장. 특히 영어 편지 상자, 2단 배치, 한컴 수식, 위 6절 차이를 본다. 이 환경에는 한글이 없다.
2. Windows 설치본 빌드와 설치 후 자체 점검(`HWPMakeBasic.exe --self-test`)에서 rhwp.exe가 함께 들어가는지 확인한다.
3. 웹 프로토타입에 HWP 출력을 넣을지 정한다.
4. rhwp가 `TOTAL`·`LEFT_*`·`RIGHT_*`를 읽도록 상류에 알리면 준비 단계의 이름 바꾸기를 뺄 수 있다.

## 8. 회귀

`scripts/run_all_verify.py` 전체를 같은 환경에서 실행했다(`packaging/rhwp-cli/`에 rhwp 0.8.7 있음).

| | PASS | SKIP | FAIL |
| --- | ---: | ---: | ---: |
| 50cd57c(원격 최신) | 109 | 44 | 31 |
| Filee 적용 후 | 115 | 44 | 31 |
| 이번 적용 후 | 117 | 44 | 31 |

늘어난 PASS 2개는 이번에 추가한 `verify_hwp_fidelity_roundtrip.py`, `verify_desktop_hwp_output.py`다. FAIL 31개는 기준과 같은 항목이다. 원인은 개인 샘플 PDF, pytest, OCR 키, 한글 글꼴 같은 환경 부재다. 변환 기록 코드를 바꾼 `verify_pdf_layout_export_api.py`는 기준과 같은 두 검사만 실패한다(글꼴이 없어 생기는 렌더 글자 누락). PASS 138개도 같다. 회귀 도중 `app/storage.py`와 대조 항목을 고쳤기 때문에, 그 코드를 쓰는 다섯 스크립트는 마지막 코드로 다시 돌렸다. 결과는 PASS 4, 기존 FAIL 1이다. 프런트엔드 `scripts/verify_*.js` 11개는 모두 통과했다.
