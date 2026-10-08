# 9월 영어 기본 변환 진행 기록

2026-10-07. 현재 사용자 범위는 **기본 PDF → 편집 가능한 HWPX 변환**이다. 프리미엄 양식, 문항 순서 변경과 시험지 재구성은 이번 완료 조건에서 제외한다. 이전에 수행한 해당 경로의 검증은 별도 증거로만 보존한다.

원본은 2026-09-02 시행 고1·고2 전국연합학력평가와 2027학년도 고3 9월 모의평가다. 영어 세 원본은 각각 8쪽·45문항이다. 원본의 공식 목록, 다운로드 URL, 바이트 해시와 물리 쪽수는 `data/external_exam_qa`의 학년별 manifest와 전체 matrix의 source inventory에 보존했다.

## 확인하고 수정한 문제

| 문제 | 기본 변환 변경 | 독립 증거 |
| --- | --- | --- |
| 고1 첫 쪽의 덮인 옛 머리말 | 뒤에 그려진 완전 불투명 사각형이 실제 글자 잉크 전체를 덮은 경우만 옛 머리말을 제외한다. 부분 가림·반투명·비사각형은 제외하지 않는다. | `verify_masthead_visibility.py`; 실제 source paint order |
| 고1 머리말의 학년·우측 쪽수 | 원본 학년 표기와 실제 페이지 안의 우측 머리말 레일을 보존한다. | native/raster/source-page masthead 회귀 |
| 고2 Q2의 저작권법 선지 삭제 | 저작권 단어만으로 본문을 삭제하지 않는다. 하단 위치와 실제 저작권 안내 문구가 함께 확인되는 footer만 제거한다. | `tmp/september-audit/english-recognition-v2.log`; 실제 Q2 ⑤ 보존 |
| 고1 Q10 열린 가장자리 표 | 실제 수평·수직 규칙선과 셀 레일로 표를 복원한다. 비어 있는 줄·불완전 규칙선·잘못된 병합은 통과시키지 않는다. | `verify_pdf_open_edge_grid.py` 실제 원본 및 negative 회귀 |
| 고2 Q32 지문 중간 분할 | 전체 span 문자와 bbox가 일치할 때만 후행 공백의 과도한 bbox를 실제 비공백 잉크 폭으로 판정한다. 본문과 빈칸은 유지한다. | `tmp/september-exam-matrix/high2-prose-final.log`; 18행·987자 및 편집 성장/재열기 |
| 고3 기본 출력 9쪽 | 모든 source literal 항목과 native line cache가 입증된 문항 wrapper에서만 불필요한 400 HWP 높이 reserve를 제거한다. 일반 개체·수식·표 reserve는 유지한다. | `verify_native_source_question_height.py`; 실제 8쪽·45문항, Q27 편집 성장과 Q28 이동 |
| 고1 마지막 쪽 지문 상자의 누적 위쪽 이동 | 원본 레일의 0/근접 0 offset도 source proof를 거쳐 native flow 표로 만든다. 원본이 입증된 상자 앞 간격을 앞 문단 뒤로 옮기며 전체 높이는 유지한다. | `tmp/september-audit/high1-zero-rail-current/zero-gap-synthetic-final.log`; fresh API 출력 |
| 고2 Q10 표 행과 선택지 | 완전한 원본 규칙선 chain과 모든 열 레일이 입증될 때 검출기의 어긋난 행 경계를 실제 가로선으로 복원한다. 내부의 결손 셀과 실제 병합은 복원 대상으로 삼지 않는다. | `tmp/september-exam-matrix/high2-table-rail-final.log`; 실제 8쪽 복원, White/Black 누락·교환 negative |
| 고2 Q28 그림 안내문 | 원본 4개 규칙선·18행·실제 그림 2개의 픽셀과 소속이 입증된 경우 하나의 native 바깥 표에 본문/삽화 관계를 담는다. 그림은 inline 셀 안에서 본문과 함께 흐른다. 각 셀의 cache 폭·높이·양의 descender도 독립 검사한다. | `verify_native_illustrated_prose_frame_flow.py`; 원문·상대 baseline·17개 negative·편집 성장/재열기. 원본 절대 위치는 아직 실패 |
| 고2 Q28 항목의 이어지는 줄 들여쓰기 | 완전한 그림 안내문 안에서 반복 label-field의 실제 raw 문자·잉크 원점·선행 ASCII 공백 폭이 입증된 경우만 항목별 의미 문단과 native hanging indent를 복원한다. 이어지는 여러 줄은 한 문단으로 유지한다. | `verify_native_source_fields.py`; 실제 원본 7공백/36.95999pt, continuation x 오차 약0.002px, 기존5baseline·총flow6537HWP·원문/runstyle·8쪽 유지 |
| 고3 안내문 제목의 같은 폭 글자 | 원본 subset TTF와 설치 글꼴의 advance가 같은 것을 확인한 뒤 `ArialBlack`을 실제 family `Arial Black`으로만 정규화한다. 강제 bold는 추가하지 않는다. | `english-source-frame-font-diagnostics.md`; 실제 66 glyph의 가변 폭 복원. 렌더러의 painting 대체 글꼴 문제는 별도 미해결 |
| 고2 한국사 source 이미지의 0 높이 예외 | tiled-image 복원 후보의 실제 bbox·pixel 폭/높이를 검증한다. 보이지 않는 후보를 제외하되 독립 source image inventory는 유지한다. | `verify_native_tiled_frame_proof.py`; 실제 500→422, 남은 품질 거절은 별도 실패 |

