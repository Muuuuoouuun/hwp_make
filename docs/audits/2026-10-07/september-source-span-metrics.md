# 기본 영어 안내문의 원본 장평·자간 복원

2026-10-07. 기본 PDF→편집 가능한 HWPX만 대상으로 한다. 프리미엄 양식·문항 순서 변경은 제외한다.

고2 Q27의 실제 원본 제목은 `Haansoft Batang`이다. 원본의 glyph ID로 embedded TTF `hmtx`를 읽으면 제목의 ASCII advance는 렌더러에 포함된 같은 family의 metric과 정확히 같다. 그러나 원본은 수평으로 줄인 글자를 사용한다. raw span의 크기만 복사하면 그 수평 비율이 빠진다. 실제 source glyph bbox와 TTF advance로 독립 측정한 제목 비율은 **96.88795%**, 본문은 **97.89195%**이고, source text trace의 수평 크기/raw span 크기 비율과도 일치한다. 제목의 문자 간격 중앙값은 약 **−0.8525% em**이다.

`app/pdf_source_span_metrics.py`는 실제 PDF를 다시 열어 완전한 네 규칙선, 원문 전체, 그림 픽셀·geometry와 실제 raw span을 먼저 재증명한다. 각 glyph의 문자·font·원점이 source trace와 같고 같은 span 전체의 수평 비율이 일관될 때만 장평을 반환한다. native에서 지원하는 정수 비율로 반올림하며, 범위를 벗어나거나 source가 불완전하면 기존 처리를 유지한다. `app/pdf_source_run_styles.py`는 이 증명이 있는 span의 장평·자간을 원래 native run style에 반영한다. 글꼴 family를 바꾸거나 문항/열 폭을 늘리거나 글자를 raster로 대체하지 않는다.

고2 whole-frame producer의 해당 callback은 그림을 동일한 run/index에 잠시 분리했다가 다시 붙여, 원문 일치 검증과 실제 header style 할당을 모두 유지한다. 본문은 의미 문단으로 남고 그림의 native 소속도 유지된다.

수평 측정값을 복원할 때 이미 원본으로 증명된 의미 문단의 native 글자 높이도 보존해야 한다. raw span 크기를 문단 안의 각 run에 다시 반영하면 794HWP의 원본 줄 캐시에 798HWP run이 섞인다. 렌더러는 이를 불완전한 줄 캐시로 보고 정상 행간을 적용해 다음 문단을 약4.20px씩 밀었다. 같은 입력에서 장평·자간을 유지하고 기존 의미 문단의 run 높이만 되돌린 독립 A/B는 원본 18줄의 baseline 오차를 −0.077..−0.115px로 복원했다. 근거는 `q27-height-ab/report.json`이다. 이 보존은 전체 source/native 증명이 성립한 wrapped frame의 callback에만 적용하며 일반 mixed-font·mixed-size 복원 경로와 구분한다. 실제 최종 출력 검증은 아래의 별도 oracle 대상이다.

- `scripts/verify_native_source_span_metrics.py` PASS: 실제 원본 18줄/22개 span, 제목 장평97·자간−1, 본문98·−2, Registration−5, Bring−3. 모든 원문 문자를 그대로 보존하고 재적용 XML이 같다.
- 같은 회귀의 **20개 negative** PASS: 누락/잘못된 source·쪽수·그림·프레임·문장, answer blank, 변조 font/flags/크기/원점/bbox/text, NaN과 잘못된 page width에서 측정값을 거절한다. source/native 본문 불일치는 style을 할당하지 않는다.
- 기존 `verify_native_source_run_styles.py`의 mixed font/크기/bold/italic/Times tracking 및 control guard도 PASS.
- 동일한 고정 native 입력에 원본에서 측정한 제목 값만 반영한 진단 A/B에서 실제 SVG 제목 30글자의 위치 오차는 최대 **0.4932px**다. 기존 first/last 오차−4.6458/+4.7030px는−0.1458/+0.4556px가 됐다. 이는 측정값의 효과를 분리한 진단이며 전체 문서 품질 통과를 뜻하지 않는다.

회귀 근거: `tmp/september-exam-matrix/source-span-metrics/report.json`. 독립 source TTF/실제 glyph ID 비교: `q27-font-metrics.{py,json,log}`. 원본 측정값 A/B: `q27-source-stretch-ab/report.json`. 같은 native의 font1 PDF 출력 근거는 `q27-paint-font1/report.json`에 있다. 후자의 실제 Q27 658glyph는 설치된 **Batang 대체 글꼴**로 출력됐다. 원본 Haansoft Batang과 설치된 Batang/HCR Batang의 실제 glyph advance는 다르므로, 장평·자간 복원과 원본 글꼴 painting 일치를 구분한다.

원본 U+00AD의 PDF painting 누락과 macOS 글꼴/런타임 검증은 이번 수정으로 해결됐다고 주장하지 않는다. 최종 whole-frame 출력·추가/삭제·재열기 검증은 별도 독립 oracle 결과로 판정한다.

