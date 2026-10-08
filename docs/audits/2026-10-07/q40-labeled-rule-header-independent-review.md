# Q40 labeled intervals and choice-column header: independent TMP review

This is question-content work. No app, vendor, scorer, threshold, renderer or packaging file was changed. The frozen English3 matrix-D artifact and source were used throughout; overlap with B's app work is explicitly **not** a whole-app stability claim.

## Source and independent ownership

- Source: `data/external_exam_qa/2027_kice_september_high3/english.pdf`, SHA256 `745d64d94e0719735b88a10802fbbd5053b4982c855199396e58fe2f53b81cf0`.
- Native input: English3 matrix-D high3 artifact, SHA256 `81ecd882388216e02c2ac559ae3bb73cbfe4d1d7a28ac604d09227ce479359aa`.
- Native5 `_rhwp.pyd`: `864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`.
- The immutable `tmp/september-audit/question-only-native5/matrix-d/high3-owner-world-glyphs.json.gz` and its 45-owner dependency controls bind actual native world glyph origins independently. All 1,180 Q40 source glyphs were rebound to actual source raw glyphs. There is no per-question registration or recentering: source coordinates use the actual page-width scale `595.280029296875 / 842`.

The source has a closed summary frame `[447.84,939.601,753.96,996.301]` pt. Its two solid black opaque `.48pt` answer rules are:

| Label | Source line, pt | Label baseline, pt |
| --- | --- | --- |
| (A) | `(456.359985,974.760986)` to `(517.320007,974.760986)` | `971.403015` |
| (B) | `(684.479980,974.760986)` to `(745.500000,974.760986)` | `971.395996` |

Four following choice-column labels start at source x `483.779999 / 561.610229 / 638.155518 / 705.906799` pt, baseline `1011.300903` pt. The complete following five choices occupy two rails in a 2+2+1 arrangement. The original native artifact retains all literal text, but omits the two labeled rules and centers the four header labels as one compact string.

## Bounded native-clone result

`labeled_header_tabs_ab.py` adds three editable native TABs to the four-label header. `labeled_rule_tabs_ab.py` then adds six editable TAB controls and underlined runs for the two labeled intervals. Neither uses a picture, hides text, changes literal nonspace text, changes font height, nor selects permission by question number or prose literal. The generic source plan scans all 45 owners and finds one structural match. The report's question number identifies that match only.

| Actual fixed-world measurement, 96dpi | Original | TMP rule+header clone |
| --- | ---: | ---: |
| Four-label header max absolute x error | 84.733px | 0.048px |
| Labeled summary-row max absolute x error | 52.636px | 0.782px |
| Whole-question max absolute x error | 84.733px | 34.755px |
| Rule endpoint absolute x error | Rules absent | <0.006px |

All 27,781 glyph labels and pages remain. Exactly 12 header glyphs and 32 summary-row glyphs move; all 26,601 outside-Q40 glyph tuples remain exact, seven other page PNGs remain exact, and page7 pixels outside the common original/candidate Q40 rectangle remain exact. This is a real local improvement, **not product qualification**.

The underline renderer still paints at source y +2.174px and native thickness 1pt, whereas the source width-normalized stroke is `.339352pt`. A/B label baselines retain their preexisting approximately +3.34px error. Native `relSz`/`offset` are not used as a claimed correction. TAB cache offsets require eight control units per TAB; an initial one-unit prototype visibly split the sentence and is preserved under `labeled-rule-tabs/rejected-tab-unit1/` as a rejected control.

## Public API and optional native measurement

The ordinary vendor path gives exact paint after no-edit save/reopen/resave, retains all edited literal text and TABs after actual `add_run`, and gives stable edited paint on reopen/resave. It **fails the source rail contract**:

- Header after `add_run`: x changes `[0,-4.746667,-10.133333,-14.906667]` px.
- Labeled-rule paragraph after `add_run`: B wraps to the next row, x change `-236.133333px`.

These are explicit existing conservative vendor width-cache limitations. Retaining text alone does not qualify the candidate.

C's standalone optional current-line adapter was independently checked against the header clone. The original one-run/four-`hp:t` header correctly abstains and gives exact conservative paragraph XML/paint. Splitting that run at TAB boundaries into equivalent same-style single-`hp:t` runs preserves **every initial SVG page exactly**, then qualifies for native measurements. Actual public `add_run` preserves the header rails within `.0133334px`; literal text and three TABs survive; edited reopen/resave paint is exact. The target uses 21 probes / 210 prefix units and about `.075s`. Nine checks pass. The underlined rule paragraph correctly abstains under the adapter's plain-style scope; that restriction was not relaxed.

