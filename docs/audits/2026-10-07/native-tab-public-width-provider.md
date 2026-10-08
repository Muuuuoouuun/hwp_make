# Actual native TAB widths during public reflow

The optional current-line metric provider is applied in the bundled vendor.
The historical TMP experiments below are retained as evidence for the design;
they describe their own earlier snapshots rather than the current product state.
Nativecell5 is frozen at
Pyd SHA256 `864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`.

The default vendor cache builder deliberately uses conservative character
factors. In actual Q17 the native first option occupies 6,375 HWPUNIT, whereas
the vendor estimate is 8,325.75. With the 814-unit paragraph margin, the latter
passes the first explicit stop (8,030) and selects 15,245. Editing only the
last option therefore changes earlier TAB rails. The renderer's independent
TAB ordinal/fraction fixes do not replace this public-cache metric contract.

## Temporary probes

`tmp/renderer-tabs-20261008/native-tab-width-provider-ab.py` measures actual
per-grapheme SVG origin intervals. Its first last-option test fails: earlier
rails move by +0.52 / +0.107 px. The initial separate-XML-run prefix probe also
fails identically. Both reports are preserved. A sentinel using the same
character-property ID coalesces with the prefix, so its origin measures a
fractional intra-run position rather than the advance used at a run boundary.

The native parser removes consecutive equal character-shape IDs in
`src/parser/hwpx/section.rs` (587–604). `composer.rs` then splits by character
shape (around 716) and language (around 894). Non-TAB run boundary advances
are rounded; explicit LEFT-TAB runs retain their fractional advance in
nativecell5. Current XML run boundaries alone are consequently insufficient.

`tmp/renderer-tabs-fractional-20261008/native-tab-run-prefix-v2-ab.py` uses a
distinct probe-only sentinel style ID and height +1, with an independent empty
prefix subtraction. This forces a true boundary and measures first-option
advances 825 + 5,550 = 6,375 HWPUNIT. Last-option append retains all three
original X rails exactly; a middle-option edit retains the preceding rail and
wraps the next option; a long first-option prefix wraps normally. Sixteen plain
style/control/font negatives abstain without mutation, and all three edited
packages reopen/resave to identical page SVGs. This probe's 36 checks pass.
The equivalent final probe can use a distinct ID with identical properties;
the parser's shape-ID split is the required boundary.

The edited Q17 world Y shifts by −37.76 px in the last/middle examples under
the existing generic question-flow policy. Rail improvement is independent
of source page-origin preservation. Source world Y is not claimed preserved.

These fixed XML-run prefix deltas remain **unqualified for product use**:
same-style XML runs can merge, and a wrapped line starts a new shaping
fragment whose rounding must reset at its own start. Additional actual PDF
every-glyph bounds and split/merge/style/language tests are recorded by
`tmp/renderer-tabs-fractional-20261008/native-tab-provider-fragment-audit.py`.

The actual PDF audit passes every current glyph's advance bounding box on
eight samples: last/middle edits (4 lines), long prefix (9), merged/split
same-style text, a same-style append before TAB, a split bold style and a
Korean/Latin mixed-language append (4). Left/right overflow is zero in each
case. The first tested split/append happen to have equal rounded totals; the
report's equality flag describes those finite samples only.

The targeted font-backed counterexamples are conclusive. Splitting the first
Times run after its first `s` leaves visible text unchanged but moves both
later rails **+1 px**. Appending same-style ` r` before the first TAB moves
them **−1 px**, although the native text still fits before that stop. All
three counterexample packages have valid text and zero glyph-bound overflow.
The per-XML-run provider therefore fails the parser coalescing contract even
when simple wrap/bounds tests pass. Evidence is
`tmp/renderer-tabs-fractional-20261008/native-provider-coalescing-negative/report.json`;
`fixed_xml_run_provider_contract_safe` is false there. This confirms the need
for merged shape/language fragments with line-start resets before any landing.

