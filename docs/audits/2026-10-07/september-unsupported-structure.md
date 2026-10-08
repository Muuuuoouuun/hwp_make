# September native writer rejection audit

The stable 51-paper baseline recorded nine HTTP 400 `unsupported_structure`
responses. These responses did not all mean that question recognition failed.
The source of truth is
`tmp/september-exam-matrix/stable-all-51-20261007-final/{findings,source_inventory}.json`.
That baseline remains unchanged; its product fingerprint was
`7b63c82ddc00b5ff3cbfebe5c06fe0b34f5c26a7aeab0f1865a250bc68a0b916`.

## Actual failure isolation

All nine source PDFs were read independently of the native writer. Source
page/number pairs were compared with recognition and native item groups.
Direct writes captured the concrete Python traceback rather than inferring a
cause from the public error message.

| Source | Actual inventory | Concrete rejection |
|---|---:|---|
| High1 mathematics | 12 pages / 30 questions | Final question whitespace exceeded signed 16-bit drawing text-margin range |
| High2 mathematics | 12 / 30 | Same |
| High3 probability/statistics | 12 / 30 | Same |
| High3 calculus | 12 / 30 | Same |
| High3 geometry | 12 / 30 | Same |
| High2 integrated social studies | 6 / 25 | Q23 wrapper required 95,255 HWPUNIT; available height 69,915 |
| High3 Chemistry I | 4 / 20 | Word fraction in vertically merged source cell unsupported |
| High3 Earth Science II | 4 / 20 | Estimated word-fraction width 24,684 exceeded source width 22,961 |
| High3 Commercial Economy | 4 / 20 | Recognition invented a second Q2 inside Q4's source frame (21 recognized) |

The first eight inventories match their independently frozen source markers.
Commercial Economy's extra marker was a smaller numbered list item. Its raised
footnote enlarged the full line box to 13.68 pt, above the actual question
marker height of 13.30 pt. The number glyph itself is only 11.76 pt high.

Evidence is under `tmp/september-exam-matrix/unsupported-structure-fix/`:
`before.json` holds source/recognition/native grouping comparisons, each source
subdirectory has a direct-write report, and failed math sections/headers are
preserved as XML. Repeated post-fix direct writes may replace the corresponding
write report; the original stable API evidence remains authoritative.

## Narrow fixes owned by this audit

`app/_vendor/hwpx/tools/question_spacing.py` retains oversized *trailing*
question whitespace. The bottom drawing margin receives only its representable
portion. The remaining measured space becomes ordinary after-spacing on the
last existing inner paragraph; drawing, editable text area and host cache
heights grow by the same total amount. No new paragraph, drawing, proof flag,
image or overlay is added. Content origins and text/equation/picture/table XML
are preserved. Reflow measures that real paragraph spacing after edits.
Oversized leading margins remain rejected rather than silently clamped.

`app/recognition/pdf_segment.py` compares the number's first source span height
when distinguishing small numbered lists inside figures. The existing source
figure containment and outside-question height comparison are still required.
Missing span geometry retains the previous conservative behavior; equal-sized
framed questions and small markers outside figures remain questions.

The fraction fixes are separately owned by the root task. Their independent
read-only review identified the need to include fixed native object widths in
the new overflow minimum; the root added that guard. Inline 30,000-unit picture
width now measures as 30,000 rather than zero; non-inline/invalid objects remain
rejected.

## Verification and remaining failures

`scripts/verify_native_question_trailing_whitespace.py` checks occupied height,
unchanged semantic nodes/content origins, idempotence, ordinary-paragraph and
leading-overflow negatives, growth/deletion and reopened saves. It also writes
all five actual math PDFs, verifies the frozen source SHA/page/number inventory,
and compares all painted SVG text coordinates before and after native saves.
The real High2 Q30 edit preserves its original equation scripts and 2,035-unit
internal trailing gap, remains 12 pages, and is stable after reopening.

All five actual math outputs remain 12 pages and 30 questions. Their native
equation counts are High1 171, High2 217, calculus 236, probability/statistics
187, and geometry 206. High2 source text preservation is 0.9787; the others
report 1.0. None uses body rasterization or text/math overlays. These are
structural checks, **not full quality passes**.

`scripts/verify_recognition_marker_glyphs.py` checks actual Commercial Economy
20/20 recognition plus superscript/list, framed-real-number, absent-figure,
absent-reference and missing-span negatives. Existing
`verify_english_recognition.py` and `verify_native_question_gap_reflow.py` pass
unchanged. The latter retains its known generic first-page masthead residual
of 13.751686 px; this audit does not relabel it as fixed.