## 현재 수치와 한계

아래는 각 수정 후 실행한 중간 결과이며, 서로 다른 시점의 코드를 한 번의 최종 matrix로 합치지 않는다. 같은 코드로 실행한 전체51부 기준과 이후 영어3부 재검사는 아래에 따로 기록했다.

| 결과 | 쪽수/문항 | 원문·독립 편집성 | 엄격 배치 | 판정 |
| --- | --- | --- | --- | --- |
| 고1 zero-rail/gap fresh API | 8/45 | 원문 1.0, editability true, 전체 8쪽 렌더 | 전체 93.21; 마지막 쪽 94.20. 이전 전체 89.82/마지막 67.53 | 목표 미달 |
| 고3 zero-rail/gap fresh API | 8/45 | 원문 1.0, editability true, 전체 8쪽 렌더 | 전체 87.04; 마지막 쪽 89.90. wrapper-height 수정 직후 전체 84.76/마지막 72.76 | 목표 미달 |
| 고2 rule-chain/illustrated frame fresh API | 8/45 | 원문 1.0, 독립 editability/open/render true | 전체 92.12, 최저 85.79, API 객관 89.75 | 목표 미달; 이후 cache guard 보강 영향 재검사 필요 |

고1 결과는 `tmp/september-audit/high1-zero-rail-gap-current/api_result.json`과 `evidence.json`, 고3 결과는 `tmp/september-audit/high3-zero-rail-gap-current/api_result.json`과 `evidence.json`에 있다. 각 fresh 출력의 코드 해시는 시작·종료가 같으며 원본 SHA-256도 동일하다. 고1·고3 실행 사이에 다른 제품 파일이 바뀌었을 수 있으므로 두 결과를 최종 안정 matrix로 합치지 않는다.

품질 기준은 변경하지 않았다. API 객관 점수 98, 외부 엄격 배치 평균 97/최저 95 및 원시 alignment/foreground 조건을 유지한다. 고1 API 객관 점수는 89.75이며, HTTP 200·8쪽·원문 보존 100%를 품질 목표 달성으로 부르지 않는다. 기본 native writer가 `source_layout_coverage_ratio=0.0`을 반환하고 고정 시험지 margin/gap profile로 구조 점수를 산정하는 진단 한계도 있으므로, 실제 배치 점수와 구조 점수를 함께 보존한다. 이 기록을 위해 점수 계산이나 기준을 변경하지 않았다.

