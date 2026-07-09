# Priority Work Queue

Updated: 2026-07-09

Goal: produce KICE/school-exam HWPX output that preserves question sync, native math equations, typography, and layout without overlaps. Direct `.hwp` output remains a Hancom/COM conversion concern after HWPX quality is stable.

Canonical references:

- `README.md` for app usage, data policy, verification commands, and HWP open guidance.
- `docs/product_b_bottleneck_specs.md` for current Product B standards and retired old standards.
- `docs/reference_samples_manifest.md` for local-only reference sample tracking.
- `docs/hwp_open_probe_checklist.md` for separating actionable HWP edit-permission issues from environment-level ad/account prompts.

## P0 - Current Blocking Gates

1. Reduce remaining real-PDF math placeholders.
   - Current status: raw PDF character/span geometry is preserved in `pdf_line_chars` and `pdf_line_spans`.
   - Current status: imported problem layout metadata carries `pdf_lines` with line text, bbox, char geometry, and span geometry.
   - Current status: real PDF QA emits per-question placeholder reports with field, nearby text, inferred type, page/column, and bbox context.
   - Current status: choice fraction repair removes all remaining `choice□` placeholders in the four local real math PDFs while keeping render overflow 0.
   - Current status: char-bbox stem fraction repair converts high-confidence stacked fractions, including `y=\frac{3}{x-1}`-style curves and `\frac{x2}{9}-\frac{y2}{16}`-style conics.
   - Current status: split vector residue cleanup removes a `□⃗` line only when the following line is already a confirmed `\vec{...}` token.
   - Current local baseline: the four-sample math PDF set reports 49 total `stem□` placeholders, down from 66 before this repair series, with malformed equation count 0 and render overflow 0.
   - Next action: classify the residual placeholders by structure type, then implement only high-confidence mixed fraction, root, script, case, and bbox-vector repairs.
   - Done when: remaining `□` counts are explained by type, and supported structural cases convert to native equations with regression fixtures.

2. Keep question sync as a non-negotiable gate.
   - Current status: HWP sample QA keeps 46-question sync and overflow 0.
   - Next action: extend real-PDF QA reports to include per-question source page, column, detected number, stem/choice split, and image fallback status.
   - Done when: every target sample has a deterministic 46-question inventory with no duplicated or missing numbers.

3. Tune PDF original-layout density without overlap.
   - Current status: `/api/pdf-layout-export` emits editable flow HWPX with two columns, middle divider, font faces, char ratio/spacing, and 165% line spacing checks.
   - Current status: full-page raster fallback is not accepted for this path.
   - Next action: calibrate flow font-size buckets, body density, and table/cell margins against real PDF/HWP samples while preserving overflow 0 and column crossing 0.
   - Done when: generated HWPX is readable, editable, and close enough to KICE/school-exam density without text collisions.

4. Keep current standards from drifting back to old criteria.
   - Current status: README and Product B docs separate active standards from retired investigation notes.
   - Next action: when changing PDF import/export or HWPX writer behavior, check against the retired-standards list before accepting the change.
   - Done when: no code path treats pypdf-only import, full-page raster fallback, GUI-open-only QA, or committed reference exams as a success criterion.

## P1 - Fidelity Improvements

1. Expand geometry-based formula recovery.
   - Fractions: choice fractions and simple char-bbox stem fractions are implemented; next fraction work is mixed inline/stacked formulas where suffix text or multiple structures share one row.
   - Roots: root index, radicand bbox, and radical bar/placeholder grouping.
   - Exponents/subscripts: y-offset and font-size based reconstruction.
   - Cases: brace fragments plus aligned condition/value rows.
   - Vectors: simple PUA/vector residue cleanup is implemented; next vector work must infer the base from bbox rather than text adjacency alone.

