# 원본 공백·짧은 span 글자 간격 독립 검토

제품 코드는 수정하지 않았다. 검토 대상은 `pdf_source_span_metrics.py`, `pdf_source_run_styles.py`, `pdf_source_choice_spaces.py` 및 실제 PDF를 다시 여는 공통 `_actual_rows` 증명이다. 기존 본문 전체 font 경로를 새 helper가 모두 검증한다는 의미로 확장하지 않는다.

## 근거와 적용 범위

- Wrapped span ratio는 실제 원본 프레임·모든 인쇄행·그림을 증명하고 raw glyph/font/flags/size/origin/bbox를 대조한 뒤, 별도 PDF text trace의 수평 transform을 사용한다. 완전히 일치하는 singleton glyph도 그 transform의 근거가 될 수 있다. 새로운 Latin 3-pair tracking은 이 ratio 증명을 통과한 span에서만 허용된다. 기존 일반 Times 경로의 4-pair 기준은 유지된다. 숫자·문장부호 대안은 증명된 span의 실제 4-pair 이상을 요구한다.
- Wrapped synthetic space는 `_actual_rows`가 원본의 모든 span/char를 다시 대조한 뒤 **실제 PDF**의 synthetic 표시와 두 ink glyph 사이의 빈 구간을 사용한다. supplied metadata의 synthetic 표시로 대체하지 않는다. 수평 Haansoft Batang, 같은 baseline, 한 span 안의 단일 ASCII space만 대상이다.
- Choice space는 실제 한 행의 circled choice에 대해 PDF path/page/width, row bbox/text, 모든 span 및 glyph를 대조한다. 현재 producer의 실제 영어 subject 판정이 `source_literal_text`를 생성한다. 이 helper의 실제 geometry 증명과 그 호출부 subject 분류는 별도 조건이며, metadata flag 하나가 원본 좌표를 대신하지 않는다. 표/다행/빈칸/inline label은 제외한다.
- Regular Times의 실제 비합성 공백 3개 이상이 같은 간격임을 증명한다. 보정은 nonspace cursor에 대응하는 native 단일 ASCII space에만 적용한다. double space, NBSP, tab에는 새 공백 스타일을 적용하지 않는다. 문자나 공백 자체를 삽입·삭제하지 않는다.
- Native space의 `.5em * ratio + tracking`과 기존 음수 자간 하한을 같이 계산한다. `(80,-15)`는 `.25em`, `(80,-19)`는 `.21em`이며 각각 하한 `.2em` 이상이다. 측정치를 합법적인 스타일로 표현할 수 없는 경우 보정하지 않는다.

## 실행한 검사

| 검사 | 결과 | 로그 |
|---|---|---|
| `verify_native_source_span_metrics.py` | exit0; 실제 18행/23 spans, synthetic space6, 20 negatives | `tmp/renderer-square/final-artifacts/review-source-span-metrics.log` |
| `verify_native_source_choice_spaces.py` | exit0; 실제 source space8, 30 negatives | `tmp/renderer-square/final-artifacts/review-source-choice-spaces.log` |
| `verify_native_source_run_styles.py` | exit0; mixed style와 기존 일반 Times tracking 보호 | `tmp/renderer-square/final-artifacts/review-source-run-styles.log` |
| 신규 `verify_source_whitespace_review.py` | exit0; 독립 cursor/empty/metadata/실제 allocator 13 checks | `tmp/renderer-square/final-artifacts/review-source-whitespace-cursor.log` |

신규 검사는 실제 고3 PDF의 원문에서 공백 앞 nonspace 수를 독립 계산한 `[12,13,18,21,24,31,33,36]`과 적용 위치를 대조한다. 한 run, 각 글자를 별도 run으로 분할하고 empty run을 끼운 경우, 앞뒤 공백 추가 모두 정확히 일치한다. double/NBSP/tab은 특수 공백 스타일을 받지 않는다. 제공된 synthetic 표시를 전부 true로 바꿔도 실제 PDF 판단이 바뀌지 않는다. span origin/bbox·row text 위조, source records 없음, native text 없음도 확인했다. 원문은 그대로 유지됐다.

최신 검토 코드 SHA는 `tmp/renderer-square/source-whitespace-review/report.json`에 기록했고 검증 전후 같았다. 실제 glyph paint/전체 페이지 품질을 이 helper 검사로 대체하지 않는다.

## Idempotence와 fingerprint 구분

기존 helper tests는 base style ID를 제외한 목표 스타일 값으로 memoize하는 시험 allocator를 사용한다. 제품 `char_style`은 base ID도 key에 포함한다. 실제 nested allocator 소스를 실제 HWPX header 복사본에서 실행해 helper를 두 번 적용하면 style 수가 142 → 145로 늘고 raw run XML의 style ID도 바뀐다. 따라서 제품 수준의 **raw style-ID idempotence**를 이 tests로 주장할 수 없다.

같은 검사에서 원문과 resolved character/paragraph style 및 fontfaces 기반 `paragraph_fingerprint`는 정확히 같았다. 이것은 namespace/ID 변동과 의미 있는 스타일 변경을 구분하는 snapshot 계약에 부합한다. 통상 import 경로는 `nativeSourceItem`을 첫 typography pass에서 제거하며 public save가 이 source helper를 다시 적용하지 않으므로, 이번 review에서 실제 save-path 회귀로 판정하지 않았다. 반복 재적용을 향후 지원한다면 실제 allocator로 raw-ID 안정성을 별도 검증해야 한다.

## 전체 결과와 구분할 한계

고정 입력 A/B의 최대 bullet x 오차 `.918px`는 실제 writer 결과가 아니다. 실제 final8 source-only 결과의 최대치는 `1.819px`이며 이를 완전 일치로 부르지 않는다. 새 bullet-inclusive PDF 검사는 실제 664 glyph/6 bullets의 bounds·그림 비중첩 component를 통과했지만, 실행 중 다른 app 파일이 추가되어 전체 snapshot 검사는 **FAIL**이었다. 근거: `tmp/september-exam-matrix/q27-final8-bullet-inclusive/report.json`. 최종 통합 freeze 뒤의 fresh full 결과가 별도로 필요하다.

이 검토는 목표98, source fontface 완전 복원, U+00AD PDF painting 또는 Mac 런타임을 통과시켰다는 의미가 아니다. 신규 body-space helper는 이 문서 작성 시점에 아직 검토하지 않았다.
