# Priority Work Queue

Updated: 2026-07-09

Goal: produce KICE/school-exam HWPX/HWP output that preserves question sync, native math equations, typography, and layout without overlaps.

Canonical references:
- `README.md` for current app usage, data policy, and verification commands.
- `docs/product_b_bottleneck_specs.md` for Product B current standards and retired old standards.

## P0 - Blocking Quality Gates

1. Resolve real PDF render QA timeout.
   - Current status: `verify_real_pdf_math_samples.py` now supports `--mode import|write|render|all`, records per-sample phase timings, and the four local real math PDFs completed render QA with 46 items, malformed equation count 0, overflow 0, and no column crossing.
   - Next action: keep this as a regression gate and investigate any future timeout using the recorded `import`, `write_hwpx`, `inspect_hwpx`, and `render_hwpx` timings.
   - Done when: this remains stable across the local four-sample set and any newly added real math PDFs.

2. Reduce remaining real-PDF math placeholders.
   - Current status: raw PDF character/span geometry is preserved in `pdf_line_chars` and `pdf_line_spans`.
   - Current status: imported problem layout metadata now carries `pdf_lines` with line text, bbox, char geometry, and span geometry; real PDF QA emits per-question placeholder reports with field, nearby text, inferred type, page/column, and bbox context.
   - Next action: use the residual placeholder report to reconstruct stacked fractions, roots, superscripts/subscripts, cases, and vector accents.
   - Done when: remaining `□` counts are explained by type, and high-confidence structural cases are converted to native equations.

3. Keep question sync as a non-negotiable gate.
   - Current status: HWP sample QA keeps 46-question sync and overflow 0.
   - Next action: extend real-PDF QA reports to include per-question source page, column, detected number, stem/choice split, and image fallback status.
   - Done when: every sample has a deterministic 46-question inventory with no duplicated or missing numbers.

4. Keep retired standards out of implementation decisions.
   - Current status: README and Product B criteria now separate current standards from old investigation notes.
   - Next action: when changing PDF import/export or HWPX writer behavior, check against the retired-standards list before accepting the change.
   - Done when: no code path treats pypdf-only import, full-page raster fallback, GUI-open-only QA, or committed reference exams as a success criterion.

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

4. Reduce HWP open friction.
   - Ad prompts are usually controlled by the installed Hancom product, viewer/free edition, account state, or update channel. Generated HWPX content cannot reliably suppress them.
   - Edit-permission/protected-view prompts are partly actionable. Check generated files for document protection flags, read-only attributes, Mark-of-the-Web zone metadata, temp/download paths, and locked output files.
   - Next action: add an open-probe checklist that records whether Hancom opens the generated HWPX as editable, read-only, protected, or blocked by a permission tab.
   - Done when: files generated into the app export directory open directly editable on a licensed Hancom install, with any remaining ad-only prompt documented as environment-level.

5. Keep reference samples local unless a sharing policy is decided.
   - Current status: `data/` is ignored and sample PDFs/HWPs are local-only.
   - Next action: document sample name, source, and purpose without committing the files themselves.
   - Done when: every local-only sample used by QA has a manifest entry or test skip message that explains what is missing.

## P2 - Tooling And Reporting

1. Add a residual-placeholder report.
   - Status: implemented in `scripts/verify_real_pdf_math_samples.py`; reports are written under `data/real_pdf_math_qa/exports/real_pdf_math_qa_report_<mode>.json`.
   - Next action: promote representative fraction/root/script cases from the JSON report into focused regression fixtures before adding repair rules.

2. Add per-phase performance logging.
   - Status: real PDF QA now records setup, import, analysis, HWPX write, HWPX inspect, render, and total time per sample.
   - Next action: add HWP COM open time if available.

3. Make visual review easier.
   - Keep HTML review pages for sample outputs.
   - Add links to generated HWPX, rendered pages, and source crops.

## Working Notes

- Current standards live in `README.md` and `docs/product_b_bottleneck_specs.md`. Treat older exploratory notes as historical context only.
- Do not treat every `□` as unknown text. Many are structural math glyphs from HyhwpEQ, especially fraction bars, radical parts, overlines, vectors, and cases.
- Prefer conservative repair rules. Only convert when local text and bbox geometry agree.
- The current best path is not OCR-first. Born-digital PDF text plus geometry is strong enough for many KICE math structures, and OCR should remain a fallback.
- Do not reintroduce full-page raster fallback as a pass condition for PDF original-layout HWPX.
- Do not commit reference exam PDFs/HWPs by default. Keep them local/private unless a rights and storage policy is explicitly chosen.
- Every repair rule needs a regression case in `scripts/verify_importers.py` or the relevant PDF QA script.
- Layout success means rendered output, not only XML validity: no overlap, no overflow, no column crossing, and readable native equations.
