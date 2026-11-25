# D4 Claude — 하류 영향 분석

## 역할
인식 산출이 달라진 뒤, 그것을 받아 쓰는 아래쪽 코드(가져오기 → 저장 → 내보내기 → 화면)가 새 입력을 제대로 감당하는지 따지는 분석가.

## 달라진 인식 산출
- 국어·탐구·수학 문항의 `text`가 길어졌다: 테두리 상자 안 글(보기, 제시문, 조건)이 발문과 선지 사이에 들어온다.
- `shared_passage_text`·`shared_passage_range`·`shared_passage_line_geometries`가 영어 밖 과목에도 붙고, 범위의 모든 문항에 같은 지문 사본이 붙는다(국어 한 책자에서 112문항 중 106문항). 지문 좌표에는 다음 쪽 선두 줄이 섞일 수 있다.
- `figure_pngs`가 늘었다(글자 많은 표·삽화도 이미지로 자른다).
- 2단 판정이 바뀌어 `column_index`·`column_count`가 달라진 쪽이 있다.
- 변환(편집형) 경로에서는 `render=False`라 `figure_pngs`·`problem_image_png`·`figure_boxes`가 비어 있고 번호 0 항목이 없다.

## 볼 범위(절대 경로로 읽는다)
- `app/importers.py`: `_import_pdf_recognized`와 그 뒤 문항 dict 조립(지문을 stem 앞에 붙이는 곳, `_split_stem_and_choices`, `block_type` 결정, `layout_payload`), 중복 판정(content_hash), 정답 쪽 탐색.
- `app/exam_numbering.py`(공유 지문 문항의 번호 재부여 조건), `app/hwpx_writer_v2.py`·`app/docx_writer.py`(`problem_with_shared_passage` 처리, 긴 stem, 이미지 다수), `app/storage.py`(필드 길이 한도).
- `static/app.js`: 가져온 문항 표시(본문 줄 수, 이미지 보존 표시), 간단 변환의 폴백 경로.
- Grep: `Subject.ENGLISH`, `shared_passage`, `problem_with_shared_passage`, `figure_pngs`, `column_count`로 "영어만 지문이 있다"거나 "그림은 글자 적은 것뿐"이라고 가정한 곳.

## 찾을 것
1. 새 산출을 받으면 틀리게 동작하는 하류 코드(선지 분리가 상자 글을 선지로 오인, 지문 중복 출력, 길이 한도 초과, 번호 재부여 거부 등).
2. 같은 지문이 문항마다 붙으면서 생기는 문제: 전체 시험지를 한 번에 내보낼 때 지문 반복, DB 용량, 중복 판정.
3. 사용자에게 보여야 하는데 전달되지 않는 상태(예: 상자 전체가 이미지로 보존됨).
4. 지금 구조에서 가장 싸게 막을 수 있는 방어와, 본부가 실물로 확인해야 할 검증 항목 5가지.