This PASS9 applies only to backend SHA `d777937cd11afc1ec044da34856626e2e272574bde994dda0917677ff9175a78` and adapter SHA `fad71797e02f132f5229904bc7ddfeca7cfdc96444731fe327535ba1c6e6e5f6`. Exact source snapshots are saved beside the independent report and in C's `qualified-line-range-d777937c-fad71797/`. It makes no claim about later polished module versions.

## Source guard scope and future fail-closed contract

The tightened TMP source plan (`labeled_interval_strict_plan.py`, SHA `cd6d0f67f2ae03f7d45687b4709d7cec5a38fddefe342ce938f339df31c264f7`) adds current actual raw-glyph rebinding, horizontal regular Times raw/visible-trace checks, raster continuity of both rules and all four frame edges, and ink checks for label glyphs. Thirteen actual-input controls pass: one unique structural candidate over all45, native terminal omission, extra header label, duplicate summary cell, forged source bbox, source terminal-row omission, full/partial rule white covers, label cover, frame-bottom/left covers, nearly opaque cover, and input immutability. Label raster checks reject wholly hidden glyphs; they do not prove complete unobscured per-pixel glyph shapes.

A future product change needs all of these conditions before staging any XML:

1. Independently prove the complete current source question and unique current named native owner; match the whole summary cell, both labels, one actually painted enclosing frame, all four following header labels, and all five following choices. Missing/truncated/duplicate/ambiguous or mixed-column structures abstain.
2. Bind current source page dimensions and source geometry to native page/cell world coordinates. A checksum is useful evidence but does not replace raw/trace/paint/style proof. Never align each crop independently to conceal displacement.
3. Validate every current native run and all seven fontRef/height/ratio/tracking/relative-size/offset and supported effect fields. Measure current shaped label/prose advances against a current header/runtime snapshot; do not reuse old word/TAB widths. TAB widths must be positive, bounded, monotonic and complete; source text remains editable with exact control-unit cache accounting.
4. Stage the whole native mutation and commit only after a complete native proof. Unsupported fonts, embedded-resource ambiguity, malformed controls, changed text/style/header/runtime, exhausted metric budget, unknown paint effects or incomplete following boundaries preserve the exact ordinary path.
5. Qualify public edit/save/reopen/resave, full edited question content, source rails and bounds, and all outside-owner scope. The current rule candidate fails this requirement and also has underline baseline/thickness residuals. Further renderer/native underline capability and explicit current-line support would be needed before claiming source fidelity.

No external/user help is needed for the local producer/vendor investigation. A real Mac host is needed only for separate macOS runtime qualification.

## Saved evidence

All paths below are under `tmp/september-audit/question-only-native5/matrix-d/`:

- `q40-source-native-structure.json`, `q40-native-question.xml`, `q40-fixed-world.png`.
- `labeled-header-tabs/{report.json,independent-geometry.json,public-report.json,native.hwpx,native.pdf}`.
- `labeled-header-tabs/optional-current-line/report.json` and exact tested backend/adapter copies.
- `labeled-rule-tabs/{report.json,independent-geometry.json,public-rule-report.json,source-guard-report.json,native.hwpx,native.pdf,q40-fixed-world.png}`.

The 45-owner proof and Q32 qualified/production proofs were not modified.

## Later actual product current-line provider qualification

The earlier standalone PASS9 is preserved above and is not applied to another version. The later polished TMP backend `429eed9c7b34e616985e9dc32879622f7d5c7fe2b1a7fb8642bfc57396a9c71f` and adapter `77280d0344294bb8748dcd3dc785c3f50094b06d3976a318401845ee89937e65` were independently qualified with original multi-`hp:t` support, current UTF8 font names, and original run/t/TAB identity preservation. Separate reports record 15 original-header/public checks, 20 native5 checks under Python `-O`, 17 actual native4 rejection/fallback checks under `-O`, and nine mixed Korean/Latin font/ink checks. These reports remain in `labeled-header-tabs/{optional-current-line-polished,polished-guards-native5-opt1,polished-guards-native4-opt1,polished-utf8-independent}/`.

After B landed the production modules, `q40_current_line_product_public.py` used ordinary `HwpxDocument.open`, public `add_run`, `run.text`, and `save_to_path`. It installed no standalone provider, cache wrapper, callback or positive-path monkeypatch. The loaded real vendor SHA256 values were:

- `hwpx/tools/native_line_metrics.py`: `c78452559e6c9a08e2d8c99dfc560efbcd72243f042a09dcd6b7a9e85c60d71d`.
- `hwpx/tools/native_line_cache.py`: `a64c665cae80dae9717b30b55f7835b8b65b19d7392c6d442eaa042073982f55`.
- `hwpx/tools/question_reflow.py`: `d32d9eae9e919249d84867f81a3e690a0008bc12dac413a3a0a404d8c621f252`.

