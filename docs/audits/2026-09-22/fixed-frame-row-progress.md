# 긴 문단 편집 개발과 5분야 재평가

> 후속 결과는 [본문 대조·기준선 수정과 5분야 평가](body-scope-baseline-progress.md)에 기록했다. 비교 코드 오류를 수정하고 배치 평균을 87.31로 개선했다. 아래는 당시 소스의 결과로 보존한다.

**문단을 길게 편집하면 제목 장식이 본문과 겹치던 문제를 수정했다. 36쪽 엄격 배치 평균은 86.47로 유지되며, 93점 목표는 아직 달성하지 못했다.** 영어 지문의 본문 10줄은 실제 한 문단이다. 여기에 316·474·790자를 추가한 뒤 저장·재열기해도 문단 구조, 장식 두께, 뒤 선택지의 비겹침을 유지한다.

| 분야 | 판정 | 이번 소스로 확인한 근거 |
| --- | --- | --- |
| 품질 | 목표 미달 | 국어 85.92, 수학 86.66, 영어 87.28. 36쪽 가중 평균 **86.47**, 최저 73.56. 이번 변경으로 점수가 오른 쪽이나 내려간 쪽은 없음 |
| 정확도 | 검사 범위 통과·비교 코드 오류 발견 | 문항 120개, 문단 연결 634쌍, 원본 비트맵 82개 대조. 국어 27자 불일치는 실제 누락이 아닌 머리말 혼입으로 확인했으나 비교 코드는 아직 미수정 |
| 편집성 | 개선·부분 통과 | 본문 한 문단 유지, +158·316·474·790자 편집·재저장 통과. 원본 장식의 위·아래 행 높이 고정. 실제 한컴 GUI 편집은 미검증 |
| 안정성 | 부분 통과 | 전체 회귀 **99 통과·11 생략·1 실패**. 정상 출력·편집 패키지 **32개** 유효. 실제 API 변환·다운로드 200, 장식 행 변조는 두 모드 모두 422 |
| 성능 | 측정 | 국어 27.054초, 수학 5.502초, 영어 19.982초, 합계 **52.538초**. 다른 검사와 동시 실행한 로컬 1회 측정이며 성능 개선 판정은 하지 않음 |

86.47은 원본 PDF와 실제 렌더 결과의 페이지 가중 **배치 지표**다. 문자 정확도나 다섯 분야 종합 점수가 아니다. 이번 범위는 2026년 6월 고1 국어·수학·영어 36쪽이다. 21과목 168쪽 전체를 이 소스로 재평가한 결과는 없다. 11개 생략도 통과에 포함하지 않는다.

[기계 판독 요약](../../../data/verification/20260922_goal_fixed_frame_rows/assessment_summary.json) · [36쪽 원본 대조](../../../data/verification/20260922_goal_fixed_frame_rows/report.json) · [이전 평가](paragraph-frame-progress.md)

## 한 문단 편집과 장식 행

이전에는 영어 18번의 배경 전체를 표 높이에 맞춰 늘렸다. 본문에 474자를 추가하면 제목 막대도 두꺼워져 인사말과 겹쳤다. 이제 원본에 실제로 존재하는 장식 비트맵의 일정한 중간 띠를 확인한 뒤, 한 개의 네이티브 표를 위 장식·본문·아래 장식의 3개 행으로 구성한다. 위·아래 높이는 **990·672 HWP 단위**이고 본문 행만 자란다.

각 행의 배경은 원본 장식 자산에서 가져온다. 원본 PDF의 본문 글자를 이미지로 만들지 않는다. 위·아래 셀은 빈 문단이고, 가운데 셀의 인사말·본문·서명은 기존의 **3개 의미 문단**을 그대로 유지한다. 원본 인쇄 13줄 중 본문 10줄이 같은 `hp:p`에 들어가며, 줄별 글상자·줄별 문단·강제 줄바꿈을 추가하지 않는다.

적용 조건은 실제 자산·원문·영역이 대응하는 완전한 단일 셀 틀이다. 원본 중간 띠가 일정하고 장식 행이 기존 여백 안에 들어가야 한다. 이번 자료에서는 영어 1개 틀이 해당하며, 공유 배경·부분 틀은 변형하지 않는다. 글상자 안의 표 셀 배경 이미지가 렌더에서 빠지던 경로도 수정했다.

