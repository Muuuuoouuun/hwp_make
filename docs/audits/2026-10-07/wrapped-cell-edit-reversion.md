# Wrapped-cell edit reversion: independent review — 2026-10-07

This review changed tests, documentation and validation metadata only. Final7 passes the root-owned complete public append/delete/save/reopen gate; the report and verifier scope were independently audited below. The final6 bookkeeping/cache tests remain separate evidence. Layout target 98 and complete visible PDF glyph painting are not established by these passes.

## Final7 actual source and public edit result

Report: `tmp/september-exam-matrix/q27-final7-independent/report.json`, SHA256 `28972c44b98447538a950edd29f45e6bdb419c6470cd445ed28b13d444278487`. Input: `tmp/september-exam-matrix/q27-product-final7/high2-native.hwpx`, SHA256 `1779adad6b50702e02c6d2c79ed6a963b98dbe43d33f1f379333a516d1d7b5e3`.

The full stored before/after snapshots match and `changed_code_files` is empty. The independent audit also checked current code against the stored snapshot, source/input SHA, and installed `_rhwp.pyd` against the nativecell3 manifest SHA. Audit evidence: `tmp/renderer-square/final-artifacts/final7-report-scope-audit.json`. The verifier snapshot aggregate `2e4f3c951dbe4c40f63a0dc3765182f659b2dddcfa9b7382b6600d11040d0cd2` includes app files and the two source verifiers; it is distinct from the English3 API product snapshot hash below.

| State | Pages | Q27 native height (HWPUNIT) | Q28 page index / x / baseline px |
|---|---:|---:|---|
| Initial | 8 | 33186 | 3 / 405.333333 / 612.24 |
| Public intro append | 9 | 42644 | 4 / 82.906667 / 189.306667 |
| Public appended run deletion | 8 | 33186 | 3 / 405.333333 / 612.24 |

Deletion restores exact native text/height, initial page count, Q28 position/distance and picture page/bounds. Fresh reopened saves retain section XML and SVG text/image coordinates. The initial source comparison also passes 18 source rows, all four source rules and actual source picture pixels/bounds. Picture edge errors are at most 0.085 px; Q28's original-source baseline error is +0.000564 px.

**PASS scope:** each source row's first glyph x/y is within 0.6 px and its baseline spread within 0.15 px; all measured SVG glyph origins stay inside the source frame with the existing 0.6 px tolerance. The actual PDF checks cover 658 initial/deleted and 942 grown nonspace glyphs, page printable ink bounds (0.3 PDF point tolerance) and picture intersection. These PDF checks do not establish every glyph's ink bounds against its physical table-cell/frame edge or source fontface identity.

**Remaining limits:** all-glyph horizontal error is reported rather than thresholded. The bullet row `September 5th...` still reaches 6.095438 px, and other short LEFT rows also retain spacing errors. Three source U+00AD soft hyphens are excluded from this PDF glyph inventory and explicitly require separate visible-paint proof; this result does not fix or pass their PDF painting. The PDF sequence also excludes six bullet markers after `•`/`∙` normalization, in addition to whitespace/NFKC normalization; these markers remain in the SVG row comparison. SVG/XML presence or these exclusions must not be counted as complete visible-glyph PDF paint coverage. Native PNG images are written by this verifier but are not independently pixel-compared here.

The fresh **English3 subset**, `tmp/september-exam-matrix/field-final-native3-20261007/report.json`, is stable at product SHA256 `e551659507c50ec18ca978990444653267151b0a59098acf6baab9d34237319f`. All three remain quality FAIL: high1 harsh mean/minimum 93.21/90.68, high2 93.29/90.07, high3 87.05/78.58. API objective scores are 89.75/89.75/87.05. This subset does not rerun or supersede the other 48 papers of the historical 51-paper baseline, and no macOS runtime was tested.

## Final6 independent checks

Input: `tmp/september-exam-matrix/q27-product-final6/high2-native.hwpx`, SHA256 `85eb81933c9586c3b8f662b3e6e6e29e850aca1dcade84de0c049af3826b670c`.

```powershell
python -X utf8 scripts/verify_wrapped_flow_break_state.py --hwpx tmp/september-exam-matrix/q27-product-final6/high2-native.hwpx --report tmp/renderer-square/break-state-independent/final6-report.json
python -X utf8 scripts/verify_wrapped_source_cache_state.py --hwpx tmp/september-exam-matrix/q27-product-final6/high2-native.hwpx --report tmp/renderer-square/cache-snapshot-independent/final6-report.json
```