Fresh strict API probes for mathematics five papers and Commercial Economy
all move from HTTP 400 to **HTTP 422 `strict_check_failed`**. Each probe and the
six-probe cohort used the same unchanged product fingerprint,
`13ea9f8e75cef9b9bd62ec6dd03b8eabd86833708a28066a348962d0041de191`.
High1/High2 math still fail running-head preservation and source semantic
checks. High3 math still fails source semantic checks. Commercial Economy
still fails positioned-table and semantic checks. No missing question content,
wrong picture ownership, wrong script ownership, wrong shared passages or
wrong question geometry is reported in this six-case cohort. Detailed semantic
issues remain in `api/<case>/report.json`; none is suppressed.

Actual and synthetic regression artifacts are in `regression-final/`, with
`regression-final.log`, `english-recognition.log`, `english-gap-reflow.log`,
and the strict API logs beside them. The unchanged objective/fidelity criteria
have not been met merely because the writer can now proceed.

## Integrated social studies Q23 follow-up

The Q23 failure is already present before the question wrapper. Its one source
chat frame becomes four text fragments separated by three avatar icons. Every
text fragment reserves the full frame's 18,483-unit height, creating 93,445
units before internal spacing and 95,255 including spacing/reserve. This is
duplicate frame reservation, not a genuinely oversized source question.

`social-height/{before,after}.json`, `section.xml`, `header.xml` and the log
preserve this diagnosis. The existing illustrated-frame coalescer remains
limited to its one/two right-side illustrations. The new
`app/pdf_dialogue_frames.py` instead proves the source's complete four rules,
every raw text span, three actual alternating avatar bitmaps and a distinct
parenthesized answer list before joining this whole conversation once.

The result has five semantic bands and three columns: notice, three turns and
the answer list. Nine editable paragraphs retain the thirteen source text
lines; no cell represents an individual printed line. The original whole
frame occupies 18,483 HWP units once. The three avatars remain ordinary native
inline pictures. Thirteen original small bubble-decoration bitmaps become the
table fill, without rendering PDF prose into an image. Their PDF soft masks
have twice the base bitmap resolution; composition respects that measured
integer grid while retaining the original placement rectangle.

The independent native consumer reopens the source and proves the four rules,
raw typography, topology, native addresses/spans, source baselines, positive
cache extents, all avatar pixels and the decoration inventory. It ignores
producer names and flags. Avatar cells must contain exactly one paragraph and
one owned picture with an unshifted first cache origin. Fractional addresses,
extra empty avatar paragraphs, shifted caches, unknown controls and incomplete
source evidence are rejected without mutating the source, native XML or
styles. Existing styles are append-only; source paragraph/run content is kept.

`app/pdf_source_image_validation.py` uses the new decoration composer only
when this same actual-source dialogue proof succeeds. Otherwise it retains
the existing composer. Existing pixel limits and the separate editable-text
proof remain unchanged. Q23's actual decoration is an exact-byte match, and
the independent text proof accounts for 247 source characters. This corrects
the previous generic composer's unequal-soft-mask exception rather than
suppressing a failed image check.

`scripts/verify_native_dialogue_frames.py` checks the frozen actual source
SHA, all six source pages and all 25 source questions, 26 producer negatives,
15 native-consumer negatives, additional decoration inventory/region
negatives and idempotence. A public one-character edit changes 225 pixels,
retains frame height and is stable after reopening. A large public paragraph
edit grows the native frame, preserves the five-by-three semantic structure
and all media, paints the appended marker, and is stable after reopening.
All 247 original and 352 enlarged-content glyphs remain within their native
frame. Artifacts and the machine-readable report are in
`dialogue-regression-final/`, beside `dialogue-regression-final.log`.
The unchanged old June English grid regression also passes with this hook:
eight pages, 35 changed pixels for the 50-to-60 edit, preserved pictures and
equations, visible large text growth and stable reopened saves. Its artifacts
and log are in `dialogue-old-june-grid/` and `dialogue-old-june-grid.log`.

The actual strict API now proceeds from HTTP 400 to **HTTP 422**. The output
still has nine pages for six source pages, so this is **not a quality pass**.
Remaining reports include running-head loss, other positioned tables and
pre-existing page-three image/text incompleteness. Q23's decoration itself
passes exact pixels and editable-text proof. The API fingerprint/result is
preserved in `api/2026_september_high2__s_soc/report.json`. Both that run and
the dedicated regression began and ended with fingerprint
`7f46361438b051e2760557d029ea554996d78cdf701af76da497e6caa9bd91f7`.
This is a stable execution snapshot, not the final whole-app freeze: other
native layout work was continuing. A later changed fingerprint makes these
results preliminary for that later product. The concurrent intermediate API
report is separately retained as `report-preliminary-concurrent.json`.
No criterion, wrapper limit, body-raster restriction or overlay gate changed.
