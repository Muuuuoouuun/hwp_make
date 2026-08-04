# Reference Samples Manifest

Updated: 2026-07-16

This repository does not commit real KICE, school-exam, or private HWP/PDF reference files by default. This manifest records which local samples are used for QA and why, without storing the files themselves.

## Policy

- Keep source PDF/HWP/HWPX samples under `data/`, user Downloads, or another private local directory.
- Do not stage files under `data/`; the directory is intentionally ignored.
- Do not add real exam PDFs/HWPs to git unless a separate rights, privacy, size, and storage policy is approved.
- Commit only code, verification scripts, small synthetic fixtures, generated reports that contain no copyrighted page content, and this manifest.
- When a verification script depends on a missing private sample, it should SKIP or explain the missing sample instead of failing CI.

## Current Local Sample Classes

| Class | Location class | Purpose | Commit file? |
| --- | --- | --- | --- |
| Edited math HWP references | `C:/Users/aaaha/Downloads` | Template, typography, equation, question sync, and HWP import comparison | No |
| Uploaded PDF references | `data/uploads` | Real PDF math/subject QA, PDF text/geometry extraction, HWPX render regression | No |
| Uploaded HWP/HWPX references | `data/uploads` | HWP import parser, image extraction, layout metadata, duplicate/order regression | No |
| Class materials reference bundle | `data/reference_samples/class_materials_20260709` | Local comparison set for PDF layout fidelity, HWP template/typography matching, import smoke tests, and image OCR fallback checks | No |
| Generated exports/reports | `data/exports`, `data/real_pdf_math_qa` | Local render QA, placeholder reports, review pages | No by default |
| Synthetic fixtures | `scripts/verify_*.py` inline data or tiny generated temp files | CI-safe regression coverage | Yes |

## Named HWP References

These files were provided as local references for matching Korean exam typography, math equations, and question layout:

- `2024년 3월 교육청 모의고사 수학(편집).hwp`
- `2024년 5월 교육청 모의고사 수학(편집).hwp`
- `2024년 6월 평가원 모의고사 수학(편집).hwp`
- `2025학년도 수능 수학(편집).hwp`

Additional local form/template references currently visible in Downloads:

- `평가원 국어 양식.hwp`
- `평가원 수학 양식.hwp`
- `평가원 영어 양식.hwp`
- `평가원 과탐 양식.hwp`
- `평가원 사탐 양식.hwp`

2026년 6월 전과목 경향 QA에 추가한 사용자 제공 HWP:

- `2026학년도 6월 고2 국어.hwp`
- `2026학년도 6월 고1 국어.hwp`
- `[고1]_2026년_06월_수학.hwp` — 개인 편집본이므로 문구 오타보다 문항 경계, 수식, 표·그림, 레이아웃 경향 검증에 사용

Additional local form/template references extracted from the class materials bundle:

- `학교 기출 시험지 양식.hwp`
- `2024-06-고3-모평(평가원)언어와 매체.hwp`
- `2024-06-고3-모평(평가원)화법과 작문.hwp`

## Named PDF References

Representative real PDFs currently visible under `data/uploads`:

- `25수능 수학.pdf`
- `26-6월 수학영역_문제지.pdf`
- `수학 2교시.pdf`
- `수학영역_문제지_홀수형_2025학년도.pdf`
- `25수능 국어.pdf`
- `25수능 영어.pdf`
- `25수능 물리.pdf`
- `25수능 화학.pdf`
- `25수능 지구과학.pdf`

`data/full_subject_qa/sources`에 로컬로 내려받은 2026년 6월 고1 문제 PDF:

- `2026-06-고1-국어-문제.pdf`
- `2026-06-고1-수학-문제.pdf`
- `2026-06-고1-영어-문제.pdf`
- `2026-06-고1-한국사-문제.pdf`
- `2026-06-고1-통합사회-문제.pdf`
- `2026-06-고1-통합과학-문제.pdf`

위 PDF는 `https://horaeng.com/460`의 과목별 `문제` 링크만 사용했다. 해설과 영어 듣기대본은 내려받지 않았다. 상세 결과는 `docs/full_subject_qa_2026_06.md`에 기록한다.

Additional local PDF references extracted from the class materials bundle include:

