# 고2 9월 영어 Q27 원본 안내문과 편집 흐름

활성 범위는 기본 PDF 원본 배치의 native HWPX 변환이다. 프리미엄 양식과 문항 순서는 이 변경의 대상이 아니다.

## 원본 근거와 native 구조

`data/external_exam_qa/2026_september_high2/english.pdf`의 실제 4쪽 Q27은 4개 외곽선 안에 18개 인쇄행과 나무 그림 1개가 있다. 소개 글 마지막 행의 세로 영역은 그림의 위쪽과 겹치지만 실제 글자는 그림 왼쪽에 있다. 이 소개 글 4행을 한 의미 문단으로 보존하고, 같은 문단이 그림을 소유하는 native SQUARE wrap으로 복원했다. 나머지는 실제 제목·항목·이어지는 줄의 의미 경계로만 나눈다.

전체 원문, raw glyph geometry, 실제 외곽선, 그림 픽셀 및 교차 관계를 다시 입증한 경우에만 한 셀의 원본 프레임을 생성한다. source column 안에 있는 실제 외곽선의 폭을 해당 문항에만 반영한다. 일반 문항/수학의 object 400 예약과 grow-only 표 동작은 유지한다. 원문 본문 이미지를 만들지 않는다.

원본 외곽선은 `(431.6480, 213.5070, 755.1740, 526.2100)`pt이며, 원본 오른쪽 단의 x 범위 `(429.4800, 755.7170)`pt 안에 있다. 기존 native column 폭보다 조금 넓은 문항 폭은 이 완전한 외곽선과 좌측 inset을 함께 측정해 해당 Q27 wrapper에만 적용한다. 반대 단의 실제 글자 및 인쇄 영역과 충돌하지 않는 것도 확인한다. 전체 column 폭이나 허용 오차를 늘리지 않는다.

모든 source cache 행은 원본 PDF의 해당 행과 UTF-16 slice를 대조한다. 그림의 8-unit 제어 위치와 첫 offset 0, 문자 경계, 실제 마스크, baseline/descender, 점유 높이를 확인한다. 단어 내부로 바뀐 행 경계나 여러 행을 삭제해서 넘치는 slice는 복원을 거절한다. 복원할 행의 폭은 지원되는 Haansoft Batang의 bundled glyph advance와 현재 장평/자간, native 정렬의 압축 하한으로 독립 검증한다. 지원하지 않는 글꼴/문자는 일반 편집 재계산으로 돌아간다.

## 정확한 원문 복귀

Writer가 실제 PDF/native 증명을 통과한 셀에서만 원래 캐시를 저장한다. 그 셀의 원문·resolved style·폭·패딩·그림이 정확히 돌아왔을 때 캐시를 재사용한다. 저장 SHA는 손상 검출용이며 원본 출처를 증명하지 않는다. namespace 선언의 차이는 의미가 같으므로 exclusive C14N으로 비교한다. 다른 셀에는 각자 소유한 캐시를 유지한다.

실제 public save 경로는 표를 deepcopy하면서 쓰지 않는 ancestor namespace 선언을 제거한다. 초기 inclusive C14N은 이 차이를 그림 또는 style 변경으로 오인해 원문 복귀 캐시를 거절했다. 그림·resolved style·font faces의 의미 있는 속성과 자식은 비교하면서 namespace 선언만 정규화했고, public open → 빈 run 추가 → staged table copy에서도 기존 캐시를 그대로 복원하는 별도 검사를 통과했다.

쪽 나누기 bookkeeping은 top-level paragraph ID/순서와 원래 break, 마지막 자동 break를 확인한다. 사용자가 바꾼 값은 보존하고, generic/math dirty 또는 잘못된 상태에서는 기존 동작으로 돌아간다. 유효한 v2 wrapped context에서 다음 문항과 기존 간격이 빈 단에 들어가면 그 native 간격을 버리지 않는다. 너무 큰 간격이나 일반 문항은 기존 소비 정책을 유지한다. 원문 수치를 빼거나 고정 y offset을 적용하지 않는다.

초기 실패에서는 내용 증가로 Q28이 다음 쪽에 갈 때 기존 단 시작 간격이 소비되어, 내용을 삭제해도 원본의 1466HWP 간격이 돌아오지 않았다. 수정은 이 수치를 저장하거나 더하지 않는다. 증명된 v2 편집 문맥이고 `question + before <= empty-column capacity`인 경우 현재 native before를 보존하므로 사용자가 정한 값도 유지된다. v1/bare marker/잘못된 상태와 일반·수학 편집은 기존 간격 소비 경로를 사용한다.

실제 public API로 소개 글에 4문장을 추가한 뒤 저장·재열기하고, 추가한 run을 비워 다시 저장·재열기한 결과:

| 상태 | 쪽수 | Q27 높이(HWP) | Q28 시작(page index, x, baseline px) |
|---|---:|---:|---|
| 원본 | 8 | 33186 | 3, 405.333333, 612.24 |
| 내용 증가 | 9 | 42644 | 4, 82.906667, 189.306667 |
| 추가 내용 삭제 | 8 | 33186 | 3, 405.333333, 612.24 |

최신 fresh 증거: `tmp/september-exam-matrix/q27-final7-fast/report.json`. 9쪽으로의 정상 성장은 원본 8쪽 보존 실패와 구별한다. 입력은 `q27-product-final7/high2-native.hwpx`, SHA256 `1779adad6b50702e02c6d2c79ed6a963b98dbe43d33f1f379333a516d1d7b5e3`이다.