Both exit 0, with stable before/after hashes for the four reviewed vendor modules. Break state passes 29 checks. Source cache passes 6 positives and 27 negatives, including all digest-valid forgeries described below.

The additional positives prove both copy boundaries that earlier direct tests missed. `staged_table_copy_restore` deep-copies the table rather than the whole section. `public_document_open_staged_table_restore` opens the actual package with `HwpxDocument.open`, uses that public document's parsed header/section and the already persisted snapshot **without reseeding**, invalidates a cache through public `add_run('')`, and restores a deep-copied table using the public resolved styles. Restored line-cache attribute vectors exactly match the actual input; root break flags remain unchanged. The synthetic second-cell isolation positive also passes.

Reports and logs: `tmp/renderer-square/{break-state-independent,cache-snapshot-independent}/final6-{report.json,log}`. These tests do not call complete public save or render, and the JSON explicitly records `public_save_render_tested_here: false`.

## Narrow v2 pagination-gap checks

The subsequent gap correction preserves an existing native before-gap only in a structurally validated v2 wrapped edit context when the question plus gap fits an empty column. The previous consume-before behavior remains for v1, a bare marker, invalid metadata, generic/math dirty context and oversized question-plus-gap.

```powershell
python -X utf8 scripts/verify_wrapped_pagination_gaps.py --hwpx tmp/september-exam-matrix/q27-product-final6/high2-native.hwpx
python -X utf8 scripts/verify_native_question_gap_reflow.py
```

Both exit 0. The new script first proves the initial Q27 against the actual PDF, then retains three existing question boxes in a synthetic section with an artificial page capacity; it does not claim source layout fidelity for the reduced fixture. All 11 actual public-save/reopen checks pass:

- At capacity 32998 HWPUNIT, equal to Q28 plus its 1466-unit before-gap, the native top margin remains 1466. At capacity 32997, the gap is consumed to zero.
- v1, a bare marker, a bad digest, an additional generic dirty paragraph and a math-control dirty paragraph all retain the ordinary consume-to-zero behavior. The math-control case checks eligibility fallback; real math layout is covered separately by the existing native/math suite.
- Manual before values 2048 and zero remain unchanged. Explicit page/column baseline intent is retained. A next-column request from the right column is correctly serialized as a next-page output flag while retaining the user's column-break baseline.
- A second public open/save leaves all section XML byte-identical.

Evidence: `tmp/renderer-square/gap-pagination-independent/report.json`, `tmp/renderer-square/break-state-independent/pagination-gap-boundaries.log`. The existing generic gap script also passes growth/deletion, actual column transition, SVG text bounds and stable reopened saves: `tmp/renderer-square/break-state-independent/gap-v2-generic.log`. Its separate known generic first-page masthead offset remains 13.751686 px.

The 6-positive/27-negative source-cache and 29-check break-state suites were rerun after this v2 gap landing and also exit 0: `tmp/renderer-square/{cache-snapshot-independent,break-state-independent}/final6-gap-{report.json,log}`. These three independent reports share reviewed `question_reflow.py` SHA256 `985ff13462729a9d2201d7e976273052f4e66826c9a1b8889da3d768daeb9a03` and `wrapped_cache_metrics.py` SHA256 `e243f3f10d2fccc10b10a5b66297c99bd777d031d41bc074cc610142a373bfab`.

## Final3 isolated checks

Input: `tmp/september-exam-matrix/q27-product-final3/high2-native.hwpx`.

```powershell
python -X utf8 scripts/verify_wrapped_flow_break_state.py --hwpx tmp/september-exam-matrix/q27-product-final3/high2-native.hwpx --report tmp/renderer-square/break-state-independent/final3-report.json
python -X utf8 scripts/verify_wrapped_source_cache_state.py --hwpx tmp/september-exam-matrix/q27-product-final3/high2-native.hwpx --report tmp/renderer-square/cache-snapshot-independent/final3-report.json
```

Both exit 0. The reports record input SHA and stable before/after hashes for `wrapped_flow_state.py`, `paragraph_floats.py`, `question_reflow.py` and `wrapped_cache_metrics.py`.