## Proposed optional contract

An optional provider should measure a complete **current line fragment**,
from its UTF-16 line start to the requested prefix end, using the actual
current header, ordered styles, native language segmentation and LEFT-TAB
mode. It should return a finite native advance and exact covered UTF-16 range,
bound to the current paragraph/header/font data and renderer binary. Equal
style IDs must merge as the native parser does. Rounding resets at every
cached line boundary. Per-character widths fixed at the original paragraph
start are insufficient.

`cache_lines` can use a proved fragment width to choose the next stop and
ordinary word wrap; it must not retain old cached TAB widths or assign stops
by ordinal. Missing or unsupported metrics keep the existing conservative
path. Mixed controls, foreign whitespace, effects, ambiguous IDs or unresolved
range boundaries must abstain before any TAB/cache mutation. A provider
failure midway should rebuild the entire paragraph through the conservative
path atomically rather than mix two width models.

A renderer-backed range API would avoid an SVG page for every possible prefix
and would expose the exact parser/composer/line-fragment contract. Until that
contract and the counterexamples are qualified, the passing small A/B is
diagnostic evidence only.

## Current-line-range TMP proof (nativecell5)

`tmp/renderer-tabs-fractional-20261008/native-tab-line-range-provider-ab.py`
replaces fixed XML-run deltas with fresh line-start/prefix ranges. Consecutive
equal style IDs merge; the renderer performs language splits. A distinct
sentinel ID has identical properties. Probe TABs have known 1-unit widths;
only newly calculated gaps from current stops are substituted. No original
TAB width or PDF source position enters the calculation.

`native-line-range-provider-ab/report.json` passes 50 checks across merged text,
the split-after-first-`s` and append-` r` counterexamples, last/middle edits,
an overlong prefix, bold style splitting and mixed language. Both previous
counterexamples retain all three native rails exactly. Every edited glyph fits
its line; complete text and all page SVGs survive reopen/resave.

`native-line-range-painted-audit3/report.json` passes 25 checks. An independent
direct-ZIP experiment inserts a sentinel at each final cache-line end. Maximum
actual end residual is 0.00006185 px; all original Unicode/origins remain exact.
That first audit wrote XML with `etree.tostring()`'s default ASCII encoding.
Non-ASCII font-face attributes became numeric entities which this native
parser retained as literal face names. The resulting 555–556 font/bbox changes
elsewhere and 66 in the mixed-language target were a diagnostic serialization
defect. The failed reports and `target-font-invariance.json` remain preserved.
The corrected explicit-UTF-8 audit at
`native-line-range-painted-audit-utf8/report.json` passes 25 checks: all eight
variants preserve every original painted glyph's complete Unicode, origin,
ink bbox and font tuple. Its maximum final-line end error is 0.00006185 px.

`native-line-range-guards2/report.json` passes 50 checks for all-language fonts,
duplicate IDs/decorations, effects, unsupported controls/whitespace, stale
text/header/style/paragraph context, nonfinite metrics and runtime failure.
Failed metrics rebuild through the exact conservative implementation atomically.

| Q17 edit | Metric-only seconds | Prefix probes | Total proof seconds |
| --- | ---: | ---: | ---: |
| Last option | 0.391 | 473 | 26.713 |
| Middle option | 0.325 | 350 | 25.813 |
| Long first prefix | 1.881 | 1,779 | 34.008 |

Total proof time includes open/save, PDF bounds and reopen/resave rendering;
it is not public-save latency. Metric-only measurements are recorded in
`native-line-range-cost-profile2/report.json`.

A production provider needs a shared document budget. The TMP budget limits
paragraphs to 512 units, an operation to 1,024 probes / 100,000 serialized
prefix units, and adds a time backstop. `native-line-range-budget-guards2/report.json`
passes nine checks: last/middle retain their successful caches; the long prefix
exhausts the deterministic budget after 401 probes (~0.457 s) and returns the
byte-identical conservative whole section with unchanged header. Limit and
midway-failure cases verify the same atomic fallback. These are prototype
bounds, not released performance guarantees.

