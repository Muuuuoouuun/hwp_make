# 고3 9월 영어 p2 지시문·본문 경계

활성 범위는 기본 PDF 원본 배치의 editable native HWPX다. 프리미엄 양식과 문항 순서는 이번 변경에 포함하지 않는다.

## 원인과 변경

실제 원본 `data/external_exam_qa/2027_kice_september_high3/english.pdf`의 p2 Q19/Q20은 한국어 지시문 뒤에 별도 영어 본문이 있다. 기존 변환은 두 의미 문단을 LEFT 문단 하나로 합쳤다. 인쇄행 cache의 `horzpos`만으로는 편집기에서 본문의 continuation rail과 첫 줄 들여쓰기를 유지하지 못했다. Q19 첫 본문 글자는 원본보다 약 20.532px 왼쪽, 이어지는 행은 약 10.635px 왼쪽에 있었다.

`pdf_source_question_body.py`는 실제 PDF의 원문 raw spans/characters/font/size/bbox/origin을 다시 대조한 뒤, 한국어 번호 지시문과 균일한 영어 본문의 rail·첫 줄 들여쓰기·행간·의미 간격이 함께 입증될 때만 두 문단으로 나눈다. 원문 행을 각각 문단으로 만들지 않는다. 영어 본문은 한 문단이며 원본의 left/first indent를 native 문단 속성으로 보존한다. 특정 문항 번호·본문 문자열·좌표를 선택 조건으로 사용하지 않는다.

혼합 글꼴 지시문의 큰 번호 run보다 cache 높이가 작은 문제도 실제 source/native 문자별 높이를 재검증한 경우에만 보완했다. 원래 run과 공유 스타일은 바꾸지 않고, 가장 큰 원본 span에 맞는 cache를 구성한다. 일반 수식·다른 과목·원문 미일치·rawchars 누락·빈칸 밑줄·그림 교차·비정상 geometry에서는 원래 경로로 돌아간다. source PDF 경로와 page index는 재검증에 쓰는 provenance이며 메타데이터 자체가 허용 근거는 아니다.

## 실제 검증

fresh 출력은 `tmp/september-exam-matrix/high3-p2-readonly/producer2.hwpx`다. 실제 렌더에서 8쪽을 유지한다. Q19/Q20 본문은 각각 원본 10/16개 인쇄행을 가진 하나의 의미 문단이며 native left/intent는 원본 raw first ink로 계산한 798/742 HWP다.

| 항목 | 실제 PDF 결과 |
|---|---:|
| Q19 본문 first-ink x 최대 오차 | 0.0054px |
| Q19 본문 first-ink y 최대 오차 | 0.4874px |
| Q20 본문 first-ink x 최대 오차 | 0.0117px |
| Q20 본문 first-ink y 최대 오차 | 0.0448px |

`scripts/verify_native_source_question_body.py --hwpx tmp/september-exam-matrix/high3-p2-readonly/producer2.hwpx`는 127 checks/38 negative, exit0이다. 실제 raw source 완전성, native 캐시만의 원자적 수정, 원래 문자별 resolved style 보존을 확인했다. public `add_run`으로 본문 cache를 무효화한 뒤 save/fresh reopen/resave에서 두 들여쓰기와 본문 소속을 유지하고 후속 선지가 아래로 이동했으며 p2 실제 SVG painting이 재저장 전후 같다. fixture가 없으면 명시 SKIP/exit2다. 결과는 `tmp/september-exam-matrix/source-question-body-regression/report.json`, 로그는 `tmp/september-exam-matrix/high3-p2-readonly/source-body-regression.log`에 있다.

## 2026-10-08 오른쪽 기준선 보정

본문의 비마지막 줄 ink right를 실제 PDF에서 재검증한 경우에만 native 오른쪽 문단 여백을 복제한다. 지시문과 본문이 기존 의미 경계에서 이미 나뉜 Q22/Q23도 같은 원문 증명 정보를 보존한다. 실제 Q19/Q20/Q22/Q23의 오른쪽 여백은 각각 516/523/520/518 HWP이며 특정 문항 번호나 좌표를 선택 조건으로 쓰지 않는다.

