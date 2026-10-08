# 기본 영어 변환: 남은 실패와 다음 수정 조건

2026-10-07 제품 동결 시점의 읽기 조사다. 현재 범위는 기본 PDF 원본 배치 native HWPX이며 프리미엄 템플릿·순서는 보류한다. 이 문서는 남은 실패를 통과로 바꾸거나 기존 품질·픽셀·glyph 임계치를 수정하지 않는다. 최종 품질 수치는 root의 동결 코드 fresh 51부 matrix가 우선한다.

## 현재 확인된 기능과 남은 실패

고2 9월 영어는 실제 strict API에서 8쪽·45문항, source text coverage 1.0, independent editability/open/render PASS다. 이는 품질 목표 달성을 뜻하지 않는다. `tmp/september-exam-matrix/high2-basic-final/report.json`의 해당 실행은 objective89.75, harsh 평균92.12/최저85.79이며 목표98/97/95에 미달한다. 해당 실행 이후 캐시 bounds guard와 재저장 reserve 수정이 추가됐으므로 최종 코드 점수로 재사용하지 않는다.

Q28은 한 원본 4변 안내문 틀을 native 3행3열/5셀로 보존한다. 셀 분할은 의미 문단과 실제 삽화 관계를 따르고, 원본 18행의 본문은 native text, 두 삽화만 원본 figure pixels다. 그림은 inline이며 전체 안내문은 paragraph flow다. 본문 증가와 등록 문단 증가에서 해당 그림·후속 선택지가 이동하고, 저장·재열기·가시 glyph bounds 검사가 통과했다. 원문/그림/테두리/셀 소속/page anchor/과도한 cache 높이를 바꾼 17개 negative는 거절된다. 다만 초기 절대 좌표·아래 가시 glyph 결함은 별도 FAIL이다.

## 고2 Q27 누적 높이와 Q28 절대 y

Q28 원본 틀은 y680.103..991.847pt이며, native 틀과 두 삽화가 모두 원본보다 약 **19.822px 아래**에 있다. 내부 18행 상대 baseline 오차는 최대 약0.036px다. 따라서 Q28 내부 줄높이를 일괄 축소하거나 틀에 음수 y를 주는 해결은 원인을 가린다.

읽기 probe `tmp/september-exam-matrix/remaining-basic-diagnosis.py`는 기존 8쪽 HWPX를 열어 다음 Q27 구조를 확인했다. 제품 변환·패키지 변경은 하지 않았다.

| Q27 native 직접 자식 | 객체 높이(HWP) | `_flow_height`(HWP) |
|---|---:|---:|
| 제목+도입 본문 table | 5675 | 6075 |
| 독립 tree picture | 4848 | 5248 |
| 나머지 안내문 table | 13448 | 13848 |
| 합계 | 23971 | 25171 |

원본에는 x431.648..755.174/y213.507..526.210pt의 완전한 한 틀이 있다. 세 객체의 reserve400씩은 총1200HWP=16px다. 각 fragment 자체의 높이와 주위 source spacing도 함께 작용하므로 **전체19.822px를 reserve1200만으로 설명하지 않는다**. 다음 수정 전에는 한 변수씩 A/B해 나머지 높이를 분해해야 한다.

실제 그림 bbox는 `[671.026,289.314,739.471,357.804]`pt다. 도입 문단 마지막 줄 bbox는 y282.034..293.312pt/x437.400..621.557pt다. 그림 위 경계가 마지막 줄의 세로 범위 안에 있지만 좌우 ink는 겹치지 않는다. 따라서 현재 `illustrated_frame_topology`의 단순 그림 상단 row-cut은 이 문단을 안전하게 수용할 수 없다. Q28의 3행3열 형식을 그대로 강제하거나 인쇄된 줄마다 셀을 만드는 방식은 피한다.