At this historical prototype stage the candidate remained TMP-only. The
production backend subsequently applied below constructs a fresh
minimal package from `blank_document_bytes()` plus current header/plain text.
It must not invoke `to_bytes`, `_to_bytes_raw` or `_to_bytes_for_validation`,
which re-enter question refresh. Vendor flow can consume an optional UTF-16
line-range callback while staging the whole paragraph. Absence, unsupported
context and budget failure retain exact conservative behavior. Generic world-Y
flow is separate: last/middle Q17 edits move by −37.76 px; source page-origin
preservation is not claimed.

## Polished standalone candidate and integration boundary

The original qualified snapshots are preserved in
`tmp/renderer-tabs-fractional-20261008/qualified-line-range-d777937c-fad71797/`.
Their backend/adapter hashes are `d777937c…` / `fad71797…`; the historical
85 module and 16 public checks belong only to those exact files.

The separate polished TMP files are `native_current_line_advance_polished.py`
(`429eed9c…`) and `native_current_line_reflow_polished.py` (`77280d03…`).
They contain explicit validation exceptions, UTF-8 XML serialization, flat
ordered multi-text/TAB runs, lazy native import/package construction, and a
four-page native capability check. Known TAB-only advances of 37 and 113
HWPUNIT test fractional LEFT advances, identical-ID coalescing and style-run
TAB slicing without relying on a glyph-width estimate. Unsupported runtimes
use the original conservative cache builder.

The shared budget counts cumulative metric work, excluding unrelated caller
time. Fixed volume limits remain 512 paragraph units, 1,024 probe pages and
100,000 serialized prefix units, with a one-second cumulative time backstop.
A synchronous native parse cannot be forcibly interrupted; a production
header-payload bound remains a documented possible future performance guard,
not an applied limit or a demonstrated blocker for this workload. The actual
fixture header is 852,803 bytes.

`native-current-line-polished-final-proof/report.json` passes 85 current XML,
native range, exact fallback, mutable-input and no-serializer checks. The
adapter validates the current paragraph/header before commit and changes only
original TAB-width attributes and the line cache. Original public run and text
nodes remain attached. It does not replace paragraph attributes or text.

The subsequently applied production boundary adds an optional keyword-only native provider
before the unchanged existing cache body. A separate staged helper returns
success or failure without capturing the public cache function.
None, wrapped paragraphs, unsupported styles, budget failures and unavailable
native metrics call that exact implementation. Only missing-cache paragraphs
containing direct TABs request a lazy current-header context. Contexts share
one refresh budget; measured geometry is never persisted as provenance.
The native helper must not capture a public wrapper that can recurse, or call
any document serializer. This section records the historical standalone
qualification; actual applied integration evidence follows below.

Independent polished qualification is recorded under
`tmp/september-audit/question-only-native5/matrix-d/labeled-header-tabs/`:
`polished-guards-native4-opt1` passes 17 checks with Python `-O`; the actual
native4 result `[0, 0, 150, 150]` fails capability and rebuilds exact
conservative XML. `polished-guards-native5-opt1` passes 20 checks with the
required `[0, 37, 150, 150]` result. `optional-current-line-polished` passes
15 actual Q40 public checks on the original multi-text-run header, including
retained run/text/TAB identities and a subsequent retained-run edit.
`polished-utf8-independent` passes nine mixed Korean/Latin checks: all original
glyph tuples remain exact, ink does not pass the painted sentinel, and the
independent advance error is 0.000465 HWPUNIT.