허용 조건은 전체 raw 원문 재대조, 현재 native 문자/공백/폰트/크기/굵기/기울임/장평/자간/상대 크기/오프셋 대조, 실제 editable 텍스트박스 폭과 기존 들여쓰기 대조다. 원본에서 `apply_source_line_cache`를 다시 실행한 cache와 모든 필드를 정확히 비교한다. 일반 저장의 누적 정수 반올림은 원본으로 다시 만든 본문을 컨테이너에 넣어 저장 시 reflow를 재현한다. 정상 Q20의 실제 native 들여쓰기는 모든 source bbox의 최소값을 쓰므로 첫 continuation rail의 반올림값과 1 HWP 차이가 난다. 기존 source proof 범위에서 검증한 현재 들여쓰기를 cache 재계산에 쓰며 cache 허용 오차는 늘리지 않았다. 캐시 누락·중복, 위조된 y/height/leading/flags, 텍스트/control/style 변경, 폭·원문·기하 불일치에서는 수정 없이 거절한다.

최종 새 writer 출력은 `tmp/september-exam-matrix/body-alignment-final-20261008/final/native.hwpx`다. 생성 전후 관련 app fingerprint는 같다. 최종 전용 검증은 785 checks/332 negative, exit0이며 8쪽과 public `add_run` → save → fresh reopen/resave의 본문 소속·원래 resolved 문자 스타일·후속 선지 이동·p2 SVG 안정성을 확인했다. left/intent/right는 초기·편집 저장·재열기 모두 798/742/516으로 같다. 보고서는 `final-verified/report.json`, 로그는 `final-verified.log`다.

기존 의미 문단 경계에서 이미 분리된 Q22/Q23에는 앞 지시문의 증명 metadata가 연결되지 않아 cache height가 792 HWP로 남고 실제 큰 번호 run의 930 HWP를 수용하지 못했다. 해당 원문 pair가 `split_source_question_body`의 전체 raw-source proof를 통과하고 바로 앞 결과 문단이 그 지시문 행과 정확히 같을 때만 같은 proof를 앞 문단에도 전달한다. 기존 최대 native/source 높이 cache helper를 재사용하며 일반 간격 코드는 수정하지 않았다. 전체 생성 A/B에서 Q22/Q23 본문 y 최대 오차가 2.767897/2.756960px에서 0.022719/0.033887px로 줄었다. 최종 제품 출력에서도 동일하게 확인했다.

Q22/Q23 밖의 visible nonspace glyph 25,719개는 전체 생성 A/B 및 최종 제품 출력 모두 x/y 변화가 정확히 0px이다. 전체 27,781개 glyph 순서와 8쪽도 같다. Q19/Q20의 모든 본문 x/y와 Q22/Q23의 모든 본문 x가 같다. A/B 보고서는 `prompt-pair-producer-ab/ab-measurement.json`, 최종 제품의 독립 대조 보고서는 `final-verified/ab-measurement.json`이다.

first-ink 복원이 모든 glyph의 복원을 뜻하지 않는다. 실제 본문 glyph 2,966개를 원본 raw origins와 대조한 결과는 다음과 같다.

| 본문 | 전체 glyph 최대 수평 오차 | 마지막 줄 최대 수평 오차 | 전체 glyph 최대 세로 오차 |
|---|---:|---:|---:|
| Q19 | 5.284px | 2.686px | 0.487px |
| Q20 | 4.636px | 1.829px | 0.045px |
| Q22 | 7.061px | 1.611px | 0.023px |
| Q23 | 2.966px | 2.966px | 0.034px |

전체 glyph 보고서는 `final-verified/report.json`의 `every_proved_body_glyph_diagnostic`이다. 원본 Times 공백 보정 자체는 별도 `english-body-word-spaces.md`에 기록한다. 회귀 JSON은 `full_fidelity_claim=false`, `remaining_wordspace_fidelity.ok=false`를 유지하며 이 의미 문단·source proof PASS를 전체 영어 품질 달성으로 집계하지 않는다.

추가 검토에서 확인한 fractional raw flags는 finite/integral 검사로 거절한다. source proof와 typography 양쪽 변조를 검사하며 native emboss/engrave도 strikeout과 함께 지원하지 않는 효과로 거절한다. 독립 late-guard 검증은 실제 네 본문의 양성과 다섯 변조의 원자적 거절을 포함해 PASS14였으며 보고서는 `tmp/september-audit/body-right-independent/report-late-fixed.json`이다.