후속 producer 조건은 한 틀의 실제4변, 전체 source text/순서, 실제 한 그림 pixels, 각 줄의 picture interval을 독립적으로 확인하는 것이다. 도입 문단 하나를 유지하면서 마지막 줄과 아래 안내문이 그림 왼쪽을 흐르고, 그림 끝 아래에서는 원래 폭으로 돌아오는 native paragraph wrapping 경로를 먼저 격리 검증한다. 그림은 해당 의미 문단/셀에 소속되어 앞 본문 증가 시 같이 움직여야 한다. page anchor나 고정 y fallback은 허용하지 않는다. 일반 표·수식 object400은 유지한다. 이 source topology가 증명되지 않으면 현재 경로와 FAIL을 유지한다.

필수 회귀는 원문 전체·그림 pixels·4변·실제 abs y, 도입 문단 증가/삭제→그림/다음 문단/Q28 이동, 그림과 glyph 비겹침, 저장·재열기·재저장이다. 고2 Q28 및 기존 고1June/CSAT·수학 mixed-frame 회귀를 함께 유지한다.

동결 중 ZIP-only 진단을 추가했다. `tmp/september-exam-matrix/q27-reserve-ab.py`는 세 source 객체의 text/pixels/크기 자체는 byte-identical로 두고, 각 객체 뒤 누적 cached vertpos와 question wrapper/host cache에서400씩만 제거했다. 8쪽을 유지하면서 Q28 prompt baseline 잔차19.8272308→3.8272308px, 제목19.8229642→3.8229642px로 **정확히16px** 줄었다. 제품의 일반 `_flow_height`를 바꾸지 않았다. Q27 prompt는 처음부터 원본 대비+.003541px, 제목 baseline은-.000697px이므로 잔여3.82px는 처음 시작점이 밀린 결과가 아니다. 원래 Q27 내부 fragment와 spacing의 남은 성분을 별도로 조사해야 한다.

같은 측정에서 Q27 제목의 x는 native405.3333px/source473.7325px로68.3991px 왼쪽이다. partial source frame 경로의 center 복원이 누락된 별도 결함이며, Q28 전체의 x를 바꾸는 근거로 사용하지 않는다. A/B 결과는 `tmp/september-exam-matrix/q27-reserve-ab/results.json`과 `q27-cached-reserve-zero.hwpx`에 있다. 이 직접 cache 변경은 편집 후 topology/line bounds가 입증된 producer가 아니므로 제품 수정안으로 채택한 것이 아니다.

## 고2 Q28 continuation의 leading advance 소실

원본 `When:` 첫 ink는 x437.400pt다. 다음 줄은 실제로 **7개 leading spaces**를 갖고, line bbox.x0는 동일437.400pt지만 첫 ink `(` 원점은 **474.360pt**다. 의미 있는 advance는36.96pt, 현재 출력 축척에서 약34.88px다. 뒤 `Where:`, `Cost:`, `Workshop Schedule`은 다시 x437.400pt다.

native 출력에서는 다섯 source 행이 한 의미 문단으로 묶이고, left/intent가 모두0이며 다섯 cache.horzpos도0이다. `(`의 실제 SVG x는412.8px로 같은 셀의 기본 left rail에 있다. `_semantic_line_groups`와 `_source_typography`가 source text에 `.strip()`을 쓰고, cache 왼쪽은 leading spaces가 포함된 line bbox로 측정한다. 따라서 선행 원인은 **leading advance를 native geometry로 넘기지 못한 것**이다. 일반 cache.horzpos를 renderer가 무시한다는 진단만으로 수정해서는 안 된다.

후속안은 원본4변+전체 source matching+실제 rawchar union 증명 아래, 같은 레일의 반복 `label:` field와 heading 경계를 의미 문단으로 복원하는 것이다. `When:`의 실제 두 행은 한 editable paragraph로 유지하고, 첫 ink 차이로 측정한 hanging indent를 설정한다. 이어지는 Where/Cost/heading은 각각 원문 field 관계로 분리한다. 단순히 모든 source 행을 문단으로 나누지 않는다. 들여쓰기 변경 후 폭·줄바꿈·본문 증가 시 재흐름을 직접 검사한다.

