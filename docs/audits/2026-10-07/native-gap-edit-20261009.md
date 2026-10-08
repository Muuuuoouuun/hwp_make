# 일반 문항 간격과 편집 후 복귀 — app199

긴 문항을 늘렸다가 원문으로 되돌리면 쪽 수는 8쪽으로 돌아와도 일부 글자의 Y가 약 5.28px 달라졌다. 현재 제품은 글자를 바꾸기 전 문서의 유효한 일반 흐름 간격과 leading을 작은 별도 이력으로 보존하고, 저장할 때 현재 글자·스타일·단 설정·높이를 다시 검증한다. 명시적 앞 간격도 다음 단에 들어갈 수 있는 경우 함께 옮긴다. 과거 좌표·높이·행 수를 다시 재생하지 않는다.

제품은 app199, 코드 `d79145b4…`, Windows native5 `33ab6b67…`다. 생성자·일반 이력·새 gap 이력·line cache·question reflow의 다섯 app 파일을 연결했다. TAB 회귀는 실제 XML에 결합된 문항과 단 원점을 기준으로 비교하도록 두 test 파일을 보강했다. 문항 전체가 다음 단으로 이동하면 선택지 X도 단 간격만큼 함께 이동하므로, 기존 절대 X 비교의 실패를 그대로 보존하고 문항 안의 상대 위치와 실제 잉크를 검사한다.

현재 기본 제품 import로 시 지문·문단·실제 TAB 편집 회귀 3종이 통과했다. 별도 독립 검사는 의미 검사 63개와 반복 문항 소속 검사 405개, 합계 468개가 통과했다. 468개의 독립 사용자 시나리오를 뜻하지 않는다. 실제 영어 3종의 열기·무편집 재저장 표시가 각 8쪽 모두 같고, 고3 36번의 8→9→8쪽 복귀와 늘어난 파일 재열기 후 원문 복귀도 baseline의 8개 SVG와 정확히 같다. 보유 run/t 노드와 45문항 텍스트를 확인했다. 이 결과는 모든 일반 문단의 편집 복귀를 보장하지 않는다.

현재 문서의 스타일·폰트·중복 ID·문단·wrapper 여백·폭·수동 나눔·알 수 없는 제어 요소 또는 이력이 유효하지 않으면 적용을 거부한다. gap 이력은 `META-INF/hwp-make-native-gaps.json`의 bounded v1 데이터이며 인증 수단이 아니다. 이력이 없는 과거 출력의 간격을 추정하지 않는다. 기존 일반 이력만 있는 파일도 새 gap 이력과 동일한 복원을 보장하지 않는다.

일반→수정된 표/격자→일반의 혼합 편집, 실제 Hancom 편집기의 이력 유지, 실제 Mac 실행은 미검증이다. 원본 PDF와의 선택지·표·편지 위치 오차를 모두 해결했다는 뜻도 아니다. 전체 51종 I 초기 변환 검사도 현재 코드로 완료했다. 312쪽·1,355문항, HTTP200 11종·strict422 40종이며 원본·코드·runtime STABLE이다. 영어3종은 각8쪽·45문항의 기본 구조를 유지했고 기존6개 품질gate 미달도 그대로다. 초기 변환과 실제 편집 회귀를 구분한다.

근거:

- `tmp/september-audit/native-gap-v3-product-transition/report.json`: 복사 직후 상태·의도한 파일·전후 해시. 기록 함수명 오류와 읽기 전용 복구 검증도 보존했다.
- `tmp/september-audit/native-gap-v3-product-regressions/report.json`: 실제 기본 제품 회귀 3종 완료.
- `tmp/september-audit/native-gap-product-independent-c-199/HANDOFF.json`: 실제 기본 제품 독립 468/468.
- `tmp/september-audit/native-gap-ordinary-candidate-v3/HANDOFF.json`: 자체 공개 31·guard 94·추가 7·합성 4·기존 회귀의 정확한 범위.
- `tmp/september-audit/native-gap-ordinary-independent-c-v3/HANDOFF.json`: 독립 후보 43/43. 최초 fixture 예상 reserve 오류는 별도 보존했다.
- `tmp/september-audit/native-gap-current-h-candidate-v3-root-v2/report.json`: 당시 실제 H 고3 입력의 독립 14/14.

직전 일반 나눔 이력 수정과 최초 실패는 [일반 페이지 복귀 기록](general-break-history-20261009.md)에 있다.

최종 완료 기록은 `tmp/september-audit/native-gap-v3-product-verification.json`(SHA `4d5681d4…`), 새 전체51종은 `full51-question-priority-native5-i.json`(SHA `9e13ad94…`)이다. 원래 transition의 복사 직후 pending 필드는 역사적 상태로 보존했다.

## 후속 발견과 미적용 수정 후보

현재 app199의 고3 33번 어휘 주석은 같은 run을 수정했다가 원문으로 되돌리면 14글자의 Y가 +0.013333px 달라진다. 원래 baseline663이 보수적 cache 재생성에서664가 되는 floor/round 차이다. 새 표 후보와 기존 app199 대조군에서 같은 결과를 확인했으며, 표 전환의 +400HWP 회귀가 아니다. 다른44문항의 실제 위치는 같다. 원래 전체51종·제품 검증 기록은 변경하지 않았다.

별도 `native-gap-baseline-scalar-candidate-v1`은 현재 글꼴 높이에 결합된 정수 baseline 하나를 새 v2 이력에 보존한다. 기존 엄격한 v1 schema와 기본 round 동작은 유지한다. native·보수적 cache 두 경로를 함께 연결한 세 파일 후보다. 정적56/56 뒤 실제33번10/10, 실제36번25/25가 통과했다. 33번의14글자 차이가 없어졌고, 실제36번의 두 복귀 경로 모두27,781개 world tuple·전체8SVG·45문항 원문이 같다. 함수 호출 관찰로33번 보수적 경로와36번 native 경로를 구분했다. provider나 적용 허가를 양성에서 강제하지 않았다.

이 후보는 아직 제품에 적용하지 않았다. 별도 독립 schema/guard53/53도 통과했다. 표 흐름 v5와 합친 새 v6는 정적64·XML34·root 독립42를 통과했고 실제 결합 검증이 남는다. 현재 app199의 알려진33번 차이를 후보 통과로 덮어 쓰지 않는다. 근거는 후보의 `static-report.json`, `actual-q33/report.json`, `actual-emitters-q36/report.json`, `native-gap-baseline-scalar-independent-r/HANDOFF.json`이다.