현재 최종 파일을 대상으로 한 독립 전체 검토도 PASS94, source/helper fingerprint stable이다. 범위는 해당 네 본문의 source/native guard이며 전체 인쇄 품질 판정은 아니다. 보고서는 `tmp/september-audit/body-right-independent/report-final-revised.json`이다.

## 초기 네 본문 동결 뒤 혼합 스타일: Q21/Q24 진단 기록

초기 네 본문의 성공을 당시 Q21/Q24에 확대하지 않았다. Q21/Q24는 각각 20/18개 source body 행을 가진 별도 의미 문단이지만 당시 `source_question_body` 증명과 오른쪽 여백·자연 공백 처리를 받지 않았다. 당시 native left/intent/right는 Q21 797/742/0, Q24 798/742/0이며 실제 본문 최대 x/y 오차는 Q21 13.9813107/2.9790522px, Q24 8.0687941/2.7513789px였다.

Q24의 raw faces는 12.18pt Times regular와 italic이다. 같은 family여도 현재 raw-font 단일성 조건에서 거절된다. 원본 재대조와 기존 기하 조건을 유지한 메모리 내 family-only split 진단에서는 두 의미 부분으로 증명된다. Q21은 같은 italic 단어 외에 작은 11.2088pt 명조 ` ―` span이 있다. family-only 진단도 거절하고, 정확히 하나의 source-proven `Pd` 구두점 glyph만 낮은 크기 범위에서 허용한 메모리 내 진단에서 두 부분으로 증명된다. 제품 코드는 바꾸지 않았다.

후속 확장은 원래 raw font/flags/size를 그대로 검증하면서 regular/italic Times의 family membership만 판정해야 한다. native 각 글자의 italic·font·height·tracking·ratio를 원본대로 대조하고, italic 제거/추가·다른 family·bold·baseline/size 변경·부분 source·원문 공백·cache/폭/문자 변조를 원자적으로 거절해야 한다. Q21의 isolated dash fallback은 일반 본문 font 예외로 넓히지 않고, 원본에 존재하는 구두점·크기·baseline·native fallback font를 개별 증명해야 한다.

공백 증명은 별도 문제다. 현재 helper는 italic을 포함한 모든 혼합 face를 거절한다. Q21 명조 span의 공백 bbox는 0.235276em으로 Times의 0.25em과 다르므로 모든 공백에 같은 값을 적용할 수 없다. Times 공백과 fallback 공백을 구별해 실제 source/native advance를 증명해야 한다. Q24 마지막 행은 공백 하나뿐이므로 현재 자연 advance 3개 이상 조건도 통과하지 못한다. 이 조건을 단순히 낮추기보다 같은 실제 source font/style의 독립 자연 advance나 내장 font metrics로 보강해야 한다. 실제 생성 A/B와 전체 glyph/쪽수/다른 문항/편집 검증 전에는 후속 확장의 개선을 주장하지 않는다.

진단 결과와 app fingerprint 불변 증명은 `tmp/september-exam-matrix/body-alignment-final-20261008/mixed-style-readonly/report.json`에 있다.

## 혼합 스타일 전체 생성 A/B 기록

동결된 app 파일은 바꾸지 않고 메모리 안에서 source proof만 확장한 fresh writer/render A/B를 실행했다. Q24의 같은 Times family regular/italic 허용은 native 오른쪽 여백을 0→518 HWP로 복원하고 전체 glyph x 최대 오차를 8.068794→3.743511px, y 최대 오차를 2.751379→0.044848px로 줄였다. 비마지막 줄 x 최대 오차는 1.286755px이며 마지막 줄 공백 오차는 그대로다. 전체 27,781개 glyph 순서와 8쪽, Q24 밖의 26,683개 glyph x/y가 정확히 같다. 원래 resolved 본문 문자 스타일도 같다. 보고서는 `mixed-family-producer-ab/ab-measurement.json`이다.