source/rawchars 누락·유니온/bbox 불일치·일반 본문 paragraph·수식·graphic label은 거절해야 한다. 원본 answer blank의 밑줄 공백은 레이아웃 공백과 구분해 그대로 보존한다. 행 앞 공백 문자만 늘리는 우회보다 native paragraph indentation과 의미 경계를 우선한다.

동결 중 `tmp/september-exam-matrix/field-indent-ab.py`로 ZIP-only 후보를 측정했다. source 반복 `label:`·실제 leading rawchar advance·whole text match로 하나의 후보를 찾았고, 특정 When/Where/Cost 문자열을 조건으로 사용하지 않았다. 원래5행을4개 의미 문단으로 복원하되 처음2행은 하나의 hanging paragraph로 남겼다. 기존 run style과 native 전체 문자열은 exact이며, total flow는 **6537→6537HWP**, 8쪽,5개 baseline은 before와0.05px 미만이다. 측정 indent2616HWP를 적용하면 `(`의 SVG x412.8→447.68px로 복원되고 source447.68452px, 상대 first-ink 오차-.00156px다. 실제 PDF159glyph는 물리cell bounds 안에 있으며 PDF `(` 원점도412.800008→447.680013px로 이동했다. PNG에서는 bbox(414,731)-(577,743)의766pixels만 달라져 실제 paint 복원도 확인했다.

결과/복사본은 `tmp/september-exam-matrix/field-indent-ab/{results.json,paint-compare.json,field-semantic-hanging.hwpx}`다. Q27 때문에 생긴 전체 y+19.82px, 두 다른 문장의 오른쪽 glyph 돌출, PDF soft hyphen은 이 A/B에서 해결한 것으로 집계하지 않는다.

전체51부 동결 검사 완료 후, 반복 label field와 실제 ASCII-space prefix의 rawchar 첫 ink가 입증되는 완전한 illustrated frame에만 제품 연결했다. `app/pdf_illustrated_prose_frames.py:restore_source_field_paragraphs`는 실제 전체 원문 matching, source span/line/char bbox union 및 유한성, 같은 label rail, 2개 이상 서로 다른 label, 그림의 native inline 소속, native cache 순서와 실제 cell bounds를 먼저 검증한다. field 경계와 다음 source bullet이 입증하는 heading만 문단 경계로 쓰며 특정 날짜나 When/Where/Cost 문자열을 조건으로 사용하지 않는다. 일반 본문 grouping과 3em indent 제한은 그대로다. native negative intent 의미에 맞춰 기존 left0을 보존하고 continuation에 intent-2616을 적용한다.

원문·원래 run attributes·전체 flow를 복사본에서 확인한 뒤 기존 paragraph style 객체를 유지한 채 새 style만 append한다. source answer blank, native underlined whitespace, genuine native equation/원문 equation font, rawchar 누락/불완전·NaN·잘못된 shape, bbox/폭/cache 불일치, 비영 left/intent/cachehorzpos는 무변경 거절한다. supplementary code point의 cache offset은 UTF-16 단위로 보존한다.

fresh 제품 출력 `tmp/september-exam-matrix/field-product/high2-native.hwpx`는8쪽이며 실제 SVG 다섯 행의 `(x,y)`는 `(412.8,725.72)`, `(447.68,740.32)`, `(412.8,759.68)`, `(412.8,779.04)`, `(412.8,798.28)`px다. 기존 다섯 baseline과 다른 네 행의 x가 유지되고 continuation 상대 x 오차는-.00156px다. 전용 `scripts/verify_native_source_fields.py`는 실제 raw PDF18행, native semantic cache `[2,1,1,1]`, 원문/run attributes exact, total flow6537→6537, 기존 style 객체·bytes 보존, 두 번째 실행 무변경, UTF-16 supplementary positive, first-before137 보존,26개 negative를 확인해 exit0으로 끝났다. 로그/JSON은 `tmp/september-exam-matrix/field-product/{source-fields.log,source-fields-report.json}`이다. 실제 public 편집·재열기와 전체594glyph 검사는 별도 독립 illustrated 회귀에 보존하며 위 기존 absolute-y/glyph/PDF-hyphen FAIL을 면제하지 않는다.

