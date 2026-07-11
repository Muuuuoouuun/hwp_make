# Reference Samples Manifest

Updated: 2026-07-09

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

## Update Rules

- Add a row when a new real exam sample becomes part of regular QA.
- Record sample names and purposes, not extracted copyrighted content.
- If a sample becomes required for a non-local CI gate, replace it with a synthetic fixture or document the external private storage policy first.
- If a local sample exposes a new bug, promote the smallest safe reproduction into a synthetic regression fixture before relying on the private sample forever.
