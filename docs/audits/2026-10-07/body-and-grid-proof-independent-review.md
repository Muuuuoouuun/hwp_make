# Source body/grid proof independent review

This review changes only new verifier scripts and this document. Product code,
source PDFs and original HWPX packages were not changed by the reviewer. All
mutants and public edit outputs are separate files under `tmp/september-audit`.

## Independent checks

`scripts/verify_source_body_right_review.py` independently counts the native
ASCII-space positions in actual Q19/Q20/Q22 (107/139/164), verifies one-run and
per-character/empty-run layouts, and confirms double spaces, NBSP and tabs do
not receive the special quarter-em style. Actual Q19/Q20/Q22/Q23 exercise the
right-margin correction, preservation of every run/cache/shared style, and
stable reapplication of the resulting margin. The guard mutants cover actual
source records, complete native text, controls, fonts, style metrics, UTF-16
cache boundaries, paragraph/container geometry and complete cache metrics.

`scripts/verify_grid_state_styles_review.py` refreshes every saved cell style
signature from the changed current XML and then generates a valid state
checksum. This is stronger than changing a style while leaving its original
signature stale. It exercises supported text decorations, all-language font
references, nonuniform metric values, supplementary/combining Unicode, tabs,
newlines, native controls, duplicate cache containers and a generic dirty
paragraph. A supported unchanged grid remains a positive control.

`scripts/verify_grid_native_source_proof_review.py` tests the source consumer
separately from native edit-cache reuse. The real PDF, decoration pixels,
provenance and native text remain unchanged. Native glyph height, weight,
ratio or spacing changes must not borrow the original source exception.
The height mutant compensates the cell top margin so that the original
printed baseline remains unchanged, and refreshes the native state, style
signatures and checksum.

## Findings reproduced and returned to the owners

1. The first body-right callback accepted arbitrary plausible line heights,
   baselines, vertical starts and spacing. Exact source-regenerated cache
   checks now reject those cases, including a duplicate cache container.
   Independent proof also exposed the one-HWP-unit distinction between source
   cumulative coordinates and saved container reflow; both independently
   regenerated representations must be compared exactly.
2. Native strikeout, outline and shadow could initially borrow body/grid
   proofs. The grid state checksum could be recomputed together with all style
   signatures, and the strikeout mutant changed actual nativecell3 SVG.
   Current grid guards reject strikeout, outline, shadow, emboss and engrave
   independently of the mutable signatures.
3. The shared source line signature truncated fractional PDF span flags with
   `int()`. A fractional proof flag in Q19 and fractional typography/proof
   flags in Q23 could therefore still borrow the body proof. Body emboss and
   engrave also remained accepted. The stable pre-fix reproduction is in
   `tmp/september-audit/body-right-independent/report-late-before-fix.json`.
4. The source-grid consumer reconstructed its expected native font height
   from the current native font. A changed height of 600 (original 861), with
   the cell margin adjusted to preserve the source baseline, was accepted.
   Added bold, ratio 90 and spacing -10 were also accepted. The stable pre-fix
   report is `tmp/september-audit/grid-native-source-independent/report-before-fix.json`.

All four groups were corrected by the implementation owners. The final body
proof rejects fractional flags and emboss/engrave. The final source-grid
consumer compares complete native character tuples with independently read
actual PDF family, size, flags, horizontal transform and tracking. Short-run
tracking can inherit only a unique measured default from the actual grid's
same face, size, flags and transform. It then reconstructs expected cells.

## Recorded verification runs

| Run | Result | Evidence |
|---|---|---|
| Frozen body fixture before the five late guards were added | PASS 89 | `tmp/september-audit/body-right-independent/report-final.json` |
| Five late body guards, with four actual positive controls | FAIL 5; positives pass | `tmp/september-audit/body-right-independent/report-late-before-fix.json` |
| Fresh grid final3 original guard/public edit review | PASS 30 | `tmp/september-audit/grid-flow-independent/report-final3-edits.json` |
| Fresh grid final3 refreshed-signature/checksum review | PASS 25 | `tmp/september-audit/grid-state-styles-independent/report-final3.json` |
| Actual source-grid/native-style consumer review | FAIL 4; both actual grids pass | `tmp/september-audit/grid-native-source-independent/report-before-fix.json` |
| Revised fresh body `body-alignment-final-20261008/final/native.hwpx` | PASS 94, including all late guards | `tmp/september-audit/body-right-independent/report-final-revised.json` |
| Fresh grid final4 guard/public edit review | PASS 30 | `tmp/september-audit/grid-flow-final4/report.json` |
| Fresh grid final4 refreshed-signature/checksum review | PASS 25 | `tmp/september-audit/grid-state-styles-final4/report.json` |
| Fresh grid final4 actual-source/native-style consumer review | PASS 7 | `tmp/september-audit/grid-native-source-final4/report.json` |

The grid public check independently reads the actual PDF cell text. Small
edits preserve the original eight pages and table height; larger edits grow;
deleting the addition restores the exact original page count, height and
table text. Every listed run records stable reviewed-code hashes before and
after. The final frozen runs pass all 156 reported checks across the four
independent verifiers. Earlier failures are retained as reproduction evidence,
not current failures.

## Scope and limits

These checks do not certify full-page fidelity, a target quality score, Hancom
painting or a Mac runtime. In current nativecell3, `relSz`, `offset`,
`useFontSpace`, `useKerning` and `symMark` are not active glyph-paint controls;
their absence from the grid's current paint guard is recorded separately from
supported decorations. Body-space reapplication uses a memoizing test
allocator. It does not establish raw producer style-ID idempotence; the prior
review's resolved-style/fingerprint distinction still applies.
