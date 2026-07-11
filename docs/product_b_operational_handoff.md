# Product B Operational Handoff

Updated: 2026-07-10

Purpose: keep the next Product B pass from repeating the same detours. This is the practical handoff for PDF original-layout HWPX work: what is canonical, what must be verified, what previously broke, and which algorithms are now fixed.

## One Screen Summary

- Canonical export path: `/api/pdf-layout-export` -> `app/pdf_layout_writer.py` -> `write_pdf_layout_hwpx()`.
- Default writer style: coordinate-based, editable HWPX. The flow writer is an experiment, not the pass/fail path for visual sync.
- Current quality gate: `layout_view_sync_ratio >= 0.94`, `quality.objective_score >= 95`, editable text coverage high, no full-page raster fallback, editor-open safety pass.
- Previous 91-point self-evaluation target is now below the active gate. Do not lower the gate back to 91 unless the user explicitly asks.
- A HWPX that opens in Hancom is not automatically good. It still needs layout sync, typography, editable text, no full-page raster fallback, and structure checks.
- A full-page screenshot inside HWPX is not acceptable final output for Product B, even if it looks similar.
- `신명 중명조` is not embedded into HWPX. The HWPX references a local Hancom-registered font face, so font installation matters on each machine.

## Current Verified Outputs

Latest good reference outputs from the English/Korean sync pass:

- `data/exports/goal_samples/sync94_final/25_suneung_english_sync94.hwpx`
- `data/exports/goal_samples/sync94_final/25_suneung_korean_sync94.hwpx`
- `data/exports/goal_samples/sync94_final/english_sync94_report.json`
- `data/exports/goal_samples/sync94_final/korean_sync94_report.json`

Latest recorded scores:

- English: `layout_view_sync_ratio = 0.9456`, mean layout view `0.9538`, pages `16`, `meets_target = true`.
- Korean: `layout_view_sync_ratio = 0.9513`, mean layout view `0.9625`, pages `40`, `meets_target = true`.
- Both: `review_flags = []`, `full_page_raster_fallback = false`, full-page raster image count `0`, editable text coverage `1.0`.
- Hancom open probe succeeded after the font install on the current Windows machine.

## Golden Path

Use the coordinate writer for production:

```powershell
python scripts/pdf_layout_hwpx_probe.py --text-mode line "data\uploads\25수능 영어.pdf" "data\exports\goal_samples\sync94_final\25_suneung_english_sync94_editable.hwpx"
python scripts/pdf_layout_hwpx_probe.py --text-mode line "data\uploads\25수능 국어.pdf" "data\exports\goal_samples\sync94_final\25_suneung_korean_sync94_editable.hwpx"
```

API path:

```text
/api/pdf-layout-export -> write_pdf_layout_hwpx()
```

Keep these paths separate:

- Problem-bank import: `/api/import` -> recognition/storage -> `hwpx_writer_v2`.
- PDF original-layout restoration: `/api/pdf-layout-export` -> `pdf_layout_writer.write_pdf_layout_hwpx()`.
- Experimental flow reconstruction: `write_pdf_flow_hwpx()` and `--flow`. Use it only when intentionally testing flow layout, not when judging Product B visual sync.

## HWPX Open-Safety Contract

XML schema validity is not enough. Hancom can still show "file is damaged" when package, header, section, or shape details are wrong.

Minimum contract:

- ZIP: `mimetype` must be first entry and stored with `ZIP_STORED`.
- Sidecars: include `Preview/PrvText.txt`, `Preview/PrvImage.png`, `settings.xml`, `META-INF/manifest.xml`, `META-INF/container.rdf`.
- `content.hpf`: manifest includes `version.xml`, `Contents/header.xml`, all `Contents/sectionN.xml`, `settings.xml`, and `BinData/*`; spine starts with `header linear="yes"`.
- Header: `hh:head version="1.5"`, `secCnt` equals section file count, top-level order is `beginNum`, `refList`, `compatibleDocument`, `docOption`, `metaTag`, `trackchageConfig`.
- Compatibility: `compatibleDocument targetProgram="HWP201X"` with `layoutCompatibility`.
- Section root: `hs:sec`.
- `hp:secPr`: first child under the first paragraph/run control shell, with `hp:ctrl/hp:colPr`.
- Shapes: rect/line point children use `hc:*`, not `hp:*`.
- Rect model: has `textWrap`, `textFlow`, `reverse`, and `shapeComment`.
- Shape fill: `hc:fillBrush/hc:winBrush`, not `hp:fillBrush`.
- Text boxes: `drawText` order and `lineShape` width must stay Hancom-compatible.

