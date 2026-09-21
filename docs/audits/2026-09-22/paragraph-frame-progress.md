# 문단 텍스트박스·원본 틀 개발과 5분야 재평가

> 후속 결과는 [긴 문단 편집·5분야 평가](fixed-frame-row-progress.md)에 기록했다. 474자 추가의 겹침을 수정하고 790자까지 편집·재저장을 확인했다. 아래의 국어 27자 불일치는 실제 누락이 아닌 머리말 혼입에 따른 비교 오류로 확인했다. 아래 수치와 실패는 당시 소스의 기록으로 보존한다.

**36쪽 엄격 배치 평균은 86.15 → 86.47이다. 93점 목표에 미달하며 완성본으로 판정하지 않는다.** 영어 18번의 중복 틀과 초기 겹침은 수정했고, 본문 10줄을 실제 한 문단으로 유지했다. 그러나 474자를 추가하는 편집에서 배경과 인사말이 겹친다. 평균이 올랐어도 12쪽의 배치 점수는 내려갔다.

| 분야 | 판정 | 이번 소스로 확인한 근거 |
| --- | --- | --- |
| 품질 | 목표 미달 | 국어 85.92, 수학 86.66, 영어 87.28. 36쪽 평균 86.47, 최저 73.56. 16쪽 상승·12쪽 하락·8쪽 점수 동일 |
| 정확도 | 검사 범위 통과 | 문항 소속 120개, 문단 연결 634쌍, 원본 비트맵 82개를 대조. 국어 문자 대응은 27,001/27,028로 완전 일치가 아님 |
| 편집성 | 부분 통과 | 영어 지문 10줄을 한 문단으로 편집·재저장. +158자 통과, +316자 제목 겹침 없음, **+474자 제목 겹침 실패**. 실제 한컴 GUI 편집은 미검증 |
| 안정성 | 부분 통과 | 전체 회귀 111개 중 **99 통과·11 생략·1 실패**. 별도 긴 편집·그림 절대좌표 검사도 실패. 정상 편집 시나리오 패키지 26개 유효, 실제 API·다운로드 200 |
| 성능 | 측정 | 국어 28.168초, 수학 5.209초, 영어 16.955초, 합계 50.332초. 다른 검사와 동시 실행한 로컬 1회 측정으로 속도 개선 판정은 하지 않음 |

86.47은 페이지 수로 가중한 **배치 지표**다. 문자 정확도나 다섯 분야 종합 점수가 아니다. 생성기의 성공 표시, XML 유효성, 출력 쪽수 일치만으로 품질을 통과시키지 않았다. 이번 범위는 2026년 6월 고1 국어·수학·영어이며 21과목 168쪽은 이 소스로 다시 평가하지 않았다.

[기계 판독 평가 요약](../../../data/verification/20260922_goal_paragraph_frames_v4/assessment_summary.json) · [36쪽 원본 대조](../../../data/verification/20260922_goal_paragraph_frames_v4/report.json) · [이전 평가](running-header-and-choice-progress.md)

## 문단 단위 텍스트박스와 원본 틀

영어 2쪽 18번은 인사말·본문·서명의 **3개 의미 문단**으로 만든다. 원본 인쇄 13줄 중 본문 10줄은 같은 `hp:p`에 들어가며, 줄별 글상자·줄별 문단·강제 줄바꿈을 만들지 않는다. 문항 글상자 안의 실제 단일 셀 표가 배경 틀과 편집 가능한 문단을 함께 소유한다.

원본 배경 비트맵이 이미 표에 있는 경우, 같은 테두리가 독립 그림으로 한 번 더 삽입되던 문제를 수정했다. 배경 전체의 원문·실제 자산·영역이 일치할 때만 중복을 제거한다. 별도의 글자·벡터 선·다른 비트맵이 포함되거나 배경 일부만 소유한 경우에는 삭제하지 않는다. 국어처럼 여러 셀이 같은 장식을 나눠 쓰는 경우를 전체 틀로 오인해 높이를 반복하는 것도 차단했다.