- Break state: 29 checks. Automatically generated page breaks remain distinct from the ordered initial baseline through XML roundtrips and repeated saves. Explicit user page/column changes and removal are preserved. Generic dirty paragraphs, ordinary tables, math controls, invalid flags, reordered/changed paragraph IDs and malformed/digest-valid invalid metadata reject the override without mutation.
- Source cache: 3 positives and 27 negatives. Exact reversion and an empty appended run recover the original caches; a manual root page break remains unchanged. Text/UTF16, resolved character/paragraph styles, fontfaces addition/change, width, padding, picture offset/size/reference and nested paragraph IDs/order reject restoration. Both the outer digest and cache integrity hash are recomputed in the forged line-removal/offset/descender/mask/oversize cases, so these are stronger than broken-hash tests.
- The cache test begins with an actual independent PDF/native source proof before calling seed. It never treats the cell name or either digest as PDF provenance.
- Supported exact cache advance validation is limited to the existing compiled Haansoft Batang metrics; unknown faces/characters fall back to normal reflow. It does not introduce font fallback or replace general paragraph layout.

Logs: `tmp/renderer-square/{break-state-independent,cache-snapshot-independent}/final3.log`.

## Actual final3 public save path failed

The root-owned actual `--edits` gate subsequently failed despite the direct restore unit positives: stable final3 input changed 8 → 9 → 9 pages. The native question height changed 33186 → 42644 → 35001 HWPUNIT, and deletion did not restore Q28's initial page/position. Evidence: `tmp/september-exam-matrix/q27-final3-independent/report.json` (`stable_verification_snapshot=true`). Thus the final3 unit PASS above is not an actual save-path PASS.

The confirmed cause is inclusive picture C14N in `cell_geometry`: the seed included unused ancestor namespace declarations, while the real save path's `deepcopy(table)` removed them. Direct original/grown/deleted cell geometry matched the stored snapshot, but the staged table copy did not. Restoration inside actual reflow therefore differed from a direct helper call. The producer owner corrected canonicalization in final6. An independent `staged_table_copy_restore` positive exercises that precise copy boundary. Final7 above supersedes this failed snapshot as the current actual result while retaining the historical failure.

Final5's fast actual save still failed after picture geometry was corrected: all 14 paragraph fingerprints differed in the actual public-open/reflow path. The remaining cause was inclusive canonicalization of resolved styles/fontfaces, whose unused namespace declarations differed after public header parsing. Final6 uses exclusive C14N for picture geometry, resolved styles and fontfaces. Its actual public-open/staged positive now passes as described above. This closes the independently reproduced helper boundary; it does not retroactively make final3/final5 actual save results pass or substitute for the final complete public edit/render gate.

## Reproduced and corrected during review

The initial v2 implementation accepted a digest-valid snapshot after deleting one middle introductory source line, changing the first title offset from 0 to 1, or changing a later offset by one. Native geometry validation also returned true. The offset-1 mutant retained the original XML prose but actually painted `shwood...` instead of `Ashwood...`; the source title compact count fell from 2 (prompt and notice) to 1.

Evidence is retained in `tmp/renderer-square/cache-snapshot-independent/{independent-report.json,actual-mutant-paint-proof.json,skip_first_title_character.hwpx,skip_first_title_character.svg}`. The final3 independent test recomputes both hashes and verifies rejection of all three. First-offset-zero, complete UTF16/control boundaries, word boundaries and supported exact-width/mask checks now prevent those cases.

## Corrected synthetic isolation finding

`finish()` initially wrote the dirty cell's complete state, including its per-cell cache snapshot, to every structurally eligible wrapped cell in the section. A synthetic native two-cell fixture reproduced an untouched second cell's snapshot being replaced with the first cell's cache; its subsequent exact-content restore then returned false. No second real source-PDF frame is claimed by this synthetic fixture.

Evidence: `tmp/renderer-square/cache-snapshot-independent/multicell-review.json`. The actual Q27 fixture contains one eligible wrapped cell, so this finding was separate from its final3 gates. The owner corrected `finish()` to synchronize section-level ordered IDs/base/last while retaining each cell's own seeded cache. Final6's `untouched_second_cell_own_snapshot_preserved` positive verifies both snapshot equality and successful subsequent restoration. No product patch was made by this reviewer.

## Review limits

The root verifier compares deletion with initial page count, exact native height/text, Q28 page/x/y/distance and picture page/bounds, rather than accepting shrink alone. Final7's actual edit/render PASS is recorded separately above. This review does not establish overall quality 98, source fontface identity, physical-cell ink bounds for every glyph, complete visible PDF soft-hyphen painting, or macOS runtime support.