- 2025 and 2026 KICE-style Korean, math, English, science, and Korean-history PDFs.
- 2025/2026 science subject PDFs for physics, chemistry, life science, and earth science.
- Middle-school math summary/problem-image samples.
- Gachon University natural-science essay exam problem/solution PDFs.

The bundle inventory is stored locally at `data/reference_samples/class_materials_20260709/inventory.json`.
The metadata-only smoke report is stored locally at `data/reference_samples/class_materials_20260709/smoke_report.json`.

## Current Verification Use

- Math PDF import/render QA: `python scripts/verify_real_pdf_math_samples.py --mode all`
- PDF layout export API: `python scripts/verify_pdf_layout_export_api.py`
- PDF layout HWPX structure/render for a generated output:

```powershell
python scripts/pdf_layout_hwpx_probe.py "data/uploads/25수능 수학.pdf" "data/exports/25수능_수학_flow.hwpx" --flow --max-pages 1
python scripts/verify_pdf_layout_hwpx.py "data/exports/25수능_수학_flow.hwpx" --render
```

- HWP sample equation/layout QA: `python scripts/qa_hwp_math_samples.py`
- HWP open probe when a licensed Hancom install is available: `powershell -ExecutionPolicy Bypass -File scripts/probe_hwp_open.ps1`

## Gate ↔ Sample Availability Map (2026-08-03 감사)

이 머신 기준으로 샘플 의존 게이트가 어떤 파일을 어디서 찾는지의 매핑. 소스가 없으면 게이트는 exit 2(SKIP)이며, 케이스 단위 SKIP을 지원하는 게이트는 가용 케이스만 검증한다.

| 게이트 | 요구 파일 | 이 머신 상태 |
| --- | --- | --- |
| `verify_real_pdf_math_samples.py` | `data/uploads/{25수능 수학, 26-6월 수학영역_문제지, 수학 2교시, 수학영역_문제지_홀수형_2025학년도}.pdf` | 4/4 가용 → 상시 실행 |
| `verify_external_exam_detail_quality.py` | `data/external_exam_qa/{2027_kice_june_high3,2026_june_high1}/{korean,math,english}.pdf` | 2026_june_high1 3/3 가용(`data/full_subject_qa/sources`에서 복사, 2026-08-03) · 2027_kice_june_high3 소스 0/3 — **2026년 6월 시행 고3(2027학년도) 모평 국/수/영 문제 PDF 확보 필요** |
| `verify_unseen_exam_quality.py` | `data/external_exam_qa/second_pass_unseen/{2026_csat,2026_march_high1}/...` | 0/6 — 2026학년도 수능·2026년 3월 고1 국/수/영 문제 PDF 확보 필요 |
| `verify_pdf_layout_real_math_exams.py`, `verify_pdf_layout_real_subjects_96.py` | `수학A_짝수형_최종.pdf`, `수학B_짝수형_최종.pdf` (+국어/영어는 가용) | 수학A/B 미보유 — 원 개발기 전용 파일. 로컬 수학 PDF 4종으로 `--sample` 수동 측정 후 대체 등록 검토 |
| `verify_final_output_quality_96.py`, `verify_pdf_layout_visual_fidelity.py` | `data/exports/final_results_96/` · `final_results_98/` 패키지(벤치마크 수동 실행 산출물) | 미생성 — 위 수학A/B 확보 후 `benchmark_four_subject_conversion.py`로 생성 |
| `verify_detection_quality_97.py`, `verify_four_theme_quality.py`, `verify_math_visual_spacing.py`, `verify_pdf_layout_hwpx.py`, `verify_hancom_pdf_visual_fidelity.py` | 인자 필수(패키지/경로 지정) 수동 도구 | 게이트에선 의도된 SKIP — 자동화하려면 기본 패키지 경로 배선 필요 |

## Update Rules

- Add a row when a new real exam sample becomes part of regular QA.
- Record sample names and purposes, not extracted copyrighted content.
- If a sample becomes required for a non-local CI gate, replace it with a synthetic fixture or document the external private storage policy first.
- If a local sample exposes a new bug, promote the smallest safe reproduction into a synthetic regression fixture before relying on the private sample forever.
