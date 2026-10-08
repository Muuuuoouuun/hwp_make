# 선택지 내부 간격과 공개 편집 병목 — 2026-10-09

> 후속 상태: 이 문서는 제품 적용 전 TMP·실패 기록이다. 이후 공개 TAB·같은 값 재대입·16TAB 두 파일을 제품에 반영하고 L 영어 3종을 검증했다. [현재 제품 범위](native-public-tab-controls-20261009.md). 선택지 자동 복원·source Y·pagination 완료를 뜻하지 않는다.

기본 변환의 문항 본문·선택지에 한정한 기록이다. 프리미엄 양식, 순서 변경, 문항 밖 안내문·머릿말은 작업 범위에 넣지 않았다. 제품 파일은 이번 실험에서 변경하지 않았다.

## 11TAB 전체 문단 측정

현재 제품 `native_line_metrics.py`는 TAB 8개까지만 허용한다. 실제 고3 영어의 두 옵션 행은 fragment 위치를 보존하려면 TAB 11개가 필요하다. TMP 후보 `0348e4d8…`는 최대값만 16으로 확장하며 UTF16·현재 스타일·실제 가용 폭·실행 예산·부분 변경 없는 복귀 조건은 유지한다. 다른 84개 vendor 파일은 제품과 같다.

실제 J 출력 `0828e19a…`에서 45개 owner를 탐색해 선택지 9개 행을 구성했다. 11TAB 행 6개와 5TAB 행 3개 모두 **전체 문단**의 실제 native provider와 한 줄 계산이 통과했다. 공유 기본 예산은 1초/1,024 probe이며 실제 사용은 0.370103초, 274 probe, 4,239 prefix unit이다. prefix fixture를 조합한 과거 실험과 구분한다.

초기 가로 실험은 원래 세로 cache를 별도로 보존했다. 180개 대상 글자 외 27,601개 world glyph, 전체 글자의 Y, 8쪽과 전체 27,781개 표시 글자는 같았다. 이 cache 보존은 source 수정 권한이나 편집 지속성을 뜻하지 않는다. 원본 CID/CFF와 실제 native Batang의 윤곽 동등성도 입증하지 않았다.

독립 일반 경계 검사는 정상 Python 89/89, `-O` 89/89다. 0/17TAB 거부, 1/8/9/11/16TAB의 실제 native 위치, UTF16 경계, 스타일·글자·stop 불일치, 예산 초과와 중간 실패의 원자적 복귀를 확인했다. 이는 source 선택지 자동 복원이나 전체 시험지 품질 검사가 아니다.

별도 독립 실제 행·TAB 기본값 검사는 `-O` 63/63이다. 실제 9행을 같은 기본 예산으로 다시 계산해 cache/TAB 값이 같았고, 사용량은 274 probe/4,239 prefix unit/0.336898초다. 경계 검사와 실제 행 검사의 범위를 합쳐 전체 제품 품질 통과로 표현하지 않는다.

## 공개 편집에서 분리한 두 문제

실제 TMP vendor를 import한 공개 `run.text` 편집·저장·재열기 검사는 **40/47**이다. 실패 기록을 보존했다. 짧은 편집에서 11TAB과 원문·객체 참조·다른 44문항의 26,877개 world glyph·재저장 SVG는 유지된다. 그러나 바뀐 run의 TAB을 Python setter가 빈 속성으로 다시 만들기 때문에 현재 native 측정이 보수적으로 거부한다. 원문으로 되돌려도 대상과 후속 행의 59개 글자 위치가 다르며 최대 X 183.973px/Y 17.213px다.

별도 `run.replace_text` 공개 편집은 기존 TAB 노드를 보존한다. 이 경로는 실제 기본 native provider를 사용하며 원문 복귀 시 **모든 X가 같다**. 같은 문항의 후속 36글자 Y만 −0.013333px 차이가 난다. 원래 cache의 spacing 431이 현재 계산의 430으로 바뀌는 1HWPUNIT 차이다. 이 경로도 엄격한 전체 SVG 복귀 검사는 통과로 바꾸지 않았다.

두 경로 모두 100자 확장 시 여러 줄과 9쪽이 되고, 원문으로 되돌린 뒤에도 9쪽이 남는다. 확장에 따른 최초 페이지 이동 자체와 **원문 복귀 후 페이지 배치가 돌아오지 않는 문제**를 구분한다. source 전체 owner 흐름과 pagination 복귀 계약이 남아 있어 선택지 자동 복원은 제품에 적용하지 않았다.

