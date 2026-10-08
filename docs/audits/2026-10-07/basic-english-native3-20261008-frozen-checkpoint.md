# 기본 영어 변환: 2026-10-08 고정 코드 검증

프리미엄 양식·문항 순서 변경은 제외했다. 아래 결과는 이후 수정과 구분되는 고정 체크포인트이며, 전체 품질 PASS를 뜻하지 않는다.

## 실제 3개 학년 API 및 렌더링

보고서: `tmp/september-exam-matrix/basic-english-native3-20261008-b/report.json`.
제품/검증기 해시 `fc6dfc1d402e7396c1178947478f68dc5503dfae0d454cd31faa1ec40793fe34` 하나로 모든 사례가 실행됐다. 각 사례 전후 코드 및 설치 렌더러 해시가 같았다. `rhwp-python 0.7.0+nativecell3`의 실제 `_rhwp.pyd` SHA-256은 `50de55e32d998bde2cf83b80219fe5d1226ee4daf03b17f0b3d1de4bba55fdd1`이다.

| 학년 | HTTP | 실제 출력 | 문항 | 독립 native 원문 보존 | API 점수 | harsh 평균 / 최저 |
|---|---|---|---|---|---|---|
| 고1 | 200 | 8쪽 | 45 | 1.0 | 89.75 | 93.21 / 90.68 |
| 고2 | 200 | 8쪽 | 45 | 1.0 | 89.75 | 93.30 / 90.07 |
| 고3 | 200 | 8쪽 | 45 | 1.0 | 88.61 | 88.61 / 83.63 |

직전 고정 영어 결과의 고3 harsh 평균87.05/최저78.58에서 개선됐다. 모든 페이지가 개선된 것은 아니다. 세 학년 모두 API98·harsh평균97/최저95·raw정렬0.96·foreground0.97 목표를 충족하지 못했다. 목표와 점수 계산은 변경하지 않았다. 51개 시험지 중 영어3개만 실행했고 나머지48개는 NOT_RUN이다.

## 같은 코드에서 통과한 별도 검사

- 일반 native 변환 회귀14개: PASS14/FAIL0/SKIP0, 제품·검증기 전후 해시 동일. 보고서 `frozen-basic-20261008-regressions-b/report.json`.
- 실제 고3 본문4개: 전용785검사/332negative, 실제 producer·편집 후 저장·새로 열기 통과. Q22/Q23 높이 오차는2.768/2.757px에서0.023/0.034px로 줄었고, 다른25719개 glyph 위치는 정확히 같았다. 모든 본문 glyph의 수평 오차가 사라졌다는 주장은 하지 않는다.
- 고3 실제 표2개: final4의 producer34/consumer17/vendor26 negative와 public6단계 통과. 길게 추가하면9쪽으로 늘고 삭제·완전 비우기 후 복원하면8쪽 및 원래 page4 PNG로 돌아온다. 실제 그려진 glyph는 현재 셀 안에 있다.
- 독립 body/grid 검사156개 통과: source/native font 차이, 변조 cache, fractional flags와 native 장식의 거부를 확인했다. 이는 전체 페이지 품질과 다른 검사다.
- 고2 Q27 그림 포함 지문: 새 final11 HWPX SHA-256 `83ce0e55e9c6b7a0550267939c64f1af5f8ac0d329c54846de4d542320b8a187`, 독립 전체 검사 PASS 및 코드/렌더러 안정. 실제 PDF glyph664개(글머리표6개 포함), 그림 겹침·인쇄 영역 이탈 없음. 추가/삭제로8→9→8쪽, 원래 Q28 위치 복원. 최대 첫 glyph 오차0.146px, 모든 glyph 최대 수평 오차1.819px는 별도 진단값이며 전체 glyph 완전 일치를 뜻하지 않는다. 원본 soft hyphen3개는 별도 paint 증명이 필요하다.

각 세부 경로는 `tmp/september-exam-matrix/` 아래의 `body-alignment-final-20261008/final-verified/`, `high3-grid-final4/`, `q27-final11-independent/` 및 `tmp/september-audit/`의 독립 보고서에 기록했다.

## 남은 실제 문제

Q21/Q24처럼 italic 및 다른 글꼴의 문장부호가 섞인 본문은 현재 보수적인 의미 문단 증명에서 제외된다. Q23 마지막 줄은 자연 공백이1개여서 기존3개 이상 공백 증명 조건을 충족하지 못한다. 표의 자연 공백 폭도 실제 source/native glyph 비교가 추가로 필요하다. 고정 여백·단간격 점수 프로필은 원본 좌표 일치 검사와 다르지만, 두 문항의 정확한 원점만으로 전체 배치 점수를 부여할 수 없다. 이 사항들을 다음 수정의 실제 근거로 조사한다.

Mac은 별도 정적 가능성/오류 요소 평가만 완료했다. 실제 Mac host, nativecell3 Mac wheel, 설치·폰트·실행은 검증하지 않았다. 현재 결과는 Windows 실행 증거다.