Do not "clean up" these details unless a verifier is updated first. They are compatibility requirements, not cosmetic XML.

## Fixed Algorithms

Coordinate layout:

- `_PageTransform` maps PDF point coordinates into the target HWPX page.
- HWP units are produced from points with `pt * 100`.
- Standard exam page transform snaps near A4/B4/A3 to exact physical page sizes.
- A3-style exam PDFs are treated as B4 114% print-layout targets where appropriate.
- Text is mostly emitted as editable line-level text boxes.
- Math-risk lines can split into per-character boxes, but that increases object count and must remain targeted.
- PDF images are clipped at higher scale and placed by bbox.
- Images overlapping text above the threshold are excluded to avoid hiding editable text.
- Lines/rectangles are reconstructed from PyMuPDF drawings for horizontal/vertical lines and simple rectangles.

KICE typography:

- Base Korean body face: `신명 중명조` first, with `HY신명조`/`한양신명조` as related references where needed.
- English body: `Times New Roman`.
- Titles, numbers, and gothic/bold labels: `돋움`/`중고딕` family.
- Body profile: roughly 10-11pt, line spacing around `160-170%`, active target `165%`.
- Character ratio: `95`.
- Character spacing: `-5`.
- Title heuristic: large spans or spans with tokens like `영역`, `문제지`, `선택`, `홀수형` use title/gothic treatment.

HWPX structure patches:

- `app/_vendor/hwpx/oxml/_document_impl.py` now emits shape point namespaces with `hc:*`.
- `app/pdf_layout_writer.py` applies compatibility patches before final save: rect/line namespaces, rect shape model, fill brush namespace, section/header shell, lineseg, content.hpf, sidecar files, version, and ZIP order.
- `app/main.py` includes page ratio in the objective paging score.
- `app/pdf_layout_fidelity.py` adds `layout_view_sync_ratio` and uses it as the whole-page margin/scale/spacing signal.
- `scripts/verify_pdf_layout_export_api.py` now expects coordinate editable HWPX, not raster fallback.
- `scripts/verify_pdf_layout_hwpx.py` catches wrong namespaces, shape issues, placeholder/PUA residue, and full-page raster fallback.

## Font Handling

Project asset location:

- `assets/fonts/shinmyeong-jungmyeongjo/original/신명 중명조.zip`
- `assets/fonts/shinmyeong-jungmyeongjo/hft/TEJMJEN.HFT`
- `assets/fonts/shinmyeong-jungmyeongjo/hft/TEJMJHG.HFT`
- `assets/fonts/shinmyeong-jungmyeongjo/hft/TEJMJHJ.HFT`
- `assets/fonts/shinmyeong-jungmyeongjo/README.md`

Current-machine Hancom user install:

- `%APPDATA%\HNC\User\Fonts\TEJMJEN.HFT`
- `%APPDATA%\HNC\User\Fonts\TEJMJHG.HFT`
- `%APPDATA%\HNC\User\Fonts\TEJMJHJ.HFT`
- `%APPDATA%\HNC\User\Common\130\Fonts\TEJMJEN.HFT`
- `%APPDATA%\HNC\User\Common\130\Fonts\TEJMJHG.HFT`
- `%APPDATA%\HNC\User\Common\130\Fonts\TEJMJHJ.HFT`

Current registration:

