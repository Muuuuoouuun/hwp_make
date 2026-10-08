# Actual English source grids and editable native row flow

2026-10-08. This is the basic PDF-to-editable-HWPX path. The source PDF is
`data/external_exam_qa/2027_kice_september_high3/english.pdf`, SHA-256
`745d64d94e0719735b88a10802fbbd5053b4982c855199396e58fe2f53b81cf0`.
The renderer remains the installed `rhwp0.7.0+nativecell3` runtime.

The two actual source grids in Q27/Q28 are each one ordinary native table.
Source-derived empty, borderless gutters preserve the surrounding decoration's
extent. The actual inner cells keep their source widths, rules and text; their
native top margins carry the source text origin. No whole-page image, text
overlay, flattened table image, extra paragraph per source line or renderer
change is involved.

The producer and consumer independently reopen the PDF and check its complete
dark rules, every raw source text span/character and geometry, the literal
native cell text, and the actual non-text background pixels. A table name or
an editing-state digest does not establish source provenance. The consumer
reconstructs the expected native table independently of the saved cache.

## Digest-valid cache forgery and the correction

An independently discovered mutation replaced the `1st prize` source cache's
native height/textheight 861 with 1000, its baseline with 850, and its reserve
344 with 205. The unchanged native source row remained 1205. Recomputing the
state checksum previously allowed this internally consistent cache to pass.

The saved source cache now has exactly one canonical line: textpos, vertpos,
spacing and horzpos are zero; vertsize and textheight equal the current resolved
native `charPr.height`; baseline is `round(height * .85)`; horzsize equals the
actual cell width. Nativecell3's resolver uses `charPr.height` as `base_size`.
The native top margin, canonical height and original reserve must independently
sum to the actual original row height. Current non-dirty caches must also agree
with the newly prepared cache. The entire operation remains transactional.

A second independent mutation cloned a native character style from861 to600,
changed the canonical cache height to600/baseline510, and increased top padding
by222 to preserve the source baseline. Reconstructing expected cells using those
current styles previously accepted it. Added bold, ratio90 and tracking-10
mutations were also accepted despite unchanged actual source glyphs. The
independent reproduction is
`tmp/september-audit/grid-native-source-independent/report-before-fix.json`.

The source proof now compares the complete native character sequence and each
character's family, rounded source font height, bold/italic/superscript state,
horizontal ratio and tracking against the actual PDF. Matching actual text
traces by face, character and origin independently supplies horizontal size;
native cache state cannot supply it. Adjacent actual source glyphs in longer
runs supply tracking. Short labels inherit only a unique measured default
from longer runs in that same actual grid with the exact same PDF face, size,
flags and horizontal transform. This keeps normal short-label kerning from
being misread as whole-run tracking. Missing/ambiguous evidence abstains.
Nonempty original native cache height and textheight must already agree with
the current native font before normalization, so canonicalization cannot erase
a forged font/cache disagreement. Supplied source flags must be finite,
integral and exactly equal actual PDF flags.

Empty styled runs are validated and included in style signatures. Their cache
height still equals their current native font height after complete public text
deletion. The real source's originally empty styled cell is canonicalized to
861, replacing its generic blank-line height 1133; its source row does not
change. Runless decoration gutters have an exact one-unit empty cache and
cannot contain runs. Removing an empty cell's style or forging a gutter cache
therefore cannot evade the font-height equality check. The importer validates
the original native line fields before canonicalizing them, so malformed blank
cache values are rejected rather than overwritten.

Public deletion of all text in a proved grid cell now remains in the question's
missing-cache work list and uses the same bounded native grid plan. Genuine
word wrapping grows the row and question; deleting the added text restores the
original row reserves and page/column break state.

## Supported metric and paint boundary

The narrow grid path supports ordinary Times New Roman ASCII runs, uniform
script ratios/tracking and left/center alignment. Character advances match
the compiled native metric table's integer HWP-unit truncation. In particular,
ASCII space is half-em before truncation: height861 gives430 units. The cache
fit check also accounts for the native painter's pixel rounding.

Italic, superscript/subscript, underline, strikeout, outline, shadow, emboss and
engrave are rejected independently of the mutable saved signature. Negative
tests recompute the state digest and synchronize changed current style hashes,
so a checksum failure is not the reason those decorations are rejected.
Nativecell3 currently ignores `relSz`, `offset`, `useKerning`, `useFontSpace`
and `symMark` in this paint path; these fields do not establish a broader font
or Hancom rendering guarantee. Unknown glyphs/controls and unsupported fonts
fail closed to the ordinary editor flow.

