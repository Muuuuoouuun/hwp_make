# 긴 문항 편집 후 페이지 복귀 — 제품 연결

일반 문항을 길게 편집해 8쪽을 9쪽으로 늘린 뒤 원문으로 되돌려도 9쪽이 남았다. 다음 저장이 직전 자동 page/column 나눔을 원래 수동 나눔의 하한으로 취급한 것이 직접 원인이다.

현재 제품은 최초 관리 편집의 수동 나눔과 마지막 자동 나눔을 구분하는 작은 문서 이력을 저장한다. 현재 문단·스타일·단 설정·파트가 그대로인 범위에서 자동 하한만 해제하고 현재 글자 높이로 다시 배치한다. 원래 수동 나눔, 바뀐 스타일·표·단 설정, 손상된 이력은 보수적으로 유지한다. 이력이 없는 과거 9쪽 파일을 8쪽이었다고 추정하지 않는다. 이력 digest는 손상 감지용이며 인증 수단이 아니다.

이 단계의 제품 변경은 `question_reflow.py` `99b1764f…`와 새 `general_flow_state.py` `63578779…` 두 파일이었다. 나머지 기존 app197 바이트는 유지했고 파일 수는 198개였다. 적용 전 백업과 전후 해시는 `tmp/september-audit/general-break-history-product-transition/report.json`에 있다. 해당 기록의 `validation_pending`은 복사 직후 상태이며 후속 검증 기록과 구분한다. 현재 app199의 후속 간격 수정은 [일반 간격과 편집 복귀](native-gap-edit-20261009.md)에 별도로 기록한다.

후보 자체 196개와 기존 회귀3종, 별도 독립162개가 통과했다. 이전 v4는 사용 중인 charPr42의 앞에 중복 ID를 삽입하면 실제 native 글자 크기가 바뀌는데도 이력을 허용하는 결함이 있어 기각했다. v5는 현재 ID의 중복·누락을 거부하며 참조하는 TAB·border·named style·font 의존성을 함께 확인한다. 이전 실패와 그 출력은 보존했다.

실제 제품 import 경로의 공개 저장22개와 기존 회귀3종도 최종 종료 PASS다. 실제 8→9→8쪽 복귀, 늘어난 파일 재열기 후 복귀, 보유 run 객체, 45문항 텍스트와 다른44문항의 26,877 world glyph 불변성을 확인했다. app198·vendor·native·입력 해시가 전후 동일하며 모든 실제 SVG는 동결 v5의 같은 시나리오와 정확히 같다. 후속 검증 완료는 `tmp/september-audit/general-break-history-product-verification.json`에 따로 기록했다.

후속 편지 두 파일까지 연결한 당시 app198 `70bf7ab8…`에서는 전체51종·312쪽·1,355문항 H API 실행을 완료했다. HTTP200은11종, strict422는40종이며 과거 G 대비 HTTP 변화는0종이다. 영어3종은8쪽·45문항·기본 구조 통과, 전체품질6개 미달이다. 이 전체 초기 변환 검사는 일반 흐름의 공개22개를 후속 편지 코드에서 모두 재실행했다는 뜻은 아니다.

**후속 상태:** 당시 남았던 대상36번의 904글자 Y −5.28/−5.293333px와 일반 간격·leading은 후속 app199에서 보강했다. 실제 고3 원문 복귀와 overflow 재열기 후 복귀의 8개 SVG가 모두 baseline과 같고, 실제 제품 회귀3종·독립468개를 통과했다. 일반→격자→일반의 혼합 편집 복귀와 실제 Hancom/Mac 이력 유지는 남는다. 편지 v2의 고3 서명 편집 +172 HWPUNIT은 별도 후속 편지 제품 변경으로 해소했으며 [편지 기록](letter-closing-rows-20261009.md)에 검증 범위가 있다.

근거:

- `tmp/september-audit/general-break-history-candidate-v5/HANDOFF.json`
- `tmp/september-audit/general-break-history-independent-v5/HANDOFF.json`
- `tmp/september-audit/general-break-history-product-integration-qualification.json`
- `tmp/september-audit/general-break-history-product-transition/report.json`
- `tmp/september-audit/general-break-history-product-independent/public-first/report.json`
- `tmp/september-audit/general-break-history-product-independent/HANDOFF.json`
- `tmp/september-audit/general-break-history-product-verification.json`
- `tmp/september-audit/full51-question-priority-native5-h.json`
