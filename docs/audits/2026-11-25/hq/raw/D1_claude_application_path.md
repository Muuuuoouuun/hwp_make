# D1 결과 — 인식 결과의 적용 경로 추적

## 적용 경로 점수: 55 / 100

**총평.** 인식 단계는 문항마다 많은 정보를 만듭니다: 줄·문자 좌표, 그림 bbox와 PNG 잘라낸 그림, 텍스트 신뢰도(text_reliable), 단(column) 위치, 공유 지문, 라우팅, notices. 그런데 기본 편집형 내보내기(`write_native_content`)가 실제로 쓰는 것은 (쪽, 번호) 인벤토리, 쪽 수, 신뢰도 낮은 문항 수 세 가지뿐입니다. 본문은 원본 PDF를 처음부터 다시 추출해 만듭니다. 그래서 인식이 한 래스터 렌더와 PNG 인코딩은 이 경로에서 그대로 버려집니다.

같은 내보내기 한 번에 `recognize_pdf`는 두 번 돕니다(작성기 1번, 편집성 검사 1번). 이 두 번은 모두 메모리 스트림으로 PDF를 열기 때문에 쪽 메모(`pdf_source_page_memo`)가 전혀 덮지 못합니다.

인벤토리를 맞춰 보는 데서 실패 경로도 두 군데 있습니다. 번호가 0인 폴백 문항, 그리고 "N)" 형식 번호입니다. 둘 다 **문서 전체 변환 실패(ValueError)**로 이어지는 경로가 코드상 열려 있습니다.

신뢰도 정보도 가져오기 문항과 내보내기 리뷰에 문항별 상태로 남지 않습니다. 리뷰는 출력 HWPX를 사후 검사한 결과일 뿐, 인식이 "불확실"이라고 표시한 정보를 반영하지 않습니다.

## 호출 흐름도 (정적 추적, 실행 안 함)

```
[가져오기] main.py:940 import_file → importers.py:255 import_pdf
  ├ pypdf PdfReader로 페이지 수 확인 (importers.py:266)
  └ _import_pdf_recognized (importers.py:277) → recognize_pdf (pipeline.py:414)
       ├ segment_pdf: fitz.open(stream) + 전 페이지 rawdict (pdf_segment.py:1394, 388)
       ├ _source_literal_english_pages: fitz.open(stream) + 전 페이지 dict (pipeline.py:113-116)
       └ render_selected_page_images: fitz.open(stream) + pixmap (cutout.py:71-76)
     → _pdf_answer_key_pages: fitz.open(stream) + 전 페이지 text (importers.py:521-522)
     → layout_payload → sink.add (importers.py:320-353, 479-498)   ※ text_reliable·figure_boxes 미기록
[편집형 내보내기] main.py:1011 _export_pdf_layout
  └ write_pdf_structured_hwpx (pdf_layout_writer.py:10111)
       ├ recognize_pdf #1 (10139) — 위의 stream open 3회, max_pages 무시
       ├ detect_source_subject: open (7446)
       ├ [기본] write_native_content (10198 → pdf_native_content.py:1924)
       │    ├ extract_native_content: open + _iter_text_lines 메모 (1372-1402) ← 인식 본문 미사용, 다시 추출
       │    ├ annotate_question_groups(items, problems) (1948) ← 인식은 (쪽,번호)로만 사용
       │    ├ split_background_frame_rows: open (pdf_frame_rows.py:46)
       │    └ _source_box_glyph_count: open + plain text, 메모 밖 (pdf_layout_writer.py:159-161)
       └ [kice_math + AI] 문항 dict 재조립 (10228-10412)
  ├ _pdf_export_scope: 쪽 수만 보려고 open (main.py:964)
  ├ inspect_pdf_editability (pdf_editability.py:283-296, 315)
  │    └ inspect_question_units → recognize_pdf #2 (pdf_question_inspection.py:339) + open (364)
  │         + graph_inspection open (pdf_graph_inspection.py:76), inline_labels open (pdf_inline_labels.py:125)
  │    └ inspect_paragraph_flow: open (pdf_paragraph_flow.py:69)
  ├ _pdf_export_fidelity (pdf_layout_fidelity.py:703, 1652)
  └ build_export_review (pdf_export_review.py:86) ← 출력 검사 기반, 인식 신뢰도 미반영
```