표의 원본 너비·본문 여백·단 안쪽 들여쓰기를 복원했고, 렌더러가 비인라인 표의 수평 오프셋을 무시하던 문제를 수정했다. 본문은 문단 흐름을 따르며 임의 페이지 좌표로 고정하지 않는다. 독립 검증기는 원본 PDF의 실제 글자와 영역을 다시 읽어 이 예외를 확인한다.

- 최초 출력의 틀 위치 최대 오차 **0.0269px**, 줄 시작점·기준선 최대 오차 **0.0552px**로 0.1px 기준을 통과한다. 이 값은 위치 오차이며 글꼴 모양 일치 점수가 아니다.
- 배경은 한 번 표시되고 중복 테두리 그림은 0개다.
- 공개 문단 setter로 본문에 **158자**를 추가하면 같은 3개 문단을 유지하면서 표 높이가 16,802 → 24,508 HWP 단위로 늘어난다. 뒤 선택지가 이동하고, 새 문구가 실제 표시되며 저장·재열기 후에도 유지된다.
- 중복 틀, 줄별 문단, 틀의 위치 제거·왜곡, 페이지 고정, 문단 흐름 해제 등 **6개 변조를 거부**한다. 별도 비트맵 소유권 5개 사례와 부분 틀 무변경 거부도 확인했다.
- 첫 줄 들여쓰기와 둘째 줄부터 이어지는 내어쓰기를 구분했다. 문항/공통 지문 × 들여쓰기/내어쓰기 **4개 기존 편집·재저장 회귀**가 통과한다.

[영어 문단·틀 검증](../../../data/verification/20260922_goal_paragraph_frames_v4/english/edit_letter_frame/report.json) · [들여쓰기 회귀](../../../data/verification/20260922_goal_paragraph_frames_v4/full_regression/verify_native_paragraph_indentation.py.log)

| 원본 | 이전 출력 | 현재 출력 |
| --- | --- | --- |
| ![원본 영어 18번](../../../data/verification/20260922_goal_paragraph_frames_v4/english/question18_source.png) | ![이전 영어 18번](../../../data/verification/20260922_goal_paragraph_frames_v4/english/question18_previous.png) | ![현재 영어 18번](../../../data/verification/20260922_goal_paragraph_frames_v4/english/question18_output.png) |

**큰 편집은 아직 실패한다.** 158자·316자 추가에서는 회색 제목 막대와 인사말이 겹치지 않지만, 474자 추가에서는 글자 픽셀 36개가 제목 막대 안에 들어간다. 배경 전체를 표 높이에 맞춰 늘리는 `TOTAL` 채우기 때문에 제목 막대도 두꺼워진다. 본문 문단이 유지되고 새 글자가 표시된다는 사실만으로 편집성을 완료 처리하지 않는다. 문단 흐름은 유지하면서 장식의 위·아래 두께가 고정되도록 수정해야 한다.

[긴 편집 실패 보고서](../../../data/verification/20260922_goal_paragraph_frames_v4/english/long_letter_edit/report.json) · [실제 겹침 화면](../../../data/verification/20260922_goal_paragraph_frames_v4/english/long_letter_edit/added_474_top.png) · [실패를 재현하는 HWPX](../../../data/verification/20260922_goal_paragraph_frames_v4/english/long_letter_edit/added_474.hwpx)

## 정확도와 기존 편집 기능

문항 120개, 줄 연결 634쌍(국어 375·수학 4·영어 255), 원본 비트맵 82개(48·6·28)의 검사 범위는 통과한다. 수학 네이티브 수식 191개와 원본 적층 분수 20개도 유지된다. 반복 머리말은 33쪽에서 99개 필드의 실제 표시를 확인했고, 자동 PAGE 필드 6개를 유지한다.

원본 텍스트층의 대응 글자 수는 국어 **27,001/27,028**, 수학 **1,609/1,609**, 영어 **23,681/23,681**이다. 수식은 별도로 검사하며 그림 안의 문자와 모든 의미·읽기 순서의 정확성을 이 문자 비율로 보증하지 않는다. 국어의 대응하지 않은 27자를 완전 보존으로 보고하지 않는다.

