# English source frames and Arial Black verification

2026-10-07. The visual and objective score thresholds were unchanged. No whole-page raster output or text overlay was added.

## Source frame flow

The source-confirmed prose frame producer now permits a zero inset and a source border overhang of at most 50 HWP units (<1 pixel). Emitted offsets remain nonnegative. The independent auditor still requires actual PDF four-rule geometry, complete ordered text, matching native dimensions, paragraph-relative vertical flow, editable cell content, and no overlapping/nested objects. Larger source displacements, negative native offsets, and forged rails are rejected.

Before spacing on an unwrapped, complete single-cell source prose frame is moved to the preceding paragraph's after spacing. Its total flow height is unchanged. Ordinary tables, illustrated frames, equations, and wrapped questions retain their existing spacing path. Current style IDs are reread before changing an already allocated preceding style.

- Product: `app/pdf_source_frame_geometry.py`, `app/pdf_source_spacing.py`; `app/pdf_table_paragraphs.py` zero-offset caller connection by the basic-layout agent.
- Regression: `python scripts/verify_native_source_frame_insets.py` PASS. Includes actual old CSAT both variants/16 pages/10 complete frames, public text edit/growth/re-save, zero/near-zero rail, geometry/text negatives, actual painted gap displacement, and repeated spacing with newly allocated style IDs.
- Log: `tmp/september-audit/high1-zero-rail-current/source-frame-regression-final.log`.
- High1 September fresh API: 8 pages/45 question IDs, source coverage 1.0, independent editability/open/render PASS. Page8 harsh 67.53 to 94.20; overall harsh 89.82 to 93.21; objective remains 89.75 and does **not** meet 98. Stable code during this case. Evidence: `tmp/september-audit/high1-zero-rail-gap-current/evidence.json`.
- High3 September fresh API before font normalization: 8 pages/45 question IDs, source coverage 1.0, independent editability PASS. Page8 harsh 72.76 to 89.90; overall harsh 84.76 to 87.04. Stable code during this case. Evidence: `tmp/september-audit/high3-zero-rail-gap-current/evidence.json`.

Page8 matched glyph medians do not identify a column starting-rail error. Root independently verified Q43/Q44/Q45 starting markers and Q45 first choice within about +0.17px of source. The approximately -5.5px median horizontal residual in later right-column glyphs must be interpreted as later advance/width differences or diagnostic grouping, not a justification for moving a column.

## Exact Arial Black family normalization

The only added font mapping is `ArialBlack` to `Arial Black` in `app/pdf_native_typography.py::_font_name`. It does not introduce a bold flag or a broad Black-name rule. Existing source-run styles regression passes, including unchanged `Blackadder ITC`.

The actual source PDF page4 embeds `ODBOIM+ArialBlack` (16,172 bytes). Its normalized glyph advances for R/C/Q/H/i/g/S/c/h/o/l/F/W/a/s/t exactly equal the installed `C:/Windows/Fonts/ariblk.ttf` advances. The installed name table has legacy family `Arial Black`, typographic family `Arial`, typographic subfamily `Black`, and weight900. It has fsSelection64/macStyle0; the source's unbolded flag is consistent with an intrinsically heavy face.

Native SVG previously used a fixed half-em width (5.3533px) for these titles. With the exact family normalization, all three actual titles/66 nonspace glyphs use nine distinct widths, matching the source embedded TTF to <=0.000034px after HWP quantization. All title glyphs remain inside the source column and all title text is preserved. Direct fresh PNG rendering of the supplied alias-only A/B package differs in bbox (458,196)-(694,631), correcting an earlier zero-pixel-difference observation. ZIP content comparison proves its sole changed entry is `Contents/header.xml` with exactly that family substitution.

- Source and installed font evidence: `tmp/september-audit/high3-zero-rail-gap-current/source-arial-black-font.json`, `arial-black-installed-font.json`, and `font-svg-diag.json`.
- Actual post-change output: `tmp/september-audit/high3-font-alias-current/actual-title-glyph-verification.json`, `title-font-p4.png`, `evidence.json`.
- Latest preliminary API: 8 pages/45 question IDs, source1.0, independent editability PASS; overall harsh/objective87.05, page4 harsh80.20, page8 harsh89.90. `app/pdf_source_grid_geometry.py` changed concurrently, so this case is explicitly preliminary. Objective98 remains unmet. Root's final frozen matrix supersedes this preliminary measurement.

## Remaining renderer font-selection issue (read only)

The installed `_rhwp.pyd` SHA256 exactly matches the shipped patched wheel binary (bc42590a8f4cd429dc7432c009b4590657b780c28f20d568e1624c30d2876f77). Packaging patches do not change font lookup or metrics.

Two renderer stages use different mechanisms:

1. Layout/SVG advances use the compiled metric table. `font_metrics_data.rs` contains `Arial Black`, boldFalse, em2048, and lacks an `ArialBlack` alias. `layout/text_measurement.rs` falls back to 0.5em when the family is unresolved. The narrow product normalization resolves this stage.
2. SVG-to-PDF painting uses usvg/fontdb system fonts. fontdb0.23 `parse_names` prefers TYPOGRAPHIC_FAMILY (name16), only reading legacy FAMILY (name1) if name16 is empty. For installed ariblk.ttf, its registered family is therefore Arial, weight900; a query for family Arial Black does not follow from that name16 entry. The SVG's fallback chain then permits Malgun Gothic.