**중복 집계** (기본 경로, 64쪽 이하, 정적 추적 기준; 실제 횟수는 미측정):
- **stream open 6회** (recognize 2회 × 3곳). 모두 메모 대상이 아닙니다(`pdf_source_page_memo.py:11-13`: 경로로 연 문서만 메모).
- **메모 밖 전 페이지 추출**: rawdict 2회, dict 2회. `_source_box_glyph_count`의 plain text 1회가 더해집니다.
- **경로로 여는 open**: 확인한 곳만 최소 10곳입니다(위 흐름도의 open 표시). 64쪽을 넘는 문서는 메모 자체가 꺼집니다(`pdf_source_page_memo.py:42, 94`).

---

## 치명

### C1. 번호 0 폴백 문항이 인벤토리를 깨서 변환 전체가 실패
1. **위치**: `app/recognition/pipeline.py:363-366`, `app/pdf_native_content.py:601-605`, `1947-1952`, `app/pdf_question_inspection.py:346-349`
2. **현재 동작**:
   ```python
   return RecognizedProblem(number=0, page_number=page_number, ...)   # pipeline.py:363
   expected = Counter((int(problem.page_number), int(problem.number)) for problem in recognized_problems)  # native:602
   raise ValueError(f"native question grouping does not match source inventory: ...")  # native:1950
   ```
   `QUESTION_START = r"^\s*([1-9]\d?)\.(?![\d.])"`(`pdf_question_markers.py:14`)는 "0."과 절대 맞지 않습니다. 그래서 (쪽, 0)은 언제나 missing으로 남습니다.
3. **문제**: 문항이 있는 PDF 안에, 마커도 `[N~M]` 지문도 없는 쪽이 하나만 있어도 실패합니다. 예: 그림·표만 있는 쪽, "이 면은 여백입니다" 쪽, 끝의 확인사항 쪽. 이런 쪽은 `_page_needs_raster`가 any_problems=True를 돌려줘서 렌더되고(`pipeline.py:264-265`), 폴백 문항(number=0)이 됩니다. 그 결과 native 경로가 ValueError를 내고 사용자는 400을 받습니다. 검사 쪽에서도 `q00`이 들어가고, `number <= previous` 조건 때문에 variant가 하나 밀려 그 뒤 모든 id가 어긋납니다.
4. **수정안**: 두 곳에서 `p.number > 0`으로 걸러 냅니다(`pdf_native_content.py:1947`, `pdf_question_inspection.py:340-342`, 각 1줄). 폴백 쪽은 notice로 따로 알립니다.
5. **예상 효과**: 이 유형의 PDF가 "변환 실패"에서 "변환 성공 + 검토 표시"로 바뀝니다. 발생 빈도는 미확인입니다(36책자 매트릭스에서 드러나지 않았다면 KICE 원본에는 드물 것으로 추정).
6. **회귀 위험**: 낮음. 번호가 있는 문항의 인벤토리 비교는 그대로입니다.
7. **검증**: fitz로 3쪽 합성 PDF를 만듭니다. 1쪽 "1. 다음을 계산하시오", 2쪽 마커 없는 본문 한 단락, 3쪽 "2. …". `write_pdf_structured_hwpx`가 ValueError 없이 끝나고, `question_grouping.inventory_matches`가 True인지 확인합니다.

### C2. 인식은 "N)"를 문항 번호로 받는데, 작성기·검사기는 "N."만 받음
1. **위치**: `app/recognition/pdf_segment.py:54`, `app/pdf_question_markers.py:14`, `app/pdf_native_content.py:619-624`, `1949-1952`
2. **현재 동작**:
   ```python
   _MARKER_RE = re.compile(r"^([1-9][0-9]?)([.)])(?:\s|$)")          # 인식
   QUESTION_START = re.compile(r"^\s*([1-9]\d?)\.(?![\d.])")          # 작성기
   ```
