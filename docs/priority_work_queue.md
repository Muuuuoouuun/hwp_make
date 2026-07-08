# Priority Work Queue

Updated: 2026-07-09

Goal: produce KICE/school-exam HWPX/HWP output that preserves question sync, native math equations, typography, and layout without overlaps.

## P0 - Blocking Quality Gates

1. Resolve real PDF render QA timeout.
   - Current status: import-only checks are fast and stable, but the full four-sample render QA timed out once.
   - Next action: split `verify_real_pdf_math_samples.py` into import, HWPX write, and render phases with per-sample timings.
   - Done when: all four real math PDFs complete with 46 questions, malformed equation count 0, overflow 0, and no column crossing.

2. Reduce remaining real-PDF math placeholders.
   - Current status: raw PDF character/span geometry is preserved in `pdf_line_chars` and `pdf_line_spans`.
   - Next action: use bbox geometry to reconstruct stacked fractions, roots, superscripts/subscripts, cases, and vector accents.
   - Done when: remaining `□` counts are explained by type, and high-confidence structural cases are converted to native equations.

3. Keep question sync as a non-negotiable gate.
   - Current status: HWP sample QA keeps 46-question sync and overflow 0.
   - Next action: extend real-PDF QA reports to include per-question source page, column, detected number, stem/choice split, and image fallback status.
   - Done when: every sample has a deterministic 46-question inventory with no duplicated or missing numbers.

## P1 - Fidelity Improvements

1. Expand geometry-based formula recovery.
   - Fractions: numerator/denominator grouped by horizontal fraction bars and vertical alignment.
   - Roots: root index, radicand bbox, and radical bar/placeholder grouping.
   - Exponents: y-offset and font-size based superscript/subscript reconstruction.
   - Cases: brace fragments plus aligned condition/value rows.

2. Improve KICE typography calibration.
   - Keep Shinmyeongjo/HY Shinmyeongjo for Korean body, Times New Roman for English/variables, and Dotum/JungGothic for numbers/titles.
   - Verify body 10-11 pt, line spacing 160-170%, char ratio around 95, and letter spacing around -5 against real HWP samples.

3. Separate editable text from image fallback more clearly.
   - Use editable text wherever confidence is high.
   - Use regional image fallback only for diagrams/tables or unresolved math structures.
   - Avoid full-page raster fallback for the PDF original-layout HWPX path.

## P2 - Tooling And Reporting

1. Add a residual-placeholder report.
   - Group `□` by source file, question number, page, nearby text, and raw bbox context.
   - Store examples for regression tests before adding new repair rules.

2. Add per-phase performance logging.
   - Import segmentation time.
   - Native HWPX write time.
   - rhwp render time.
   - HWP COM open time if available.

3. Make visual review easier.
   - Keep HTML review pages for sample outputs.
   - Add links to generated HWPX, rendered pages, and source crops.

## Working Notes

- Do not treat every `□` as unknown text. Many are structural math glyphs from HyhwpEQ, especially fraction bars, radical parts, overlines, vectors, and cases.
- Prefer conservative repair rules. Only convert when local text and bbox geometry agree.
- The current best path is not OCR-first. Born-digital PDF text plus geometry is strong enough for many KICE math structures, and OCR should remain a fallback.
- Every repair rule needs a regression case in `scripts/verify_importers.py` or the relevant PDF QA script.
- Layout success means rendered output, not only XML validity: no overlap, no overflow, no column crossing, and readable native equations.