실제 source raw glyph의 여러 내부 공백이 마지막 행보다 일관되게 넓어진 다행 의미 문단에 한해 JUSTIFY와 source의 마지막 nonspace ink로 측정한 오른쪽 여백을 복원한다. 특정 항목명이나 문자열로 선택하지 않는다. source 전체 frame·raw spans·font/size·연속 행을 다시 대조하는 `pdf_source_justification.py`가 근거를 반환한 경우에만 native style clone에 반영한다. 이 연결 뒤에도 위 편집 원복 수치가 같다.

최신 final7의 실제 Registration 문단은 JUSTIFY/right254, 2개 인쇄행을 가진 1개 의미 문단이다. 첫 줄 끝 오차는 +0.699px, 전체 glyph 최대 오차는 1.208px이고, 이어지는 줄 끝은 +0.677px/최대 0.782px다. 처음 줄 시작은 원본 대비 −0.003px이다. 전체 14개 의미 문단과 원문을 보존했다. 독립 helper의 metadata negative 29개와 실제 PDF synthetic 7종도 통과했으나, 이 수치는 0.6px 전체 glyph 오차 기준의 완전 성공을 뜻하지 않는다. 증거는 `tmp/september-exam-matrix/source-justification/report.json`이다.

## 독립 검사와 남은 오차

`verify_native_wrapped_frame_guards.py`는 실제 source proof 및 35개 보호 검사를 통과했다. 별도 `verify_wrapped_source_cache_state.py`는 실제 public-open/staged-table copy를 포함한 6개 positive와 내부 checksum까지 다시 계산한 27개 negative를 통과했다. `verify_wrapped_flow_break_state.py`의 29개 검사는 별도 독립 결과다. 이 단위 결과만으로 전체 렌더의 성공을 주장하지 않는다.

`verify_wrapped_pagination_gaps.py`의 실제 public save/reopen 11개 경계 검사는 v2만의 간격 보존, 빈 단 capacity와 정확히 같음/1HWP 초과, v1/bare/잘못된 digest/generic/math fallback, 수동 간격 0/2048 및 page/column break, 두 번째 저장의 section XML 동일성을 확인했다. root의 최종 전체 source/render/API oracle은 이 부분 결과와 구분한다.

최초 full oracle에서 발견한 본문 glyph 폭, 저장 후 namespace 차이, 삭제 뒤 간격 소실은 각각 실제 실패 기록을 남긴 뒤 수정했다. 수평 effective cache 폭은 native 여백·들여쓰기를 한 번만 빼도록 producer, source predicate, 편집 재계산, 캐시 검사를 일치시켰다. 임시 A/B에서 소개 첫 줄 끝 오차는 14.235px에서 0.661px로 줄었다.

좁은 wrapped 경로에서 cache `horzsize`는 그림 exclusion으로 남은 폭에서 해당 행의 native left/indent/right를 한 번 뺀 effective text width다. 편집 재계산과 snapshot 검증은 여기에서 여백을 다시 빼지 않는다. 일반 native cache의 폭 의미는 바꾸지 않는다. 원본 수평 장평·자간을 복원하는 callback도 기존 의미 문단의 run height를 유지한다. 장평 복원과 함께 source span 높이까지 세분화하면 renderer line correction이 여러 항목에 +4/+8/+12px로 누적되는 것을 A/B에서 확인했기 때문이다.

일부 짧은 LEFT 항목의 단어 간격은 여전히 원본과 다르다. 원본 Haansoft Batang의 space advance는 약 1/3em이지만 현재 renderer는 ASCII space를 1/2em으로 취급한다. 원본의 보이는 U+00AD soft hyphen은 literal text에 유지하며 실제 paint 여부를 별도로 확인한다. SVG의 좌표·family와 PDF paint가 선택한 font face는 서로 다른 증거이므로 한쪽 성공을 다른 쪽 성공으로 집계하지 않는다. 아래 구조·경계·편집 복구 PASS는 모든 glyph origin의 원본 오차가 사라졌다는 뜻이나 전체 제품 품질 목표 달성을 뜻하지 않는다.

## 최종 독립 실물 판정

`tmp/september-exam-matrix/q27-final7-independent/report.json`의 전체 독립 oracle은 **PASS**다. source PDF, 입력 HWPX, 검사 코드, nativecell3 runtime의 검사 전후 SHA가 같으며 변경된 코드 파일은 없다. 실제 원본 18행과 4개 외곽선, 나무 그림 픽셀/표시 영역 및 Q28 절대 위치를 확인했다. 초기와 내용 삭제 후 각각 일반 PDF glyph 658개, 내용 증가 후 942개를 검사했고 인쇄 영역 초과와 그림 겹침이 없다. public append → save → fresh reopen → delete → save → reopen에서 **8→9→8쪽**, Q27 높이와 Q28 위치의 정확한 원복을 확인했다.

이 PASS의 범위는 Q27 원본 프레임의 native 구조·흐름·가시 경계 및 편집 복구다. 문서의 개별 glyph 수평 잔차, ASCII 공백 폭, soft hyphen의 별도 painting 판정과 전체 영어 시험지의 품질 점수는 각각 남은 증거 및 다른 gate로 유지한다.
