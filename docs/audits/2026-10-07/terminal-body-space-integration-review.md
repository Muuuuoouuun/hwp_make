# Actual terminal body spaces and complete-source boundary review

This review follows the frozen three-English matrix. Root explicitly released owned app edits after the independent temporary experiments; earlier matrix results do not include this new terminal-space branch.

## Source and A/B evidence

The Q23 source contains one natural terminal-row ASCII space. Its actual Type0 resource, ToUnicode CID 3, identity CID-to-GID mapping, explicit PDF width 250/1000, embedded TrueType unitsPerEm 2048 and GID 3 horizontal advance 512 all agree. Actual source trace origins, face, size and flags independently match all 157 source spaces. The terminal natural following-origin advance is .2489011605 em. Exact xrefs, program offsets, hashes and malformed resource/program negatives are retained in `tmp/september-exam-matrix/q23-single-space-prototype/README.md` and its JSON reports.

The all-body experimental branch narrowed 157 spaces and worsened Q23's whole-body maximum horizontal residual from 2.966102 to 5.486554 px. It was excluded. The terminal-only experimental branch narrows one actual terminal-row cursor and reduces that whole-body maximum to 1.634272 px; terminal-row maximum improves to .215924 px. All 831 complete native glyph tuples in the preceding 16 body rows and all 26,936 complete glyph tuples outside Q23's body remain exactly unchanged. The full 27,781 visible non-whitespace glyph inventory/page order, eight pages, native text and every y coordinate are preserved. Existing Q19/Q20/Q22 helper maps remain exactly 107/139/164 entries.

## Generic complete-body boundary

B's shared coverage candidate was independently tested against 11 actual complete bodies from the original three English PDFs. Exact ordered actual instruction/body band signatures reject first/interior/final-row omissions, duplicate/reversed rows and actual opposite-column row substitutions. The actual following column boundary must be nearby first choice `①`, after optional vocabulary-note rows.

An initial `startswith('*')` note condition accepted an omitted raw body row whose first character was replaced by `*`. This was an isolated consistent raw-row logic fixture, not a claim of an actual altered PDF. B tightened notes to an English headword followed by colon and Korean gloss, smaller source font, and bounded actual adjacency. The revised candidate passes 131 independent cases: 11 positives and 120 negatives, including malformed note grammar, body-size/tiny/far note styles and the original bypass. See `tmp/september-exam-matrix/q23-single-space-prototype/generic-coverage-review.json`. This is an additional completeness guard after actual raw/style/semantic/rail proof, not a standalone classifier for arbitrary documents.

## Product scope and consumer requirements

The new `app/pdf_source_font_spaces.py` directly proves the actual resource/program/trace relation and returns only actual terminal-row ASCII-space cursors after shared complete-source proof. `app/pdf_source_body_spaces.py` retains its existing full reproof and exact >=3-final-advance output; only the new one/two-advance branch filters its result to the terminal-row cursors. No product inspect/source-copy/monkeypatch implementation is used.

The dedicated verifier is `scripts/verify_native_terminal_source_body_spaces.py`. It covers ordinary/per-character native runs, double/NBSP/tab/empty/changed/control rejection, source proof absence, native metric/style mutations and public add_run/save/reopen/resave.

During verifier preparation, changing only the narrowed space's height, bold or italic state was accepted by the old native right-margin consumer. Its source/native tuple comparison excluded whitespace. B owns the fix: every ordinary space must match the next proved source nonspace font/height/flags in addition to exact ratio/tracking/effects guards. The before-fix failure report is `tmp/september-exam-matrix/q23-single-space-prototype/public-edit-prototype/report.json`. Final integrated checks are recorded separately after all owners finish; no passed public-edit or full matrix result is inferred from the temporary A/B alone.

## Integrated validation

After B's explicit final app freeze, the direct product implementation passes 49 source/font/program and synchronized native/source truncation negatives (`q23-single-space-prototype/integrated-guards/`), all 131 generic completeness cases (`generic-coverage-product-review.json`), and all 46 dedicated native/public checks (`public-edit-final/report.json`). The public run's complete app and installed runtime fingerprints are identical before and after. It checks all seven terminal-space font references, height/bold/italic/effect/metric mutations, empty/changed/control bodies, public append cache invalidation, growing semantic reflow, preservation of all original resolved character styles and native margins, complete painted body text, and exact page 3 SVG after reopen/resave.

An earlier functional public run passed its edit/paint assertions but correctly failed the final fingerprint comparison because B's question-body module changed during that run. Its `public-edit-integrated/report.json` is retained as a failed run and is not counted as stable validation. The 46-check run above is the stable rerun. These checks use the actual terminal-only native A/B package; authoritative fresh integrated producer checks are separate.

The authoritative fresh package `tmp/september-exam-matrix/basic-english-integrated-high3/native.hwpx` subsequently passes all 98 independent right-margin/source/native checks, including actual positives and reapplication stability for Q19–24, and all 39 direct terminal-space native guards. Reports are `tmp/september-audit/body-right-independent/report-integrated-six.json` and `q23-single-space-prototype/fresh-integrated-native-guards/report.json`. App/runtime snapshots remain stable. Public edit validation and source font proof are distinct from the root's whole-page matrix score.
