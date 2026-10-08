# 편지 서명 줄과 편집 후 마지막 줄 간격 — 제품 연결

기존 생성은 편지의 맺음말·이름·직책을 공백으로 합쳐 한 문단에 넣었다. 제품은 실제 source의 `Dear …,` 또는 `To whom it may concern,` 인사말과 마지막3행의 맺음말을 확인한 편지에서 맺음말과 이후 physical row를 각각 편집 가능한 문단으로 유지한다. 특정 시험지·문항번호·이름으로 분기하지 않는다.

고3의 원본으로 완전히 입증된 frame 마지막 한 줄은 cache spacing0인데 문단 서식은 PERCENT120이었다. 새 문단을 편집하면172 HWPUNIT이 추가되는 문제가 드러났다. 현재 최종 문단 서식을 고유 ID로 복제해 지원되는 두 PERCENT branch만100으로 바꾸고 모든 여백·들여쓰기·다른 속성을 유지한다. 늦은 callback의 stale ID map을 사용하지 않으며 content height 계산 전에 현재 스타일 map을 갱신한다. 완전한 frame·마지막 source 한 행·단일cache·지원되는 현재 서식 조건이 없으면 이 수정은 적용하지 않는다.

제품 변경은 `pdf_native_content.py` `245e3a56…`, `pdf_table_paragraphs.py` `fecd0504…` 두 파일이다. 직전 일반 페이지복귀 제품의198파일 중 이 둘만 바뀌었다. 백업과 전후 해시는 `tmp/september-audit/letter-closing-v3b-product-transition/report.json`에 있다. 초기 v3는 stale style map과 숫자 범위 문제를 확인해 중단했고 입력·로그·부분 결과를 보존했다. 수정한 새 v3b만 제품에 반영했다.

검증 범위:

- 수정 후보의 실제 영어3종 API: 모두 HTTP200·8쪽·45문항·원문/native 텍스트1.0·독립 열기/편집구조/렌더 통과. 전체 품질6개는 모두 미달이다.
- 생성/world28·직접guard35·무편집7과 별도 독립80개 유효 검사가 통과했다. 독립 초기 hp:t 변경 후 identity 및 XML unused namespace 비교의 잘못된 기대는 실패 자료를 보존하고 별도 수정 검사로 구분했다.
- 실제24페이지 PNG의 해당문항 밖 픽셀은 모두 같고 다른44문항의 world glyph도 같다. 고3의 생성 초기 전체SVG는 직전245 후보와 같다.
- 실제 제품 기본 import 경로의 공개 편집16개가 통과했다. 고3 반복 편집·같은값 대입·재열기/재저장·원문 복귀에서 셀16616·마지막spacing0·다른27,149 world glyph가 유지된다. rootH의 새 제품 고1·고2·고3 영어는 모두 후보와 45문항 텍스트·모든8SVG/world 및 저장된 전체 header XML이 정확히 같다. 실제 제품 독립 검사는 최종44/44로 종료했다.
- 전체51종·312쪽·1,355문항 H는 동일한 제품198/native snapshot에서 실행을 완료했다. HTTP200은11종, strict422는40종으로 이전 G 대비 변화가 없다. 영어3종은 기본 구조 통과·품질6개 미달이다. 실행 완료를 전체 품질 통과로 표현하지 않는다. 별도 `letter-closing-v3b-product-verification-v2.json`이 제품 연결의 명시된 검증 범위를 닫는다. 최초 기록의 pre-terminal 한계 문구를 그대로 복사한 불일치는 최초 기록을 보존하고 v2에서 정정했으며 실제 검사 결과는 같다.

**남은 한계:** 고2 같은서식 편집의 +1 HWPUNIT 및1387 downstream glyph Y +0.013333px는 원래 제품의 같은 동작과 동일하다. 기본폰트 add_run은 의도적으로 글자 크기와 셀 높이를 바꿀 수 있어 모든 공개 편집의 절대위치 불변을 주장하지 않는다. 고2 본문12source행→11native행, letter font hscale/tracking 및 서명 잔여X/Y는 해결하지 않았다. 고1 서명Y는 최대약5.17px, 고2 이름Y는 약28.03px다. 일반 implicit gap·혼합격자·Mac/Hancom·전체 품질도 별도 미완료다.

근거:

- `tmp/september-audit/letter-closing-physical-rows-independent-v3b/HANDOFF.json`
- `tmp/september-audit/letter-closing-r-independent-v3b/HANDOFF.json`
- `tmp/september-audit/letter-closing-v3b-product-integration-qualification.json`
- `tmp/september-audit/letter-closing-v3b-product-transition/report.json`
- `tmp/september-audit/letter-closing-v3b-product-independent/public-report.json`
- `tmp/september-audit/letter-closing-v3b-product-independent/HANDOFF.json`
- `tmp/september-audit/letter-closing-v3b-product-verification-v2.json`
- `tmp/september-audit/full51-question-priority-native5-h.json`
- `tmp/september-exam-matrix/all51-native5-20261009-h/report.json`