The same retained-run sequence is checked on Q17 in
`native-current-line-public-retained-run-polished2/report.json` (nine checks).
Both saves preserve the held run and each current text node, the second setter
reaches the document and invalidates its cache, complete text survives reopen,
all glyphs fit, and every SVG page is exact on resave. The longer second edit
moves the question to the next column. The three TAB rails remain exact
relative to that current question origin; the column migration is recorded
separately from local TAB geometry. Earlier failed test oracles compared the
pre-setter text node or absolute coordinates across this normal migration;
their reports remain preserved and are not passing qualifications.

`native-current-line-public-polished-final2/report.json` closes the complete
corrected Q17 public sequence with 24 passing checks and stable files. Last and
middle option metrics take 0.299 s / 473 prefix probes and 0.218 s / 350 probes.
The first process also performs the four capability probes. The long prefix
reaches 401 probes / 80,200 prefix units, then uses whole-paragraph conservative
fallback in 0.544 s. Actual painted bounds, full text and every-page resave SVG
are checked. These timings measure the optional cache call rather than total
document save latency.

## Landed vendor guard proof

The integration is applied to these exact files and SHA256 hashes:

| Actual product file | SHA256 |
| --- | --- |
| `app/_vendor/hwpx/tools/native_line_metrics.py` | `c78452559e6c9a08e2d8c99dfc560efbcd72243f042a09dcd6b7a9e85c60d71d` |
| `app/_vendor/hwpx/tools/native_line_cache.py` | `a64c665cae80dae9717b30b55f7835b8b65b19d7392c6d442eaa042073982f55` |
| `app/_vendor/hwpx/tools/question_reflow.py` | `d32d9eae9e919249d84867f81a3e690a0008bc12dac413a3a0a404d8c621f252` |

The staged helper returns a boolean and imports
no question-flow module or captured conservative callback. The public cache
builder executes its unchanged conservative body when the optional plan does
not succeed. Current-header contexts are lazy; one bounded metric budget is
shared across a refresh. Contexts renew lazily per section because question
spacing can change header styles between sections. Public `save_to_path`,
`save_to_stream` and `to_bytes` use this path automatically after a qualifying
plain LEFT-TAB paragraph cache is invalidated. No application callback
registration is required. The wrapped-table cache call remains conservative.

`native-current-line-production-proof/report.json` and
`native-current-line-production-proof-opt1/report.json` each pass 88 checks
against those actual vendor files, normally and with Python `-O`. They verify
all eight current-range plans, unsupported current contexts, invalid UTF-16
boundaries, exact whole-section fallback for missing/runtime/budget failures,
revalidation after a live header mutation, and zero calls to any document
serializer. Their tests use explicit failures under optimized Python. The
native helpers contain no optimization-removable assertions.

`native-line-production-native4-opt1/report.json` passes six further actual
production checks: native4 gives `[0, 0, 150, 150]`, is rejected by the runtime
capability gate, leaves header/paragraph XML unchanged during preflight, and
uses byte-identical conservative whole-section cache output. This gate is
behavior-based and does not assume an operating system or version string.
These guard reports do not replace the actual production public saves below.

## Applied default and actual public-save proof

`tmp/renderer-tabs-fractional-20261008/integration-production-default-checks/report.json`
passes 12 checks through the installed canonical vendor imports against the
preserved pre-change implementation. All 120 sampled real ordinary, TAB and
control paragraphs produce exact default conservative XML. None, explicit
wrapped context, failed native-plan startup and factory-None fallback preserve
the original behavior, including complete section/header XML. Unchanged,
non-TAB and unsupported RIGHT-TAB paragraphs create no native context.
Qualifying LEFT-TAB paragraphs create one lazy section context; native commits
retain the original run/text objects. All app/vendor Python files remain stable.