TAB 속성 생략을 명시적 LEFT로 간주하는 방식으로 측정 조건을 풀지 않는다. 설치된 native의 parser에서 생략한 type은 0, 명시적 LEFT는 1이며 실제 표시 경로가 다르다. 공개 생성·교체 경로가 의도한 속성을 보존/생성하는 방향의 별도 수정 검증이 필요하다.

독립 실제 표시에서도 type 생략/명시적 1의 차이가 일반 문맥 최대 3.1413px였고 autoTabRight 문맥은 훨씬 컸다. `run.text = run.text`처럼 값이 같은 대입도 live TAB 속성을 재생성하면서 cache를 무효화하지 않는다는 별도 결함을 확인했다. 첫 저장은 원래 패키지를 사용해 같지만, 이어지는 실제 편집·저장에서 속성 누락과 보수적 두 줄 복귀가 드러난다. 즉시 디스크 표시가 손상된다는 초기 검사 가정은 틀렸으며 그 실패도 보존했다. 이 공개 setter는 현재 8TAB 제품과 TMP 후보에서 동일한 코드다.

## 다음 작업과 도움 필요 여부

1. 공개 TAB 생성·교체와 명시적 TAB 속성의 계약을 정리한다.
2. 원본 전체 문항·실제 font program·현재 native cache를 근거로 fragment 복원을 허용하고, 뒤 행 및 페이지 복귀를 검증한다.
3. 표 흐름은 원본 PDF를 담은 이동 가능한 재검증 시제품을 별도로 검증한다. 최소 공개 재열기 실험은 동작하지만 저장 한 번에 약 25초가 걸려 성능 개선과 실패 복귀 검증이 필요하다.

표 시제품의 완료된 두 저장에서 전체 24.32–24.91초 중 source/native 재검증이 12.09–12.44초, 전체 native 표시·PDF·잉크 검사가 10.85–10.92초다. 별도 15개 압축 크기·누락 part·manifest 검사 등은 원래 parts와 같은 보수적 복귀를 확인했다. 그러나 **현재 wrapper 폭을 바꾼 음성 사례의 거부가 실패**했다. source의 단 폭과 현재 wrapper를 독립적으로 결합하는 권한 검증이 아직 부족하므로, 정상 두 번의 공개 저장 성공이 제품 적용 자격을 부여하지 않는다. 이전 표 v2의 42/42 결과와 이번 새 portable adapter의 실패는 별도 기록이다.

Windows 구현을 계속하는 데 추가 사용자 자료나 결정은 필요하지 않다. Mac 운영 확정에는 실제 Mac의 변환·편집·재열기·렌더 결과가 필요하다. 이번 TMP 성공은 현재 K 영어 3종의 전체 품질 실패를 해소했다는 뜻이 아니다.

## 보존한 증거

- `tmp/september-audit/native-tab-count16-candidate/manifest.json`: 실제 85파일 overlay, 후보와 제품의 해시.
- 같은 경로의 `actual-nine-rows-report.json`, `actual-nine-rows-native.hwpx` (`45adcdc2…`): 실제 전체 11TAB/default provider와 초기 표시.
- 같은 경로의 `public/report.json`, `public-provider-diagnostic.json`, `public-flow-diagnostic.json`: setter와 실제 실패.
- 같은 경로의 `public-preserved-controls/report.json`, `public-preserved-controls-provider-diagnostic.json`, `public-preserved-controls-flow-diagnostic.json`: 원래 TAB을 보존하는 공개 편집과 잔여 흐름 오차.
- 같은 경로의 `public-binding-failure-diagnostic.json`: 초기 검사 도구가 nested paint 순서를 평문 순서로 가정해 실패한 기록. 이후 실제 `bind_native_owner`로 904글자와 wrapper 소속을 검증했다.
- 같은 경로의 `public-provider-passive-profile.json`: 관찰용 profile이며 시간·품질의 긍정 근거로 사용하지 않는다.
- `tmp/september-audit/native-tab-count16-independent/generic-{normal,opt1}/report.json`: 독립 경계 검사.
- 같은 경로의 `actual-and-defaults-opt1-v3/report.json`: 실제 9행·TAB 생략/default 의미·공개 setter의 두 단계 편집 검사. 초기 v1/v2 실패 자료는 별도로 보존했다.
- `tmp/september-audit/table-flow-portable-context/initial-qualified/report.json`: 이동 가능한 표 source context의 첫 최소 실험. 이후 검증과 구분한다.
