# Source-proved editable English choice spacing

The basic native English writer now repairs circled-marker gaps, actual ASCII
wordspaces, and independently permitted line leading in complete five-choice
groups. The shared `hwpx_writer_v2.write_hwpx` hook runs after native package
saving and before the caller's heading/TAB refresh. It requires source layout,
native source content, and the `kice_english` template.

Product files at freeze:

- `app/pdf_source_choice_geometry.py`: SHA256
  `ba4252d4e2d504a150a04c106b10420e937518265f146d788322a0595235db81`
- `app/hwpx_writer_v2.py`: SHA256
  `b6a61a4dbf5aa0a52a4d73a6753c7689d0e77d37acb37bbd6d471da698490264`

The original qualified TMP candidate remains unchanged at
`tmp/september-exam-matrix/source-choice-geometry-candidate.py`, SHA256
`ab85b3a6cff2de7242a428440219b72864f9a18a7d69472f9615519a7da1101a`.

## Permission and atomicity

The module proves complete actual PDF raw/trace rows, source font resources
and U+0020 glyph widths, complete native paragraph ownership/order, all seven
native language-font/metric slots, and exact canonical caches. Marker gaps use
isolated real-native-font SVG probes. Source wordspaces have a bijection to
current native ASCII-space cursors. Leading requires every prefix glyph's
source/native height to agree, independently of gap/wordspace permission.

Actual left/right source rails are independently resegmented from the PDF,
cached by its bytes hash. The native horizontal section geometry is replayed
from those actual rails and the existing writer width contract. This rejects
synchronized source-rail, native-indent, and native-cache changes. Current
native geometry/font metrics also require canonical integer XML lexemes;
decimal/exponent aliases cannot exploit different Python/Rust parsing.

The whole package is staged and checked for editor-open safety before atomic
replacement. Unsupported groups abstain. Duplicate native IDs/character-style children,
source-group IDs, ZIP entries, and noncanonical aliases reject without partial
package writes.

## Production verification

All reports below are under
`tmp/september-exam-matrix/source-choice-geometry-production-native5/`.

| Check | Result | Report |
| --- | --- | --- |
| Actual source/native/style/cache mutations | 432/432 PASS | `guards.json` |
| Six actual positives and column/integer mutations | 84/84 PASS | `column-negative.json` |
| Package ambiguity and actual PDF object/font mutations | 13/13 PASS | `atomic-package-guards.json` |
| Fresh production writer | 8 pages, 45 questions, six automatic groups | `fresh-producer/stats.json`, `hook-report.json` |
| Actual source/world-glyph A/B | All 30 choices improve in X; 26,311 outside glyph tuples exact | `fresh-producer/measurement.json` |
| Public add_run/save/reopen/resave | Six cases PASS; all-app/runtime stable | `fresh-producer/public/report.json` |
| Final storage containment/output replay | No persistent files; 16 actual rails exact; all eight SVGs exact | `column-side-effects-contained/report.json` |

The fresh baseline captures the same producer before this pass, then runs the
same normal TAB/frame refresh. This isolates the choice change while retaining
the current answer-blank and other app fixes. Normal 21-row TAB refresh remains
active. All native nonspace glyph inventory, 45 named question texts, nonspace
styles, margins, and ownership remain exact.

Actual source-qualified groups were Q11, Q13–16, and Q41, discovered without
question selectors. Worst choice X error changes from 18.518 to 3.838 px.
Permitted-leading worst Y changes from 13.333 to 1.163 px. Q14's leading remains
unchanged at 7.013 px because its prefix height is not fully represented;
marker gaps and wordspaces still improve.

Each public edit expands its first choice to 10 or 11 cache rows and advances
the following choice by 154.9–173.1 px. Edited output has nine pages and all 45
named questions. Unedited save and edited reopen/resave preserve every SVG.
All original painted question paragraphs remain covered (24,513 glyphs), with
the pre-existing Q40 private-use placeholder documented. This public check is
not a generic world-coordinate bijection for every question across edited
pagination.

The native runtime is isolated nativecell5, Pyd SHA256
`864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`.

The independent rail extraction originally added nine duplicate PNG uploads
(234,402 bytes) on its first call. It now runs under the existing scoped-upload
context in a fresh temporary directory inside the actual resolved DATA_DIR.
The absolute cleanup target is verified as a direct child before its cleanup
context starts. Final first-call/cached tests add no persistent files or leftover
temporary directories and restore both nested caller and default upload scopes.
First-call extraction takes 6.308 seconds in the isolated proof; the cached call
takes 0.000131 seconds.

All 432/84/13 guards pass on the final contained module. The fresh producer,
source geometry and six public checks were qualified before this storage-only
change (module `00057275…`). Final replay of the contained module preserves
every XML body/media byte and all eight SVG byte strings from that qualified
artifact. Raw ZIP bytes differ only because replaying geometry after the
already-refreshed baseline changes the XML declaration's `utf-8` spelling to
`UTF-8` in sections 0 and 1. No coordinates, styles, caches or media differ.
The original report scopes are preserved in sibling `*-before-scope-correction`
copies; final report metadata explicitly describes six production cases.

## Remaining scope

Speaker-prefix answer lines are classified from actual source geometry and
remain unchanged; this pass does not claim their native paint fidelity.
Q14 leading, wrapped/multicolumn/control choices, mixed/body fonts, summary
rules and labels, and grade1 merged instruction/body restoration remain
separate work. Outside notices/headers and premium forms are outside this
qualification. These results do not establish full-document quality PASS.
