# Multi-column choice tab runtime review

This review concerns editable question choices. Mastheads and outside-question notices are excluded.

The authoritative input is the frozen matrix-c grade3 native package recorded in
`tmp/september-audit/frozen-c-page-review/choice-tabs-ab/report.json`. The package
SHA256 is `8f391436b0c96ec92ce1ef596f5dd10de9c900a5813722d80d92cfb6e653a69e`.

## Actual defect

Q17 marker origins in the original nativecell3 render are approximately
93.707, 189.920, 245.920px. The actual source's third rail is 285.96px, so the
third marker is 40.04px left. Full-page SVG and PDF agree. Q19's second/fourth
marker rails already agree with the source; its larger option-text residual is
a separate typography problem.

On a native package clone, adding750HWP to Q17's first inline tab moves the
three markers by `[0,10,20]`px. Adding750HWP to the second tab moves them by
`[0,0,0]`px. The second tab width is ignored. Repeated actual SVG refresh
updates21 measured rows with5 changed rows on every invocation; Q17's second
cached width grows6649→9664→12679 without moving its third marker. Reports and
native mutants are under `tmp/september-audit/frozen-c-page-review/`.

## Renderer change and source tests

The paragraph model documents inline tab records as corresponding one-to-one
to the paragraph's tab characters. Composition splits text by character style
and language. Native text measurement restarts its local tab index at zero for
each shaped run, while layout formerly supplied every run the entire paragraph
tab array. This caused later runs to reuse the first record.

The owned change is only
`tmp/rhwp_renderer_square_build/rhwp-core-patched/src/renderer/layout/paragraph_layout.rs`.
It supplies the appropriate remaining records to each run and TAC text segment
for both estimation and rendering, preserves paragraph order across lines and
partial-line layout, and uses the same run records for tab leader selection.
No app choice producer or SVG refresh workaround was changed.

Upstream HEAD is `ce45231c0c88efd5397d8fae9cd7d73de915095d`. Before editing,
all9 existing patched source files matched the canonical clean nativecell3
patch replay after CRLF normalization. Raw snapshots and hashes are retained in
`choice-tab-runtime-contract/baseline-source-proof.json`. The damaged build
tree Git object database was not reset. The missing compile-time
`samples/hwpx/ref/ref_empty.hwpx` fixture was restored verbatim from healthy
same-HEAD `git show`; no unrelated source was modified.

Final owned source SHA256:
`b4bb9b52d5876321c8b86737f2c154991497e3afed377abecca5151358c8c4f9`.

Five generic layout regressions cover actual composition across styles and
languages, tab-specific width sensitivity, paragraph-global order when starting
at a later line, right-alignment estimate/render agreement, leader order, and
TAC segmentation between distinct tabs. The first4 tests all fail on the old
functional source and pass on the candidate. The added TAC test first reproduced
20px excess at the right edge, then passed after the estimation correction.

Final focused Linux filters pass18 tests: inline_tab11, task2905, extra-spacing1,
mock-tab1. This includes the5 new layout tests and existing left/right/center/
decimal/fallback behavior. An overly broad substring `tab` also selected table
and editable-control tests:200 passed,3 ignored,5 failed because unrelated
BookReview/kps-ai/other fixture files were absent. That run is retained and is
not reported as a pass. These Linux tests do not establish Windows or macOS
runtime behavior.

## Public and packaged-runtime verification status

The nativecell3 diagnostic publicly appends choice text, saves, reopens and
resaves. Complete edited text and distinct save-regenerated tab widths survive;
resaved page SVG is exact. This preliminary result does not establish correct
source rails after a public edit.

The candidate-only verifier is
`tmp/september-audit/frozen-c-page-review/choice_tabs_candidate_validation.py`.
It requires an explicit isolated nativecell4 site and has not been run before
candidate installation. Its checks include width responses `[0,10,10]` and
`[0,0,10]`, refresh idempotence, actual-source Q17 rails, all8-page SVG/PDF marker
agreement, exact glyph tuples outside all21 complete tab rows, and public
add/save/reopen/resave. Root owns patch packaging, build and installation.

## Isolated nativecell4 actual evidence

The installed candidate's native library SHA256 is
`84f935f6eb3c98bdd9886d2f9f69ae7c820bde1bfba48495f9162e79d7d0ebb1`.
The global nativecell3 installation was retained during qualification.

Actual Q17 +750HWP mutants now give the correct `[0,10,10]` and `[0,0,10]`px
responses. Q06's4 independent tab mutants also give exactly10px movement of
only all markers following the selected tab. After one source-preserving SVG
refresh, Q17 marker origins are93.707,189.920,286.120px; their source x errors
are.160,.166,.159px. The approximately2.97px pre-existing Q17 vertical offset
is unchanged.

