# Actual source grid page origins and complete source-frame rows

The final4 source-grid suite establishes native cell bounds, strict source
font proof and public edit/revert behavior. Its local cell checks do not
establish actual source page-baseline alignment. A separate every-glyph oracle
on the actual high3 English PDF page4 found that Q27/Q28 native grids were
lower than their source positions.

## Independent source/native measurement

`tmp/september-audit/grid-quality-ab.py` reads the actual source PDF raw text,
glyph traces and dark vector rules. It recovers the physical grid rails from
the source vector lines, rather than treating the table detector bbox as the
painted frame. Native grid rails are independently read from actual native
SVG black0.4 lines, and native glyph origins/bboxes from the rendered PDF.
Every nonspace source/native character matches by complete cell and printed
row. The scale is the actual native page width59528 / source page width842 /
75 HWP units per native pixel.

The oracle covers all226 grid glyphs and all1428 Q27/Q28 glyphs. Its glyph
bboxes are native PDF glyph advance/em bounds, not outline-ink measurements.

| Variant | Q27 grid mean Y residual | Q28 grid mean Y residual | Q27 full-question Y MAE | Q28 full-question Y MAE |
|---|---:|---:|---:|---:|
| Original final4 | +6.45435px | +9.99199px | 3.64246px | 11.46979px |
| Full-producer crop-only A/B | +5.33435px | +8.87200px | 2.28177px | 10.35560px |
| Tmp crop plus source-object reserve removal | +0.00101px | −0.007998px | 0.68242px | 0.59501px |

The original local cell-baseline error is below.0064px. The large error is
therefore the page/table origin inherited from preceding flow. Crop-only
leaves every grid X coordinate unchanged and improves Q27 full-question X
MAE from6.22931px to5.47989px; Q28 X is unchanged. Across all26353 glyphs
outside Q27/Q28, every native painted origin remains identical. The tmp
transition variant changes32 pixels outside question content at native
column-separator antialias overlap endpoints; it does not establish zero
outside-question pixel change. All variants retain eight pages and exact text.

Reports and complete per-glyph residuals are under
`tmp/september-audit/grid-y-producer-ab/` (`measure-report.json`,
`baseline-glyphs.json`, `crop-glyphs.json`, `transition-glyphs.json`).

## Crop-only correction

Q27's complete prefix decoration crop is
`[447.8399963,198.9610138,753.9599610,426.8110046]` source points, height16109
native units. The previous guard used the dominant Times height861 and
baseline732 for the first Arial Black title and final smaller bold label.
Its required height16113.04 exceeded the actual crop by4.04 units, so the
source frame restore abstained and a legacy text fragment used an ink-top
anchor with a shorter15622-unit frame.

The actual source/native first title height is803/baseline683; the final
`Prizes` label is823/baseline700. Preserving source baselines gives top793 and
terminal occupied requirement16107, including the unchanged200-unit native
cell reserve. The complete native flow fits height16109 after all rounded
inter-paragraph gaps. This is an actual occupied-descender proof, not a larger
fit tolerance.

`app/pdf_source_frame_native_rows.py` applies the correction only to a complete
plain one-cell decoration fragment from a source frame containing a grid.
It independently reopens every actual raw row/span/character, checks complete
native source-derived family/height/bold/italic/ratio/tracking coverage,
rederives canonical source typography, verifies the original decoration pixels,
and validates existing cache metrics and UTF16 boundaries before normalization.
It rejects unsupported font modes/effects, styled empty runs, missing controls
and compensated mutable metadata. The source grid's existing strict font proof
is unchanged.

The public `restore_background_frame` entrypoint stages the fragment and an
isolated header. Its paragraph-style callback allocates only in that header;
the original font/style callbacks are not invoked. It validates all source row
tops, leading, inter-paragraph gaps and occupied height before reconstruction,
then re-proves the resulting caches. Only successful reconstruction commits
the fragment and newly appended paragraph styles. Strict-path failure cannot
fall through to the older source-frame exception.

The app keeps the ordinary200-unit cell and400-unit object reserves. No
question selector, renderer change or quarter-space translation is included.
App freeze at2026-10-08 14:10:32 KST:

| File | SHA256 |
|---|---|
| `app/pdf_source_frame_native_rows.py` | `fe9184225cf324517254b5b953920856d8dc5bfeae86d3272ca6fb6816f509c0` |
| `app/pdf_table_paragraphs.py` | `da46b0ff48c3e0f2dc0d3b3fb8d6e815155f411ed9f0f6743e61b85398ca4dc1` |

The three actual frame positives preserve the exact source crop heights after
the native row fitter. There are46 guard checks:36 source/native/cache/style
mutants, one UTF16 surrogate-boundary unit check, two forced staged failures
and seven malformed header/style cases. Actual entrypoint rejections leave
both original root and header byte-identical. Replay:

