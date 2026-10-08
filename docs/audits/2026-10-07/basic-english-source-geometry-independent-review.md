# Basic English source geometry: independent read-only review

The fixed native margin/column profile is not a source-conformance test for the
three original English PDFs. This review changes no scorer, weights, gates,
product code or original files. It independently reads original PDF raw glyph
origins and vector rules, native HWPX XML, and actual nativecell3 PDF painting
of the old stable outputs.

## Source and native measurements

Original high1/high2 pages are 841 × 1190 PDF points; high3 pages are 842 × 1191
points. The existing output is A4, approximately 595.280 × 841.880 points. The
following source glyph coordinates are normalized by the observed native/source
page-width ratio, the same explicit coordinate system used for the comparison.

| Source | p2 left/right question-number x in source points | A4-normalized x in mm | Native painted x in mm |
|---|---|---|---|
| high1 | 87.839996 / 429.959991 | 21.934051 / 107.362986 | 21.935725 / 107.364398 |
| high2 | 87.839996 / 429.479980 | 21.934051 / 107.243125 | 21.935725 / 107.244455 |
| high3 | 87.900002 / 436.559998 | 21.922967 / 108.881571 | 21.967474 / 108.881339 |

Q13 and Q18 are identified by their unique complete printed first-row text;
the compared coordinates are the first nonspace raw source glyph origin and
the corresponding visible painted native glyph origin. The high1/high2 maximum
absolute error is 0.006328 px horizontally and 0.003600 px vertically at 96 dpi.
The old stable high3 result has a 1.099047 px vertical residual; it is not a
perfect source-alignment result.

The independent source vertical separator is x=420.979 points in high1 and
x=420.500 points in high2. Their question rails and these actual rules support
a substantially narrower central separation than a prescribed 6–10 mm gap
after A4 reduction. Ink clearance alone does not uniquely define a native
column gap, so it is not substituted for the native geometry below.

| Stable native | Left / right margin mm | Top margin section0 / section1 mm | Header margin section0 / section1 mm | Column gap mm |
|---|---|---|---|---|
| high1 | 21.935722 / 21.635861 | 27.414361 / 28.493861 | 30.811611 / 14.029972 | 4.427361 |
| high2 | 21.935722 / 21.755806 | 27.414361 / 28.493861 | 30.811611 / 14.029972 | 4.307417 |
| high3 | 21.921611 / 20.118917 | 27.227389 / 26.839333 | 30.028444 / 12.841111 | 5.958417 |

Top and header margins are distinct native fields. For example, high1/high2
section1 has top+header = 42.523833 mm; the actual p2 question ink begins near
42.54 mm. Comparing the source body's top with the native `top` field alone
would discard the header region and misinterpret the native page model.
These values describe the saved XML; actual painted glyph coordinates remain
the separate source-alignment evidence.

## Why the current cap does not establish source error

`inspect_layout_template_profile` requires 17–23 mm left/right/top margins and
6–10 mm native column gaps. All three stable outputs fail the top condition;
all three fail the gap condition, with high3 only 0.041583 mm below 6 mm.
The high1/high2 first-question origins nevertheless match the originals within
0.007 px. The fixed profile therefore tests a prescribed layout style rather
than fidelity to these original source layouts.

`_pdf_structured_objective_score` deducts the paging profile points and also
uses the separate `source_layout_coverage_ratio`. The documented layout 80 and
paging 65 yield the structural weighted score 89.75. This review does not
replace that calculation, award missing coverage points, or claim that the
whole document meets a quality target. Two precisely matched question origins
are evidence against interpreting the fixed profile as source geometry; they
are not complete source-layout coverage.

## Independent source-conformance proof to use in a future design

A source-preservation check should bind actual source and native dimensions,
an explicit scale/rotation transform, all printed glyphs and images, question
ownership/order, and physical page/column ownership. It should compare native
rendered positions with actual source origins/bounds and validate native flow
rails, container widths, wraps and page/column breaks independently. Native
margin/header parameterization should be assessed through the resulting body
and masthead geometry. An arbitrary margin value or correct object count does
not prove any of this.

The comparison must cover all pages and components, preserve editable text,
reject incomplete/duplicated/cropped source subsets, and keep image/rule bounds
and non-overlap checks. Actual rendering thresholds and existing API targets
remain separate requirements. Replacing the fixed style profile with a
source-conformant proof would require an explicitly authorized scorer design
change and full validation; no such change was made here.

## Inputs

Source PDFs:

- `data/external_exam_qa/2026_september_high1/english.pdf`
- `data/external_exam_qa/2026_september_high2/english.pdf`
- `data/external_exam_qa/2027_kice_september_high3/english.pdf`

Native packages are the `english_structured_native.hwpx` files in the matching
English cases under `tmp/september-exam-matrix/stable-all-51-20261007-final`:
high1/high2 batch2 and high3 batch1. This is an old stable-output comparison,
not a substitute for the current frozen three-English API/render matrix.