All285 circled markers on all8 pages agree between candidate SVG and PDF by
label-and-origin bijection, maximum discrepancy.000092px. The first verifier's
P4 comparison zipped two differently sorted lists, falsely reporting an origin
mismatch; this harness error and its original report are preserved, and the
independent bijection result is `independent-actual/svg-pdf-bijection.json`.
The27,781 native visible glyph/page/Unicode inventory is unchanged, and every
one of27,275 glyph tuples outside the21 complete tab rows is exact. This proves
the renderer change's bounded actual effect.

Two remaining contracts are explicitly failing. SVG refresh still changes3
rows on its second call: Q06/Q42/Q44 have corrections up to30HWP (.4px), then
last-tab propagation before convergence on the fourth call. This is larger
than integer rounding jitter; no iteration/deadband producer workaround was
added in this review. Parent owns the isolated-probe investigation.

Public Q17 terminal append/save/reopen/resave preserves edited text, explicit
tab stops and exact resaved page paint, but breaks the original rails. The
vendor `question_reflow.cache_lines` uses conservative character advances:
first-option8325.75HWP versus native6375HWP. Adding left margin814 gives9139.75,
past first tab stop8030, so the fallback selects15245 and overwrites tab841 with
6105. Marker② shifts70.187px and marker③ wraps. The next overwritten gap1947
uses default stop21600 after the explicit stops are exhausted. The generic
cache/shaper metric contract is a separate question-content bottleneck. No
vendor/app change was made here.

Reports are under `tmp/renderer-tabs-20261008/independent-actual/`,
`q06-native-tab-sensitivity/`, and `refresh-svg-diagnostic.json`. Current
application quality and real macOS runtime remain separate checks.

## Fractional inline LEFT advance follow-up

The remaining refresh drift is independently reproduced by small width
mutations. On nativecell4, Q06 tab3 −30HWP moves marker④ −.4px but marker⑤
−1px. A +750HWP change moves both exactly10px, so the integer sensitivity
alone misses this defect. `EmbeddedTextMeasurer::estimate_text_width` rounded
each shaped run's total to a whole pixel, while `compute_char_positions`
retained fractional advances. The isolated probe and full-page marker-gap
vectors agree; this is a run-advance contract issue rather than probe geometry.

The additional source candidate changes only native `text_measurement.rs`:
when a run contains at least one TAB and every consumed TAB has a corresponding
inline record whose type high byte is1 (LEFT), return its fractional total.
Other tab types, legacy raw type values, missing/partial records and runs
without tabs retain the old rounded total. Unused suffix records belong to
later runs and do not change the current run's eligibility. The prior
`paragraph_layout.rs` change stays byte-identical.

Four new regressions fail before this change; the unsupported-rounding
matrix already passes. Final focused Linux checks pass47 tests: the complete
text-measurement unit module30, inline-tab11, task2905, and extra-spacing1.
Six new tests cover fractional rendered end agreement, complete record
coverage, small negative width propagation, unsupported rounding, explicit
LEFT behavior under auto-right, and font/style/spacing/leader combinations.
These are source tests; the separate actual Windows qualification is below.

The frozen text-measurement raw/LF SHA256 is
`feb2417e31c688abc94f4d69ee220c72c209c463b41488589ec9b9c7e284cc10`.
All8 other pre-existing patched nativecell3 source files are unchanged;
the prior paragraph patch remains `b4bb9b52…`. Exact source delta and test
evidence are under `choice-tab-runtime-contract/nativecell5/`.

The independent nativecell5 validator is
`tmp/september-audit/frozen-c-page-review/choice_tabs_fractional_candidate_validation.py`.
It adds Q06 +45HWP and −30HWP actual sensitivities, retains label/origin
SVG/PDF bijections and exact outside-row scope, and records the already
known vendor public-edit rail failure as a separate existing limitation.
A passing native-runtime result does not imply that the full public choice
contract passes.

The isolated nativecell5 native-library SHA256 is
`864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`.
The Windows actual verifier passes all scoped runtime checks. Refresh measures
21 rows and changes5 once; its second call changes0. Every Q06 tab +45HWP
moves only following markers by exactly.6px, and tab3 −30HWP moves both later
markers exactly−.4px. Integer Q06/Q17 sensitivity also passes. Q17 source-rail
x errors remain.160/.166/.159px. All285 circled markers agree between actual
SVG and PDF within.000092px, all8 pages and27,781 visible glyph inventory
remain, and every27,275 glyph tuple outside the21 complete tab rows is exact.
Relevant runtime/vendor/input/source/choice-app snapshots remain stable.

Public add/save/reopen/resave retains the complete edit, explicit stops and
exact resaved page paint. The separate vendor cache limitation still reproduces:
regenerated Q17 gaps6105/1947 move marker② +70.187px and wrap marker③. The
report therefore records `ok=true` for its explicitly scoped runtime checks
and `full_public_choice_contract_ok=false`. Evidence:
`tmp/renderer-tabs-fractional-20261008/independent-actual/report.json`.