- 초기 틀 위치 최대 오차 **0.0269px**, 줄 시작점·기준선 최대 오차 **0.0552px**로 기존 0.1px 기준을 통과한다. 글꼴 모양까지 같다는 뜻은 아니다.
- 실제 장식 조각 3개가 이음새·중복 없이 하나의 틀을 이룬다. 원본 비트맵 대조와 화면 표시를 모두 검사한다.
- +158자 편집에서는 표 높이가 16,802 → 24,508 HWP 단위로 증가하며 뒤 선택지가 이동한다.
- **+316·474·790자** 각각 편집과 재저장을 검사했다. 같은 3개 의미 문단, 고정 장식 높이, 본문·서명·뒤 선택지의 비겹침과 실제 텍스트 표시를 유지한다. +790자 결과 PNG도 직접 확인했다.
- 기존 위치·중복·줄 분절 변조에 **장식 높이 변경·행 순서 교환·장식 누락**을 더한 9개 부정 사례를 거부한다. 별도 비트맵 소유권 5개 사례와 부분 틀 무변경 거부도 통과한다.
- 셀 배경 자산이 패키지 안에 남아 있어도 표를 화면 밖으로 옮기면 실제 표시 검사가 실패한다.

[문단·장식 편집 검사](../../../data/verification/20260922_goal_fixed_frame_rows/english/edit_letter_frame/report.json) · [790자 추가 후 화면](../../../data/verification/20260922_goal_fixed_frame_rows/english/edit_letter_frame/letter_added_790.png) · [편집·재저장 HWPX](../../../data/verification/20260922_goal_fixed_frame_rows/english/edit_letter_frame/letter_added_790_resaved.hwpx) · [배경 실제 표시 회귀](../../../data/verification/20260922_goal_fixed_frame_rows/full_regression/verify_native_background_rendering.py.log)

| 이전 474자 편집 | 수정 후 474자 편집 |
| --- | --- |
| ![이전 제목 막대 겹침](../../../data/verification/20260922_goal_paragraph_frames_v4/english/long_letter_edit/added_474_top.png) | ![고정 장식 행으로 겹침 해소](../../../data/verification/20260922_goal_fixed_frame_rows/english/edit_letter_frame/letter_added_474_top.png) |

## 정확도와 평가 오류

문항 120개, 문단 연결 634쌍(국어 375·수학 4·영어 255), 원본 비트맵 82개(48·6·28)를 다시 확인했다. 수학 네이티브 수식 191개와 원본 적층 분수 20개, 33쪽 반복 머리말의 실제 표시 99개 필드와 자동 PAGE 필드 6개도 유지한다. 국어 병합 셀·그림 둘러싸기, 운문, 수학 혼합 문단·빈칸, 선택지 탭 편집 회귀도 통과한다.

현재 비교기의 원문 텍스트층 수치는 국어 **27,001/27,028**, 수학 **1,609/1,609**, 영어 **23,681/23,681**이다. 국어의 불일치 27자는 다음 문구다.

> [4~6] 다음은 방송부 회의 중 일부이다. 물음에 답하시오.

이 문구는 실제 본문에 들어 있다. 비교기가 문단 내부의 머리말 제어를 본문과 이어 붙여 `물음에국어영역고1고1국어영역답하시오`로 읽기 때문에 연속 문자열 비교에서 실패한다. 실제 HWPX를 읽고 머리말·꼬리말 제어를 분리했을 때 해당 문구 전체가 대응함을 확인했다. **27자 누락으로 해석하면 잘못된 평가다.** 이번 고정 소스의 비교 코드는 아직 수정하지 않았으며 원래 수치도 고쳐 쓰지 않았다. 후속 수정에는 머리말로 옮긴 본문을 보존으로 오인하지 않는 부정 검사가 필요하다.

이 진단은 해당 27자에 한정된다. 그림 안의 문자, 수식 의미, 모든 읽기 순서의 완전성을 텍스트 조각 비율로 보증하지 않는다.

[실제 XML 경로·문구·파일 해시를 포함한 진단](../../../data/verification/20260922_goal_fixed_frame_rows/korean_text_comparison_scope_evidence.json) · [수학 혼합 문단 편집](../../../data/verification/20260922_goal_fixed_frame_rows/math/edit_mixed_table/report.json)

## 품질 결과와 남은 실패

| 과목 | 쪽수 | 이전 평균 | 현재 평균 | 현재 최저 |
| --- | ---: | ---: | ---: | ---: |
| 국어 | 16 | 85.92 | 85.92 | 76.30 |
| 수학 | 12 | 86.66 | 86.66 | 73.64 |
| 영어 | 8 | 87.28 | 87.28 | 73.56 |
| 페이지 가중 평균 | 36 | 86.47 | 86.47 | 73.56 |

35쪽은 이전 출력과 픽셀까지 같다. 영어 2쪽은 1,841픽셀이 달라졌지만 점수는 91.40으로 같다. 이번 변경은 긴 편집의 겹침을 고친 것이며, 전체 원본 배치 품질이 좋아졌다고 평가하지 않는다.