This is directly observed in fresh `rhwp.render_pdf()` output: all 66 actual title glyphs in the three title lines select `MalgunGothic`, despite the correct Arial Black SVG metrics. Evidence: `tmp/september-audit/high3-font-alias-current/pdf-painted-title-fonts-exact.json` and `font-selected.pdf`.

Native PNG uses Skia `FontMgr` with its own family/style matching, independently of PDF painting. An isolated Windows executable now probes the actual Skia0.97.2 system manager (335 families), using the same normal style and fallback chain as `skia/text_replay.rs`: `Arial Black` fails to resolve, while `Arial` at weight900 returns `Arial-Black`. The first fallback face supporting `R` is **Noto-Sans-KR400**, rather than the PDF path's MalgunGothic. `FontMgr::default()` delegates to `FontMgr::new()`, which the probe calls. This proves the default system-manager lookup, not custom supplied font-path behavior. No arbitrary Arial substitution, synthetic bold, renderer patch, font installation, or threshold change was made.

The standalone Rust fontdb0.23 probe reads the actual Windows Arial regular/bold/black and Malgun files. `Arial Black` fails at both weight400 and weight900; `Arial` at weight900 resolves the actual Arial-Black face. Adding only the proved file's legacy-name alias in the scratch database resolves `Arial Black` to intrinsic900 while preserving ordinary Arial400 and explicit bold700. The actual Windows Skia probe separately verifies ArialMT400, Arial-BoldMT700 and Arial-Black900. This is a qualified face-identity repair candidate, not a general Black-name or weight rewrite. Evidence: `tmp/september-font-probe/fontdb-query-probe.json`, `windows-skia-query-probe.json`, and their source/build logs. The tiny Windows probe links existing cached Skia libraries; the renderer source and installed binary were not rebuilt or replaced.

Follow-up should run only after the original family/style lookup fails, resolve an unambiguous actually loaded face through its legacy name1 or qualified exact PostScript correspondence, and preserve that face's intrinsic weight. Existing successful Arial400/bold700 lookups, unrelated Black names, ambiguous aliases, unsupported styles and per-character CJK fallback require negative tests. Both PNG and PDF need actual face/outline verification. A renderer patch requires reproducible native-wheel rebuilds, shared patch/lock provenance across Windows/macOS, and actual Mac family/CoreText/font-availability tests; no Mac runtime has been tested here. The Korean design and full regression list are in `renderer-font-lookup-followup.md`.

The source cache is `tmp/rhwp_renderer_build/rhwp-core-patched`; fontdb dependency source is in WSL `/root/.cache/hwp-make-renderer-build/cargo/registry/src/index.crates.io-1949cf8c6b5b557f/fontdb-0.23.0/src/lib.rs`. Source references: renderer/font_metrics_data.rs:41393, renderer/layout/text_measurement.rs:1572, renderer/pdf.rs:8, renderer/skia/text_replay.rs:54; fontdb parse_names around1062.

## Old June table-cell edit/save reserve regression

The actual June high1 Q27 public edit from `50` to `60 students` changed 26,333 pixels on page4 while retaining eight pages. The edited question's internal glyph baselines changed by at most 0.027px, but every following Q28 glyph moved down 5.333333px. Its native question wrapper height increased from 34,698 to 35,098 HWP units. The original source-confirmed wrapper had zero extra reserve; public save unconditionally added 400 units after recalculating its direct child flow. Restoring only that saved wrapper and its host cache dimensions reduced the difference to 35 pixels around the edited digit. Source frame gap movement and the existing underline reflow change were not the cause.

`app/_vendor/hwpx/tools/question_reflow.py` now measures the existing reserve before changing nested table-cell caches. It preserves a reserve between 0 and 400 only when every dirty paragraph is inside a table, direct child caches are present with finite positive descenders, original wrapper/textHeight/insets agree, and the measured flow difference is finite. Invalid geometry, missing direct caches, direct-paragraph edits, and reserves outside that range retain the existing 400-unit fallback. Table object reserve and genuine equation behavior remain unchanged. No custom XML source flag authorizes this path.

The unchanged `<500` pixel threshold now passes with **35 changed pixels and eight pages** in a fresh original conversion. The same actual Q27 accepts a 155-character table-cell expansion, grows, paints all added glyphs within its column, preserves images/equations, and remains stable after repeated save and a fresh reopen/save. The regression also rejects negative/oversized reserve, nonfinite or inconsistent dimensions, missing direct cache, nonpositive descender, and forged source labels. Separate ordinary question edit/reflow and gap/reflow suites pass.

- Fresh complete regression: `tmp/september-audit/grid-save-regression-fixed-fresh.log`; artifacts and `report.json` in `tmp/september-audit/grid-save-regression-fixed-fresh/`.
- Original failure, glyph/XML diagnosis, and isolated dimension-only A/B: `tmp/september-audit/grid-save-regression-current/diagnosis.json`, `wrapper-reserve-ab.json`.
- Generic regressions: `tmp/september-audit/grid-save-generic-reflow.log`, `grid-save-question-gap-reflow.log`.
- Scope limitation: reserve preservation is proved for table-contained edits. Direct-paragraph edits deliberately keep the existing fallback; this work does not claim to resolve an analogous reserve change for those edits.