수학 14번은 인쇄 20줄을 의미 문단 13개로 유지한다. 문단에 162자를 추가한 뒤 표 성장·저장·재열기를 확인했고, 빈칸 8개와 수식 191개가 실제 표시된다. 전체 문항 글상자 검사가 정상적인 원본 `(가)` 라벨까지 일괄 거부하던 판정 불일치를 수정했다. 이름 변경만으로 우회할 수 없으며, 임의 본문 글상자·잠긴 라벨·테두리 없는 라벨·수식이 든 라벨은 거부한다. **정상 이름 변경과 부정 사례를 포함한 5개 구조 검증**을 추가했다.

각 과목 본문 +155자 편집, 국어 병합 셀·그림 둘러싸기, 운문 행·연, 중첩 빈칸, 선지 탭과 반복 머리말 편집도 다시 실행했다. 수학 그림 앞 문단 +197자 편집은 같은 문단·수식·이미지와 12쪽을 유지하며 그림이 140.827px 아래로 이동한다. 이는 검사한 편집 시나리오의 증거이고 실제 한컴에서 직접 입력·저장한 증거는 아니다.

[수학 혼합 문단·중첩 구조](../../../data/verification/20260922_goal_paragraph_frames_v4/math/edit_mixed_table/report.json) · [반복 머리말](../../../data/verification/20260922_goal_paragraph_frames_v4/running_furniture/report.json) · [선지 편집](../../../data/verification/20260922_goal_paragraph_frames_v4/choice_tabs/report.json) · [그림 문단 편집](../../../data/verification/20260922_goal_paragraph_frames_v4/real_diagram_source_and_edit_evidence.json)

## 배치 점수와 남은 실패

| 과목 | 쪽수 | 이전 평균 | 현재 평균 | 현재 최저 |
| --- | ---: | ---: | ---: | ---: |
| 국어 | 16 | 85.59 | 85.92 | 76.30 |
| 수학 | 12 | 87.07 | **86.66** | 73.64 |
| 영어 | 8 | 85.87 | 87.28 | 73.56 |
| 페이지 가중 평균 | 36 | 86.15 | 86.47 | 73.56 |

영어 2쪽은 86.06 → 91.40으로 개선됐다. 반면 국어 5쪽은 81.91 → 78.48, 수학 7쪽은 91.70 → 88.53으로 하락했다. 전체 16쪽 상승·12쪽 하락·8쪽 점수 동일이며, 픽셀 자체가 같은 페이지는 7쪽이다. 일부 좌표를 맞춘 것이 페이지 전체 개선을 뜻하지 않는다.

전체 회귀의 실패는 `verify_external_exam_detail_quality.py`다. 원본 정합 96%, 전경 겹침 97%, 수학 영역 정합 94%·전경 겹침 80%, 배치 평균 97·최저 95 등 기존 기준에 미달한다. 수학 14번의 중첩 구조 오류는 이번 실패 목록에서 해소됐다. **11개 생략은 통과가 아니다.**

별도 가혹 검사에는 다음 실패가 남는다. 이 항목들은 전체 회귀의 `FAIL 1`에 포함된 것으로 오해하면 안 된다.

1. 영어 문단 +474자 편집에서 제목 막대 겹침이 재현된다.
2. 수학 그림의 세로 위치는 4쪽 **+2.8783px**, 11쪽 **+15.6557px**로 0.1px 기준에 실패한다. 7쪽은 −1.9399 → +0.0068px로 수정되어 통과한다.
3. 일반 대체 머리말을 쓰는 합성 문서 첫 쪽의 본문 기준선 오차는 **4.081255px**로 실패다. 기존 문항 간 상대 간격·추가·삭제 검사는 통과하며, 이번에 추가한 뒤쪽 페이지의 절대 기준선·단 넘김 검사는 0.1px를 통과한다. 첫 쪽 실패는 로그에 별도로 기록했다.

꼬리말·첫 쪽 번호의 자동 필드화, 본문 글꼴, 수식 간격·절대 배치도 남아 있다. 영어 18번은 원본의 명조체와 출력 글꼴이 다르다. 원본 내장 `Haansoft Batang`의 56개 문자 폭과 설치된 후보 글꼴을 비교했으나 정확히 일치하는 후보를 찾지 못했다. 해당 조사는 개선 완료 근거가 아니다.