## Verification

The reproducible full regression is:

```powershell
$env:PYTHONUTF8='1'
python scripts/verify_native_source_grid_layout.py tmp/september-exam-matrix/high3-grid-final4
```

It generates a fresh real source document, checks producer/consumer/vendor
negatives, and exercises public small edits, large growth, restoration,
complete deletion/restoration and the ASCII-space wrapping boundary. For
nonempty edited cells it measures actual native PDF-painted glyph bboxes
against independently painted native table rules. Reopening and saving must
preserve table XML; restoration must reproduce the complete original page4
PNG. All native binary media must remain byte-identical.

The earlier fresh component evidence is
`tmp/september-exam-matrix/high3-grid-final2-components.log`: 13 consumer
negatives and the five edit/deletion stages passed. The final guard component
passes 26 vendor negatives. Small editing preserves eight pages and grid height
5593, changing 77 page4 pixels. Large editing yields nine pages and height18760.
Its 86 actual painted nonspace glyphs have bbox
`[431.9934,428.2202,488.6733,615.2561]` inside the actual ruled cell
`[431.1333,425.16,489.8533,616.7867]`. Both text restoration and complete
deletion/restoration return to eight pages, height5593 and the exact original
page4 PNG.

The fresh final4 run completed at 2026-10-08 13:22:26 KST: 34 producer,17
consumer and26 vendor negatives and all six public edit stages passed. The
ASCII-space boundary wraps to nine pages and first-grid height6790; its eight
painted nonspace glyphs remain inside the actual ruled cell. Reopened table XML
and native media are unchanged in every stage. The independent actual-source
font proof also passes its seven checks, including all four digest-valid
font/style mutants. The complete report is
`tmp/september-exam-matrix/high3-grid-final4/report.json`.

The 13:06:10 candidate freeze was released after the concrete producer and
consumer font findings above. Final application freeze was announced at
2026-10-08 13:17:47 KST, with these hashes:

| File | SHA-256 |
|---|---|
| `app/pdf_source_grid_layout.py` | `bd465814930e21592530cd340e354981c3850bc0c7f326701c01e35176af33aa` |
| `app/_vendor/hwpx/tools/ruled_grid_flow.py` | `5ef6226263a322c5490acda41d64503baa8deb8984ed42b2b2e4bbda68adf6f6` |
| `app/_vendor/hwpx/tools/question_reflow.py` | `4fe2f7b65c0f0aab8e5df57368d6575b7ea1e490f4493bbd8a4998b6cd42673c` |

These are local source/cell/edit-flow findings. They do not claim target98 or
a whole-document visual-quality pass. The root's final frozen API matrix and
independent review remain the whole-document evidence.

The subsequent actual-source glyph diagnostic also establishes a specific
limit: final4's correctly bounded cells still paint below the source page
positions. Across all226 actual grid glyphs, Q27 has mean Y residual+6.45435px
and Q28+9.99199px. The local cell-baseline residual is below.0064px, so the
displacement originates in preceding question/table flow. These measurements
are recorded in `tmp/september-audit/grid-quality-ab/baseline-glyphs.json`.
They do not invalidate the edit/bounds checks, but those checks cannot establish
actual source page-baseline alignment.

A tmp-only source-space experiment independently proves actual page4 Times
GID3 has quarter-em advance (PDF CID width250 and embedded TTF512/2048).
Translating28 exact internal ASCII spaces to native ratio80/tracking-15 reduces
Q27/Q28 grid X mean absolute residual from1.851/1.889px to.275/.369px, with
zero changed pixels outside the two grid rectangles. It leaves the Y residual
unchanged. This translation is not in the app: the public paragraph setter
collapses split runs, so current strict flow signatures correctly abstain and
ordinary edits fall back to generic table growth. A source-space translation
needs its own portable editing contract and independent source proof before
product integration. The complete diagnostic is
`tmp/september-audit/grid-quality-ab/report.json`.

The subsequent crop-only app correction and its actual page-origin A/B,
strict staged source-font guards, public edit checks and remaining portable
reserve limitation are documented in
[`source-grid-page-origin-diagnostic.md`](source-grid-page-origin-diagnostic.md).
The app retains the200/400 native reserves and original uniform grid spaces.