```powershell
$env:PYTHONUTF8='1'
python scripts/verify_source_frame_native_rows.py
```

This replay uses the saved actual writer capture, corresponding native package
and original decoration assets; the paths can be supplied explicitly. It
does not start another writer. The report is
`tmp/september-audit/grid-y-producer-ab/entrypoint-negatives.json`.

Crop-only full-producer A/B passes all six strict public grid stages, including
both complete original page4 PNG restorations, media byte identity, reopened
table XML equality, native glyph bounds and expected8/9-page growth. It also
passes the existing17 source-consumer and26 vendor negatives. The report is
`tmp/september-audit/grid-y-producer-ab/crop-public/report.json`.

## Changes deliberately retained as diagnostics

Removing the generic400-unit object reserve from the complete source-proved
table transitions solves actual grid Y in the tmp full producer. It fails
the current portable edit contract: ordinary saves reintroduce that reserve
through `question_reflow.flow_height` and `ruled_grid_flow.apply`, and both
original-page restoration checks fail. All six stages and their explicit
restoration failures are recorded in
`tmp/september-audit/grid-y-producer-ab/transition-diagnostic-public/report.json`.
Producer-only reserve removal is absent from the app.

The separate28-space quarter-em experiment also remains absent from the app.
Actual page4 Times GID3 has PDF CID width250 and embedded TTF advance512/2048.
Native ratio80/tracking−15 improves Q27/Q28 grid X MAE from1.851/1.889px to
.275/.369px, but the public setter collapses the split runs and strict flow
signatures correctly abstain. That translation needs an independently proved
portable source-space editing contract. Neither diagnostic is a target98 or
whole-document visual-quality pass.

## Authoritative matrix-c artifact check

The completed frozen matrix-c writer produced
`basic-english-native3-20261008-c/cases/2027_kice_september_high3__eng_1_32a2ddb4/structured/engine/exports/pdf_layout/20261008_141402_english/english_structured_native.hwpx`,
SHA256 `8f391436b0c96ec92ce1ef596f5dd10de9c900a5813722d80d92cfb6e653a69e`.
The independent oracle matched all 1,428 painted Q27/Q28 glyphs, including
all 226 grid glyphs. Grid world-Y means are +5.334354 px and +8.871998 px;
cell-local absolute Y maxima are only 0.006370 px and 0.004972 px. This
confirms the crop correction's 1.12 px improvement and the remaining
page-flow reserve defect. Full-question Y MAE is 2.281767 px / 10.355595 px.
The strict target is still unmet.

All six public edit stages pass on this exact artifact, with 17 source
consumer and 26 vendor negative cases. Small / large / restored / empty /
empty-restored / space-boundary outputs have 8 / 9 / 8 / 8 / 8 / 9 pages.
Both restoration stages reproduce the complete original page 4 PNG exactly;
media bytes, reopened table XML and painted cell bounds are verified.

Reports are `tmp/september-audit/grid-y-final-c/measure-report.json` and
`tmp/september-audit/grid-y-final-c/public/report.json`. Individual glyphs are
in `final-c-glyphs.json`. The older pre-integration comparison also reports
2,409 changed outside-question tuples; that baseline predates the separate
body integrations, so this is not an isolated crop invariance claim. The
earlier isolated producer crop A/B supplies the exact outside-glyph proof.

These results use nativecell3. A subsequent renderer correction requires
fresh native measurement and public-edit validation; this archive does not
claim that result in advance.

The later isolated nativecell4 fresh producer was also measured independently:
all 1,428 Q27/Q28 glyphs and 226 grid glyphs match, with the same grid world-Y
means +5.334354 / +8.871998 px and cell-local absolute maxima
0.006370 / 0.004972 px. All six public stages, 17 consumer negatives and 26
vendor negatives pass with stable app fingerprints. Reports are
`tmp/september-exam-matrix/mixed-terminal-nativecell4/grid-measure-summary.json`
and `grid-public/report.json`. This is nativecell4 evidence; nativecell5 has
its own subsequent qualification.

Nativecell5 fresh writer and public qualification is complete under Pyd SHA256
`864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`.
The complete 1,428 / 226 glyph oracle again reports the same world-Y and
cell-local residuals; this confirms the remaining reserve defect is still
present. All six edit stages and 17 / 26 source-consumer/vendor negatives pass,
with 8 / 9 / 8 / 8 / 8 / 9 pages and original table heights restored after both
revert operations. The checker verifies complete original page-4 PNG equality
for both reverts, media preservation, reopened table XML and painted cell
bounds. Frozen app fingerprints and exact isolated loaded-runtime proof are
recorded in `tmp/september-exam-matrix/mixed-terminal-nativecell5`:
`grid-glyph-oracle/report.json`, `grid-public/report.json`, and
`grid-public-worker.json`.