- `%APPDATA%\HNC\User\Common\130\Fonts\ShareFont.ini`
- Backup: `%APPDATA%\HNC\User\Common\130\Fonts\ShareFont.ini.bak-20260710_003121`
- `FontPath2=%APPDATA%\HNC\User\Common\130\Fonts\`
- `FontList2=%APPDATA%\HNC\User\Common\130\Fonts\Fontlist\Fontlist01.lst`

`Fontlist01.lst` entries:

```text
신명 중명조=TEJMJEN.HFT,Latin
신명 중명조=TEJMJHG.HFT,Hangul
신명 중명조=TEJMJHJ.HFT,Hanja
```

Font guardrails:

- HFT is Hancom-specific. Do not try to solve this by copying HFT into `C:\Windows\Fonts`.
- `HY신명조` in Windows Fonts does not replace `신명 중명조` HFT registration.
- The exact `신명 중명조` face must be written as `type="HFT"` and `isEmbedded="0"`; declaring it as TTF prevents Hancom from resolving the registered HFT glyph files.
- On a new PC, install/register the Hancom HFT files before judging final typography.
- Read/write Hancom font list files with CP949/ANSI awareness. UTF-8 assumptions can corrupt the Korean names.
- `Common\130` is Hancom Office 2024-era. Other Hancom versions may use another number.
- `assets/` is currently untracked in git status, so do not assume these fonts exist in another clone until tracking/licensing policy is settled.

## Verification Gates

Basic code sanity:

```powershell
python -m py_compile app\pdf_layout_writer.py app\main.py app\pdf_layout_fidelity.py app\_vendor\hwpx\templates.py app\_vendor\hwpx\oxml\_document_impl.py scripts\verify_pdf_layout_hwpx.py scripts\verify_pdf_layout_export_api.py
git diff --check
```

API gate:

```powershell
python scripts\verify_pdf_layout_export_api.py
```

Generated HWPX structure gate:

```powershell
python scripts\verify_pdf_layout_hwpx.py "data\exports\goal_samples\sync94_final\25_suneung_english_sync94.hwpx" "data\exports\goal_samples\sync94_final\25_suneung_korean_sync94.hwpx"
```

Optional first-page render check for a specific generated file:

```powershell
python scripts\verify_pdf_layout_hwpx.py "data\exports\<out>.hwpx" --render
```

Hancom COM open probe on a licensed Hancom Windows install:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\probe_hwp_open.ps1 -Path "data\exports\<out>.hwpx" -TimeoutSeconds 45
```