3. **문제**: 학원·학교 프린트처럼 "1) …" 형식으로 번호를 단 PDF가 해당합니다. 인식은 이 문항들을 (쪽, 번호)로 인벤토리에 넣지만 native 단락은 시작으로 인정되지 않습니다. 그러면 missing이 생겨 변환 전체가 ValueError로 끝납니다. `extract_native_content`가 "N)"를 "N."으로 바꿔 주는지는 **미확인**입니다(확신도 중간).
4. **수정안**: `QUESTION_START`를 `([.)])`로 넓히되, 선지 "1)~5)"와 섞이지 않게 인벤토리 상한(`observed[key] < expected[key]`, `pdf_native_content.py:622-624`)을 그대로 둡니다. 1~2줄입니다. 검사기의 START 정규식도 같이 맞춥니다(정의 위치 미확인).
5. **예상 효과**: "N)" 형식 문서가 변환 실패에서 정상 변환으로 바뀝니다(추정).
6. **회귀 위험**: 같은 쪽에서 실제 문항 "1." 앞에 선지나 보기 "1)"이 먼저 나오면 그 줄을 문항 시작으로 잡을 수 있습니다. 수능 원본에는 거의 없다고 추정합니다.
7. **검증**: 합성 PDF 1쪽에 "1) 다음 중 …\n① …\n2) …"를 넣습니다. 내보내기가 성공하고 그룹 id가 `v1:q01`, `v1:q02`인지 확인합니다. 선지 "1)~5)"가 들어간 문항도 함께 넣어 오탐이 없는지 봅니다.

---

## 중요

### I1. 내보내기 한 번에 recognize_pdf가 두 번 실행됨
1. **위치**: `app/pdf_layout_writer.py:10139`, `app/pdf_question_inspection.py:339`
2. **현재 동작**:
   ```python
   recognized = recognize_pdf(payload, filename=pdf_path.name)                               # 작성기
   recognition = recognize_pdf(Path(source).read_bytes(), filename=Path(source).name)        # 검사기
   ```
3. **문제**: 모든 born-digital 내보내기에 해당합니다. 세분화, 영어 판정 추출, 래스터 렌더, 그림 잘라내기를 모두 두 번 합니다. 입력 바이트가 같아서(`source_copy` = 업로드 원본) 결과도 같습니다.
4. **수정안**: `pipeline.py`에 sha256 키로 쓰는 모듈 수준 메모를 둡니다(약 10줄). `pdf_source_page_memo.forget_file`이 불릴 때 함께 비웁니다. 결과는 읽기 전용으로 다룹니다.
5. **예상 효과**: 인식 1회분 시간이 줄어듭니다. 40쪽 기준 수 초로 **추정**합니다(인식 단독 시간은 미측정).
6. **회귀 위험**: 소비자가 `RecognizedProblem`을 고치면 공유 객체가 오염됩니다. 현재 두 소비자는 읽기만 한다고 추정합니다. 메모리에 그림 PNG가 잠깐 더 남습니다.
7. **검증**: 합성 2쪽 PDF로 내보내기를 돌리면서 `segment_pdf`를 monkeypatch 카운터로 감쌉니다. 호출이 정확히 1회인지 assert합니다.

### I2. 기본 native 경로가 인식의 래스터·잘라낸 그림을 전부 버림
1. **위치**: `app/recognition/pipeline.py:448-463`, `515-532`, `app/pdf_native_content.py:1940-1947`, `2015-2021`
2. **현재 동작**:
   ```python
   items, provenance = extract_native_content(pdf_path, max_pages=page_limit, area_hint=subject_area)
   problems = [p for p in recognized.problems if 0 < p.page_number <= page_limit]
   grouping = annotate_question_groups(items, problems)
   ```
   이 경로에서 쓰는 인식 필드는 `page_number`, `number`, `page_count`, `text_reliable` 넷뿐입니다.
3. **문제**: 수학처럼 그림이 많은 시험지, 또는 PUA 비율이 높은 문항이 있는 쪽이 해당합니다. 150dpi pixmap, PIL 변환, PNG 인코딩을 모두 하고 나서 버립니다. 이 비용은 위의 2회 실행 때문에 두 배가 됩니다.
4. **수정안**: `recognize_pdf(..., render: bool = True)`를 추가해 False면 `page_images = {}`로 둡니다(약 4줄). 작성기는 `render=math_ai_recognition`, 검사기는 `render=False`로 부릅니다. 이렇게 하면 폴백 문항(number 0)도 생기지 않아 C1이 native 경로에서 자연히 사라집니다.
5. **예상 효과**: 그림이 있는 쪽 수만큼 렌더와 인코딩이 줄어듭니다(추정, 미측정).
6. **회귀 위험**: AI 수식 경로는 render=True를 유지하니 그대로입니다. 검사기가 `problem.box`나 그림 bbox 말고 PNG를 쓰는지는 미확인입니다. 코드상 PNG는 쓰지 않고 provenance를 씁니다(`pdf_question_inspection.py:368-379`).
7. **검증**: 그림(벡터 사각형 + 텍스트)이 든 합성 PDF로 `render=False`를 호출합니다. `figure_pngs == []`인데 `number`, `page_number` 목록이 render=True일 때와 같은지 비교합니다.

