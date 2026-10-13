# Filee 검토와 적용 결과 (2026-10-13)

[Filee v1.10.2](https://github.com/KnifeLemon/Filee/releases/tag/v1.10.2)는 MIT 라이선스의 C# 파일 변환기다. 이 앱과 겹치는 부분은 HWP 엔진(rhwp 명령줄 도구, 글꼴 대체), HWPX 읽기·쓰기, DOCX↔HWPX 변환이다. 코드를 직접 대조했고, 내려받은 저장소 안에서는 아무것도 실행하지 않았다. Filee 코드는 옮기지 않고 동작과 규칙만 참고했다(`app/third_party_licenses/NOTICE.md`).

## 적용한 것

| 분야 | 문제(수정 전) | 수정 | 검증 |
| --- | --- | --- | --- |
| HWP 내보내기 | HWP 직접 출력은 한컴 COM이 있어야 한다고 보고 HWPX·DOCX만 제공함 | Filee처럼 rhwp 명령줄 도구 `convert`로 같은 HWPX(네이티브 수식 포함)를 HWP 5.0으로 바꿈. `--verify --verify-pages`로 rhwp가 결과를 다시 읽어 IR 차이와 쪽 수를 대조하고, 어긋나면 HWP를 내주지 않음. 도구가 없으면 503 `hwp_unavailable`. `/api/health`의 `hwp_export_available`이 참일 때만 스튜디오에 HWP 선택지가 나타남 | `verify_hwp_export_rhwp_cli.py`(신규): HWP 5.0 머리, 다시 가져오기 4문항·한컴 수식·표 안 수식 유지, 실패·도구 없음 경로 |
| 배포용 HWP 가져오기 | 미리보기 앞부분만 가져온다는 안내만 했음 | rhwp 도구가 있으면 편집 가능한 HWP로 먼저 풀어 평소 경로로 가져옴 | 같은 스크립트(배포용 아닌 HWP는 해제하지 않음). 실물 배포용 표본으로는 미검증 |
| rhwp 도구 받기 | 없음 | `scripts/fetch_rhwp_cli.py`가 v0.8.7 릴리스를 플랫폼별로 받아 SHA-256을 확인하고 `packaging/rhwp-cli/`(git 제외)에 둠. `HWP_MAKE_RHWP_CLI`나 PATH의 `rhwp`도 사용 | 리눅스 x86_64 해시 일치 확인 |
| DOCX 가져오기 문단 | run 바로 아래 `w:t`만 읽음. 탭·줄바꿈, 하이퍼링크·콘텐츠 컨트롤 글자가 빠짐. 숨김 글자(숨긴 정답)가 들어오고, 글상자는 `mc:Choice`와 `mc:Fallback`이 둘 다 읽혀 두 번 들어감 | 문단 내용을 문서 순서대로 걸으며 위 요소를 처리하고, 숨김·삭제 글자는 빼고, AlternateContent는 한 갈래만 읽음 | `verify_docx_import_semantics.py`(신규) |
| Word 자동 번호 | `numPr` 처리가 없어 자동 번호로 매긴 문항 번호와 ①~⑤가 사라지고 한 문항으로 합쳐짐 | `numbering.xml`의 `lvlText`·`numFmt`·`lvlOverride/startOverride`로 번호를 복원 | 같은 스크립트(1·2·7번, 원문자 선지) |
| 병합 셀(DOCX·HWPX 가져오기) | DOCX는 병합 셀 글자가 칸마다 반복됨. HWPX는 격자 배치만 하고 병합 정보를 저장하지 않음 | 왼쪽 위 칸에만 글을 두고 `layout.table_spans`로 저장. HWPX·DOCX writer는 이미 이것을 실제 병합으로 냄 | 같은 스크립트(HWPX `cellSpan`, DOCX `gridSpan`·`vMerge`) |
| DOCX 내보내기 기본값 | python-docx 기본 템플릿 그대로: US Letter, 모든 문단 뒤 10pt·1.15줄, 파란 제목, 호환 모드 14 | A4(HWPX와 같음), 2pt·1.2줄, 동아시아 글꼴 명시, 검은 제목, 호환 모드 15 | `verify_export_document_defaults.py`(신규) |
| DOCX 표 | 쪽 전체 폭이라 2단에서 단 밖으로 넘침. 연속된 두 표가 Word에서 한 표로 합쳐짐 | 단 폭에 맞춘 고정 폭, 두 표 사이 빈 문단 | 같은 스크립트 |
| 그림 형식 | TIFF·WebP 업로드를 HWPX는 png 표시로 원본 바이트 그대로 넣고, DOCX는 "[이미지 삽입 실패]" | PNG로 바꿔 넣음 | 같은 스크립트 |
| HWPX 변경 추적 | `deleteBegin`~`deleteEnd` 사이 삭제 글자가 문항에 들어감 | 뺌 | `verify_hwpx_import_semantics.py` |
| DOCX MathType 수식 | OLE 개체 수식이 안내 없이 사라짐 | 빠진 개수와 변환 방법을 안내 | `verify_docx_import_semantics.py` |

## 확인했지만 적용하지 않은 것

- **문단 여백 두 벌 저장**: 한컴 기본 서식 파일은 문단 여백을 `hp:switch`의 `case`와 `default`에 두 번 쓰고, 값이 다른 17건 모두 `default`가 `case`의 2배다. 이 앱의 벤더 writer와 여러 `pdf_*` 모듈은 같은 값을 쓰고, `pdf_source_choice_geometry.py`는 두 값이 같은지를 일부러 검사한다("native margin alternative mismatch"). rhwp-python(0.7)과 rhwp 0.8.7은 둘 다 `case`만 읽는 것을 직접 시험했다(`default`를 바꿔도 글자 위치 그대로). 한글 2016 이후도 `case`를 읽으므로 영향은 구버전 리더에 한정된다. 바꾸려면 모듈 여러 곳을 함께 고쳐야 한다.
- **원본 좌표 표 병합의 덮인 칸**: `hwpx_writer_v2._add_table`의 `source_geometry` 경로는 `merge_cells`만 불러 덮인 칸을 크기 0으로 남긴다. 같은 파일의 `_apply_table_spans`는 한컴처럼 지운다. 이 경로의 결과는 뒤이은 `pdf_source_*` 후처리기가 칸 격자로 다시 검사하는데, 그 검증용 원본 PDF가 이 환경에 없어 고쳐도 확인할 수 없다.
- **`hp:tab` 위치**: 벤더 writer는 탭을 `hp:run` 바로 아래에, 한글 저장본과 Filee는 `hp:t` 안에 둔다. 선택지 TAB 렌더는 이 팀이 렌더러 패치(`nativecell5`)와 함께 맞춰 온 부분이라 한글 실물 확인 없이 쓰는 쪽은 바꾸지 않았다. 읽는 쪽은 고쳐서, HWPX 가져오기가 두 위치의 탭·줄바꿈을 모두 읽는다(`verify_hwpx_import_semantics.py`).
- **렌더러 0.8.7**: Filee 1.9.0은 rhwp 0.8.7에서 "2단 시험지 머리 표가 첫 문항 위에 겹치던 문제"가 고쳐졌다고 적었다. 이 앱의 렌더 검증은 1,241줄 패치를 얹은 rhwp 코어 0.7.13이다. 같은 시험지를 두 버전으로 렌더하면 둘 다 2단으로 그리지만, 이 컨테이너에는 한글 글꼴이 없어 품질 비교가 불가능했다. 0.8.7의 겹침 진단(`LAYOUT_TABLE_OVERLAP`)은 서로 다른 단의 표를 겹친다고 보고한 것으로 보여 2단 판정에 그대로 쓰기 어렵다.
- **ID 무결성 검사 연결, 음수 개체 좌표**: 벤더의 `tools/id_integrity.py`가 저장 경로에 연결돼 있지 않고 `pdf_floating_figures.py`에서 음수 좌표가 나올 수 있다. 실패를 새로 만들 수 있어 별도 작업으로 남긴다.
- **가변 글꼴(CFF2) 대체**: Filee 1.10.2의 수정이다. rhwp의 PDF 글꼴 서브셋터가 CFF2 가변 글꼴에서 실패해 빈 쪽이 나오던 문제다. 이 앱은 rhwp로 PDF를 만들지 않고 PNG 렌더만 쓴다.

## 회귀

전체 회귀(`scripts/run_all_verify.py`, 기준 50cd57c 대비) 실행 중. 결과는 다음 커밋에 기록한다.

## 한글에서 확인할 것

1. `/api/export`의 `format=hwp` 결과를 한글에서 열어 수식·표·2단 배치와 편집 가능 여부를 확인한다. rhwp는 `RhwpHwpxOrigin` 스트림을 추가하는데, 한글이 이를 무시하는지도 함께 본다.
2. 실물 배포용 HWP를 가져와 해제 경로를 확인한다.
3. 위 "적용하지 않은 것" 가운데 탭 위치와 여백 두 벌 저장은 한글 저장본과 비교해 정한다.
