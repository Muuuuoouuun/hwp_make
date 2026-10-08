# 기본 영어 선택지의 원본 단어 공백

2026-10-07. 기본 PDF→편집 가능한 native HWPX만 대상으로 한다. 프리미엄 양식·순서 변경은 제외한다.

고3 원본의 한 영어 선택지는 Times New Roman 글자 내부 advance가 native 출력과 거의 같다. 그러나 원본의 단어 공백은 약0.25em이고 현재 native renderer의 일반 ASCII 공백은0.5em이다. 첫 Latin 글자의 x 오차는−4.225px로 시작해 같은 단어 내부에서는 거의 일정하지만 공백마다 약2.87px씩 증가해 마지막 글자는+19.187px가 된다. 실제 source/native PDF glyph 비교는 `tmp/september-exam-matrix/high3-choice-space-readonly.json`에 있다. 앞의 circled marker와 첫 단어 사이의 별도 원점 오차는 이 수정의 해결 범위가 아니다.

`app/pdf_source_choice_spaces.py`는 source 위치 metadata를 허용 근거로 사용하지 않는다. 원본 PDF를 다시 열어 같은 쪽의 유일하고 완전한 raw row, 모든 span과 문자·font·flags·size·origin·bbox, 수평 방향과 page width를 실제값과 대조한다. 완전한 한 줄의 circled 선택지이며 보통 Times New Roman의 실제 공백3개 이상이 일관된 경우만 지원한다. table, 수식, 밑줄 빈칸, inline label, 여러 줄 및 CENTER 경로는 그대로 둔다. 실제 source 원점에서 측정한 공백 advance를 renderer의 음수 자간 최소폭/정수 퍼센트로 표현할 수 있을 때만 whitespace charPr를 반환한다.

`restore_source_run_styles`가 source/native 전체 원문 일치를 다시 확인하고 native ASCII 공백만 별도 장평·자간으로 표현한다. 공백을 삭제하거나 문자를 이미지로 바꾸지 않는다. 두 공백, tab, 원문 변경, 새 수식에는 이 공백 스타일을 강제하지 않는다. source font와 일반 문자 style 경로도 유지한다. producer는 source_literal_text item에 source_pdf_path와0-based source_page_index를 보존하며, helper가 해당 실제 파일을 재검증한다.

검증과 제한:

- `scripts/verify_native_source_choice_spaces.py` PASS: 실제 원본 공백8개, native 장평80/자간−15, 원문 보존·memoizing 테스트 allocator에서 재적용 XML 일치, 변조/누락/NaN 원본·범위/새 수식/편집된 문자/tab 등30개 거절 또는 보존 검사. 실제 생산 allocator를 직접 두 번 호출하면 동등한 style이 새 ID를 받을 수 있으므로 제품 raw-ID idempotence를 주장하지 않는다. 독립 리뷰 `source-whitespace-typography-review.md`에서 resolved style fingerprint의 동일성을 별도로 확인했다.
- 실제3개 학년의 source 후보 행을 읽은 범위 진단에서 고3 선택지46개가 증명 조건을 만족했다. 고1·고2는0개다. 다른 font의 공백까지 같은 값으로 강제하지 않는다. 이 수는 제품 변환에서 실제 적용된 문단 수나 전체 품질 통과 수가 아니다. 근거는 `source-choice-spaces/actual-source-coverage.json`이다.
- 같은 고정 native 입력의 한 선택지에 새 helper가 증명한 공백 스타일만 적용한 ZIP A/B에서8쪽·원문·공백8개를 보존하며 마지막 글자 x 오차가+19.187→−2.586px로 줄었다. 첫 Latin 글자의−4.225px는 그대로이고, 그 지점에 대한 최대 상대오차는1.785px다. 새 run 경계의 renderer 정수 반올림도 남는다. `high3-choice-spaces-ab/report.json`은 진단 A/B이며 실제 전체 writer/API 품질 증거를 대체하지 않는다.

실제 변환·편집·저장·재열기 및 영어3종의 새 동결 품질 결과는 별도 확인한다. macOS의 실제 font/runtime 실행을 이 Python 변경으로 검증했다고 주장하지 않는다.
