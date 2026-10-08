# Embedded-cell Square picture renderer — 2026-10-07

`rhwp-python 0.7.0+nativecell3` adds one renderer change to the validated `nativecell2` font build. It is built separately, with the same upstream commits and lock-based Windows ABI3 build. App producer/save changes are separate work; this document does not claim target quality 98 or complete source-font recovery.

## Actual branch and change

The high2 September Q27 picture lives in a table inside the editable question textbox. Its actual branch is `layout_embedded_table` in `src/renderer/layout/table_cell_content.rs`, rather than ordinary `table_layout.rs`. The previous embedded branch ignored the non-TAC paragraph-relative Square position and painted the tree at the cell's left edge.

The new path requires a horizontal, top-aligned positive-size cell; valid positive line-cache geometry; exactly one picture control; non-TAC + flowWithText + Square; PARA vertical reference; PARA or COLUMN horizontal reference; positive picture size and nonnegative signed offsets. Other controls, including equations, reject the new path. Existing TAC and other wrap paths remain unchanged.

The path reuses `layout_body_picture` to compute position and paint crop/effect/transform/border once. Its anchor is the actual first rendered TextLine top, which already includes paragraph before spacing. The Square return height is intentionally ignored: text wraps beside the picture instead of advancing below it. Owner/following semantic paragraphs retain their cached cs/sw exclusion while above the picture bottom. This does not remove the ordinary app object reserve or change math/table height rules.

## Reproducible build and packaged artifacts

- Core upstream: `ce45231c0c88efd5397d8fae9cd7d73de915095d`.
- Binding upstream: `c42f46aee3959c7caa33db771c0addc1a8302e61`.
- Separate source: `tmp/rhwp_renderer_square_build/{rhwp-core-patched,rhwp-python}`.
- Packaged wheel: `packaging/renderer/wheels/rhwp_python-0.7.0+nativecell3-cp310-abi3-win_amd64.whl`.
- Wheel SHA-256: `b34f19f66d585a3f82e9c5ba3722a352c3eacf5837267ff4daaef733c4303082`.
- `_rhwp.pyd` SHA-256: `50de55e32d998bde2cf83b80219fe5d1226ee4daf03b17f0b3d1de4bba55fdd1`.
- Final isolated site: `tmp/renderer-square/final-site`.
- Clean upstream patch replay and actual compiled-source match: `tmp/renderer-square/final-artifacts/patch-replay-proof.json`.

The package manifest records the wheel, both patches, Cargo.lock, README and validation artifacts. Windows requirements select nativecell3. Nativecell1/2 wheels and the non-Windows PyPI path remain available. After isolated validation, root installed nativecell3 globally and verified its fresh-process `_rhwp.pyd` SHA above; the final7 integrated report uses that same binary.

## Independent checks

1. `scripts/verify_renderer_embedded_cell_square.py`, using the same immutable input for nativecell2/3: positive plus 18 unsupported-mode negatives PASS. Input `tmp/renderer-square/prototype-input.hwpx`, SHA-256 `91143dfdb7b00236cc94b225ffe5e55f569c14fcbb1e76213a655f09f59122a8`. Scope report: `tmp/renderer-square/final-scope/report.json`.
2. TAC, no flow, TOP_AND_BOTTOM, behind/in-front, PAGE/PAPER horizontal/vertical references, negative offsets, missing/bad caches, second picture, center-aligned cell, and math control retain exact old SVG/PNG/page results. A caption mutant is not claimed: the current HWPX parser does not expose that caption to the renderer model.
3. Five native/math/public-edit regressions PASS: equation paragraph geometry, mixed table paragraphs (192 equations), nested textbox editing, shared table paragraphs, question edit reflow. Report: `tmp/renderer-square/native-regressions/report.json`.
4. Eleven identical-input font fixtures match fresh nativecell2 exactly in SVG, PNG and actual PDF faces/glyph bounds. Report: `tmp/renderer-square/final-artifacts/font-invariance-proof.json`. A historical mixed PNG differed by 3 pixels; a fresh nativecell2 run reproduced the same result as nativecell3, separating that historical drift from the candidate change.
5. Root's prototype independent source oracle: tree x error +0.00224px / y error −0.08456px; 18 text baseline errors −0.08 to −0.115px; following Q28 baseline error +0.00056px; actual PDF glyph/tree overlap 0. Artifact: `tmp/september-exam-matrix/q27-core-prototype-independent/report.json`. This prototype snapshot was marked unstable while app work continued, so its source-quality findings are not a final full-product PASS.

## Final integrated source and public edit checks

Final7's immutable full source/public edit report passes: `tmp/september-exam-matrix/q27-final7-independent/report.json` (SHA256 `28972c44b98447538a950edd29f45e6bdb419c6470cd445ed28b13d444278487`). The stable input SHA is `1779adad6b50702e02c6d2c79ed6a963b98dbe43d33f1f379333a516d1d7b5e3`; before/after source/code/renderer snapshots match. The independent scope audit is `tmp/renderer-square/final-artifacts/final7-report-scope-audit.json`.

The integrated app producer/save plus nativecell3 preserves 18 source rows, four frame rules, picture pixels/bounds, and the next-question baseline. Actual public intro append/delete/save/reopen changes 8 → 9 → 8 pages and native question height 33186 → 42644 → 33186 HWPUNIT. Deletion restores exact original text, Q28 page/x/y/distance and picture page/bounds. Reopened section XML and rendered text/image coordinates remain stable. This is an integrated product result, not a claim that the renderer patch alone implements the app's source-proof/cache/pagination logic.

Its PDF checks find no page-printable ink overflow or picture intersection among 658 original/deleted and 942 grown checked glyphs. They exclude three source U+00AD soft hyphens requiring separate visible-paint proof and six normalized bullet markers, do not certify every physical cell-edge ink bound, and do not verify source fontface identity. The SVG row comparison still includes the bullet markers. Row first-glyph x/y and baseline checks pass, but maximum all-glyph x error is diagnostic only: a short bullet row still has 6.095438 px error. Native PNGs are written, not independently pixel-compared by this final7 verifier. Complete visible PDF painting and exact horizontal typography are not proven by `ok: true`.

The fresh English3 subset remains quality FAIL at frozen app snapshot `e551659507c50ec18ca978990444653267151b0a59098acf6baab9d34237319f`: high1 harsh mean/minimum 93.21/90.68, high2 93.29/90.07, high3 87.05/78.58. Evidence: `tmp/september-exam-matrix/field-final-native3-20261007/report.json`. It is separate from the older full51 baseline. Target98 and the remaining PDF/font/spacing limits remain open.

## macOS

No actual Mac runtime is available. The same common Rust patch must be built natively for macOS arm64/x86_64, with matching commits/lock and renderer features, then exercised with actual CoreText/Skia loaded faces, PDF fallback, cell picture position, math, edit/save/reopen and packaging/signing. The Windows wheel cannot establish Mac runtime support or quality equivalence, and the non-Windows PyPI dependency currently does not ensure patch equality.
