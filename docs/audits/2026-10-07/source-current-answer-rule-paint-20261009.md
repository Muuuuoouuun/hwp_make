# 현재 보이는 답란 선 판정 — 제품 적용

2026-10-09 기본 영어 PDF→native HWPX의 빈 답란 판정을 보강했다. 뒤에 덧그린 선·문자·덮개가 있는 경우 가려진 옛 선을 복원하거나 잘못된 두께를 사용하는 문제를 다룬다. 문항 밖 안내문·머릿말과 프리미엄 양식·순서 변경은 이번 작업 범위 밖이다.

## 적용 내용

`app/pdf_answer_blanks.py`를 `e5a3d042…`에서 독립 검토한 `0651760922876b9acfdccd50987d5c83d154b3dd9d67fd580b9e2dc35b467711`로 교체했다. 실제 보이는 전체 선의 범위·두께와 PDF/SVG paint 순서·clip·현재 glyph ink를 함께 확인한다. 더 짧거나 일부만 굵게 덧그린 선을 하나의 균일한 선으로 표현할 수 없으면 해당 성분의 복원을 생략한다.

실제 embedded TrueType의 단순·복합 glyph 윤곽점을 해석하고 기록된 bbox가 그 점들을 포함하는지 확인한다. 이탤릭의 음수 bearing, 실제 affine 변환과 복합 glyph의 변환도 대조한다. 폰트 checksum이나 기록된 bbox만으로 잉크가 없다고 판정하지 않는다. 점의 convex hull을 사용하므로 실제 곡선보다 넓게 잡는 보수적 범위이며, 복합 offset의 모호성·순환·깊이·성분·공유 point/GID 연산 한도에서는 복원을 생략한다.

공개 함수 인자와 `restore_answer_blanks`의 AST는 기존과 같다. 추가 의존성은 표준 라이브러리 `struct`뿐이다. QA 결과·특정 문항번호·시험지 hash·TMP 경로에 의존하지 않는다. 영어 영역 opt-in 조건은 유지하며 native renderer와 vendor 저장 코드는 이번 적용에서 바꾸지 않았다.

## 확인한 범위

- TMP 작성자 155개와 별도 독립 검토 89개가 통과했다. 최초 후보 c53의 42/46 실패와 v2의 45/47 실패는 보존했다.
- 실제 제품의 기본 `app.pdf_answer_blanks` import로 155/155, 별도 독립 연결 검사 16/16이 통과했다. 두 경로 모두 실제 모듈 경로와 SHA를 확인하며 양성 module injection은 없다.
- 원본 32쪽의 19개 답란 record는 기존 제품과 정확히 같다. 실제 이탤릭 `j`의 bbox만 축소한 두 PDF는 각각 답란 위 파란 잉크 672px를 유지하면서 거부한다. 하나는 모든 table/whole-font checksum을 정상 재계산한 PDF다. 실제 복합 glyph는 겹치는 366px 사례와 겹치지 않는 정상 사례를 구분한다. 128/129개 고유 GID의 실제 PDF로 연산 한도의 보수적 복귀도 확인했다.
- 실제 영어 3종 K API는 고1·고2·고3 모두 HTTP 200, 8쪽/45문항, 원문/native 텍스트 보존 1.0, 독립 열기·편집 구조·렌더 검사를 통과했다. 세 시험지의 전체 SVG는 직전 J와 정확히 같다. source 판정 검사를 새 native 공개 편집 검증으로 표현하지 않는다.

K의 제품 snapshot은 `c53fddeb…`, renderer snapshot은 `33ab6b67…`이며 세 시험지 동안 STABLE이다. 점수는 89.75/89.75/89.72로 J와 같고 전체 페이지 품질 gate 6개는 세 시험지 모두 미달이다. 나머지 48종은 K에서 재실행하지 않았다. 이번 수정의 원본 정상 출력과 기존 답란을 보존한 결과이며 전체 품질 목표를 충족한 결과가 아니다.

최초 제품 검사 실행은 옛 참조 코드를 package 밖 이름으로 불러 상대 import가 실패해 0/0에서 멈췄다. 제품 기본 import는 정상이었으며, 별도 v2 driver에서 옛 참조만 private `app` package 이름으로 읽어 155개를 실행했다. 최초 staging manifest·driver·실패 보고서는 덮어쓰지 않았다.

## 증거

- 적용 전 백업과 호환성: `tmp/september-audit/q32-v3-production-staging/manifest.json` (`9b59abd5…`), `backup/pdf_answer_blanks.py`.
- 적용 시점: `tmp/september-audit/q32-v3-production-transition/report.json`. 이 파일의 `validation_pending:true`는 당시 상태이며 후속 완료 보고서와 구분한다.
- source 독립 검토: `tmp/september-audit/q32-current-paint-independent-v3-06517609/{final-report.json,assessment.md}` (`89/89`, 보고서 `27f332e4…`).
- 실제 제품 155개: `tmp/september-audit/q32-v3-production-staging/product-driver-v2/results/aggregate-report.json` (`395c6df5…`).
- 실제 제품 독립 16개: `tmp/september-audit/q32-current-paint-product-independent/{report.json,assessment.md}`.
- 실제 K: `tmp/september-exam-matrix/basic-english-native5-20261009-k/report.json` (`6403813d…`), `tmp/september-audit/basic-english-k-question-priority-checkpoint.json` (`c8045b78…`).
- 적용·현재 제품 검증 완료 요약: `tmp/september-audit/q32-visible-rule-product-verification.json`. 실제 제품 171개와 K API의 확인 범위를 구분한다.
- 최초 0/0 실행: `tmp/september-audit/q32-v3-production-staging/product-results/aggregate-report.json`.

## 남은 한계

native 밑줄의 원본 Y·두께 일치는 별도 renderer 과제다. 편집 후 원본 셀 높이·source 흐름 지속성, 표·편지·선택지 내부 간격, 전체 페이지 품질 목표 및 실제 Mac 실행도 완료하지 않았다. 현재 실제 원본의 정상 record 보존과 검사한 덧그림·폰트 윤곽 판정 범위를 확인한 것이며 임의 PDF의 완전한 잉크 해석을 보장하는 결과가 아니다.