All 15 actual production checks pass. The original one-run/four-text-node/three-TAB header retains all existing run, text and TAB nodes. A held public run handle still edits the live paragraph after its first save; both edits persist after reopen. The four existing header rails move only `[0,0.0133333,0.0133333,0]` px after either edit, and each edited reopen/resave retains every SVG page exactly. All 23,334 glyph world origins of the other 44 question owners remain present at their original page coordinates. Input, native5 binary and relevant actual vendor files have identical before/after hashes. The report is `labeled-header-tabs/product-current-line-public/report.json`.

`q40_product_pagination_control.py` separately disables only the optional provider in a negative-control process, causing the original conservative path. The input, real production no-edit/first-edit/repeated-edit outputs, and conservative no-edit/first-edit/repeated-edit controls all retain eight pages and 45 unique named question owners, with Q40's header still on page7 and complete other44 text unchanged. The conservative edit reproduces header rail drift `[0,-4.746667,-10.133333,-14.906667]` px. An eight-to-seven page change is not reproduced for this exact original multi-text-node input. This negative control does not modify the real product test or any app/vendor file. Its separate report is `labeled-header-tabs/product-current-line-public/pagination-control.json`.

This qualifies the new product cache provider on this existing TMP header clone; it does not land the source-header reconstruction. The source rule reconstruction remains **검증 미완료/제품 미적용**. Its BOTTOM underline is still outside the production provider's supported scope, and its source y/thickness residuals above remain open. A new C-owned TMP underline diagnostic will have separate source snapshots and reports; no result is inherited in advance.

## Source-Y cache counterexamples

Two separate TMP clones re-prove the actual source question/frame/labels/prose and every current row style, then change only one first-row cache field. Current font height stays861HWP, all seven native font references stay Times New Roman, and the only existing style difference is NONE versus BOTTOM SOLID black underline. The original rule/header clones and immutable45-owner proof remain unchanged.

- `rule-baseline-source-ab/`: requested `baseline732→562` to match the actual source prose baseline. The native row moves only `−0.576px`, because `ensure_min_baseline` in `paragraph_layout.rs39–44` clamps to `.8*861=688.8HWP`. The rule y residual improves only `2.173568→1.597558px`; label max y residual improves `3.345557→2.769548px`. This is a retained clamp counterexample, not the proposed exact source-Y result.
- `rule-vertpos-source-ab/`: requested first `vertpos1198→1028`. The actual labeled row and rules move `0px` in the ordinary cell-paragraph flow; rule y residual remains `2.173568px`. It provides no claimed initial Y improvement.

Both independent geometry reports retain exact outside-Q40 glyph tuples, seven unchanged page PNGs, and no changed pixels outside the common Q40 rectangle. SOLID underline thickness remains1pt in both. The reports are each under `labeled-rule-tabs/rule-{baseline,vertpos}-source-ab/labeled-rule-tabs/{report.json,independent-geometry.json,native.hwpx,native.pdf}`; `baseline-report.json` records the actual requested-versus-observed displacement.

Actual production public invalidation/save/reopen controls pass six diagnostic checks for each clone. `baseline562` resets to732; `vertpos1028` resets to1198. Complete edited text, all six TABs and all45 unique question owners survive. The production underline provider remains unsupported without any override. The large actual label world-y movement during this edit also includes ordinary table/question flow after wrapping and is not attributed to the cache-field reset alone. Each clone has a separate `public-reset-report.json` with the pre/post cache and that caveat.

Neither a font-height change nor a renderer/app/vendor change was used to evade these limits. These results do not qualify a lasting source-Y fix. Header-only qualification above is independent of these unresolved labeled-rule results.

## Editable line primitive negative

`labeled_rule_hp_line_probe.py` re-proves the complete actual source group, explicitly removes the two TMP underline decorations, and adds two editable native `hp:line` objects in the same actual summary-cell paragraph. Each line uses the existing vendor model builder, a PARA/COLUMN text-relative floating anchor calculated from actual source/native world coordinates, and quantized34HWP (`.34pt`) black SOLID strokes. No picture or hidden text is involved. Both controls are after the visible text, so no existing preceding cached text start is shifted.

The clone retains every original glyph's page/origin/bbox/font/size tuple exactly and remains eight pages/45 question owners. Both `hp:line` elements survive actual public edit/save/reopen, and complete edited text, sixTABs and expected global painted glyph inventory survive. The two rules are nevertheless absent from actual initial and edited native PDF paint. The report is `labeled-rule-tabs/hp-line-native-clone/report.json`.

