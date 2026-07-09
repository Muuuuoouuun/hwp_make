# PDF Flow Validation Samples

Updated: 2026-07-09

This repository keeps a small, force-tracked validation sample set under `data/`
even though `data/` is ignored by default. These files are used to reproduce the
editable PDF flow HWPX checks for Korean and English exam layouts.

## Input PDFs

- `data/uploads/25수능 영어.pdf`
- `data/uploads/25수능 국어.pdf`
- `data/uploads/영어.pdf`
- `data/uploads/국어.pdf`
- `data/uploads/영어영역_문제지_홀수형_2025학년도.pdf`
- `data/uploads/국어영역_문제지_홀수형_2025학년도.pdf`

## Current Verified Outputs

- `data/exports/goal_samples/experiments/25_suneung_english_current_detail.hwpx`
  - `rhwp`: 16 pages
  - Hancom HWP 2024 status line: `1/16쪽(근사값)`
- `data/exports/goal_samples/experiments/25_suneung_korean_current_detail.hwpx`
  - `rhwp`: 40 pages
  - Hancom HWP 2024 status line: `1/40쪽`

## Reproduce

```powershell
python scripts\pdf_layout_hwpx_probe.py --flow "data\uploads\25수능 영어.pdf" "data\exports\goal_samples\experiments\25_suneung_english_current_detail.hwpx"
python scripts\pdf_layout_hwpx_probe.py --flow "data\uploads\25수능 국어.pdf" "data\exports\goal_samples\experiments\25_suneung_korean_current_detail.hwpx"

python scripts\verify_pdf_layout_hwpx.py --render "data\exports\goal_samples\experiments\25_suneung_english_current_detail.hwpx"
python scripts\verify_pdf_layout_hwpx.py --render "data\exports\goal_samples\experiments\25_suneung_korean_current_detail.hwpx"
python scripts\verify_pdf_layout_export_api.py
```

Expected API checks include:

- editable flow lines
- required font faces
- 95% char ratio and `-5` spacing
- 10pt-centered flow font size bucket guard
- 165% body line spacing
- middle divider border
- cell margins
