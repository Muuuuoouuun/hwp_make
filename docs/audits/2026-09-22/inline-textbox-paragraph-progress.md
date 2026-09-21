# 중첩 글상자 복원·문단 편집 재평가

후속 개발과 최신 결과는 [반복 머리말·선지·문단 편집 평가](running-header-and-choice-progress.md)를 따른다. 아래 결과는 이전 소스 스냅샷이다.

**누락되던 빈칸 8개를 실제 편집 가능한 글상자로 복원했다. 36쪽 엄격 배치 평균은 82.54 → 82.56이며, 93점 목표와 완성본 판정에는 미달한다.** 문단·빈칸·수식의 수정과 재저장, 실제 표시, 원본과의 대응을 함께 검사했다. 이번 변경의 핵심은 보존 오류 해결이며 점수 상승 폭은 0.02점이다.

## 5분야 평가

| 분야 | 판정 | 실제 근거 |
| --- | --- | --- |
| 품질 | 목표 미달 | 국어 84.00, 수학 79.18, 영어 84.75. 36쪽 가중 배치 평균 82.56. 수학 5쪽 68.00 → 68.85 |
| 정확도 | 검사 범위 통과 | 문항 소속 120개, 문단 연결 634쌍, 국어 단어 경계 330개, 원본 비트맵 82개 보존. 원본 빈칸 8개와 네이티브 8개·실제 표시 8개 대응 |
| 편집성 | 검사 범위 통과 | 수학 14번의 인쇄 20줄을 13개 의미 문단으로 유지. 문단 +162자, 라벨 `(가)→(라)`, 재저장 후에도 빈칸 8개·수식 191개·12쪽 유지 |
| 안정성 | 부분 통과 | 전체 109개: 96 통과·11 생략·2 실패. 출력·편집 패키지 19개 오류·경고 0. 실제 API 다운로드 패키지도 유효 |
| 성능 | 측정 | 국어 27.488초, 수학 5.058초, 영어 16.234초. 로컬 1회·회귀 검사 동시 실행이므로 통제된 성능 비교는 아님 |

82.56는 다섯 분야 종합 점수나 정확도가 아닌, 페이지 수로 가중한 엄격 배치 지표다. 국어 16쪽·수학 12쪽·영어 8쪽이며 쪽수 변화는 없다. 최저 점수는 각각 74.27·68.85·72.37이다. 평가 임계값은 낮추지 않았다. 31쪽은 이전 결과와 픽셀이 동일하다. 수학 5쪽 외 나머지 4쪽은 1~4개 픽셀만 달라졌고 점수는 동일하다.

[36쪽 결과](../../../data/verification/20260922_goal_inline_frames_final/report.json) · [전체 109개 회귀](../../../data/verification/20260922_inline_frames_final_full/report.json) · [쪽별 비교](../../../data/verification/20260922_goal_inline_frames_final/page_pixel_comparison.json) · [평가 요약 JSON](../../../data/verification/20260922_goal_inline_frames_final/assessment_summary.json)

## 실제 변경

원본의 작은 닫힌 직사각형과 내부 글자·크기·위치를 읽어, 원문 전체와 대응하는 구간에 인라인 `hp:rect/hp:drawText`를 넣는다. 기존 문단 안의 개체이며 인쇄 줄마다 새 문단을 만들지 않는다. 수식 내부의 지수·함수 인자·분수 인자는 쪼개지 않고, 복원 가능한 최상위 항만 처리한다. 원문 불일치·잘못된 위치·중복 소유 구간은 스타일이나 본문을 바꾸기 전에 거부한다.

문서 생성만으로는 충분하지 않았다. 기존 렌더러는 ‘문항 글상자 → 풀이 표 → 빈칸 글상자’에서 도형을 그리지 않았고, 수식과 빈칸만 있는 줄은 위치도 등록하지 않았다. 해당 렌더 경로를 고치고 개체 폭을 반영했다. 줄 높이를 글자 높이로 줄여 다음 문단과 겹치는 문제와, PNG에서 내부 U+FFFC 개체 표시 문자를 글리프로 그리는 문제도 수정했다. 최종 PNG를 원본과 직접 비교했으며, 글꼴·머리말·절대 배치는 여전히 다르다.

[수학 5쪽 원본](../../../data/verification/20260922_goal_inline_frames_final/math/renders/source_page_005.png) · [수정 HWPX 출력](../../../data/verification/20260922_goal_inline_frames_final/math/renders/output_page_005.png)

## 편집·재저장 검증

- 두 줄짜리 설명 한 문단에 162자를 추가한 뒤 표 높이는 28,611 → 40,090 HWPUNIT로 늘었다. 인쇄 20줄을 13문단으로 유지하는 초기 구조, 편집 후 13문단, 수식 191개, 12쪽, 빈칸 8개를 검사했다. 새 문장이 실제로 보이며 재저장 후에도 유지된다. 첫 `(나)` 박스와 다음 문단의 겹침도 검사한다.
- 실제 수학 파일의 첫 `(가)`를 `(라)`로 바꿨다. 글상자의 위치·크기는 유지되고, 라벨 줄 폭은 바깥 표의 폭을 빌리지 않고 자신의 3,810 HWPUNIT를 사용한다. 원본·편집·재저장 결과 모두 8개 프레임이 표시된다.
- 국어·수학·영어 본문 각각 +155자, 국어 병합 셀 +155자, 수학 그림 앞 문단 +197자 편집을 확인했다. 마지막 검사에서 그림은 140.827px 아래로 이동하고 모든 수식·이미지·쪽수는 유지됐다.

