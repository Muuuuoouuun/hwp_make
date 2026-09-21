# 반복 머리말·선지 간격 개발과 5분야 재평가

> 후속 평가: [문단 텍스트박스·원본 틀 개발](paragraph-frame-progress.md). 최신 36쪽 배치 평균은 86.47이며 긴 문단 편집 실패와 12쪽 배치 하락을 포함해 다시 평가했다. 아래는 이전 소스의 86.15 스냅샷이다.

**36쪽 엄격 배치 평균 82.56 → 86.15. 93점 목표와 완성본 판정에는 미달한다.** 단일 줄마다 글상자를 만드는 방식으로 돌아가지 않았으며, 본문·표·중첩 글상자의 문단 편집 검사를 다시 실행했다.

| 분야 | 판정 | 이번 소스로 확인한 근거 |
| --- | --- | --- |
| 품질 | 목표 미달 | 국어 85.59, 수학 87.07, 영어 85.87. 가중 평균 86.15, 최저 페이지 73.64. 이전 대비 점수 하락 페이지 0 |
| 정확도 | 검사 범위 통과 | 문항 소속 120개, 문단 연결 634쌍, 원본 비트맵 82개 보존. 반복 머리말 33쪽에서 99개 필드의 실제 표시를 원문과 대조 |
| 편집성 | 검사 범위 통과 | 각 과목 본문 +155자, 수학 14번 문단 +162자, 중첩 라벨 교체, 그림 앞 문단 +197자, 반복 머리말 문단 수정·재저장. 수학 수식 191개와 12쪽 유지 |
| 안정성 | 부분 통과 | 전체 110개 중 98 통과·11 생략·1 실패. 출력·편집 패키지 25개 오류·경고 0. 실제 수학 API·다운로드 200, 머리말 누락 변조는 두 모드 모두 422 |
| 성능 | 측정 | 국어 27.006초, 수학 5.549초, 영어 17.418초. 로컬 1회·회귀 검사 동시 실행으로 통제된 속도 비교는 아님 |

86.15는 페이지 수로 가중한 **배치 지표**이며, 다섯 분야 종합 점수나 문자 정확도가 아니다. 쪽수는 16/12/8로 유지된다. 과목별 최저는 75.69/73.64/73.92다. 실제 수학 API의 별도 종합 규칙 점수는 83.5이며, 이 값도 목표에 미달한다. 평가 기준을 낮추지 않았다.

## 구현과 독립 검증

- 반복 머리말의 학년·과목명·쪽번호를 원본에서 각각 확인하고, 홀수·짝수 쪽마다 실제 네이티브 머리말 표의 문단으로 배치한다. 쪽번호는 여섯 개의 PAGE 자동 필드가 33쪽에 반복 표시된다. API의 한쪽 머리말 설정이 반대쪽 제어까지 삭제하던 문제도 수정했다.
- 학년 테두리는 원본 선분을 네이티브 다각형으로, 가로선은 원본의 실제 선 위치·두께를 측정해 네이티브 선으로 복원한다. 측정에 사용한 픽셀 이미지는 결과물에 넣지 않는다. 원본 머리말의 폰트가 식별되지 않는 경우는 남아 있어 글꼴까지 동일하다고 판정하지 않는다.
- 선지 문단의 네이티브 탭 위치는 보존하고, 실제 출력 글자·수식의 폭으로 탭의 저장 간격을 갱신한다. PDF 빈 공간만 복사하면서 생기던 누적 오차를 해결했다. 세 과목 44개 행을 측정했고, 별도 PDF 회귀의 최대 오차는 **7.89px → 0.1114px**로 기존 6px 기준을 통과한다. 같은 문단에 문장을 추가한 뒤에도 자동 줄바꿈·단 범위·탭 속성·재저장이 유지된다.
- 생성 통계를 신뢰하지 않고 원본 PDF와 출력 제어/XML·실제 SVG를 다시 대조한다. 고정 숫자를 반복한 파일, 학년을 흰색으로 숨긴 파일, 홀수 머리말을 삭제한 파일은 실패한다. 기존 과목명만 있는 머리말도 실패로 재현했다.

실물 수학 머리말만 바꾼 전후 **11쪽의 본문 픽셀이 완전히 동일**하다. 원본 학년 테두리의 전체 점 좌표 최대 오차는 0.1159px, 가로선은 0.0072px다. 머리말 문단을 `수학실험영역`으로 수정·재저장해도 본문·그림·수식·쪽수는 유지된다. 전체 변환 전후의 36쪽 중 1쪽은 픽셀 동일, 35쪽은 변경됐으며 배치 점수 하락은 없다.

[머리말·변조·편집 검증](../../../data/verification/20260922_goal_running_furniture/running_furniture/report.json) · [선지 실제 위치](../../../data/verification/20260922_goal_running_furniture/choice_tabs/report.json) · [페이지별 비교](../../../data/verification/20260922_goal_running_furniture/page_pixel_comparison.json)