Q21의 source-proven 단일 `Pd` fallback까지 허용한 첫 A/B에서는 비마지막 줄 x가 개선됐지만 y가 악화됐다. 원인은 두 줄 지시문의 첫 cache 보정 뒤, 나중 indentation 단계가 dominant 792 HWP cache로 다시 생성하는 순서였다. 임시 보정 시 계산한 문단 간격 309 HWP만 남아 원래보다 117 HWP 아래로 이동했다. 이 실패 결과는 `mixed-punctuation-producer-ab/instruction-cache-ab.json`과 같은 폴더의 A/B 보고서에 보존했다.

후속 임시 A/B는 실제 지시문 각 행의 source/native UTF16 문자 범위를 재검증해 height 930/792, baseline 791/674를 각각 유지했다. 원본 baseline 간격 1264 HWP를 유지하려면 두 번째 top은 1381 HWP이며 spacing은 451/472 HWP다. indentation 뒤에도 같은 전체 원문과 현재 native 들여쓰기로 재증명한 cache만 적용했다. 일반 간격은 수정하지 않았다. Q21 y 최대 오차는 2.979052→0.040844px, 비마지막 줄 x는 7.592818→2.135890px다. 마지막 줄 x 13.981311px는 그대로이며 공백 충실도 개선을 주장하지 않는다. Q24 개선은 그대로 유지하고 모든 원래 문자 스타일도 같다. 전체 27,781개 glyph/8쪽이 같으며 Q21/Q24 밖 25,382개, family A/B 대비 Q21 밖 26,480개 glyph 변화는 정확히 0px다. 보고서는 `mixed-perrow-producer-ab/ab-measurement.json`이다.

같은-font 거절 조건 하나만 제거한 고1/고2 임시 A/B는 별도로 보존했다. 고1 본문 rail은 복원됐지만 분리 후 일반 source typography 재계산이 기존 98/-3 또는 98/-1 장평/자간을 100/0으로 바꿔 일부 glyph 오차가 커졌다. 고2는 painting이 전혀 바뀌지 않았다. 이 결과로 해당 거절 조건의 단독 제거를 제품에 반영하지 않는다. 보고서는 `samefont-high1-producer-ab/ab-measurement.json`과 `samefont-high2-producer-ab/ab-measurement.json`이다. Haansoft Batang 공백은 Times quarter-em으로 추정하지 않는다.

후속 source-completeness 검토에서는 실제 원문에 포함된 행이라는 사실만으로 전체 본문을 증명할 수 없다는 점을 확인했다. 마지막 한두 행을 원문 proof와 native에서 함께 제거하면 기존 split이 허용했다. 일반 completeness 후보는 실제 같은 column의 지시문부터 마지막 본문까지 모든 raw 행 signature의 순서를 대조하고, 뒤의 실제 선택지 ①까지 optional vocabulary-note 경계를 확인한다. 별표만으로 note를 인정하지 않고 영어 headword/colon/한국어 gloss, 더 작은 원본 글자 크기와 인접 간격도 검사한다. 후보는 실제 11개 pair에 통과하고 마지막/중간 행 누락·중복·역순 변조를 거절했으며 독립 검토에 넘겼다. `terminal-coverage-readonly.json`과 `perrow-guards.json`은 제품 반영 전 후보 검증이며 기존 785-check 제품 결과를 대체하지 않는다.

## 실제 통합 제품 반영과 범위

위 A/B에서 검증한 Q21/Q24의 mixed Times 및 단일 `Pd` 원문 조건, 지시문 행별 font-height cache, indentation 뒤의 재증명 hook을 제품에 반영했다. `source_question_body_complete(page, instruction, body, source_lines=...)`는 실제 PDF의 전체 ordered column band와 인접한 vocabulary-note/첫 선택지 경계를 재검증한다. 영어 headword·colon·한국어 gloss 없이 별표로 시작하는 본문 행은 note로 인정하지 않는다. 더 작은 source font 및 실제 baseline/gap 범위도 모두 필요하다. 독립 검토는 실제 11개 양성과 120개 음성을 포함한 PASS131이며 `q23-single-space-prototype/generic-coverage-review.json`에 있다. 이 판정은 기존 raw/style/semantic/rail 증명과 함께 쓰는 좁은 경계 검사다.