고2 Q28은 본문·그림의 상대 위치, 실제 그림 픽셀과 동적 편집 흐름을 검사했으나, 상자와 그림 전체가 원본보다 약 19.82px 아래에 있다. 완전한 원본 절대 geometry gate는 여전히 FAIL이다. 앞 Q27의 분리된 본문/그림 흐름과 여유 높이가 원인 후보이며 고정 y offset으로 덮지 않았다. `Pre\u00ADregistration`의 원본에 보이는 hyphen은 XML과 native PNG에는 보존되지만, native PDF painting의 usvg/rustybuzz 경로에서 누락된다. 서로 다른 렌더 경로의 결과를 구분한다. 실제 원문 594개 font glyph와 native PDF glyph의 별도 검사에서는 Day1 `through`의 h가 우측 셀 경계보다 약 0.724px, Day3 `to`의 o가 약 0.465px 나오는 것도 확인했다. 본문 보존 1.0이나 상대 위치 통과로 이 실패를 감추지 않는다. 최종 근거는 `tmp/september-exam-matrix/illustrated-final-verified/report.json`과 `high2-illustrated-frame.md`에 보존했다.

추가 편집 회귀에서 기존 6월 고1 Q27의 `50 → 60 students` 변경 후 다음 Q28이 400 HWP(약 5.33px) 내려가는 문제를 수정했다. 모든 수정 문단이 표 안에 있고 실제 wrapper·여백·direct cache·기존 여유 높이 0~400이 일치할 때만 저장 전 여유 높이를 보존한다. 일반 수식·개체와 직접 문단 수정의 기존 400 fallback은 유지한다. fresh 전체 회귀에서 화면 변화는 26,333→35픽셀, 8쪽 유지로 통과했다. 155자 추가 시 상자 확장·실제 추가 glyph 경계·그림/수식 보존·반복 저장·fresh 재열기도 통과했다(`tmp/september-audit/grid-save-regression-fixed-fresh.log`). 실제 출력·편집 출력과 원인 A/B는 `tmp/september-audit/grid-save-regression-current`에 보존했다. 표 gutter 회귀의 merged-row negative 선택 오류는 실제 ①②③을 각각 입증한 뒤 변조하도록 고쳤고, missing/swapped/wrong-cell negative는 모두 유지했다(`final-regressions/table-gutters-final.log`).

전체 51부의 최초 기본 matrix는 실행됐지만 모두 품질 FAIL이었다. 실행 중 제품 코드가 바뀐 결과 11개도 포함되어 최종 안정 코드의 전체 검증으로 사용할 수 없다. 원본 inventory 51부·312쪽·1,355문항의 등록 증거와 품질 검증은 구분한다. 상세 계약은 `september-exam-matrix.md`에 있다.

전체 51부의 안정 matrix를 `tmp/september-exam-matrix/stable-all-51-20261007-final`에서 완료했다. 제품 SHA-256은 `7b63c82ddc00b5ff3cbfebe5c06fe0b34f5c26a7aeab0f1865a250bc68a0b916`이며 시작·종료가 같았다. 두 격리 batch의 원본 inventory 51부/312쪽/1,355문항/100,039,478바이트와 전체 case ID·fresh worker ID가 일치했다. `baseline_stability=STABLE`, 제품 snapshot 1개, manifest 오류와 incomplete 이유 0개다. 실행 예외/HTTP500은 없었다. **51부 모두 품질 FAIL**이며 HTTP200 10부, `strict_check_failed`/HTTP422 32부, `unsupported_structure`/HTTP400 9부다. HTTP200도 품질 통과로 세지 않는다. 개별 원인과 독립 검사는 `report.json`과 `findings.json`에 보존했다.

| 같은 안정 코드의 영어 결과 | 출력/문항 | 원문/독립 open·editability·render | 엄격 평균/최저 | API 객관 | 품질 |
| --- | --- | --- | --- | --- | --- |
| 고1 | 8/45 | 1.0 / 모두 true | 93.21/90.68 | 89.75 | FAIL |
| 고2 | 8/45 | 1.0 / 모두 true | 92.12/85.79 | 89.75 | FAIL |
| 고3 | 8/45 | 1.0 / 모두 true | 87.05/78.58 | 87.05 | FAIL |

세 영어 모두 원본 쪽 전체 비교·전체 출력 쪽 렌더·인쇄 문항 ID 일치·본문 raster 없음·전면 이미지/텍스트/수식 overlay 없음이 확인됐다. 고1·고2는 layout-view94% 조건을 충족하고 고3은 그 조건도 미달이다. 엄격 평균97/최저95, raw alignment96%/foreground97%와 API98 기준은 세 결과 모두 미달이다. 이 안정 실행 이후 고2 field/continuation의 source leading advance를 복원하는 좁은 수정에 착수했다. 위 결과를 그 이후 코드의 최종 51부 결과로 재사용하지 않는다.