2. Improve KICE typography calibration.
   - Keep Shinmyeongjo/HY Shinmyeongjo or Shinmyeong Jungmyeongjo for Korean body, Times New Roman for English/variables, and Dotum/JungGothic for numbers/titles.
   - Verify body 10-11 pt, line spacing 160-170%, char ratio around 95, and letter spacing around -5 against real HWP samples.
   - Track deviations as named profiles, not ad hoc one-off values.

3. Separate editable text from image fallback more clearly.
   - Use editable text wherever confidence is high.
   - Use regional image fallback only for diagrams/tables or unresolved math structures.
   - Avoid full-page raster fallback for the PDF original-layout HWPX path.

4. Reduce HWP open friction.
   - Ad prompts are usually controlled by the installed Hancom product, viewer/free edition, account state, or update channel. Generated HWPX content cannot reliably suppress them.
   - Edit-permission/protected-view prompts are partly actionable. Check generated files for document protection flags, read-only attributes, Mark-of-the-Web zone metadata, temp/download paths, and locked output files.
   - Current status: `docs/hwp_open_probe_checklist.md` records editable, read-only, protected, permission-tab, and ad/account prompt distinctions.
   - Next action: wire the checklist into `scripts/probe_hwp_open.ps1` output when practical.
   - Done when: files generated into the app export directory open directly editable on a licensed Hancom install, with any remaining ad-only prompt documented as environment-level.

5. Keep reference samples local unless a sharing policy is decided.
   - Current status: `data/` is ignored and sample PDFs/HWPs are local-only.
   - Next action: maintain `docs/reference_samples_manifest.md` with sample name, type, source location class, purpose, and last verification status.
   - Done when: every local-only sample used by QA has a manifest entry or a test skip message that explains what is missing.

## P2 - Tooling And Reporting

1. Promote residual-placeholder cases into regression fixtures.
   - Status: `scripts/verify_real_pdf_math_samples.py` writes reports under `data/real_pdf_math_qa/exports/real_pdf_math_qa_report_<mode>.json`.
   - Status: representative choice-fraction, simple stem-fraction, and split-vector-residue cases are promoted into `scripts/verify_importers.py`.
   - Next action: promote representative root/script/cases, bbox-vector, and mixed-fraction cases from the JSON report before adding repair rules.

2. Keep per-phase performance logging useful.
   - Status: real PDF QA records setup, import, analysis, HWPX write, HWPX inspect, render, and total time per sample.
   - Next action: add HWP COM open time if available.

3. Make visual review easier.
   - Keep HTML review pages for sample outputs.
   - Add links to generated HWPX, rendered pages, and source crops.

## Stabilized Gates

- Real PDF render QA timeout is no longer treated as an unsolved P0 by itself. `verify_real_pdf_math_samples.py` supports `--mode import|write|render|all`, records per-sample phase timings, and completed the four local math PDFs with 46 items, malformed equation count 0, overflow 0, and no column crossing.
- This remains a regression gate: a future timeout is a failure to investigate with the recorded phase timings, not a reason to fall back to OCR-first or full-page image output.

## Working Notes

- Current standards live in `README.md` and `docs/product_b_bottleneck_specs.md`. Treat older exploratory notes as historical context only.
- Do not treat every `□` as unknown text. Many are structural math glyphs from HyhwpEQ, especially fraction bars, radical parts, overlines, vectors, and cases.
- Prefer conservative repair rules. Only convert when local text and bbox geometry agree.
- The current best path is not OCR-first. Born-digital PDF text plus geometry is strong enough for many KICE math structures, and OCR should remain a fallback.
- Do not reintroduce full-page raster fallback as a pass condition for PDF original-layout HWPX.
- Do not commit reference exam PDFs/HWPs by default. Keep them local/private unless a rights and storage policy is explicitly chosen.
- Every repair rule needs a regression case in `scripts/verify_importers.py` or the relevant PDF QA script.
- Layout success means rendered output, not only XML validity: no overlap, no overflow, no column crossing, and readable native equations.
