# 영어 문자가 들어간 답란 자동 생성 — 실제 제품 J

기본 영어의 원본 배치 변환에 원본에서 확인한 `(A)`/`(B)` 답란을 편집 가능한 native TAB·문자·밑줄로 생성하는 경로를 연결했다. 프리미엄 양식과 문항 밖 안내문·머릿말은 이번 범위 밖이다. 문항번호나 시험지 hash로 대상을 선택하지 않는다.

## 결과

실제 J API 고1·고2·고3 영어는 모두 HTTP 200, 8쪽/45문항, 원문 보존 1.0, native 텍스트 보존 1.0 및 독립 열기·편집 구조·실제 표시 검사를 통과했다. 세 시험지 동안 코드 snapshot `bf00a44836be6c439301a88daa31e965819878fa8b3b07d90db71c2bf2306257`와 native5 renderer snapshot은 STABLE이다.

고3 40번의 답란 행 35글자 중 33글자가 원본 간격으로 이동했다. 최대 가로 오차는 **52.636523→0.768304px**다. 답란 행 밖 **27,746글자의 전체 표시 tuple과 픽셀**, 전체 글자의 Y는 I와 같다. 두 실제 검정 실선은 끊김 없이 표시되며 원본 대비 가로 끝점 오차는 최대 **0.005407px**다. 실제 J 전체 SVG는 검증된 제품 bytes API 출력과 같고, 고1·고2 전체 SVG는 I와 같다.

전체 페이지 품질 기준은 세 시험지 모두 여전히 미달이다. API 점수 89.75/89.75/89.72와 harsh 평균·최소는 I와 같다. **나머지 48종은 J에서 재실행하지 않았다.** 앞선 전체 51종 G는 이전 코드의 기준선으로 보존한다.

## 적용 경로와 허가 조건

`hwpx_writer_v2.py`의 영어/source-layout/native 조건에서 기존 선택지 간격·열 제목 보정 다음에 `apply_source_labeled_rules`를 실행한다. 새 파일은 `app/pdf_source_labeled_rules.py`와 `app/pdf_native_labeled_rules.py`다.

실제 producer item으로 문항 소속을 발견한 뒤 PDF의 완전한 번호 구간·1,180글자·요약 셀·표지·검정 실선·프레임·현재 paint 및 embedded Times Unicode/CID/GID/hmtx를 다시 확인한다. 현재 native의 완전한 문항 표시 소속·일곱 언어 폰트 참조·단 폭·셀 geometry와 세 cache 행은 실제 원본으로 재생성한 결과와 같아야 한다. 예전 cache 폭은 새 가로 좌표의 허가로 사용하지 않는다.

실제 현재 폰트 측정과 현재 가용 폭으로 여섯 TAB을 계산한다. 완전한 TAB/표지/TAB 구간이 줄 안에 맞고, 뒤의 평문 스타일이 밑줄 외에 같을 때만 ASCII 공백 한 개를 첫 행의 줄 경계에 포함한다. 초기 후보의 경계 87은 다음 행을 +5.733px 이동시켰으므로, 제품은 정확한 경계 88을 요구하고 그렇지 않으면 원본 bytes로 복귀한다. 숫자 88은 문항별 상수가 아니라 원래 전체 행의 UTF-16 길이와 새 여섯 TAB의 길이로 계산된다.

파일 wrapper는 임시 HWPX를 editor-open validator로 확인하고 대상 파일 bytes가 변하지 않은 경우에만 교체한다. 실패 시 임시 파일을 정리한다. 이 확인은 비교 시점의 동시 편집 보호이며 OS 수준 CAS 보장을 뜻하지 않는다.

## 실제 제품 검증