이 제품 snapshot의 fresh 영어3부 strict API는 모두 HTTP200/8쪽/45문항/source text1.0/독립 기능 검사 PASS지만 품질은 세 건 모두 FAIL이다. stable SHA는 `dacd4d4d7719768269da6d486dce7ab19c28a7a6f5f2081c9e9af779f46caf97`, harsh 평균/최저는 고1 `93.21/90.68`, 고2 `92.12/85.77`, 고3 `87.05/78.58`다. `tmp/september-exam-matrix/field-final-current/report.json`은 **English3 subset**이며 이전51부 baseline을 대체하거나 전체51부 통과로 집계하지 않는다.

## 가시 soft hyphen과 두 glyph 돌출

Q28 `Pre\u00ADregistration`의 원본 U+00AD는 PDF fonttrace에 실제 painted glyph와 양수 bbox `[466.4395,979.2201,470.4895,990.3743]`pt가 있다. Native XML와 SVG에는 같은 문자가 있지만 같은 위치의 실제 `rhwp.render_pdf()` painted glyph가 없다. 반면 PNG의 x445..446/y949..950에는 gray ink164/211의 하이픈 획이 있으므로 **실패를 PDF backend(usvg/rustybuzz)에 한정**한다. 독립 PNG 근거는 `tmp/september-audit/high2-soft-hyphen-readonly/png-original-top-hyphen-bottom-crop.png`이다. XML 문자 일치/coverage1.0으로 PDF painting을 통과시키지 않고, PDF 실패를 PNG 누락으로 확대하지 않는다. 같은 문서의 다른 내부 단어에도 U+00AD가 있으므로 해당 위치만의 현상으로 일반화하지 않는다.

후속안의 gate는 실제 원본 내부-word U+00AD, 양수 glyph bbox·paint trace·font 매핑, native 측정에서 미paint가 함께 확인되는 경우다. 일반 discretionary soft hyphen을 전역 hard hyphen으로 치환하지 않는다. 원본 문자 inventory의 엄격 비교와 native 편집/저장 semantics를 함께 만족하는 source-proven display 표현을 먼저 A/B한다. `hp:softHyphen`은 현재 rhwp HWPX parser에서 lineBreak와 함께 newline으로 읽는 경로가 있으므로 무검증 대체로 쓰지 않는다. 실제 하이픈 모양·주변 glyph origin·전체 text inventory·편집 뒤 reflow가 모두 별도 검사 대상이다.

초기 전체frame 594 source glyph 검사에서 원본은 틀 안에 있지만 native에서 물리cell/frame 오른쪽으로 넘는 두 글자를 확인했다.

| 글자 | 원본 glyph bbox 오른쪽(pt) | native 실제 오른쪽(px) | native 물리cell 오른쪽(px) | 초과(px) |
|---|---:|---:|---:|---:|
| Day1 `through`의 h | 745.5218 | 708.6836 | 707.96 | 0.7236 |
| Day3 문장끝 `to`의 o | 745.6431 | 708.4249 | 707.96 | 0.4649 |

원본 frame right750.139pt 안에 실제 ink가 있으므로 원본 자체 돌출로 면제하지 않는다. 다음 수정은 source per-span tracking/actual advance와 native font painting을 비교해 두 행의 원인을 먼저 입증한다. native table 폭을 늘리거나 glyph 검사 허용오차를 높이지 않는다. 제목/Information의 glyph가 source text margin 위로 닿는 현상은 물리cell clip과 구분한다. 현재 cell-clip-* SVG id가 없다는 이유로 테스트를 통과시키거나 제품 clip으로 오판하지 않으며 실제4외곽rule+XML cell bounds를 기준으로 검사한다.