If access prompts block automation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\probe_hwp_open.ps1 -Path "data\exports\<out>.hwpx" -TimeoutSeconds 120 -AllowAccessPrompt
```

Important: `scripts\probe_hwp_open.ps1` requires `-Path`. Older docs that omit `-Path` are wrong.

Important: `scripts\verify_pdf_layout_hwpx.py` requires at least one HWPX path. Do not run it with no args.

Important: `scripts\run_all_verify.py` currently invokes `verify_*.py` scripts without per-script args, while `verify_pdf_layout_hwpx.py` requires args. Do not treat `run_all_verify.py` as the final green Product B gate until that mismatch is fixed.

## How To Interpret Scores

Primary pass signal:

- `layout_view_sync_ratio`: whole-page layout comparison, including left/right margins, spacing, scale, and page balance.

Diagnostics:

- `visual_sync_ratio`: content-crop glyph/render similarity. Useful, but too sensitive to font rasterization differences to be the sole pass signal.
- `whole_page_visual_sync_ratio`: raw full-page luminance comparison. Useful strict diagnostic.
- `foreground_overlap_ratio`: foreground overlap after dilation.
- `min_strict_alignment_ratio`: strict alignment guard.
- `aspect_ratio_mismatch_pages`: page size/ratio mismatch guard.
- `stats.line_rects`, `stats.images`, `stats.text_items`: object count and fallback diagnostics.

Do not pass a file on `visual_sync_ratio` alone. For this work, the user specifically called out whole-page left/right margins, spacing, and size. That maps to `layout_view_sync_ratio` plus page-ratio/style-profile checks.

## Common Failure Patterns

`파일이 손상되었습니다` or `Hwp.Open returned false`:

- Check rect/line point namespaces first: `hc:pt0..pt3`, `hc:startPt`, `hc:endPt`.
- Check shape fill namespace: `hc:fillBrush/hc:winBrush`.
- Check rect attrs and `shapeComment`.
- Check header version/order/secCnt, section root `hs:sec`, `content.hpf` manifest/spine, sidecar files, and ZIP order.
- Run `verify_pdf_layout_hwpx.py` and then Hancom COM open probe.

File opens, but it is only a picture:

- This is not Product B success.
- Check `full_page_raster_fallback`, `full_page_images`, and `verify_pdf_layout_hwpx.py` full-page raster warnings.
- Keep only local/region image fallback for drawings, tables, or uncertain regions.

File opens, but margins/scale feel wrong:

- Check `layout_view_sync_ratio`, `page_ratio_ok`, `page_sizes`, `page_standard_names`, `page_print_scale_values`.
- Check the standard page transform and A3/B4 snap.
- Check font fallback. A missing `신명 중명조` install can change text width and margins visually.

File opens, but typography looks unlike CSAT/mock exams:

- Verify font faces: `신명 중명조`, `Times New Roman`, `돋움`.
- Verify ratio `95`, spacing `-5`, line spacing `165%`.
- Confirm `신명 중명조` HFT is registered in Hancom, not just stored in the repo.

API synthetic gate passes, but real exams regress:

- The synthetic PDF is intentionally small. It cannot fully cover 16/40-page density, dense options, PUA math, long passages, or overflow.
- Always run real English/Korean or math samples before claiming final quality.

`verify_pdf_layout_hwpx.py --render` passes, but strict verification fails:

- `--render` only proves renderability for the checked render path. Structure, placeholders, PUA residue, header version, and raster fallback can still fail.

Hancom prompt or timeout:

- Use `docs/hwp_open_probe_checklist.md` to separate environment prompts from content failures.
- Account/ad/update prompts are environment issues.
- Read-only/protected/edit-permission prompts may be file metadata, Mark-of-the-Web, output path, document protection, or locked file.

Mojibake in commands or inline Python:

- PowerShell can mangle Korean paths/text in inline snippets.
- For Python inline probes, prefer Unicode escapes for file-name matching when needed, for example `'\uc601\uc5b4'` for `영어` and `'\uad6d\uc5b4'` for `국어`.

## Bottlenecks

Main bottleneck: HWPX object count.

- Dense samples can produce thousands of line/rect objects.
- Per-character math text boxes multiply object count quickly.
- Region image overlays are safer than full-page raster, but still add render/open cost.
- Flow writer is heavier because it repeatedly calls PDF text/drawing extraction and region text counts.

Performance priorities:

- Cache page-level `rawdict`, `dict`, drawings, and image metadata.
- Keep per-character splitting targeted to math-risk lines.
- Keep image fallback local.
- Avoid adding global overlays or page-wide fallback paths.
- Watch `stats.line_rects`, `stats.images`, `stats.text_items`, render time, and Hancom open time together.

## Do Not Regress These

- Do not switch `/api/pdf-layout-export` back to `write_pdf_flow_hwpx()` for the main Product B pass.
- Do not count full-page raster fallback as success.
- Do not use Hancom GUI open as the only QA signal.
- Do not rely on XML/schema validation alone for open-safety.
- Do not remove sidecar files, ZIP order, header compatibility, section shell, shape namespace patches, or `shapeComment`.
- Do not read/write Hancom `Fontlist*.lst` as plain UTF-8 without confirming encoding.
- Do not assume another clone has `assets/fonts/...` until asset tracking/licensing is settled.
- Do not run `verify_pdf_layout_hwpx.py` without HWPX args and treat the resulting failure as a product regression.

## Immediate Known Cleanup Items

- Fix or exclude `verify_pdf_layout_hwpx.py` in `scripts/run_all_verify.py`, because it requires HWPX args.
- Correct older docs that show `probe_hwp_open.ps1` without `-Path`.
- Resolve the policy mismatch around tracked `data/` samples versus docs that describe real references as local-only.
- Decide whether `assets/fonts/shinmyeong-jungmyeongjo` should be tracked, ignored, or documented as a local licensed asset.
- Keep real-sample regression commands close to the generated final reports so a future worker does not rely only on the synthetic API gate.