field 수정 후 `tmp/september-exam-matrix/field-final-current/report.json`에서 영어 **3부만** 새 격리 worker로 재검사했다. 시작·종료 및 세 worker 제품 해시는 `dacd4d4d7719768269da6d486dce7ab19c28a7a6f5f2081c9e9af779f46caf97`로 같고, source inventory와 fresh worker ID도 일치한다. 세 부 모두 HTTP200/8쪽/45문항/원문1.0 및 독립 open·editability·render가 유지됐다. 엄격 평균/최저는 고1 93.21/90.68, 고2 92.12/85.77, 고3 87.05/78.58이며 API 객관 점수89.75/89.75/87.05로 품질 FAIL이다. 고2 평균은 반올림 수치가 같고 최저는85.79→85.77이므로 전체 점수 개선으로 설명하지 않는다. 복원 효과는 실제 source first-ink 좌표와 원문/스타일/높이 유지로 입증한다. 다른48부의 이후 코드 실행을 완료했다고 부르지 않는다.

전용 source-field 회귀는 실제18행·4개 의미 문단의 cache `[2,1,1,1]`, UTF-16 supplementary 문자, 기존 first-before137 보존, 기존 style 객체/bytes 유지와4개 append, 반복 적용 불변 및26개 잘못된 source/geometry/본문/수식/answerblank negative를 통과했다. 로그와 원시 수치는 `tmp/september-exam-matrix/field-product/source-fields.log`, `source-fields-report.json`에 있다.

별도 독립 통합 검사는 `tmp/september-exam-matrix/field-independent-verified/report.json`과 같은 이름의 `.log`에 보존했다. source18행/594개 실제 PDF glyph/원본 그림2개/22개 negative(기존17+field5), 원문·실제 charPr·flow6537·owner 높이31532 및 continuation 외 glyph x/y 변화0.05px 미만을 확인했다. 새 When 문단 자체의 public `add_run`으로 source cache를 무효화한 뒤 저장·fresh 재열기도 통과했다. left0/intent-2616과7개 continuation의 상대 들여쓰기가 유지되고, Where/Cost·그림2개·후속 선지가 같이 이동했다. 실제 추가/편집 PDF glyph249개의 인쇄 경계·그림 비겹침과 재저장 XML/렌더 좌표 안정성도 통과했다. 기존 본문/등록행 편집295/158glyph 검사도 통과했다. 원본 출력은8쪽이고 긴3단계 누적 편집 결과는 자연스러운 pagination으로9쪽이다. 독립 보고서의 **전체 exit1/ok=false**는 기존 절대 y+19.82px·PDF 오른쪽 glyph2개·PDF U+00AD 실패가 남았기 때문이며 이를 통과로 바꾸지 않았다.

동일한 코드로 별도 QA 서버를 재시작하고 브라우저의 기본 `HWPX로 변환`을 통해 고2 영어 원본을 새로 업로드했다. 변환·자동 다운로드·최근 변환·검수 내용 표시를 확인했다. 내려받은 파일과 서버 파일의 SHA-256이 일치하고, 독립 재열기·8쪽 전체 렌더·편집성 검사는 통과했다. 화면은 45문항/원본 8쪽 중 8쪽/출력 8쪽/텍스트 100%와 함께 자동 점검 89.8점·목표 98점 미달을 표시한다. 브라우저 console 오류/경고는 0건이었다. 증거는 repo 밖 QA 폴더의 `basic-high2-final-browser-verification.json`, `basic-high2-final-desktop.png`에 있으며 실제 한컴 GUI 편집·인쇄 검증으로 대신하지 않는다.

macOS는 `macos-readiness.md`에 별도로 기록했다. 소스 실행 가능성에 대한 정적 근거는 있으나 custom renderer의 Mac wheel과 실제 Mac 실행·편집·재저장 증거가 없다. Windows 결과를 Mac 품질 통과로 전용하지 않는다.