`tmp/september-audit/native-tab-production-q17/report.json` records the actual
applied modules above on the fresh F English output. The successful public path
has no positive metric monkeypatch. Last-option edits retain all three rails;
middle edits retain the preceding rail and wrap the later marker normally.
Both remain eight pages, preserve held-run subsequent edits and have zero
actual target PDF glyph overflow across four cache rows. The overlong prefix
uses exact conservative target XML and every-page SVG fallback, with nine pages
and eleven cache rows. Complete edited text survives reopen, and every-page
SVG is exact on resave. Measured total save times are 1.493, 1.395 and 1.546 s;
these are sample timings, not performance guarantees. The input and whole app
snapshot remain unchanged during the proof. Existing question-flow world-Y
changes are recorded separately and are not claimed corrected.

`tmp/september-audit/question-only-native5/matrix-d/labeled-header-tabs/product-current-line-public/report.json`
passes 15 actual applied-vendor Q40 checks on the original multi-text/TAB
paragraph. No standalone backend or adapter overrides the positive public path.
Original run, text and TAB node identities survive save and a held-run repeated
edit; complete literal text and all three TABs survive reopen. Four source
header rails differ by `[0, 0.013333, 0.013333, 0]` px after both edits. Every
page SVG is exact after reopen/resave, and all 23,334 painted glyph world origins
in the other 44 questions remain present unchanged. Relevant input, vendor and
native binary hashes are stable; this report makes no whole-app stability claim.

The same directory's `pagination-control.json` passes three controls. Production
and factory-None conservative paths retain eight pages, 45 unique named questions
and exact complete text for all other 44 questions through both edits. The
conservative header rails drift by `[0, -4.746667, -10.133333, -14.906667]` px;
the applied provider retains the source rails above. An earlier suspected
eight-to-seven page change does not reproduce on this original multi-text input.

This applied change repairs native current-line TAB reflow. At this historical
proof stage, the Q40 source header reconstruction used as its test input was a
separate TMP candidate. A later generic source-item/actual-numbered-band header
pass is applied separately; see [its audit](source-choice-column-headers-20261008.md).
The source underlined-rule geometry is not qualified by these public-save tests.
The one-second budget measures cumulative native work and cannot preempt an
active synchronous native call. Fixed paragraph, probe and prefix-volume limits
and exact conservative fallback remain applied. Full-corpus matrix results are
reported separately; these bounded proofs do not claim complete PDF fidelity.

## TMP underlined closing-TAB investigation

This candidate is separate from the applied provider. No app/vendor file or
runtime was changed for this experiment. The immutable actual input is
`tmp/september-audit/question-only-native5/matrix-d/labeled-rule-tabs/native.hwpx`
(SHA256 `6bbe99b714efb3694a9dd0ccd2b00c3d221b049c3d1134a67759d1e786a6e54a`).
The frozen candidate files under `tmp/renderer-tabs-fractional-20261008` are:

| TMP file | SHA256 |
| --- | --- |
| `native_line_metrics_underline_tmp.py` | `285e61778d499791cdf6aec3fc665f5e0e99eaadd45665bb6d088e95189af265` |
| `native_line_cache_underline_tmp.py` | `99d4e96469b80e1731fb124c490ce1840272e4c99cd5d27cfb75d11ff5dc494c` |

The metric gate additionally accepts only exact BOTTOM/SOLID/black underline,
black text and no shading. Current all-seven-language font references, style,
effects, full ordered text/TAB ownership, UTF-16, capability, budget and stale
input guards remain in force. This eligibility is a current-native metric
contract, not source evidence or permission to reconstruct source rules.

The underline-only experiment with the original 97% wrap margin failed:
`q40-rule-native-range-tmp/report.json` retains the actual `(B)` displacement
of -236.133 px in X and +16.533 px in Y, including unchanged text invalidation.
The current cell's usable width is 20,453 HWPUNIT. The measured closing blank
TAB ends at 20,442, inside that interval but beyond its 97% word-wrap margin.
The ordinary word rollback therefore moved a visible label that already fit.

The second TMP helper permits that final blank advance only when the current
same-ID-coalesced style fragment is exactly TAB + nonspace text + TAB, the
whole fragment belongs to the current line, the following whitespace/TAB has
a distinct style ID, and the native measured final advance fits the current
usable width. It reads no source coordinate, saved TAB width or old cache
width. Other trailing TABs retain the original 97% rule. Unsupported cases
and any failed transaction use the existing conservative cache body.