그림 속 문자 라벨 개별 편집, 공개 HWPX 4종의 미주·정답 소속 가져오기, 한컴 GUI 직접 편집도 완료되지 않았다. 다음 개발은 긴 편집의 장식 겹침, 12쪽 배치 회귀·원본 글꼴, 남은 절대 위치 순으로 검증해야 한다.

[페이지별 전후 비교](../../../data/verification/20260922_goal_paragraph_frames_v4/page_pixel_comparison.json) · [전체 회귀 실패 항목](../../../data/verification/20260922_goal_paragraph_frames_v4/remaining_regression_failures.json) · [별도 실패 목록](../../../data/verification/20260922_goal_paragraph_frames_v4/known_visual_failures.json) · [글꼴 폭 조사](../../../data/verification/20260922_goal_paragraph_frames_v4/source_font_family_evidence.json)

## API·패키지·재현 근거

실제 영어 8쪽 PDF를 공개 API 경로에 넣어 변환 200과 다운로드 200을 확인했다. 내려받은 HWPX 220,881바이트의 패키지 검증은 오류·경고 0이다. 정상 편집 시나리오의 출력·재저장 패키지 **26개**도 유효하다. 의도적으로 손상한 파일과 별도 긴 편집 실패 파일은 이 26개에 포함하지 않았다.

API 자체의 품질 응답은 목표 미달을 유지한다. 원문 편집성 검사는 통과하지만 `objective_score=87.28`, `meets_objective_score_target=false`, 시각 정합 목표 미달·사람 검토 필요이며, 실제 출력 8쪽이 일치해도 별도의 `meets_paging_target` 판정은 false다. HTTP 200을 품질 통과로 바꿔 해석하지 않는다. 홀수 쪽 머리말을 실제 출력에서 지운 뒤 생성 통계를 그대로 둔 변조는 `structured`와 `coordinate` 모두 **HTTP 422**로 차단한다.

[전체 회귀·111개 로그](../../../data/verification/20260922_goal_paragraph_frames_v4/full_regression/report.json) · [패키지 26개](../../../data/verification/20260922_goal_paragraph_frames_v4/native_package_validation.json) · [API 응답](../../../data/verification/20260922_goal_paragraph_frames_v4/api_real_english/response.json) · [다운로드 검증](../../../data/verification/20260922_goal_paragraph_frames_v4/api_real_english/download_validation.json) · [structured 변조](../../../data/verification/20260922_goal_paragraph_frames_v4/api_corrupt_header/structured.json) · [coordinate 변조](../../../data/verification/20260922_goal_paragraph_frames_v4/api_corrupt_header/coordinate.json)

이전 검증본 대비 Python 소스 11개가 변경됐다. 36쪽 평가는 실제 가져올 Python 소스를 고정해 실행했고, 모든 후속 검사 뒤 파일 추가·삭제까지 비교한 차이는 0개다. Windows 렌더러는 `rhwp-python 0.7.0+nativeflow2` / core `0.7.13`이며, 설치된 바이너리가 보관 wheel과 같은지 해시로 확인했다. 고정 상위 커밋·소스 패치·잠금 파일·빌드 로그·wheel·라이선스를 보관했다. 다른 OS와 한컴 GUI 호환성, 바이트 단위 재빌드 재현성을 증명한 것은 아니다.

[Python 소스](../../../data/verification/20260922_goal_paragraph_frames_v4/tested_python_sources.zip) · [소스 해시](../../../data/verification/20260922_goal_paragraph_frames_v4/source_hashes.json) · [검사 후 차이](../../../data/verification/20260922_goal_paragraph_frames_v4/source_differences_final.json) · [렌더러 일치](../../../data/verification/20260922_goal_paragraph_frames_v4/installed_renderer_check.json) · [렌더러 묶음](../../../data/verification/20260922_goal_paragraph_frames_v4/renderer_bundle.zip) · [추가 검사 스크립트](../../../data/verification/20260922_goal_paragraph_frames_v4/evidence_scripts/publish_paragraph_frames_evidence.py)

[국어 HWPX](../../../data/verification/20260922_goal_paragraph_frames_v4/korean/korean.hwpx) · [수학 HWPX](../../../data/verification/20260922_goal_paragraph_frames_v4/math/math.hwpx) · [영어 HWPX](../../../data/verification/20260922_goal_paragraph_frames_v4/english/english.hwpx)