### I3. 영어 판정이 PDF를 따로 열어 전 페이지를 다시 추출함
1. **위치**: `app/recognition/pipeline.py:101-138`, `437`
2. **현재 동작**:
   ```python
   with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
       for page in document:
           header_lines = [... for block in page.get_text("dict").get("blocks", []) ...]
   ```
3. **문제**: 모든 PDF가 해당합니다(영어가 아니어도). 결과는 `source_literal_text` 하나에만 쓰이는데(`pipeline.py:622-631`), segment_pdf가 이미 rawdict로 줄 텍스트와 위치를 뽑아 두었습니다(`pdf_segment.py:384-410`).
4. **수정안**: `_segment_page`가 만든 text_lines 가운데 상단 25% 줄을 page metadata(`header_lines`)에 넣습니다. 판정 함수는 그 값을 받아 씁니다. 약 15줄입니다.
5. **예상 효과**: 쪽당 dict 추출 1회 × 인식 2회만큼 줄어듭니다(추정, 미측정).
6. **회귀 위험**: dict와 rawdict의 span 텍스트 조합이 공백 처리에서 다를 수 있습니다. 정규식이 공백을 지우고 비교하므로(`pipeline.py:119`) 위험은 낮다고 추정합니다.
7. **검증**: 합성 PDF 상단에 "제3교시 영어 영역"과 본문 "1. …"을 넣습니다. 수정 전후 `source_literal_text`가 같은지 확인하고, 국어 헤더 PDF에서는 False인지도 확인합니다.

### I4. 신뢰도와 폴백 상태가 가져온 문항에 남지 않음
1. **위치**: `app/importers.py:320-353`, `363-365`
2. **현재 동작**:
   ```python
   "block_type": ("image_fallback" if getattr(prob, "problem_image_png", None)
                  else "problem_with_shared_passage" if ... else "problem"),
   ```
   `text_reliable`, `figure_boxes`, `routing`, `empty_page_numbers`는 문항 dict에 들어가지 않습니다.
3. **문제**: PUA 비율 12% 이상(`pipeline.py:32`)인데 렌더가 실패해 `problem_image_png`가 None인 문항은 `image_only_fallback`이 False가 되어, 깨진 텍스트가 "problem"으로 조용히 편집 텍스트가 됩니다. 그림 위치(`figure_boxes`)도 버려집니다. 작성기는 `figure_boxes_px`를 읽습니다(`pdf_layout_writer.py:8781`, `9444`). 다만 이 키를 DB 문항에서 읽는 경로가 있는지는 미확인입니다.
4. **수정안**: `layout_payload`에 `"text_reliable"`, `"figure_boxes_px"`, `"recognition_fallback": "page"|"problem"|None`을 추가합니다. 3~4줄입니다.
5. **예상 효과**: 정확도 자체는 그대로지만, 워크벤치에서 문항별로 "검토 필요"를 표시할 수 있게 됩니다.
6. **회귀 위험**: 낮음. layout JSON이 약간 커지고, 모르는 키를 무시하는지는 소비자별로 미확인입니다.
7. **검증**: 본문에 U+E000 같은 PUA 문자를 15% 넣은 합성 PDF를 만들고, 렌더 함수를 예외로 monkeypatch합니다. 가져온 문항의 `layout.text_reliable`이 False인지 assert합니다.

### I5. 문항 단위 인식 인벤토리 JSON이 없음
1. **위치**: `app/pdf_native_content.py:652-654`, `2011-2021`, `app/importers.py:510`
2. **현재 동작**:
   ```python
   question_groups.append({"id": active_group, "number": number, "variant": variant, "page": page})
   return {"created": sink.created, ..., "notices": notices, "exam_title": ...}
   ```