The following reports are closed against the frozen candidate and native5
binary `864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`:

| Report under `tmp/renderer-tabs-fractional-20261008` | Result |
| --- | --- |
| `q40-rule-native-trailing-tab-guards2/report.json` | 41/41, Python `-O` |
| `underline-native-line-eight-regression/report.json` | 88/88, Python `-O` |
| `q40-rule-native-trailing-tab-final/report.json` | 14/14 actual public save |
| `q40-rule-native-trailing-tab-retained/report.json` | 11/11 retained-run repeated edit |
| `q40-rule-native-trailing-tab-overflow-final2/report.json` | 14/14 actual overwide-label save and paint |

The 41 guards include whole-section/header byte-exact conservative fallback
for None, unsupported underline/effects/fonts/controls, native failure,
budget/time exhaustion and stale header. Mid-plan failure occurs after 96
native prefix probes with no partial writes. First/empty/whitespace/ordinary
TABs, next visible text, same-ID continuation, a fragment crossing a line
start and actual overflow cannot use the exception. Ordinary trailing TAB,
next-visible-text and 45-`M` label cache plans equal the prior native 97%
planner byte for byte. The eight plain-style fixtures retain their qualified
plans and fallback contracts.

Actual unchanged-text invalidation and append preserve both label XY origins
and both native rule endpoints, current Y and 1 pt thickness exactly. A second
edit through the same retained public run remains attached and persists.
Complete literal text and all six TABs reopen; every native SVG page is exact
on resave. Metric call samples are 0.1023 s / 133 probes / 4,602 prefix units
for unchanged invalidation and 0.1040 s / 139 probes / 5,267 prefix units for
append, including initial capability probes. These are sample metric-call
costs, not whole-save latency guarantees.

The actual overwide label wraps to four rows through the public missing-cache
callback. All 113 painted glyph advance boxes fit the current physical cell;
the 4x raster has no black ink outside that cell beyond one raster pixel.
The current physical interval retains the existing 200-HWPUNIT reserve.
The earlier raster failure is preserved: prebuilding a cache before public
refresh skipped wrapper reflow and left following paragraphs overlapping.
Its report is not qualification. A test encoding error and an earlier
detached-namespace fallback oracle are also preserved separately.

Independent `underline-tmp-independent/painted-report.json` and
`width-contract-report.json` under the actual labeled-rule fixture close
20 painted checks and 12 Python-`-O` width/atomic checks. All 23,334 glyphs
in the other 44 questions retain their complete world origin, bbox, font and
size tuples through the three actual edit artifacts. The full painted
inventory, eight pages and 45 named questions remain. Both native rule strokes
fit the current physical cell, with 2.110 pt right clearance. Actual cell height
changes from 4,009 to 4,390 HWPUNIT (+3.81 pt) after invalidation; unchanged
frame geometry is not claimed. Forging the old cache width does not change
the new plan; reducing the current width below the measured endpoint wraps
normally. These independent reports keep `product_qualified=false`.

The source rule Y residual of +2.174 px, label Y residual of +3.346 px, and
current 1 pt rule versus source-scaled 0.339352 pt remain unresolved. The
candidate fixes measured local public width behavior only. This checkpoint
contains 168 C checks and 32 independent checks against the frozen TMP files;
source rule reconstruction and product integration remain unapplied.

`underline-actual-g-eligibility/report.json` is a separate read-only impact
scan of all 51 G case records, excluding source-clone experiments. All eleven
HTTP-200 generated exports exist: 3,747 paragraphs, 132 direct-TAB paragraphs
and 337 TABs. The applied and TMP gates each accept the same 130 paragraphs.
No actual export has a paragraph combining direct TABs with a BOTTOM underline;
the TMP extension adds zero eligible paragraphs and affects zero available
exports. The forty HTTP-422 cases have no retained generated
`structured_native.hwpx`; their individual missing case IDs are recorded and
are unassessed for style eligibility. The scan takes 3.50 s and keeps input and
module hashes stable. It does not establish rendering or candidate quality.