[문단 +162자](../../../data/verification/20260922_goal_inline_frames_final/math/edit_mixed_table/report.json) · [실물 라벨 교체](../../../data/verification/20260922_goal_inline_frames_final/math/edit_inline_label/report.json) · [라벨 재저장 화면](../../../data/verification/20260922_goal_inline_frames_final/math/edit_inline_label/label_resaved_page5.png) · [중첩 글상자 회귀](../../../data/verification/20260922_goal_inline_frames_final/nested_textbox_editing/report.json) · [그림 편집·절대 위치](../../../data/verification/20260922_goal_inline_frames_final/real_diagram_source_and_edit_evidence.json)

## 잘못된 결과는 계속 차단

테두리 없이 같은 글자만 있거나, 크기·개수·투명도·클립·실제 내부 표시가 다르면 통과하지 않는다. 원본/문서/표시 손상 18종, 새 복원기의 거부 사례 13종과 정상 6종을 검사했다. 내부 개체 문자의 불필요한 잉크 검사도 수정 전 실패, 수정 후 통과를 확인했다.

실제 수학 PDF의 API 변환과 다운로드는 HTTP 200이며 반환한 HWPX를 다시 패키지 검사했다. 반대로 변환 직후 테두리 하나를 투명하게 바꾸면, 정상 생성 통계와 `source-inline-label` 이름이 그대로 있어도 `structured`와 `coordinate` 양쪽 요청은 HTTP 422로 거부한다. 이는 품질 목표 달성과 별개의 원본 보존·표시 관문이다. API 응답의 엄격 품질 점수도 79.18이며 목표 미달로 표시된다.

[API 실제 성공](../../../data/verification/20260922_goal_inline_frames_final/api_real_math/response.json) · [다운로드 검증](../../../data/verification/20260922_goal_inline_frames_final/api_real_math/download_validation.json) · [structured 손상 거부](../../../data/verification/20260922_goal_inline_frames_final/api_corrupt_frame/structured.json) · [coordinate 손상 거부](../../../data/verification/20260922_goal_inline_frames_final/api_corrupt_frame/coordinate.json) · [라벨 독립 검증](../../../data/verification/20260922_goal_inline_frames_final/inline_label_audit/report.json)

## 남은 실패와 검증 한계

전체 회귀의 실패 2개는 정밀 배치 기준(평균 97·최저 95·원시 전경 일치 97%)과 선지 위치 오차 7.89px(허용 6px)다. 생략 11개는 통과로 계산하지 않았다. 수학 그림 4·7·11쪽의 절대 세로 위치 오차 +2.8783·−1.9399·+15.6557px도 남아 있다. 글꼴·수식/선지 간격·테두리·머리말/꼬리말 복원은 계속 개선해야 한다.

원본 그림 안 문자 라벨의 개별 편집, 기존 4종 HWPX의 미주·정답 소속 가져오기, 실제 한컴 GUI에서 직접 입력·저장은 완료되지 않았다. 이번 편집 검증은 공개 문서 API를 통한 수정·저장과 독립 렌더 확인이다. 창 활성화 오류 이후 GUI 검증을 새로 수행하지 않았다. 21과목 168쪽 전체를 이번 소스로 다시 평가하지도 않았다.

## 재현성·런타임

Windows x64용 **프로젝트 수정 빌드 `rhwp-python 0.7.0+nativeinline1` / core 0.7.13**을 실제 실행 환경과 의존성 파일에 반영했다. 공식 배포판과 구분하며 다른 운영체제의 새 빌드는 검증하지 않았다. 고정된 상류 소스 커밋, Rust 패치 3개 파일, 바인딩 Cargo 설정, lock, 라이선스, wheel 해시와 재빌드 절차를 [렌더러 패키지](../../../packaging/renderer/README.md)에 보존했다. 설치된 바이너리가 이 wheel과 일치하는지도 확인했다.

최종 Python 소스는 이전 검증본 대비 13개 파일이 달라졌으며, 전체 검사 후 추가·삭제 포함 소스 차이는 0개다. [Python 소스 압축본](../../../data/verification/20260922_goal_inline_frames_final/tested_python_sources.zip) · [소스 해시](../../../data/verification/20260922_goal_inline_frames_final/source_hashes.json) · [검사 후 차이](../../../data/verification/20260922_goal_inline_frames_final/source_differences_final.json) · [렌더러 묶음](../../../data/verification/20260922_goal_inline_frames_final/renderer_bundle.zip) · [설치 바이너리 검증](../../../data/verification/20260922_goal_inline_frames_final/installed_renderer_check.json) · [19개 패키지 검사](../../../data/verification/20260922_goal_inline_frames_final/native_package_validation.json)

[국어 HWPX](../../../data/verification/20260922_goal_inline_frames_final/korean/korean.hwpx) · [수학 HWPX](../../../data/verification/20260922_goal_inline_frames_final/math/math.hwpx) · [영어 HWPX](../../../data/verification/20260922_goal_inline_frames_final/english/english.hwpx)

다음 우선순위는 선지 위치 오차, 머리말·꼬리말과 절대 배치, 글꼴·수식 간격이다. 현재 결과를 93점 또는 완성본으로 표시하지 않는다.