3. **문제**: 최저 72.85점 책자처럼 낮은 점수의 원인을 문항 단위로 추적하려 할 때 막힙니다. 문항마다 원본 쪽·단(column)·번호·선지 분리 수·이미지 폴백·그림 수·공유 지문 범위를 한 번에 볼 출력이 없습니다. `routing`과 `passage_page_numbers`는 어디로도 나가지 않습니다(grep으로 소비처를 찾지 못함).
4. **수정안**: `stats["recognition_inventory"]`를 만듭니다. `recognized.problems`에서 page, column_index/column_count, number, 선지 수(`len(re.findall("[①-⑤]", text))`), text_reliable, problem_image 여부, len(figure_boxes), shared_passage_range를 뽑고, 쪽 단위로 empty/passage/error 목록과 routing을 붙입니다. 가져오기 응답에도 같은 목록을 넣습니다. 약 15줄입니다.
5. **예상 효과**: 점수에 직접 영향은 없습니다. 배치 평가에서 실패 문항을 특정하는 시간이 줄어듭니다.
6. **회귀 위험**: 응답이 커집니다(36쪽 기준 수십 KB로 추정).
7. **검증**: 2단 합성 PDF(왼쪽 1·2번, 오른쪽 3번)로 인벤토리 길이가 3이고 column_index 집합이 {1,2}인지 확인합니다.

### I6. 세분화 예외가 "스캔 추정"으로 잘못 안내됨
1. **위치**: `app/recognition/pdf_segment.py:1410-1428`, `app/recognition/pipeline.py:474-477`, `645-655`
2. **현재 동작**:
   ```python
   elif page.metadata.get("error") or marker_count == 0:
       result.empty_page_numbers.append(page_index + 1)
   ...  f"{n}개 페이지는 텍스트 마커가 없어(스캔 추정) 기존 방식으로 처리합니다."
   ```
3. **문제**: 특정 쪽에서 `_segment_page`가 예외를 내면 오류 문자열이 사라지고 "스캔 추정"으로 표시됩니다. 그 쪽의 PageModel은 width_px/height_px가 0이라 폴백 crop도 빈 상자가 됩니다(`pipeline.py:353-357`).
4. **수정안**: `result.error_page_numbers`를 따로 두고 notice를 "N쪽 구조 분석 오류"로 나눕니다. 오류 문자열은 로그로 보냅니다. 약 5줄입니다.
5. **예상 효과**: 원인 진단이 정확해지고, 사용자에게 틀린 안내를 하지 않게 됩니다.
6. **회귀 위험**: 낮음. notice 문구만 바뀝니다.
7. **검증**: `_segment_page`를 2쪽에서만 raise하도록 monkeypatch합니다. 결과의 `error_page_numbers == [2]`이고 notice에 "스캔 추정"이 없는지 확인합니다.

### I7. max_pages를 무시하고 전 페이지를 인식함
1. **위치**: `app/pdf_layout_writer.py:10139`, `app/recognition/pdf_segment.py:1396`, `app/pdf_question_inspection.py:339-342`
2. **현재 동작**:
   ```python
   for page_index in range(doc.page_count):        # segment_pdf
   problems = [p for p in recognition.problems if not page_limit or p.page_number <= page_limit]
   ```
3. **문제**: 40쪽 PDF를 `max_pages=2`로 미리보기 변환해도 40쪽 전체를 2번 인식하고 렌더합니다. 그 결과는 나중에 필터로 버립니다.
4. **수정안**: `recognize_pdf`/`segment_pdf`에 `page_limit`을 추가하고, `variant_policy == "all"`일 때만 넘깁니다. variant 판정에는 전체 쪽이 필요하기 때문입니다. 약 6줄입니다.
5. **예상 효과**: 부분 변환 시간이 줄어든 쪽 비율만큼 줄어듭니다(추정).
6. **회귀 위험**: `[N~M]` 지문은 앞쪽에서 뒤쪽 문항으로 연결되므로, 제한 범위 밖의 문항 연결은 원래 필요 없습니다. 위험은 낮다고 추정합니다.
7. **검증**: 10쪽 합성 PDF와 max_pages=2로, `_segment_page` 호출이 2회인지 카운터로 확인합니다.

---

## 사소

### S1. 쪽 수 하나 보려고 PDF를 다시 엶
1. **위치**: `app/main.py:961-965`
2. **현재 동작**:
   ```python
   with fitz.open(source_path) as document:
       original_pages = len(document)
   ```
3. **문제**: `stats["original_source_pages"]`가 이미 있습니다(`pdf_native_content.py:2015`).
4. **수정안**: `stats.get("original_source_pages")`를 쓰고, 값이 없을 때만 엽니다. 2줄입니다.
5. **예상 효과**: 수 ms(추정).
6. **회귀 위험**: AI 경로의 stats에 이 키가 있는지는 미확인입니다. 그래서 없을 때 여는 폴백을 남겨 둡니다.
7. **검증**: 기존 내보내기 테스트의 `source_scope` 값이 바뀌지 않는지 확인합니다.