같은 font를 쓰는 한국어 지시문/영어 본문은 이미 존재한 의미 문단 경계에서만 추가 증명한다. `split_source_question_body(..., existing_boundary=True)`도 기존 원문·기하·완전성 조건을 모두 통과하고 `source_body_span_ratios(page, body_rows)`가 모든 실제 span/raw/visible trace를 증명해야 한다. producer의 `previous_split` 경로에만 이 mode를 사용하며 proof의 `boundary_mode`는 `existing`이다. 새 의미 분리의 mode는 `split`이다. mode 값만으로 source/style/trace 검사를 생략하지 않는다. 기존에 합쳐진 같은-font 문단은 분리하지 않아 고1 지시문의 관찰된 spacing 회귀를 피한다. 같은-font 문자 metric 자체의 proof와 결과는 root 소유 `pdf_source_body_metrics.py` 검증에서 별도로 다룬다. 본문 오른쪽 여백과 Times 공백 조건을 Haansoft Batang으로 확대하지 않았다.

native 본문 공백도 인접한 다음 source 문자에 대응하는 모든 언어 slot의 font, height, bold, italic을 검증한다. 기존 ratio/tracking/relSz/offset/effects 검사와 함께 적용하므로 공백 하나의 height나 face만 바뀌어도 원자적으로 거절한다. 지시문 helper는 source에서 다시 계산한 record text/baseline/size를 정확히 대조하고, 중복 cache/지원하지 않는 문단 자식을 거절한다.

root의 새 실제 writer 산출물은 `tmp/september-exam-matrix/basic-english-integrated-high3/native.hwpx`이며 생성 전후 전체 app hash가 같다. 실제 PDF는 8쪽, visible nonspace glyph 27,781개의 순서를 유지한다. Q21/Q23/Q24 밖 24,270개 painted glyph tuple이 초기 네 본문 산출물과 정확히 같다. Q23 terminal row 밖 27,767개 tuple은 성공한 mixed-perrow A/B와 정확히 같다. Q19/Q20/Q22의 모든 x/y와 모든 원래 resolved 문자 스타일, Q21/Q24의 원래 resolved 문자 스타일도 같다. Q23은 source-backed terminal 공백 스타일 한 곳만 좁혀 마지막 행을 개선한 별도 helper 변경이다.

실제 여섯 본문의 모든 glyph 4,832개를 측정한 잔여 오차는 다음과 같다. 보고서는 `body-alignment-released-20261008/integrated-measurement.json`이다.

| 본문 | 오른쪽 여백 HWP | 전체 glyph 최대 수평 오차 | 마지막 줄 최대 수평 오차 | 전체 glyph 최대 세로 오차 |
|---|---:|---:|---:|---:|
| Q19 | 516 | 5.284px | 2.686px | 0.487px |
| Q20 | 523 | 4.636px | 1.829px | 0.045px |
| Q21 | 518 | 13.981px | 13.981px | 0.041px |
| Q22 | 520 | 7.061px | 1.611px | 0.023px |
| Q23 | 518 | 1.634px | 0.216px | 0.034px |
| Q24 | 518 | 3.744px | 3.744px | 0.045px |

source/native 오른쪽 여백 독립 검토는 이 통합 입력의 실제 여섯 본문을 포함해 PASS98이다. 보고서는 `tmp/september-audit/body-right-independent/report-integrated-six.json`이며 app/runtime fingerprint가 같다. 전체 glyph 수평 잔여 오차가 남아 있으므로 이 결과는 의미 경계·font/cache/rail·편집 안정성의 성공이며 전체 영어 인쇄 충실도 PASS가 아니다.

최신 전용 제품 검증은 1,464 checks/630 negatives, exit0이다. 지시문 cache 양성 6개, 실제 두 줄 cache와 native/source 동시 truncation·공백 native font/height/bold/italic/언어 slot 변조의 원자적 거절을 포함한다. public 편집은 Q19/Q21/Q24 각각에 추가 문자열을 넣어 cache 무효화, 원래 resolved 문자 스타일과 left/intent/right 보존, 후속 선지 이동, fresh reopen/resave 이후 모든 편집 페이지의 SVG 동일성을 확인했다. 초기 출력은 8쪽이며 편집 후 각 출력은 9쪽이다. 보고서는 `tmp/september-exam-matrix/body-alignment-released-20261008/final-verified/report.json`, 로그는 같은 상위 경로의 `body-alignment-released-20261008-final-verified.log`다. body/content/typography 세 소유 app 파일 fingerprint가 검증 전후 같다.
