# D1 Codex — 문항 인식 알고리즘 감사

## 역할
문항 세그멘테이션 알고리즘의 결함·일반화 한계·불필요한 비용을 코드에서 찾아내는 감사자.

## 볼 범위(저장소 경로 기준)
- `app/recognition/pdf_segment.py` 전체 — 특히 `_extract_markers`, `_filter_choice_like_markers`, `_filter_figure_embedded_markers`, `_cluster_columns`, `_refine_problem_bottom`, `_segment_page`, `_extract_figures`, `_merge_boxes`, `_english_reading_order`, `_english_shared_regions`.
- `app/recognition/pipeline.py` 전체 — 특히 `recognize_pdf`, `_page_needs_raster`, `_problem_has_figure`, `_page_shared_passage`, `_pua_ratio`.
- `app/recognition/cutout.py`, `app/recognition/schema.py`의 관련 부분.
- 기존 회귀: `scripts/verify_marker_regression.py`, `scripts/verify_recognition_schema.py`, `scripts/verify_lazy_pdf_raster.py`.

## 찾을 것
1. **오인식**: 문항 누락·과분할·병합이 나는 입력 조건. 마커 정규식 `^([1-9][0-9]?)([.)])(?:\s|$)`이 못 잡거나 잘못 잡는 번호 형식, 선지 억제 로직의 차선(lane)·간격 임계값이 깨지는 배치, 컬럼 클러스터가 3단·1단 혼합·전폭 지문에서 틀리는 경우.
2. **순서·상태 의존 버그**: 정렬 기준, 누적 상태(lane의 지수 이동 평균 등), 페이지 간 이월이 결과를 바꾸는 곳.
3. **불필요한 비용**: 같은 페이지를 여러 번 파싱·렌더하는 곳, O(n²) 이상 루프, 버려지는 char 단위 페이로드 생성.
4. **하드코딩 임계값**: 픽셀 절댓값이 dpi나 용지 크기에 비례하지 않는 곳.

## 출력
D0의 7칸 형식으로 8~15건. 맨 위에 인식 알고리즘 점수(100점)와 총평.