글꼴 대체 순서, 명조체 별칭, 비트맵 글리프 처리도 실험했다. 원본과 글꼴 계열이 가까워 보여도 전체 점수가 내려가 최종 빌드에서 제외했다. 예를 들어 글꼴 대체 순서 변경은 국어 85.92 → 84.99, 수학 86.66 → 86.50, 영어 87.28 → 86.37이었다. 일부 페이지 상승만으로 채택하지 않았다.

전체 회귀의 실패는 `verify_external_exam_detail_quality.py`다. 기존 원본 정합·전경 겹침·수학 영역·배치 평균 97/최저 95 기준에 미달한다. 별도 엄격 검사에는 수학 그림 세로 위치 4쪽 **+2.8783px**, 11쪽 **+15.6557px**, 일반 대체 머리말 첫 쪽 기준선 **4.081255px** 오차가 남는다. 이 오차들의 기준은 0.1px다. 7쪽 그림은 +0.0068px로 통과한다.

꼬리말·첫 쪽 번호의 자동 필드화, 원본 글꼴·수식 간격, 그림 속 문자 개별 편집, 미주·정답의 가져오기 소속, 실제 한컴 GUI 편집은 남은 과제다. 이전 단계에서 발생한 12쪽의 배치 점수 하락도 이번 수정으로 복구된 것이 아니다.

[페이지별 전후 비교](../../../data/verification/20260922_goal_fixed_frame_rows/page_pixel_comparison.json) · [채택하지 않은 글꼴 실험](../../../data/verification/20260922_goal_fixed_frame_rows/rejected_font_experiments.json) · [전체 회귀 실패](../../../data/verification/20260922_goal_fixed_frame_rows/remaining_regression_failures.json) · [별도 실패·미검증 목록](../../../data/verification/20260922_goal_fixed_frame_rows/known_visual_failures.json)

## API·패키지·재현 근거

실제 영어 8쪽 PDF의 공개 API 변환과 다운로드는 HTTP 200이다. 다운로드한 HWPX **223,854바이트**와 정상 출력·편집 패키지 32개는 오류·경고 0이다. 32개에는 새로운 긴 편집·재저장 6개가 포함되며 의도적인 변조 파일은 제외한다.

실제 출력의 위 장식 행 높이를 300 HWP 단위 바꾸고 생성 통계는 그대로 두면 `structured`와 `coordinate` 모두 **HTTP 422 / positioned_text_tables**로 거부한다. 정상 API의 품질 응답도 배치 목표 미달을 유지한다. 원문 편집성은 통과하지만 `objective_score=87.28`, `meets_objective_score_target=false`, `meets_paging_target=false`다. HTTP 200과 실제 쪽수 일치를 품질 통과로 사용하지 않는다.

Python 소스 6개가 이전 검증본과 달라졌다. 36쪽 평가에 사용할 소스를 고정했고 전체 검사 후 파일 추가·삭제를 포함한 차이는 **0개**다. Windows 렌더러는 `rhwp-python 0.7.0+nativecell1`, 코어 0.7.13이며 실제 설치 바이너리와 wheel의 바이트 해시가 일치한다. 패치·lock·wheel·소스 스냅샷·실행 로그를 함께 보존했다. 렌더 후처리나 본문 이미지 덮개는 추가하지 않았다.

[전체 회귀 111개](../../../data/verification/20260922_goal_fixed_frame_rows/full_regression/report.json) · [패키지 32개](../../../data/verification/20260922_goal_fixed_frame_rows/native_package_validation.json) · [실제 API](../../../data/verification/20260922_goal_fixed_frame_rows/api_real_english/response.json) · [다운로드 검증](../../../data/verification/20260922_goal_fixed_frame_rows/api_real_english/download_validation.json) · [structured 변조](../../../data/verification/20260922_goal_fixed_frame_rows/api_corrupt_frame/structured.json) · [coordinate 변조](../../../data/verification/20260922_goal_fixed_frame_rows/api_corrupt_frame/coordinate.json) · [설치 렌더러 대조](../../../data/verification/20260922_goal_fixed_frame_rows/installed_renderer_check.json) · [소스 변경 0개](../../../data/verification/20260922_goal_fixed_frame_rows/source_differences_final.json)

현재 변환본: [국어](../../../data/verification/20260922_goal_fixed_frame_rows/korean/korean.hwpx) · [수학](../../../data/verification/20260922_goal_fixed_frame_rows/math/math.hwpx) · [영어](../../../data/verification/20260922_goal_fixed_frame_rows/english/english.hwpx). 검토용 산출물이며 완성 판정이 아니다.
