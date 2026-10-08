# 고2 9월 영어 Q28 독립 검증

검증 대상은 `data/external_exam_qa/2026_september_high2/english.pdf`의 4쪽 Q28 및 최신 기본변환 `tmp/september-exam-matrix/high2-illustrated-native.hwpx`이다. 원문 기대값은 제품의 추출 결과나 metadata flag 대신 PDF의 실제 문자·baseline·벡터 선·보이는 이미지 bbox에서 독립적으로 얻었다. 제품 코드 및 품질 기준 98은 이 감사 과정에서 변경하지 않았다.

## 재현

```powershell
python scripts/verify_native_illustrated_prose_frame_flow.py --hwpx tmp/september-exam-matrix/high2-illustrated-native.hwpx --artifacts tmp/september-exam-matrix/illustrated-final-verified
```

최종 결과는 **FAIL / exit 1**이다. 로그는 `tmp/september-exam-matrix/illustrated-final-verified.log`, 판정별 JSON은 같은 이름의 폴더 안 `report.json`에 남긴다. 실패를 수집한 뒤 편집·재저장 검사까지 계속하며, 부분 통과를 전체 통과로 표시하지 않는다.

## 통과한 부분

- 원문의 18개 baseline, 전체 본문 문자, 두 그림의 실제 decoded pixels, 4개 외곽선이 독립 원본 oracle로 확인된다.
- 편집 가능한 하나의 3×3 native table, 5개 의미 영역 cell과 두 inline 그림이 보존된다. 문장을 인쇄된 행별 cell로 쪼개지 않는다.
- 모든 원문 baseline의 상대 간격 오차는 0.04px 미만이며, 기본 결과는 원본과 같은 8쪽이다.
- 독립 native oracle의 오류 주입 7종과 실제 source-proof 예외 경로의 오류 주입 10종이 모두 거부된다. 본문 누락, 그림 교체, 외곽선 변경, 잘못된 폭·cell 소유권, 고정 페이지 anchor, 과도한 cache 높이·폭, 잘못된 baseline 및 비유한 cache를 포함한다.
- 본문을 늘리면 아래쪽 두 그림과 후속 선지가 이동한다. 등록 안내 문단을 늘리면 같은 행의 QR 그림과 후속 선지도 따라간다. 두 편집의 실제 PDF font glyph 295개·158개는 페이지 경계 안에 있고 그림과 겹치지 않는다. 다시 열고 저장한 XML·렌더 좌표도 동일하다.

## 남은 실패

| 항목 | 독립 측정 결과 |
| --- | --- |
| 전체 Q28 세로 위치 | prompt는 원본 대비 +19.827px, 외곽선·두 그림도 약 +19.82px. 그림 사이와 본문 내부 간격은 보존됨 |
| Day 1 문장 끝 `through`의 `h` | 원본 bbox 오른쪽 745.5218pt < 원본 외곽 750.139pt. native 실제 PDF glyph bbox 오른쪽 708.6836px > 물리 cell 오른쪽 707.96px, 0.7236px 초과 |
| Day 3 문장 끝 `to`의 `o` | 원본 bbox 오른쪽 745.6431pt < 원본 외곽 750.139pt. native 실제 PDF glyph bbox 오른쪽 708.4249px, 물리 cell을 0.4649px 초과 |
| PDF painting의 `Pre\u00ADregistration` 하이픈 | 원본 PDF의 실제 painted glyph 173, 양수 glyph ID, 원문 origin과 bbox로 확인됨. native XML/SVG에는 문자가 있으나 `rhwp.render_pdf()`의 해당 위치에는 실제 font glyph가 없음. PNG에는 획이 존재하므로 PDF 경로에 한정한 실패 |

마지막 하이픈의 원본 bbox는 `[466.43948, 979.22009, 470.48947, 990.37433]`pt, 대응 native SVG origin은 `[443.63097, 953.01333]`px이다. `missing_source_visible_glyph`는 **native PDF painting**의 별도 실패이다. PNG 실제 x445..446/y949..950에는 gray ink 164/211인 하이픈 획이 확인되어 일반 native painting 누락으로 확대하지 않는다. 독립 PNG 증거는 `tmp/september-audit/high2-soft-hyphen-readonly/png-original-top-hyphen-bottom-crop.png`이다. XML/SVG text inventory와 각각의 실제 painting 보존을 구별하며, 실제 vector circle로 그려지는 bullet도 별도로 확인한다.

원문 전체의 실제 **native PDF font glyph** 594개를 검사한다. editable table SVG에는 cell clip이 없으므로 실제 4개 외곽선으로 table 위치를 확인한 뒤 native cell 주소·크기와 실제 PDF glyph bbox를 비교한다. text margin 안쪽 침범과 물리 cell 밖 초과를 구별한다. 두 오른쪽 초과는 PDF glyph bounds 기반 실패이며, 선택 face가 별도로 확인되지 않은 PNG의 실제 clipping 실패로 확대하지 않는다.

## 반복 라벨 문단과 hanging indent 후속 검증