독립 회귀와 최신 로그는 `scripts/verify_native_illustrated_prose_frame_flow.py`, `tmp/september-exam-matrix/illustrated-final-verified.log`, `tmp/september-exam-matrix/illustrated-final-verified/report.json`에 보존한다. 전체 `ok=false`와 위 실패를 유지한다. 두 오른쪽 초과도 실제 PDF glyph bounds 기반이며 선택 face를 독립 확인하지 않은 PNG의 clipping 실패로 확대하지 않는다.

## 고3 title font: metric 복원과 실제 paint 선택의 차이

`ArialBlack`→`Arial Black`의 정확 alias는 이미 제품에 들어갔다. 고3 p4의 원본 embedded `ODBOIM+ArialBlack`16172B는 설치 ariblk.ttf와 sample glyph advance가 정확히 같고, alias 이후 native SVG66titleglyph/9폭이 원본 TTF와0.000034px 이내로 맞는다. 그러나 실제 `rhwp.render_pdf()`의 같은66glyph는 모두 **MalgunGothic**으로 그려진다. 즉 현재 남은 문제는 source typography 메타나 alias 미적용과 구분되는 paint face selection이다.

설치 ariblk.ttf는 name1=`Arial Black`, name16=`Arial`, name17=`Black`, weight900이다. fontdb0.23의 typographic family 우선 등록과 usvg system-font query가 legacy family 요청을 놓치는 경로가 확인됐다. PNG Skia 선택 face는 Python API에 노출되지 않아 PDF fonttrace를 PNG face의 증거로 쓰지 않는다.

다음 단계에서는 source-proven 정확 face+weight900에 한정해 PDF fontdb와 Skia 각각의 실제 face lookup/paint glyph를 probe한다. `Arial` 일반체 대체나 synthetic bold700을 정답으로 간주하지 않는다. native 편집용 family와 SVG metric 이름을 유지한 채 painting 단계에서 동일 source face를 선택할 수 있는지 검증한다. renderer/wheel 변경은 독립 소유 협의 후 별도 범위로 수행하고 Windows/macOS 각각 실제 title glyph 및 설치되지 않은 face의 fallback을 검사한다.

상세 근거는 `english-source-frame-font-diagnostics.md`의 Exact Arial Black/Remaining renderer 절과 `tmp/september-audit/high3-font-alias-current/{actual-title-glyph-verification,pdf-painted-title-fonts-exact}.json`이다. alias API 실행 중 다른 제품 파일이 바뀌었으므로 해당 점수는 preliminary이며 root의 최종 동결 matrix가 대체한다.

## 동결 직전 재저장 회귀

기존 고1June Q27의 50→60 작은 편집이 뒤 Q28 전체를5.333333px 움직인 원인은 source wrapper reserve0→save generic400 불일치였다. Choice agent의 좁은 변경은 table-contained dirty paragraph일 때만 기존 source reserve0..400을 유한성·wrapper/textHeight/insets 일치·direct cached descender로 측정하여 보존한다. 직접 문단 편집·direct cache 부재·잘못된 geometry는 기존400fallback이다. generic object/equation400은 유지한다.

fresh 전체 회귀 exit0: 작은 편집26333→**35changed pixels**, 8쪽 유지; 실제 nested-cell155자 증가·전체 가시 glyph bounds·그림/수식 보존·second save/fresh reopen PASS. 로그 `tmp/september-audit/grid-save-regression-fixed-fresh.log`, 결과 `tmp/september-audit/grid-save-regression-fixed-fresh/report.json`이다. 기존 수학/object400·directmissing·negative/401·NaN/Inf·descenderinvalid·forgedsourceflag negative도 PASS다. 이는 위 고2 Q27의 초기 fragment topology/누적 높이를 해결한 것으로 확대 해석하지 않는다.
