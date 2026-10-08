# 기본 영어 본문의 자연 공백 폭

프리미엄 양식과 순서 변경은 이 작업의 범위에 포함하지 않는다.

고3 p2의 실제 Times 본문은 자연 공백 glyph bbox가0.25em이다. 비마지막 행의 공백 advance는 원본 양쪽 정렬에 따라 달라지고, 마지막 행에서 실제 자연 advance가0.25em 근처임을 별도로 확인했다. native renderer 일반 공백0.5em로 마지막 줄이 Q19 최대26.033px, Q20 최대15.303px 오른쪽으로 밀렸다.

`app/pdf_source_body_spaces.py`는 원본 PDF를 다시 열어 모든 body row/span/char의 font·flags·size·origin·bbox·text와 수평 방향/page width를 대조한다. 원본 페이지의 실제 instruction 후보와 완전한 body를 `split_source_question_body`로 다시 증명한다. 한 regular Times face/size, 실제0.25em space bbox, 마지막 줄의 자연 advance3개 이상이 확인된 경우만 ASCII 공백에 장평80/자간−15를 반환한다. 원본 문단의 비마지막 행은 native JUSTIFY를 유지한다. PDF 경로, 번호, source marker, 좌표 metadata만으로 허용하지 않는다.

실제 writer 입력의 source 메타로 Q19 공백107개/Q20 공백139개/Q22 공백164개가 증명됐다. 전체3개 학년의 source 범위 검사에서 고1·고2는 적용 조건을 만족한 본문이 없고, 고3은 이3개 본문이다. 이 수는 전체 품질 통과 수가 아니다. `scripts/verify_native_source_body_spaces.py`는 원문 보존 및33개 source/native 변조·부분·수식·비유한값·tab 검사를 확인한다. 재적용 XML 일치 검사는 memoizing 테스트 allocator의 범위이며 실제 제품의 style ID 불변성을 주장하지 않는다.

고정 producer2 HWPX에 공백 스타일만 바꾼 ZIP A/B는8쪽과 모든 공백을 유지하면서 마지막 줄 최대 오차를 Q19 2.686px/Q20 1.829px로 줄였다. `tmp/september-exam-matrix/high3-body-spaces-ab/report.json`은 실제 PDF glyph 진단이며, 새 제품 writer/API 검증을 대체하지 않는다. 비마지막 행의 별도 target width 차이는 이 공백 수정만으로 해결되지 않았다. 전체 페이지 품질 PASS와 Mac runtime 검증을 주장하지 않는다.
