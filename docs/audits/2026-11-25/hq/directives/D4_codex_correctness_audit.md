# D4 Codex — 변경분 정확성 감사

## 역할
변경분의 버그와 회귀를 찾는 감사자. 설계 취향이 아니라 "이 입력에서 틀린 결과가 난다"를 찾는다.

## 볼 범위
`git diff 50cd57c eefba30 -- app` 전체와, 바뀐 함수의 호출 지점. 특히:
- `app/recognition/pdf_segment.py`: `_figure_has_graphics`, `figure_is_crop_candidate`, `_extract_figures`(반환형이 튜플로 바뀜 — 다른 호출자가 남았는지), `_range_heading`, `_page_leading_lines`, `_shared_passage_regions`, `_segment_page`의 단 판정·`crop_figures`·`leading_passage`, `_refine_problem_bottom(marker_line=...)`, `_extract_markers`의 여백 밴드.
- `app/recognition/pipeline.py`: `open_passage` 이어 붙이기(쪽 번호 비교, 같은 dict 변형), 지문 연결 루프, `render=False`일 때 달라지는 분기(`_page_fallback_problem`, 미연결 지문 폴백), `_text_light_figures`.
- `app/main.py`: `recognized` 전달, `quality_check="fast"`일 때 `fidelity` dict를 읽는 뒤 코드가 KeyError·잘못된 판정을 내지 않는지, `fast_check` 변수의 정의 범위.
- `app/pdf_native_content.py:1947` 부근과 `app/pdf_question_inspection.py:339` 부근의 번호 0 제외가 다른 집계(`source_problem_count` 등)와 어긋나지 않는지.
- `app/pdf_source_frame_geometry.py`: `page_memo`에 넣은 `get_drawings` 결과를 호출자가 변형하는지, 메모 키가 문서 닫힘 뒤에도 안전한지.
- `app/pdf_layout_writer.py`: `return stats` 뒤 도달 불가 블록이 문법·이름 해석상 문제를 일으키지 않는지.

## 찾을 것
1. 틀린 결과를 내는 구체 입력(시험지 배치, 값).
2. 예외가 날 수 있는 경로(None, 빈 리스트, 길이 불일치: `figure_graphics`와 `figures` 길이, `counts` 길이).
3. 기존 동작이 의도치 않게 바뀐 곳(영어 경로는 유지가 목표였다 — 정말 유지되는가).
4. 새 회귀 검사(`scripts/verify_recognition_content.py`)가 놓친 중요한 경우.