## 문단 텍스트박스 재검증

수학 14번은 원본 인쇄 20줄을 13개 의미 문단으로 유지한다. 문단에 162자를 추가하면 표가 커지고 자동 줄바꿈이 갱신되며, 빈칸 8개와 수식 191개가 실제로 표시된다. 별도 `(가)→(라)` 교체·재저장에서도 라벨이 자신의 글상자 폭을 사용하고 위치·크기를 유지한다. 그림 앞 문단에 197자를 추가하면 그림이 140.827px 아래로 이동하며 같은 문단·수식·이미지·12쪽을 유지한다.

[본문·표 편집](../../../data/verification/20260922_goal_running_furniture/math/edit_mixed_table/report.json) · [라벨 편집](../../../data/verification/20260922_goal_running_furniture/math/edit_inline_label/report.json) · [그림 문단 편집·절대 위치](../../../data/verification/20260922_goal_running_furniture/real_diagram_source_and_edit_evidence.json)

## 실패와 미검증

전체 회귀의 남은 실패는 `verify_external_exam_detail_quality.py`다. 평균 97·최저 95·전경 정합 97% 등 기존 원본 배치 기준을 충족하지 못한다. 같은 실패 로그에는 수학 14번의 중첩 글상자를 거부하는 별도 구조 판정도 포함된다. `_verify_no_draw_text_equations()`의 전체 문항 상자 검사가 내부 `drawText`를 일괄 거부하고, 원본 빈칸·편집·표시 검사는 통과하는 상태다. 두 검사의 판정 불일치는 미해결로 남겼다. [실패 항목 전체](../../../data/verification/20260922_goal_running_furniture/remaining_regression_failures.json). 별도 실물 그림의 0.1px 절대 위치 검사도 실패하며, 수학 4·7·11쪽 세로 오차는 +2.8783/−1.9399/+15.6557px다.

화면 대조에서 **영어 2쪽 18번 지문 틀의 중복·변위와 첫 줄 겹침**을 확인했다. 이 영역은 이전 출력과 픽셀이 같아 이번 머리말·탭 변경으로 새로 생긴 문제는 아니지만, 여전히 실패다. 본문 텍스트 보존 검사 통과가 배치·가독성 전체 통과를 뜻하지 않는다.

[18번 원본](../../../data/verification/20260922_goal_running_furniture/english/question18_source.png) · [18번 현재 출력](../../../data/verification/20260922_goal_running_furniture/english/question18_output.png) · [남은 시각 오류](../../../data/verification/20260922_goal_running_furniture/known_visual_failures.json)

하단 쪽번호·대각선 틀, 첫 쪽 번호의 자동 필드화, 과목명과 본문 글꼴, 수식 간격·절대 배치는 남았다. 그림 속 문자 라벨 개별 편집, 공개 4종 HWPX의 미주·정답 소속 가져오기, 한컴 GUI 직접 입력·저장도 완료되지 않았다. 편집 증거는 프로그램의 공개 문단 API와 렌더 기준이며, 생략한 11개 검사를 통과로 계산하지 않는다. 21과목 168쪽은 이번 소스로 다시 평가하지 않았다.

## 증거와 결과물

[전체 36쪽 보고서](../../../data/verification/20260922_goal_running_furniture/report.json) · [전체 회귀](../../../data/verification/20260922_running_furniture_full/report.json) · [패키지 25개](../../../data/verification/20260922_goal_running_furniture/native_package_validation.json) · [실제 API](../../../data/verification/20260922_goal_running_furniture/api_real_math/response.json) · [다운로드 검증](../../../data/verification/20260922_goal_running_furniture/api_real_math/download_validation.json) · [structured 변조 차단](../../../data/verification/20260922_goal_running_furniture/api_corrupt_header/structured.json) · [coordinate 변조 차단](../../../data/verification/20260922_goal_running_furniture/api_corrupt_header/coordinate.json)

Python 소스 9개 파일이 이전 검증본과 달라졌다. 평가 소스를 고정하고 검사 후 추가·삭제까지 대조했으며 차이는 0개다. 이전에 고정한 Windows 렌더러 `0.7.0+nativeinline1` / core `0.7.13`을 그대로 사용했고, 설치된 바이너리와 보관 wheel의 일치를 다시 확인했다.

[소스 압축본](../../../data/verification/20260922_goal_running_furniture/tested_python_sources.zip) · [소스 해시](../../../data/verification/20260922_goal_running_furniture/source_hashes.json) · [검사 후 차이](../../../data/verification/20260922_goal_running_furniture/source_differences_final.json) · [렌더러 검증](../../../data/verification/20260922_goal_running_furniture/installed_renderer_check.json)

[국어 HWPX](../../../data/verification/20260922_goal_running_furniture/korean/korean.hwpx) · [수학 HWPX](../../../data/verification/20260922_goal_running_furniture/math/math.hwpx) · [영어 HWPX](../../../data/verification/20260922_goal_running_furniture/english/english.hwpx)
