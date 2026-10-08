# 기본 영어: 안내문과 글꼴이 같은 본문의 폭·자간

범위는 기본 PDF→편집 가능한 HWPX다. 프리미엄 양식과 문항 순서 변경은 포함하지 않는다.

본문을 별도 문단으로 처리하면 한국어 글자 쌍에서 얻었던 문단 폭·자간 표본이 사라진다. 기존 `_source_typography`는 영어 전용 문단에서 이 표본을 얻지 못해 100%/0으로 돌아간다. 실제 고1 A/B에서 문단 경계만 나눴을 때 최대 가로 오차가 오히려 28.75/42.20px로 늘었다.

`pdf_source_body_metrics.py`는 원본 PDF를 다시 열어 공급된 모든 행·글자·글꼴·크기·flags·좌표가 실제 원본과 같은지 확인한다. 각 글자는 수평 방향의 유일한 visible text trace와 일치해야 하며, trace의 가로 크기와 raw span 크기 비율로 실제 가로 변환을 구한다. 문단 metadata나 경계 플래그만으로 폭을 설정하지 않는다. 영어 자간은 이렇게 입증된 실제 span의 인접 영문자 표본에서 기존 측정 함수가 구한다. 이는 정수 단위 근사이며 모든 원문 글자 간격의 완전한 재현을 주장하지 않는다.

처음부터 안내문과 본문이 별도 의미 문단인 경우에만 이 경로를 적용한다. 전체 원본 행과 뒤따르는 어휘 설명·첫 선지를 확인하는 공통 완전성 검사도 통과해야 한다. 합쳐진 같은 글꼴 문단을 새로 나누는 경로는 계속 거절한다. 고1 Q19 실험에서 본문은 개선됐지만 안내문 최대 x 오차가 3.668→4.915px로 늘어났기 때문이다. 경계 모드 `existing`은 보수적인 적용 범위 표시이며, 실제 원문·변환 증명의 대체물이 아니다.

읽기 전용 실제 원본 A/B 결과는 다음과 같다. 공백 너비를 별도로 바꾸지 않았다.

| 고2 본문 | 실제 폭/자간 | 전체 글자 최대 x 오차 전→후 |
|---|---|---|
| Q19 | 97% / −1% | 15.211→2.462px |
| Q20 | 98% / −2% | 18.453→5.664px |
| Q26 | 98% / −2% | 13.219→2.470px |

8쪽과 27,170개 visible nonspace 글자의 쪽·문자 순서를 유지했다. 세 본문 외 25,310개 글자의 완전한 native glyph tuple은 모두 같다. 본문의 y 좌표도 이전과 같다. 이 결과는 `tmp/september-exam-matrix/samefont-source-metrics-high2/ab-measurement.json`에 있으며 전체 문서 품질 통과를 뜻하지 않는다.

실제 통합 코드의 source 전용 검사는 `source-body-metrics-integrated-source/report.json`에서 164 checks/90 negatives, 코드 hash stable PASS다. 원문/metadata를 함께 줄인 마지막 1~2행 누락, metadata 폭·자간 위조, 중복·회전·수직·숨김 trace 및 span 내부 가로 변환 불일치를 거절하며 입력을 변경하지 않는다.

임시 패치 없이 새로 생성한 `basic-english-integrated-high2/native.hwpx`도 app 생성 전후 hash stable, 실제 8쪽이다. 그 파일의 27,170개 native glyph tuple 전체가 위에서 측정한 A/B 출력과 같아 같은 개선을 확인했다. 결과는 해당 폴더의 `ab-measurement.json`과 `app-code-hashes.json`이다. `source-body-metrics-integrated-native/report.json`은 174 checks/90 negatives PASS이며, 저장된 폭·자간과 public `add_run` → 저장 → 재열기/재저장 후 원래 글자 스타일·들여쓰기 및 편집된 모든 페이지의 실제 SVG 일치를 확인했다.