| 검사 | 결과 | 범위 |
| --- | --- | --- |
| source/native 가드 | 66/66 | 현재 셀·폰트·cache·source metadata 및 전체 bytes 복귀 |
| 독립 cache/공개 원문 복원 | 43/43 | 실제 설치된 native5·기본 연산 한도, 실제 폭·넘침, 일반 TAB 문단 22개 기존 결과 동일 |
| 제품 bytes API 출력의 공개 편집 | 20/20 | 원래 run/TAB 참조·반복 편집·다른 44문항·재열기/재저장 |
| 독립 실제 파일 wrapper | 14/14 | 정상 결과 bytes 동일, validator·I/O·동시 편집·임시 파일 정리, 강제 경계 87 거절 |
| 실제 J API 출력의 공개 편집 | 20/20 | 새 출력의 실제 paragraph ID로 다시 연결, adapter/provider override 없이 반복 편집 |
| 기존 일반 native TAB 회귀 | 88/88 | Python `-O`, UTF-16 경계·폰트/style·budget/runtime 실패의 보수적 복귀·serializer 재진입 없음 |

공개 편집 후 답란 행 35글자의 X/Y는 유지됐고, 다른 44문항의 26,601개 world glyph는 같다. 원문 편집·복원 후 이어지는 행의 Y 차이 +0.026667px는 144% 줄 간격 반올림이며, 재열기·재저장 SVG는 정확히 같다. 시험 드라이버가 직접 제품 소스 파일을 편집하지 않는다는 일부 보고서의 `product_applied:false`와, 실제 제품 모듈을 불러 검사했다는 범위를 구분한다.

## 남은 한계

- 원본 대비 선 Y는 +2.173568px, 표지 Y는 최대 +3.345532px다. native 실선 두께 1pt는 원본을 출력 크기로 환산한 0.339352pt와 다르다. renderer의 밑줄 표시 계약은 이번에 바꾸지 않았다.
- 공개 재흐름의 셀 높이·원본 세로 흐름 일치는 완료되지 않았다. 기존 편집 지원의 +3.81pt 셀 높이 증가도 별도 범위로 남긴다.
- 32번 현재 paint 검출의 후속 후보는 별도 검토 중이다. 이 자동 생성 적용이 해당 검출기 결함을 고쳤다는 뜻이 아니다.
- 실제 Mac 변환·편집·재저장·렌더 검증은 아직 없다. Windows native5 wheel만 검증됐다.

## 파일과 증거

- `app/pdf_native_labeled_rules.py`: `ddde6979a537e8da383aa38dbd271e9f2757b3ea504b94e3d18cb4612efca546`
- `app/pdf_source_labeled_rules.py`: `bf5f7dbaf5c1b19269dab72bd4e0f893d737418ed0ca3098965b91d667475e27`
- `app/_vendor/hwpx/tools/native_line_cache.py`: `589da0bf3286bf98619b4cdf1fdfc32f6bb1ccb7a42e38f344925763d66cf7a7`
- `app/hwpx_writer_v2.py`: `98717722b69480da570755d30d7d4993228f8c8a95e6f8dcf8d94d633e4c775f`
- 변경 전·staging 차이: `tmp/september-audit/labeled-rule-product-transition/`, `labeled-rule-production-staging/`.
- 실제 J: `tmp/september-exam-matrix/basic-english-native5-20261008-j/report.json`, `tmp/september-audit/basic-english-j-question-priority-checkpoint.json`.
- 실제 J 표시·공개 편집: `tmp/september-audit/labeled-rule-actual-j/{geometry-current-i.json,rule-paint.json,public/report.json}`.
- 제품 검사: `tmp/september-audit/labeled-rule-product-checks/{qualification.json,guards.json,public/report.json}`, `labeled-separator-product/report.json`, `labeled-rule-product-wrapper-independent/report.json`, `labeled-rule-cache-589d-ordinary-guards-opt/report.json`.

동결 TMP 및 첫 경계 87 실패는 [이전 TMP 감사 기록](labeled-answer-rule-native-tmp-20261008.md)에 보존했다. 적용 시 바뀐 것은 import·설명·보고 scope, 정확한 현재 줄 경계 요구, 파일 wrapper와 writer 연결이다. source 계획의 TMP/제품 공통 header 핵심은 같음을 diff로 확인했다.
