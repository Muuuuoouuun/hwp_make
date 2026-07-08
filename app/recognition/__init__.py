"""문항 인식(recognition) 파이프라인.

edb_make(C:\\Projects\\Class_project\\edb_make)의 인식/구조화 아키텍처를 벤치마킹해
hwp_make로 이식한 경량 스파인이다.

레이어
  schema      : 공통 IR (Box / ContentBlock / ProblemUnit / PageModel) — edb structured_schema 포팅
  pdf_segment : PyMuPDF 기반 PDF 문항 세그멘테이션 (결정론적)
  cutout      : 문항 박스 → 그림 crop
  ocr_backend : OCR 추상화 (Gemini/Tesseract/Paddle) — 키 없으면 graceful degrade
  router      : "결정론적 인식이 충분한가?" 판정 → AI 폴백 여부 결정
  cache       : content-addressed 캐시 (AI 재과금 방지)
  settings    : API 키 저장/로드

설계 원칙(edb_make와 동일): 결정론적 인식이 항상 완전한 baseline을 만들고,
AI는 low-confidence 요소에만 additive 하게 얹힌다. API 키가 없으면 baseline 그대로 반환.
"""