독립 규칙선 oracle도 바로잡았다. `union_covers`는 목표 구간이 이미 연속으로 덮였는데 그 아래 Q28의 무관한 규칙선이 나타나면 false를 반환했다. 이미 목표 끝에 도달하면 true를 반환하고 목표 앞의 무관한 구간은 건너뛴다. 실제 gap/불완전 끝/빈 구간의 거절과 기존 0.4px 허용치는 유지한다. 고정 Q27 whole-frame 입력의 네 규칙선은 원본과 최대 약0.008px 차이로 실제 존재한다.

## 실제 최종 출력과 후속 공백 수정

`q27-final7-independent/report.json`은 source/input/app/verifier/runtime 해시가 검사 전후 동일한 상태에서 PASS다. 원본18줄·4규칙선·그림 픽셀/위치, 일반 public append/save/reopen/delete/save/reopen의 **8→9→8쪽**, 문항 높이 **33186→42644→33186HWP**, 다음 문항의 쪽/x/y 정확한 복귀를 확인했다. 실제 PDF의 검사 대상658/942글자는 쪽 인쇄영역을 벗어나거나 그림과 겹치지 않았다. 이 수에는 U+00AD3개와 정규화 과정에서 제외된 글머리표6개가 포함되지 않는다. 최대 가로 오차6.095px는 보고값이며 이 검사의 통과 기준이 아니다. 물리적 cell ink edge 전체, 원본 fontface painting 일치, 전체 문서 품질 통과로 확대 해석하지 않는다.

원본 글머리표 뒤 공백6개는 font의 일반 공백이 아니라 PDF의 명시적 글자 위치 사이에 MuPDF가 만든 `synthetic` 공백이다. 실제 source의 빈 구간은 약0.20745em인데 native 기본 공백은0.5em이라 첫 단어가 약2.97px 오른쪽으로 밀렸다. `wrapped_source_synthetic_spaces`는 실제 PDF를 다시 열어 모든 row/span/문자/geometry가 일치한 경우에만 이 빈 구간을 측정한다. 양옆 실제 글자와 원점/bbox가 연속이고 같은 수평 span인 Haansoft Batang만 지원한다. native ASCII 공백은 그대로 두고 공백만 별도 charPr의 장평·자간으로 표현하며, renderer의 음수 자간 최소 advance와 정수 퍼센트 양자화로 표현할 수 없는 구간은 그대로 둔다. 문항 번호·필드명·고정 좌표를 사용하지 않는다.

완전히 대응하는 실제 text trace는 한 글자 punctuation span의 수평 transform도 증명하므로, 독립 matched glyph가1개인 짧은 구간의 장평도 복원한다. 원본으로 독립 증명된 짧은 Latin word의3개 인접 문자 advance, 또는 숫자/구두점의4개 advance가 있으면 자간을 측정한다. 일반 source proof가 없는 Times 경로의4개 Latin pair 요건은 유지한다.

후속 실제 writer 출력 `q27-product-final8/high2-native.hwpx`(SHA256 `d9a29611eadb1c8a5a745cec773cc93e438eaa44ee9778a3f05a42f6e3a960e5`)은 source-only 독립 검사에서 코드/입력/runtime이 고정된 상태로 PASS했다. 글머리표 줄 최대 가로 오차는6.095→1.819px이고 다른5줄은0.243~0.773px다. 모든 원본 baseline·그림·다음 문항 위치는 유지됐다. public 저장/재열기의 빠른 검사도8→9→8쪽/동일 높이/정확한 다음 문항 위치 복귀를 확인했다. 이는 **전체 편집 PDFglyph oracle 재실행을 대체하지 않는다**. 원본 `Free`의 짧은 자간 복원은 그 뒤 추가했으므로 이 final8 artifact에 포함되지 않으며 다음 writer 출력에서 검증한다.

현재 전용 source span 검사에는 실제23span·6syntheticspace·짧은 punctuation/숫자/word·원문 보존·재적용 XML 일치 및20개 변조 원본 거절이 포함된다. `q27-literal-advances-ab/report.json`의 더 작은 잔차는 고정 입력을 직접 수정한 진단 A/B이며 제품 변환 결과로 간주하지 않는다.

영어3종 최신 동결 matrix `field-final-native3-20261007/report.json`(제품 SHA256 `e551659507c50ec18ca978990444653267151b0a59098acf6baab9d34237319f`)은3종 모두 품질 FAIL이다. 고1 평균/최저93.21/90.68, 고2 **93.29/90.07**, 고3 **87.05/78.58**이다. 이 matrix는 위 후속 공백 수정 전 결과다. 같은 matrix에서 고2는 이전92.12/85.77보다 개선됐으며, 프리미엄·문항 순서 변경과 actual macOS runtime은 검사 범위에 포함되지 않는다.