2026-10-07 후속 제품 변경은 complete illustrated source frame 안에서 원본 raw character의 반복 라벨과 실제 leading-space advance가 입증되는 문단에만 적용된다. 일반 semantic grouping이나 렌더러는 변경하지 않는다. 독립 검수에서는 제품의 grouping helper 대신 원본 PDF 글자에서 `When:` 두 행, `Where:` 한 행, `Cost:` 한 행과 다음 소제목을 직접 구분한다.

```powershell
python scripts/verify_native_illustrated_prose_frame_flow.py --hwpx tmp/september-exam-matrix/field-product/high2-native.hwpx --before-hwpx tmp/september-exam-matrix/hanging-independent-before.hwpx --artifacts tmp/september-exam-matrix/field-independent-verified
```

첫 줄의 원본 ink x는 437.39999pt, When continuation은 474.35999pt이다. 새 native continuation x는 447.68px로 원본 배율 적용값 447.68452px와 0.00452px 차이이다. 두 rail 사이의 실제 들여쓰기 간격 오차는 -0.00156px이다. HWPX의 native left는 0, intent는 -2616이며, HWP의 `left + max(0, -intent)` continuation 계약에 따라 처음 줄의 rail을 바꾸지 않고 후속 줄을 들여쓴다.

수정 전 파일과 비교한 전체 원문 character별 resolved charPr, 다섯 행 combined flow 6537 HWP, question wrapper 높이 31532 HWP는 동일하다. continuation을 제외한 원문 glyph의 x/y 변화도 0.05px 미만이다. 원문 전체를 유지한 채 두 field를 합치는 mutant, field 일부 삭제, 두 source행 cache 상실, 잘못된 left와 intent의 다섯 오류를 추가로 거부한다. 기존 17개 illustrated-frame 오류 검사와 별도이다.

코드 검토 결과 새 처리의 table/header 변경은 복사본에 먼저 수행되며, source 문자와 기존 flow가 일치할 때만 적용된다. source literal text, complete frame 본문, raw span/character/font/bbox, cache와 실제 앞 공백 증거가 부족하거나 equation/answer-blank가 있으면 기존 경로를 유지한다. 이번 독립 검토에서 재현 가능한 추가 제품 회귀는 발견하지 못했다.

기존 absolute 위치와 native PDF glyph 실패는 후속 문단 복원으로 해결되지 않았으며 별도 FAIL로 유지한다. 최종 편집 결과는 `field-independent-verified/edit-summary.json`, 통합 판정은 `report.json`, 명령 로그는 같은 이름의 `.log`에 기록한다. 내용 증가로 다음 페이지·다른 단으로 이동할 수 있으므로 편집 후 hanging rail은 그 문단의 첫 줄과 원본의 실제 들여쓰기 간격을 기준으로 검사한다.

최종 통합 명령은 **exit 1**이며 실패는 위의 기존 absolute 위치·PDF glyph bounds 두 건·PDF soft-hyphen에 한정된다. 원본 결과는 8쪽이고, 세 문단에 의미 있는 내용을 누적 추가한 편집 결과는 정상적인 pagination으로 9쪽이 된다. 세 편집 모두 package, 본문·그림 flow, 실제 PDF glyph 경계와 그림 겹침, reopen 후 XML·text/image 좌표 동일성 검사를 통과했다.

특히 새 When 문단은 public `add_run`으로 원본 layout cache가 무효화된 것을 확인한 뒤 저장했다. native left 0/intent -2616과 원본 resolved run style이 유지됐다. 다음 페이지 왼쪽 단으로 이동한 첫 줄의 x는 90.37333px, 뒤의 7개 줄은 모두 125.25333px이며 독립 원본 상대 rail 기대값 125.25489px와 0.00156px 차이이다. Where/Cost 문단, 두 그림과 후속 선지는 늘어난 When 문단 아래로 이동했다. When의 실제 PDF font glyph 249개가 경계 안에 있으며 그림과 겹치지 않는다. 기존 본문/등록 문단 편집도 각각 295개/158개로 통과해, 세 편집에서 총 702개 glyph를 검사했다.

## 기존 시험지 회귀

`scripts/verify_english_layout.py` 최종 실행은 exit 0이다. 고1 6월은 8쪽·45문항·2578개 cell glyph·4개 선지 rail, 수능 합본은 16쪽·90문항·3162개 cell glyph 및 반복 frame positive 2종·negative 3종을 확인했다. 양쪽 editability/rendering도 통과했다. 로그: `tmp/september-exam-matrix/final-regressions/old-english-layout.log`.

일반 native/math/height 관련 9개 회귀는 별도 보고서 `tmp/september-exam-matrix/illustrated-regression-report/report.json`에서 모두 exit 0이다. 숫자 하나를 편집했을 때 기존 grid frame에 생겼던 불필요한 26333px 변화는 별도로 재현했으며, 담당자가 source wrapper reserve의 400-unit 변화를 좁게 수정해 fresh 회귀에서 35px로 통과했다. 관련 로그는 `tmp/september-audit/grid-save-regression-fixed-fresh.log`, 세부 근거는 `english-source-frame-font-diagnostics.md`이다.
