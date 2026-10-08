# 공개 편집의 TAB·서식 보존 — 2026-10-09

기본 변환에서 사용하는 공개 편집 API 두 파일을 제품에 반영했다. 같은 텍스트 재대입은 원래 run·글자 서식·TAB·줄 cache를 유지한다. 실제 교체나 새 run의 리터럴 TAB은 명시적 LEFT(type 1)/leader 0으로 만들며, 새 run의 줄바꿈도 native 제어문자로 표현한다. TAB 폭은 현재 글자 폭과 가용 폭으로 계산한다. 임의의 기존 TAB 속성을 정상화하거나 source 수정 자격을 주지 않는다.

## 변경과 검증 범위

- `app/_vendor/hwpx/oxml/_document_impl.py`: `459dca9d…` → `ed284718…`. 공통 리터럴 TAB 생성, run/문단의 정확한 같은 값 재대입, 새 run의 제어문자 생성 경로를 수정했다.
- `app/_vendor/hwpx/tools/native_line_metrics.py`: `e0172040…` → `0348e4d8…`. 지원 TAB 수를 8→16으로 확장했다. UTF16·스타일·실제 가용 폭·연산 예산·부분 변경 없는 복귀 조건은 그대로다.
- native renderer, cache `589da0bf…`, question reflow `d32d9eae…`, 답란 source 판정 `06517609…`는 변경하지 않았다.

후보의 집중 검사 69개, 기존 시 지문·문단 계약·실제 17번 TAB 편집 회귀 3종이 통과했다. 별도 독립 검사에서는 실제 고3 출력의 **45문항 전체**에 같은 값을 재대입해 XML·모든 실제 SVG가 같았다. lxml/stdlib XML의 혼합 tail·legacy TAB·객체·Unicode·줄바꿈과 실제 11TAB 문단의 텍스트 교체·보유 run 객체·재열기·재저장도 확인했다.

제품 반영은 원래 vendor 85파일과 후보 해시를 비교한 뒤 두 파일만 교체했다. 원래 파일과 전체 app 해시는 `tmp/september-audit/native-public-tab-control-product-transition/`에 보존했다. 다른 app 파일이 바뀌지 않았음을 확인했다.

반영 후 실제 제품 import 경로로 독립 3,138개 검사가 통과했다. 이 수에는 45문항의 문단/run별 노드 동일성 검사가 포함되며, 서로 다른 3,138개 사용자 시나리오를 뜻하지 않는다. 기존 실제 J 출력의 40번 밑줄 답란 공개 편집도 새 제품 경로에서 20/20 통과했다. 이 결과는 후보의 overlay 검사와 별개다.

## 남은 범위

이 수정은 PDF에서 선택지 fragment 간격을 자동 복원하는 기능의 제품 적용을 뜻하지 않는다. 실제 11TAB 기술 실험에서 원문 복귀 후 X는 같지만 후속 36글자의 Y가 1HWPUNIT(0.013333px) 다르다. 긴 편집 뒤 원문 복귀 시 페이지 수가 돌아오지 않는 문제도 남는다. 새 실제 제품 재현에서 자동 생성 page/column 나눔이 다음 저장의 original slot 하한이 되는 원인을 확인했다. 표 높이와 대상 cache는 정상 복귀하므로 이번 직접 원인은 일반 나눔 이력 관리다. `tmp/september-audit/public-overflow-revert-independent/HANDOFF.json`에 8→9→9→9와 실제 여유 1,733 HWPUNIT를 보존했다. source 전체 owner·현재 paint·폰트·표 흐름의 수정 자격도 남는다.

새 제품의 실제 L 영어 3종 검사를 완료했다. 모두 HTTP 200·8쪽·45문항, 원문/native 텍스트 보존 1.0, 독립 열기·편집 구조·렌더 통과이며 모든 실제 SVG가 K와 같다. 제품 snapshot `d8432136…`와 renderer `33ab6b67…`는 STABLE이다. 전체 페이지 품질 6개는 여전히 미달이며 나머지 48종은 재실행하지 않았다. 전체 품질 문턱은 변경하지 않는다. 현재 51종 전체의 최신 제품 재검사와 실제 Mac 운영은 완료로 주장하지 않는다. 실제 검증 완료 상태는 `tmp/september-audit/native-public-tab-control-product-verification.json`, L 근거는 `basic-english-l-question-priority-checkpoint.json`에 있다.

## 증거

- 후보 불변 자료: `tmp/september-audit/native-public-tab-control-candidate-v3/{manifest.json,HANDOFF.json,public-controls-opt1/report.json,tab-edit-regression/report.json}`. v1/v2 자료도 보존했다.
- 독립 후보: `tmp/september-audit/native-public-tab-control-independent-v3/report.json`.
- 독립 실제 제품: `tmp/september-audit/native-public-tab-control-product-independent/report.json`.
- 새 제품의 실제 40번 공개 편집: `tmp/september-audit/native-public-tab-control-product-q40/public/report.json`.
- 이전 원인·실패와 엄격한 경계 검증: [11TAB 기술 기록](native-tab-count16-tmp-20261009.md). root 최초 검사 도구의 UTF16 예상값 오류도 별도 보존했다. retained equation의 8unit을 누락한 검사 오류였으며 후보 파일은 수정하지 않았다.