### S2. 원본 □ 글리프 개수 세기가 메모 밖 plain text 추출을 씀
1. **위치**: `app/pdf_layout_writer.py:156-161`
2. **현재 동작**:
   ```python
   return sum(source_pdf[index].get_text().count(_SOURCE_BOX_CHAR) for index in range(count))
   ```
3. **문제**: 모든 내보내기에서 쪽마다 plain text 추출이 1회 더 돕니다.
4. **수정안**: `page_memo(page, "text_plain", page.get_text)`로 바꿉니다. 1줄입니다.
5. **예상 효과**: 작음(추정).
6. **회귀 위험**: 없음.
7. **검증**: "□"를 3개 넣은 합성 PDF로 반환값이 3인지 확인합니다.

### S3. 문제/선지 분리 결정 규칙이 두 군데에 중복되고 서로 다름
1. **위치**: `app/importers.py:416-446`, `app/pdf_layout_writer.py:10253-10306`
2. **현재 동작**: 작성기 쪽에만 `fraction_choices_verified` 분기가 있습니다.
   ```python
   len(geometry_choices) == len(choices) and len(choices) >= 4 and fraction_choices_verified
   ```
   반대로 영어 분기(`_split_english_stem_and_choices`)는 가져오기 쪽에만 있습니다.
3. **문제**: 같은 수학 문항이라도 워크벤치로 가져올 때와 AI 내보내기를 할 때 선지가 다르게 잘릴 수 있습니다.
4. **수정안**: 공용 함수 `choose_stem_choices(text, geometry, *, english, fraction_verified)`로 묶습니다. 약 30줄 이동입니다.
5. **예상 효과**: 두 경로의 결과가 일치합니다(정확도 수치는 미확인).
6. **회귀 위험**: 중간. 분수 선지 판정이 가져오기 쪽에도 적용되면서 출력이 달라질 수 있습니다.
7. **검증**: 세로 분수 선지 4개를 넣은 합성 PDF로 두 경로의 선지 목록이 같은지 비교합니다.

### S4. 가져오기에서 PDF를 4번 열고, 정답 쪽 탐색이 전 페이지 텍스트를 추출함
1. **위치**: `app/importers.py:266`, `513-536`
2. **현재 동작**:
   ```python
   page_count = len(PdfReader(io.BytesIO(payload)).pages)
   texts = [page.get_text("text") for page in document]
   ```
3. **문제**: 정답 쪽은 첫 문항 쪽 뒤에서만 찾는데도 모든 쪽의 텍스트를 뽑습니다.
4. **수정안**: 루프 안에서 `document[i].get_text("text")`를 필요할 때만 부릅니다. 3줄입니다.
5. **예상 효과**: 작음(추정).
6. **회귀 위험**: `_parse_answer_key(texts[page_number-1:])`가 뒤쪽 텍스트 목록을 쓰므로, 그 부분은 그때 따로 만들어야 합니다.
7. **검증**: 4쪽 합성 PDF(3쪽 문항, 4쪽 "빠른 정답 1 ③")로 정답이 연결되는지 확인합니다.

### S5. AI·OCR 사용 가능 여부를 매 인식마다 OCR 백엔드를 만들어 확인함
1. **위치**: `app/recognition/pipeline.py:293-314`, `444`
2. **현재 동작**:
   ```python
   backend = build_ocr_backend("auto")
   ```
3. **문제**: 내보내기 한 번에 2회 생성됩니다. 생성 비용은 미확인입니다.
4. **수정안**: 키 설정이 바뀌면 무효화하는 짧은 TTL 캐시를 둡니다. 5줄입니다. 또는 I1의 메모로 자연히 1회로 줄어듭니다.
5. **예상 효과**: 미확인.
6. **회귀 위험**: 키를 저장한 직후 캐시가 낡은 값을 줄 수 있습니다.
7. **검증**: 카운터 monkeypatch로 내보내기 한 번에 `build_ocr_backend` 호출이 1회인지 확인합니다.

**확인하지 못한 것**: 정확한 open 횟수와 시간(실행 금지라 정적 추적만 했습니다), `extract_native_content`가 "N)"를 정규화하는지, 검사기 START 정규식의 정의 위치, DB 문항 내보내기에서 `figure_boxes_px`를 읽는 경로가 있는지.

=== 끝 ===