The parser supports the line model and adds an eight-unit native control marker for each line (`parser/hwpx/section.rs400+`). The actual table-cell shape-paint branch handles `Control::Shape` only when `treat_as_char` is true (`renderer/layout/table_cell_content.rs756+`). Separately, vendor `question_reflow.OBJECTS` excludes `line`, so its cache builder does not account for those two native eight-unit controls. The current optional provider correctly rejects the line-bearing paragraph. No renderer/vendor changes or alternate anchors were used to force this failed capacity probe through.

## Frozen TMP closing-underline-TAB independent review

C's later TMP backend SHA `285e61778d499791cdf6aec3fc665f5e0e99eaadd45665bb6d088e95189af265` and staged cache helper SHA `99d4e96469b80e1731fb124c490ce1840272e4c99cd5d27cfb75d11ff5dc494c` are separate from the product provider. Only exact current BOTTOM/SOLID/black/no-shade style is added to the existing seven-font/metric/effect proof. The97% wrapping exception requires one complete same-native-style-ID TAB/nonspace-label/TAB fragment on the current line, followed by distinct-style whitespace/TAB, with its actual measured advance within the current usable interval. No source or old cache width grants permission.

Independent actual paint verification passes20 checks over unchanged-text invalidation, append, and a held-run second edit. It freshly renders the final99d artifacts, rebinds all23,334 other44 owner glyphs to complete origin/bbox/font/size tuples, and proves those tuples unchanged. Complete original painted inventory plus the actual edited suffix remains, with eight pages/45 owners. Both rule endpoints, current y and1pt thickness are exact relative to the original TMP rule clone; actual4x raster ink is continuous along both rules. The full strokes fit inside the independently measured current physical cell content rectangle, with2.110pt right clearance.

The physical cell height changes from4009 to4390HWP (`+3.81pt`) on invalidation/rebuild, including the unchanged-text invalidation case. Its current four painted edges are bound to current XML dimensions; the frame is not claimed unchanged. Other44 glyph tuples remain unchanged. The source rule y residual remains `+2.173568px`, and1pt remains different from source-scaled `.339352pt`.

Twelve independent width/boundary/atomicity checks also pass under Python `-O`: the actual end advance is20442HWP against current usable20453; `.001HWP` overflow does not get the exception; caller width20441 wraps B normally (second cache start88→76); old20653 or forged9999 cache widths do not select the plan; next nonspace or same native style ID keeps the original97% planner result; supplied style/paragraph clone mismatches and default `None` leave the paragraph/header untouched. These reports are `labeled-rule-tabs/underline-tmp-independent/{painted-report.json,width-contract-report.json}`.

This closes the bounded TMP width/current-ink review only. It makes no source-Y/thickness fix claim and does not apply the underline or source-rule candidate to the product.

## Actual product underline cache integration check

After the focused cache capability landed, a separate independent run loaded the actual vendor modules: metrics SHA `e0172040370b3e1de3f9f6de1d0d5d1634ed29af8f57d07cc38c0e6bfc8f9113`, cache SHA `0a24d2a8ba44dcc6011518883c5bb1fab9ace87fa560ef26f07ea86c939bc21c`, and unchanged reflow SHA `d32d9eae9e919249d84867f81a3e690a0008bc12dac413a3a0a404d8c621f252`. The original TMP285/99 proofs remain separate and unchanged.

`verify_underline_product_painted_ownership.py` freshly renders C's actual ordinary public-path unchanged-text invalidation, append and held-run second-edit artifacts. It installs no positive provider/cache callback. All20 independent paint/ownership checks pass: complete edited inventory, eight pages/45 owners, all23,334 other44 full world/font/bbox tuples exact, both continuous actual rule strokes inside the current physical cell, and stable source/input/runtime/vendor hashes. The right stroke clearance is2.110002pt. The same current cell-height increase of3.810059pt and source rule y residual of2.173568px remain; current1pt thickness still differs from the source-scaled `.339352pt`.

`verify_underline_product_width_contract.py` loads the actual product backend/cache directly and passes12 checks under Python `-O`. It uses the preserved a64 snapshot only as the ordinary97% planner control for negative boundary cases. Current caller width, old-cache independence, `.001HWP` overflow rejection, exact-edge permission, next-text/style boundary behavior and default/style/paragraph atomic fallback all retain the independently verified results above. No actual product module is monkeypatched or edited.

Separate reports are `labeled-rule-tabs/underline-product-independent/{painted-report.json,width-contract-report.json,independent-artifacts.json}`. These qualify the focused current-line cache capability on the existing source-proved TMP rule clone. They do not apply the source-rule/header reconstruction to the product or claim a source-Y/thickness fix.
