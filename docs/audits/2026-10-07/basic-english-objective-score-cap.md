# 기본 영어 변환의 현재 구조 점수 한계

범위는 기본 PDF→편집 가능한 HWPX다. 프리미엄 양식과 순서 변경은 포함하지 않는다. 이 문서는 읽기 전용 분석이며 점수·가중치·통과 기준·판정 코드를 변경하지 않았다.

고정 `field-final-native3-20261007` 결과에서 고1과 고2는 실제 렌더 harsh mean이 각각93.21/93.29인 반면 API objective는89.75다. objective는 구조 가중 점수와 실제 렌더 점수의 최솟값을 사용한다. 고3은 실제 렌더87.05가 더 낮다. 따라서89.75가 전체 페이지의 실제 시각 일치도를 직접 뜻하지 않는다.

고1 evidence의 구조 점수에서는 다음 감점이 있다.

- layout80/100: 질문별 native text box 소속·문단·쪽/단 나눔은 확인됐지만 `recognize_pdf_native`가 `source_layout_coverage_ratio=0.0`을 반환한다. source 좌표를 완전히 보존한 정도를 별도 증명하지 않은 현재 상태에 점수를 추가할 수 없다.
- paging65/100: native 실제 여백은 left21.936/right21.636/top27.414~28.494/bottom17.999mm이며 단 사이 간격4.427mm다. 현재 스타일 검사는 top17~23mm 및 단 간격6~10mm의 고정 프로필을 요구한다.
- 다른 다섯 구성 항목은100이다. 가중 합계89.75가 실제 렌더93.21보다 낮아 objective를 제한한다.

근거: `app/main.py::_pdf_structured_objective_score`, `app/pdf_layout_writer.py`의 스타일 프로필 검사, `app/pdf_native_content.py::recognize_pdf_native`의 source-layout 통계와 `tmp/september-exam-matrix/field-final-native3-20261007/cases/2026_september_high1__eng_1_d161fb23/structured/evidence.json`.

원본 보존 변환과 고정 시험지 프로필의 관계를 추후 검토할 때도 source 좌표·실제 native 배치·완전한 원문/그림/문항 소속과 쪽/단 구조를 독립적으로 증명해야 한다. 단순 출력 개수나 metadata 플래그로 source-layout 점수를 채워서는 안 된다. 실제 렌더97/95, raw alignment/foreground 및 API98 기준은 유지한다. 현재 전체 품질 PASS를 주장하지 않는다.