## Applied narrow underline metric extension

After the preceding TMP qualification and independent review, the exact
two-file implementation was applied. Only TMP wording/newline formatting was
adjusted. The applied source hashes are:

| Actual product file | SHA256 |
| --- | --- |
| `app/_vendor/hwpx/tools/native_line_metrics.py` | `e0172040370b3e1de3f9f6de1d0d5d1634ed29af8f57d07cc38c0e6bfc8f9113` |
| `app/_vendor/hwpx/tools/native_line_cache.py` | `0a24d2a8ba44dcc6011518883c5bb1fab9ace87fa560ef26f07ea86c939bc21c` |
| unchanged `app/_vendor/hwpx/tools/question_reflow.py` | `d32d9eae9e919249d84867f81a3e690a0008bc12dac413a3a0a404d8c621f252` |

Exact c784/a64/d32 source backups, the historical G report and its original
code/runtime hashes are retained in
`tmp/renderer-tabs-fractional-20261008/qualified-pre-underline-c784-a64-g-b75e5eea`.
The frozen TMP files and all earlier failures/reports remain separate.

Fresh checks against the canonical actual product modules close 268 checks:

| Report under `tmp/renderer-tabs-fractional-20261008` | Result |
| --- | --- |
| `underline-product-ordinary-guards/report.json` | 88/88 |
| `underline-product-ordinary-guards-opt1/report.json` | 88/88, Python `-O` |
| `q40-rule-product-guards/report.json` | 41/41, Python `-O` |
| `underline-product-default-checks/report.json` | 12/12, including 120 real default paragraphs |
| `q40-rule-product-final/report.json` | 14/14 actual public save |
| `q40-rule-product-retained/report.json` | 11/11 same retained run edited after save |
| `q40-rule-product-overflow/report.json` | 14/14 actual overwide-label save and paint |

The positive public tests call the normal `save_to_path` implementation with
no flow, metric-factory or cache override. Original run/text/TAB identity,
complete edited text and six TABs persist. Both label origins and both native
rule endpoints/current Y/thickness equal the original native fixture; all
eight SVG pages reopen/resave exactly. The 45-`M` edit wraps across four rows,
keeps all 113 glyph advance boxes inside the current physical cell, and has
zero 4x raster ink outside the horizontal cell interval beyond one raster
pixel. No source coordinate or old TAB/cache width supplies these plans.

Sample complete product save times are 1.201 s for unchanged invalidation,
1.036 s for append and 1.186 / 1.171 s for the retained-run sequence. These
samples include ordinary document refresh and are distinct from the TMP
metric-only timings above. The ordinary 97% planner, actual unsupported and
budget/runtime fallback, original plain-style range fixtures and lazy/default
behavior remain verified. Separate actual-product independent reports under
`tmp/september-audit/question-only-native5/matrix-d/labeled-rule-tabs/underline-product-independent`
close 12 Python-`-O` width checks (`width-contract-report.json`) and 20 painted
checks (`painted-report.json`). The positive public path has no override.
All 23,334 glyphs in the other 44 questions keep their complete world origin,
bbox, font and size tuples. Eight pages, 45 owners, complete edited inventory
and both actual native rules remain; the strokes fit the physical cell with
2.110 pt right clearance. Applied module hashes are stable. This closes 300
actual-product checks in total, separately from the prior 200 TMP checks.

The extension does not reconstruct source underlined rules. Its zero newly
eligible paragraphs in the available G exports, remaining source Y/thickness
residuals and cell-height change are still applicable. Historical G remains
the pre-extension full-corpus snapshot; a new full-51 run is not claimed here.
