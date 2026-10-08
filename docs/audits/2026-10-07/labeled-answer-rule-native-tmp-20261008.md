# Editable labeled answer rules: current-I TMP qualification

This candidate is **TMP only**. No app, vendor, renderer or production writer
hook was changed. It builds ordinary HWPX TABs and BOTTOM underline styles in a
clone of the actual current-I high3 English output. Source Y and underline
thickness remain unresolved; this is not a whole-document quality pass.

## Inputs and permission

`tmp/september-audit/choice-column-header-candidate/native_labeled_answer_rules.py`
SHA `fd22aee99ad32f69ad9108ef70d0277905018b702012ab23cde92f89ed8ba7b1`.
The separate TMP cache adapter `native_labeled_rule_cache.py` has SHA
`cfde1d5086a8d38023a90a9ae561c199c8181984c97b28c125187f0721382c60`.

The input is the actual grade3 row of
`tmp/september-audit/basic-english-i-question-priority-checkpoint.json`, its
original PDF, and the actual 268 producer items at
`tmp/september-audit/labeled-interval-source-current-g/producer-area-hint/items.json`.
The items' source membership is re-proved against the PDF; their earlier folder
name does not select an old native package. Old D/G owner gzip records, QA
oracles, old TAB advances and saved cache widths do not grant permission.

The frozen source planner is
`tmp/september-audit/choice-column-header-candidate/source_labeled_answer_rules.py`,
SHA `6f973499818eaea540f4eb529523251f3c057110b85fed8a40fe88ebd5133972`.
Its independent 35/35 source/paint checks remain separately recorded in
`tmp/september-audit/labeled-rule-source-independent-6f973/report.json`.
This file was not modified.

The new helper scans all 45 producer/native numbered owners. It verifies their
complete text inventories, then independently qualifies one actual candidate
(observed Q40), without a question-number, paper-hash or prose selector. The
target's complete 1,180-glyph PDF numbered band and actual native wrapper paint
are bound. Actual source frame rows, raw/trace direction, Unicode/CID/GID/font
program, visible rules and current seven-language native font/style metrics
are required before mutation.

Current page columns are independently replayed from actual PDF segmentation.
Actual table/cell size, position and margins, paragraph styles and every field
of all three source cache rows are re-derived using source frame restoration
and the canonical common-subList position pass. Exact equality is required;
there is no tolerance or saved-cache normalization. The native frame must also
retain the producer's plain black border profile.

## Preserved failure and narrow cache correction

The first current-native fitter assigned textpos 87 to the continuation after
the closing underlined TAB. That puts the original separator ASCII space at
the beginning of the next row, shifting all 36 continuation glyphs by 5.7333px.
The failure is preserved under
`tmp/september-audit/choice-column-header-candidate/labeled-rule-native-current-i/failed-first-fit-87/`:
`qualification.json`, `geometry-current-i.json`, and `native.hwpx`
(SHA `49ea2183611662a09dd8643832f2027fc6caf209bd078bba1935939594722079`).

The TMP cache correction consumes one nonpainted ASCII separator after a
complete currently measured `TAB + label + TAB` interval. The distinct plain
space style must match every label metric/style field except ID and underline,
the next unit must be ink, and the complete underlined interval must fit the
actual current usable width. The separator's actual native advance remains
bounded. No source cache position or source width is consulted by this cache
correction. All six actual font-derived TAB widths are unchanged; the resulting
textpos 88 follows naturally from consuming the delimiter.

The 19 actual-provider differential controls cover NBSP, TAB, repeated spaces,
missing separator, same underline SID, transformed height/ratio/tracking/
baseline/relative size/bold/italic, an over-limit closing TAB, zero width,
None provider and wrapped context. Unsupported cases reproduce the original
cache XML or unchanged fallback exactly. The cache adapter remains separate
from the installed vendor implementation.

## Actual results and evidence

All current evidence is under
`tmp/september-audit/choice-column-header-candidate/labeled-rule-native-current-i/`:

- `canonical-cell-diagnostic.json`: actual source replay reproduces all current
  table/cell geometry and all three row caches exactly.
- `qualification.json`: 45-owner scan, one reconstruction, eight pages,
  source/app/vendor/runtime stable; second call returns identical bytes and
  changes zero groups. Candidate HWPX SHA
  `23d02d37483cb53b20c1332bbe6e817d7a9f7c804c2efd3e866bc8c187140adc`.
- `guards.json`: 66 source/native canonical-envelope and exact bytes-fallback
  checks pass under `-O -B`. These include all seven current font slots, styles,
  both rows' nine cache fields, native integer lexemes, size/margins/columns,
  duplicate cache/style/border structures, source row/font/bounds omissions,
  malformed input and source I/O fallback.
- `separator-cache-guards.json`: 19 actual native-font/provider differential
  controls pass; no fake positive provider is used.
- `geometry-current-i.json`: all 27,781 native glyphs remain present. Exactly
  33 of the 35 target-row glyphs move horizontally; all other 27,746 complete
  glyph tuples and outside-row pixels are identical. All glyph Y coordinates
  remain exactly unchanged. Target row maximum absolute X error improves from
  52.6365px to 0.7683px; the label origins are within 0.01px of source.
- `rule-paint.json`: both actual native PDF lines have continuous black ink;
  source endpoint X errors are at most 0.00541px.
- `public/report.json`: 20 public add-run, held-run repeated-edit,
  save/reopen/resave and identity checks pass with the **explicit TMP cache
  adapter** and installed current-header/native font factory. Original run/t/TAB
  references, literal text and six TABs survive; the other 44 question texts and
  26,601 outside-owner world glyph tuples remain exact. Ordinary no-edit saves
  use the installed product directly and preserve every SVG.

Drivers are `qualify_labeled_native_current_i.py`,
`verify_labeled_native_guards.py`, `verify_labeled_separator_cache.py`,
`measure_labeled_native_current_i.py`, `measure_labeled_native_rule_paint.py`
and `public_labeled_native_current_i.py` beside the helper. `audit-manifest.json`
records current hashes for these artifacts and the unchanged product modules.

## Limits and next gate

The installed product cache still emits the failing 87 boundary after this new
paragraph is edited. Positive edited public checks explicitly substitute the
guarded TMP cache adapter in their own process; they do not establish a landed
product cache fix. Independent review of this narrow correction is required
before any integration.

The original source-to-native row Y residual is 2.2663–3.3455px and remains
unchanged. Native underline Y is 2.1736px below the source rule, and native
underline thickness is 1pt versus the source's 0.33935pt at the A4 native scale.
The first target row keeps its original Y after editing; normal 144% line-cache
rounding moves continuation Y by 0.02667px. This small edited-flow rounding is
recorded separately from the initial exact-Y A/B. Source Y, stroke thickness,
full producer integration and broader corpus qualification are not claimed.
